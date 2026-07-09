#!/usr/bin/env python3
"""
Maven MCP server — MCP stdio (JSON-RPC 2.0) over stdin/stdout.
No external dependencies; Python 3.9+ standard library only.
"""

import base64
import datetime
import email.utils
import functools
import hashlib
import http.client
import json
import logging
import os
import random
import re
import socket
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_NAME = "maven-mcp"
SERVER_VERSION = "0.23.0"
USER_AGENT = "maven-mcp/0.23.0"
HTTP_TIMEOUT = 15

# Bounded retry/backoff (ported from the retired TS `fetchWithRetry`). The TS
# default was `retries = 1` => 2 total attempts; this matches it. Backoff base
# mirrors the TS 200ms + up-to-300ms jitter, here applied exponentially.
HTTP_MAX_ATTEMPTS = 2          # total attempts (1 initial + 1 retry)
HTTP_BACKOFF_BASE = 0.2        # seconds; delay = base * 2**attempt + jitter
HTTP_BACKOFF_JITTER = 0.3      # seconds; uniform [0, jitter) added per attempt
HTTP_RETRY_AFTER_MAX = 30.0    # cap an upstream Retry-After so a hostile header can't stall us
HTTP_TOTAL_RETRY_BUDGET = 60.0  # wall-clock cap across all attempts + sleeps

# Cap on a single HTTP response body. Maven metadata/POMs are KB-scale;
# OSV/GitHub/Solr JSON is typically well under a few MB. A hostile or
# misconfigured endpoint returning multi-GB bodies must not OOM the
# long-lived stdio server (#350). HTTP_TIMEOUT only bounds time, not size.
HTTP_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MiB

MAVEN_CENTRAL_URL = "https://repo1.maven.org/maven2"
GOOGLE_MAVEN_URL = "https://dl.google.com/dl/android/maven2"
GRADLE_PLUGIN_PORTAL_URL = "https://plugins.gradle.org/m2"

GOOGLE_MAVEN_GROUPS = (
    "androidx.", "com.google.android.", "com.android.", "com.google.firebase.",
    "com.google.gms.", "com.google.mlkit.", "com.google.ar.",
)

STABILITY_PATTERNS = [
    (re.compile(r'[-.]?SNAPSHOT$', re.IGNORECASE), "snapshot"),
    (re.compile(r'[-.](?:alpha|a(?=\d|[-.]|$))[-.]?\d*', re.IGNORECASE), "alpha"),
    (re.compile(r'[-.](?:beta|b(?=\d|[-.]|$))[-.]?\d*', re.IGNORECASE), "beta"),
    (re.compile(r'[-.](?:M|milestone)[-.]?\d*', re.IGNORECASE), "milestone"),
    (re.compile(r'[-.](?:RC|CR)[-.]?\d*', re.IGNORECASE), "rc"),
]

PRERELEASE_WEIGHT = {"snapshot": 0, "alpha": 1, "beta": 2, "milestone": 3, "rc": 4, "stable": 5}

GITHUB_API = "https://api.github.com"
OSV_API = "https://api.osv.dev/v1/querybatch"
# OSV.dev documents a maximum of 1000 queries per /v1/querybatch request.
# query_osv_batch chunks above this so a large monorepo audit cannot fail as a unit.
OSV_QUERYBATCH_MAX = 1000
# /v1/querybatch returns only {id, modified} per vuln — severity/summary/fixed
# require a follow-up GET /v1/vulns/{id} (#338). Cap bounds worst-case fan-out
# per query_osv_batch call (unique IDs, first-seen order); excess stay bare.
OSV_VULN_API = "https://api.osv.dev/v1/vulns"
MAX_OSV_VULN_HYDRATIONS = 100
SEARCH_API = "https://search.maven.org/solrsearch/select"
# search_artifacts limit: coerced to int and clamped in the handler before the
# Solr URL is built (MCP schema bounds are advisory client metadata only).
SEARCH_LIMIT_DEFAULT = 10
SEARCH_LIMIT_MAX = 100
# get_dependency_vulnerabilities dependency-list cap — same bound and rationale
# as verify_coordinates (enforced in-handler before any network I/O).
MAX_VULN_DEPENDENCIES = 100

# Persistent file cache TTLs and capacity (see FileCache below).
TTL_POM = 7 * 86400     # 7 days — release POMs are immutable once published
TTL_METADATA = 3600     # 1 hour — version lists change, but not constantly
TTL_SEARCH = 3600       # 1 hour — Maven Central Solr search index

CACHE_MAX_ENTRIES = 2000

# Belt-and-suspenders denylist for http_get_cached.  Private Maven repo hosts
# are NOT listed — this is a blocklist (not an allowlist) so project-declared
# repos at any host are still cached via the call-site-discipline path.
_CACHE_DENYLIST = frozenset({"api.github.com", "api.osv.dev"})

GRADLE_BUILD_FILES = ["build.gradle.kts", "build.gradle"]
GRADLE_SETTINGS_FILES = ["settings.gradle.kts", "settings.gradle"]
MAX_MODULE_DEPTH = 5
# Cap recursive BOM import / parent-property fetches (#286).
MAX_BOM_DEPTH = 5

# deps.dev GetDependencies (#287). Caching is allowed by their ToS; TTL matches
# metadata/search (version graphs change, but not constantly).
DEPSDEV_API = "https://api.deps.dev/v3"
TTL_DEPSDEV = 3600  # 1 hour
# Fan-out / size caps — Wave 0 hardening: never unbounded network or memory.
MAX_TRANSITIVE_GRAPH_NODES = 2000
MAX_CONFLICT_SCAN_ROOTS = 50
MAX_DEPSDEV_ERRORS_REPORTED = 20

# Gradle configuration names matched by shape (#346), not a closed allow-list:
# variant/flavor prefixes (`debugImplementation`, `paidReleaseApi`, …),
# source-set forms (`androidTestImplementation`, `testFixturesImplementation`),
# annotation processors (`kapt`/`ksp`/`kaptTest`/…), and common standalone
# configs (`coreLibraryDesugaring`, `lintChecks`, `detektPlugins`).
# Test-ness is classified later via `_is_test_configuration`.
_GRADLE_CONFIGURATION_PATTERN = (
    r"(?:"
    # Prefix may be empty (bare `implementation` / `api`) or a variant/flavor/
    # source-set name (`debugImplementation`, `androidTestApi`, …).
    r"\w*(?:[Ii]mplementation|[Cc]ompileOnly|[Rr]untimeOnly|"
    r"[Aa]nnotationProcessor|[Aa]pi)"
    r"|kapt(?:AndroidTest|Test)?"
    r"|ksp(?:AndroidTest|Test)?"
    r"|coreLibraryDesugaring"
    r"|lintChecks"
    r"|detektPlugins"
    r")"
)

SCOPE_TO_CONFIG = {
    "compile": "implementation",
    "runtime": "runtimeOnly",
    "test": "testImplementation",
    "provided": "compileOnly",
    "system": "compileOnly",
}

# ---------------------------------------------------------------------------
# HTTP utilities
# ---------------------------------------------------------------------------

def _make_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    h = {"User-Agent": USER_AGENT}
    if extra:
        h.update(extra)
    return h


def _github_headers() -> Dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    h = _make_headers({"Accept": "application/vnd.github.v3+json"})
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# Injectable so tests can monkeypatch it and run instantly (no real sleeping).
_sleep: Callable[[float], None] = time.sleep

# Injectable clock: monkeypatch _now in tests to control TTL boundary assertions.
_now: Callable[[], float] = time.time

# Module-level logger targets sys.stderr — the MCP protocol uses stdout for
# JSON-RPC; any diagnostic byte written there corrupts the channel.
# Guard against double-adding the handler on module re-import (test isolation).
_logger = logging.getLogger("maven_mcp")
_logger.propagate = False
if not _logger.handlers:
    _logger.addHandler(logging.StreamHandler(sys.stderr))


def _is_retryable_status(status: int) -> bool:
    """Transient HTTP statuses worth retrying: 429 + any 5xx (matches the TS
    `isRetriableStatus`). Definitive responses (2xx/3xx/4xx-except-429) are not
    retried — the caller's tri-state contract treats them as final."""
    return status == 429 or 500 <= status < 600


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter for retry ``attempt`` (0-based)."""
    return HTTP_BACKOFF_BASE * (2 ** attempt) + random.random() * HTTP_BACKOFF_JITTER


def _parse_retry_after(headers: Any) -> Optional[float]:
    """Parse a ``Retry-After`` header (delta-seconds or HTTP-date) into seconds,
    clamped to ``HTTP_RETRY_AFTER_MAX`` so a hostile value cannot stall the
    server. Returns ``None`` when the header is absent or unparseable."""
    if headers is None:
        return None
    get = getattr(headers, "get", None)
    raw = get("Retry-After") if callable(get) else None
    if not raw:
        return None
    raw = raw.strip()
    try:
        secs = float(int(raw))  # delta-seconds form
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(raw)  # HTTP-date form
        except (TypeError, ValueError):
            # 3.9 raises TypeError, 3.10+ raises ValueError on a bad date.
            return None
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        secs = (dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    if secs < 0:
        secs = 0.0
    return min(secs, HTTP_RETRY_AFTER_MAX)


# urllib's default opener registers handlers for file:// and ftp://. Repo URLs
# are captured verbatim from build files, so a declared ``file:///...`` (or
# uppercase ``FILE://``) must never reach urlopen. Only http/https are allowed.
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def _url_scheme(url: str) -> str:
    """Return the URL scheme lowercased, or ``""`` if missing/unparseable."""
    try:
        return urllib.parse.urlsplit(url).scheme.lower()
    except ValueError:
        return ""


def _assert_http_url(url: str) -> None:
    """Raise ``URLError`` unless ``url`` uses an allowed http(s) scheme.

    Checked before Request construction so the default opener never honors
    ``file://`` / ``ftp://`` / other non-HTTP schemes (#348).
    """
    scheme = _url_scheme(url)
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise urllib.error.URLError(
            f"URL scheme not allowed: {scheme or '(none)'} (only http/https)"
        )


def _is_file_url(url: str) -> bool:
    """True when ``url`` is a ``file:`` URL (scheme compared case-insensitively)."""
    return _url_scheme(url) == "file"


class ResponseTooLargeError(urllib.error.URLError):
    """Raised when an HTTP response body exceeds ``HTTP_MAX_RESPONSE_BYTES``.

    Not retried: re-fetching an oversized body cannot help and would only
    amplify memory pressure (#350).
    """


def _read_response_body(resp: Any) -> bytes:
    """Read ``resp`` body with an explicit size cap (#350).

    Short-circuits on an oversized ``Content-Length`` before allocating, then
    reads at most ``HTTP_MAX_RESPONSE_BYTES + 1`` bytes and raises
    ``ResponseTooLargeError`` if the body exceeds the cap. Chunked / missing
    Content-Length still cannot grow without bound because of the read cap.
    """
    headers = getattr(resp, "headers", None)
    if headers is not None:
        get = getattr(headers, "get", None)
        raw_cl = get("Content-Length") if callable(get) else None
        if raw_cl is not None and str(raw_cl).strip():
            try:
                content_length = int(str(raw_cl).strip())
            except (TypeError, ValueError):
                content_length = -1
            if content_length > HTTP_MAX_RESPONSE_BYTES:
                raise ResponseTooLargeError(
                    f"HTTP response too large: Content-Length {content_length} "
                    f"exceeds {HTTP_MAX_RESPONSE_BYTES} bytes"
                )
    body = resp.read(HTTP_MAX_RESPONSE_BYTES + 1)
    if len(body) > HTTP_MAX_RESPONSE_BYTES:
        raise ResponseTooLargeError(
            f"HTTP response too large: body exceeds {HTTP_MAX_RESPONSE_BYTES} bytes"
        )
    return body


def _request_with_retry(req: urllib.request.Request) -> Tuple[int, bytes]:
    """Issue ``req`` with bounded retry/backoff on transient failures.

    Tri-state contract (relied on by the resolution layer and verify_coordinates):
    returns ``(status, body)`` for ANY HTTP response — including a persistent
    429/5xx after retries are exhausted — and only re-raises the last transport
    error (URLError / socket.timeout) when EVERY attempt failed at the transport
    level without ever obtaining an HTTP response. A 4xx (incl. 404) is never
    turned into a raise. Retry is fully internal and transparent to callers.
    Oversized bodies raise ``ResponseTooLargeError`` immediately (not retried).
    """
    deadline = time.monotonic() + HTTP_TOTAL_RETRY_BUDGET
    last_result: Optional[Tuple[int, bytes]] = None
    last_exc: Optional[BaseException] = None
    for attempt in range(HTTP_MAX_ATTEMPTS):
        retry_after: Optional[float] = None
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                status, body = resp.status, _read_response_body(resp)
                if not _is_retryable_status(status):
                    return status, body
                # A retryable status surfaced as a success object (rare — urllib
                # normally raises HTTPError for 4xx/5xx); remember it and retry.
                last_result = (status, body)
                retry_after = _parse_retry_after(getattr(resp, "headers", None))
        except ResponseTooLargeError:
            # Oversized body is definitive — do not retry (#350).
            raise
        except urllib.error.HTTPError as e:
            # HTTPError IS-A URLError but represents a real HTTP response, not a
            # transport failure — must be caught first. Body stays b"" (the
            # legacy mapping callers depend on); we never read e.read().
            if not _is_retryable_status(e.code):
                return e.code, b""
            last_result = (e.code, b"")
            retry_after = _parse_retry_after(e.headers)
        except (urllib.error.URLError, socket.timeout) as e:
            last_exc = e
        # http.client.InvalidURL (e.g. a malformed userinfo URL) is deliberately
        # NOT caught here — it is a request-construction failure, not a transport
        # failure, so it is not retryable and propagates to the caller. Both
        # known callers (fetch_metadata and _verify_one) handle it explicitly at
        # their own layer rather than relying on a generic retry-and-swallow here.
        if attempt >= HTTP_MAX_ATTEMPTS - 1:
            break
        delay = retry_after if retry_after is not None else _backoff_delay(attempt)
        if time.monotonic() + delay > deadline:
            break  # honoring the delay would blow the total-time budget
        _sleep(delay)
    # Prefer any HTTP response seen over a transport error: raise only when no
    # attempt ever produced an HTTP response.
    if last_result is not None:
        return last_result
    if last_exc is not None:
        raise last_exc
    # Defensive: unreachable while HTTP_MAX_ATTEMPTS >= 1 (every attempt sets
    # last_result or last_exc). Raise an explicit error rather than `raise None`.
    raise urllib.error.URLError("HTTP request failed: no response and no transport error")


def http_get(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[int, bytes]:
    """Returns (status_code, body_bytes). Retries transient failures internally
    (see _request_with_retry); raises urllib.error.URLError / socket.timeout only
    when every attempt hit a transport error. Non-http(s) schemes are rejected
    before any network/filesystem open (#348)."""
    _assert_http_url(url)
    req = urllib.request.Request(url, headers=headers or _make_headers())
    return _request_with_retry(req)


def http_post_json(url: str, payload: Any, headers: Optional[Dict[str, str]] = None) -> Tuple[int, bytes]:
    _assert_http_url(url)
    data = json.dumps(payload).encode()
    h = _make_headers({"Content-Type": "application/json"})
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    return _request_with_retry(req)


# ---------------------------------------------------------------------------
# Persistent file cache
# ---------------------------------------------------------------------------

class FileCache:
    """On-disk response cache for Maven read paths.

    Key is sha256(url) hex — a hash is used rather than a path-encoded URL so
    keys cannot contain path separators regardless of URL content.  Headers are
    intentionally excluded from the key: every wired call site uses the default
    User-Agent-only headers, and accepting auth-bearing headers not folded into
    the key would be a latent footgun (cached response served for a different
    caller's credentials).

    Security properties:
    - Only status == 200 is ever written; error bodies are never cached.
    - Each entry JSON stores the full URL; stored url != requested url
      (hash collision, practically impossible) is treated as a miss.
    - Cache dir and files use owner-only permissions (0o700 / 0o600).
    - Disk errors on set() are swallowed and logged to stderr (never stdout,
      which is the JSON-RPC channel); any error on get() produces a miss.
    """

    def _get_dir(self) -> Optional[str]:
        """Resolve and ensure the cache directory, per-call (reads os.environ at call time).

        Returns the path on success, None on OSError (degrade to no-op).
        Re-running makedirs + chmod on every call is cheap for an already-correct
        dir and correctly handles the pre-existing loose-perm case (makedirs'
        mode= is umask-masked and a no-op when the dir pre-exists).
        """
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".cache")
        d = os.path.join(base, "maven-central-mcp")
        try:
            os.makedirs(d, mode=0o700, exist_ok=True)
            # Explicit chmod on the LEAF dir only: makedirs' mode= is
            # umask-masked and does nothing when the dir pre-exists with
            # loose perms.  The chmod is the reliable tightening path.
            os.chmod(d, 0o700)
            return d
        except OSError:
            return None

    def _key_path(self, cache_dir: str, url: str) -> str:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return os.path.join(cache_dir, h + ".json")

    def get(self, url: str, ttl: float) -> Optional[Tuple[int, bytes]]:
        """Return (status, body) if a fresh entry exists, else None.

        TTL check is strictly >, so exactly-at-TTL is a HIT.
        Any error (missing file, corrupt JSON, OSError, url mismatch) -> None.
        """
        if os.environ.get("MAVEN_MCP_CACHE_DISABLE", "").lower() in ("1", "true", "yes", "on"):
            return None
        d = self._get_dir()
        if d is None:
            return None
        path = self._key_path(d, url)
        try:
            with open(path, "rb") as fh:
                entry = json.loads(fh.read())
            if entry.get("url") != url:
                return None
            if _now() - entry["ts"] > ttl:
                return None
            return (entry["status"], base64.b64decode(entry["body_b64"]))
        except Exception:
            return None

    def set(self, url: str, status: int, body: bytes) -> None:
        """Write url->body to cache. No-op for non-200, disabled, or dir failure."""
        if status != 200:
            return
        if os.environ.get("MAVEN_MCP_CACHE_DISABLE", "").lower() in ("1", "true", "yes", "on"):
            return
        d = self._get_dir()
        if d is None:
            return
        path = self._key_path(d, url)
        entry = {
            "v": 1,
            "url": url,
            "status": 200,
            "body_b64": base64.b64encode(body).decode("ascii"),
            "ts": _now(),
        }
        data = json.dumps(entry).encode("utf-8")
        tmp: Optional[str] = None
        try:
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except OSError as exc:
            _logger.warning("FileCache set failed for %s: %s", url, exc)
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass  # best-effort cleanup of the temp file; a concurrent delete or vanished file is not an error
            return
        self._evict(d)

    def _evict(self, cache_dir: str) -> None:
        """FIFO eviction: if count > CACHE_MAX_ENTRIES delete oldest-by-mtime
        down to ~90% of the cap.  get() never touches mtime so order is by
        write time, not access time."""
        try:
            entries = [
                os.path.join(cache_dir, f)
                for f in os.listdir(cache_dir)
                if f.endswith(".json")
            ]
            if len(entries) <= CACHE_MAX_ENTRIES:
                return
            entries.sort(key=lambda p: os.stat(p).st_mtime)
            target = int(CACHE_MAX_ENTRIES * 0.9)
            for p in entries[: len(entries) - target]:
                try:
                    os.unlink(p)
                except (OSError, FileNotFoundError):
                    pass  # concurrent delete between listdir and unlink is harmless; skip and continue eviction
        except OSError:
            pass  # best-effort eviction — a transient I/O error does not affect correctness of the cache


_file_cache = FileCache()


def _headers_have_authorization(headers: Optional[Dict[str, str]]) -> bool:
    """True when ``headers`` carries an Authorization value (any casing)."""
    if not headers:
        return False
    return any(str(k).lower() == "authorization" for k in headers)


def http_get_cached(
    url: str,
    ttl_seconds: float,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, bytes]:
    """Cached GET: returns a cached (200, body) on hit, else delegates to http_get.

    Auth-bearing requests (``Authorization`` present) NEVER touch the disk cache —
    the cache key is URL-only, so serving a cached private-repo body to a later
    caller without the same credentials would be a latent footgun (#291). Public
    UA-only GETs keep the existing cache path.

    Sensitive hosts (api.github.com, api.osv.dev) bypass to raw http_get via
    a static denylist: belt-and-suspenders against future mis-wiring.  Private
    Maven repo hosts are NOT blocked — this is a blocklist, not an allowlist.

    A cache hit short-circuits ABOVE the #306 retry layer: the response is
    returned directly without ever calling http_get (and thus without consuming
    any retry budget).  Non-200 responses and propagating transport errors are
    never cached; the caller receives them exactly as http_get would return/raise.
    """
    if _headers_have_authorization(headers):
        return http_get(url, headers)
    host = urllib.parse.urlparse(url).hostname or ""
    if host in _CACHE_DENYLIST:
        return http_get(url, headers)
    result = _file_cache.get(url, ttl_seconds)
    if result is not None:
        return result
    status, body = http_get(url, headers)
    if status == 200:
        _file_cache.set(url, status, body)
    return (status, body)


# ---------------------------------------------------------------------------
# Private Maven repository credentials (#291)
# ---------------------------------------------------------------------------
# Credentials are NEVER read from build files. Resolution order (first match
# wins): environment variables → ~/.m2/settings.xml <servers> →
# ~/.gradle/gradle.properties. Secrets must never be logged or echoed into
# tool-facing JSON — only Authorization headers on the outbound request.

_CRED_ENV_PREFIX = "MAVEN_REPO_"


def _sanitize_cred_key(identifier: str) -> str:
    """Turn a repo id or hostname into an env-var fragment: non-alnum → ``_``,
    uppercased, trimmed of leading/trailing underscores."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", (identifier or "").strip())
    return cleaned.strip("_").upper()


def _repo_host(url: str) -> str:
    """Hostname from a repo URL, or ``""`` if unparseable / missing."""
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _repo_id_candidates(entry: Dict[str, Any]) -> List[str]:
    """Identifiers worth matching credentials against, in priority order.

    Maven ``<id>`` / Gradle ``name = "…"`` land in ``entry["name"]`` when they
    differ from the URL. Host is always a fallback so a Gradle ``maven { url }``
    with no name still matches ``MAVEN_REPO_<HOST>_…`` env vars.
    """
    candidates: List[str] = []
    name = (entry.get("name") or "").strip()
    url = (entry.get("url") or "").strip()
    if name and name != url and "://" not in name:
        candidates.append(name)
    host = _repo_host(url)
    if host:
        candidates.append(host)
    return candidates


def _creds_from_user_secret(
    username: Optional[str], password: Optional[str], token: Optional[str]
) -> Optional[Dict[str, str]]:
    """Build a credential dict from optional user/password/token pieces.

    - token alone → Bearer
    - username + password → Basic
    - username + token (no password) → Basic with the token as the password
      (GitHub Packages / Artifactory PAT style)
    Incomplete pairs return None — never invent a half-auth header.
    """
    user = (username or "").strip() or None
    pwd = (password or "").strip() or None
    tok = (token or "").strip() or None
    if tok and not user and not pwd:
        return {"type": "bearer", "token": tok}
    if user and pwd:
        return {"type": "basic", "username": user, "password": pwd}
    if user and tok:
        return {"type": "basic", "username": user, "password": tok}
    return None


def _resolve_creds_from_env(identifier: str) -> Optional[Dict[str, str]]:
    """``MAVEN_REPO_<ID>_USER`` / ``_PASSWORD`` / ``_TOKEN`` (see #291)."""
    key = _sanitize_cred_key(identifier)
    if not key:
        return None
    prefix = f"{_CRED_ENV_PREFIX}{key}_"
    return _creds_from_user_secret(
        os.environ.get(prefix + "USER"),
        os.environ.get(prefix + "PASSWORD"),
        os.environ.get(prefix + "TOKEN"),
    )


def _parse_settings_xml_servers(xml: str) -> Dict[str, Dict[str, str]]:
    """Parse Maven ``settings.xml`` ``<servers><server>`` entries into
    ``{id: {username?, password?}}``. Regex-only (no XML parser dependency).
    Password values are kept in memory only for header construction — never
    logged. Malformed / comment-only files yield an empty map."""
    servers: Dict[str, Dict[str, str]] = {}
    # Strip XML comments so a commented-out <server> cannot contribute.
    xml = re.sub(r"<!--.*?-->", "", xml, flags=re.DOTALL)
    for sm in re.finditer(r"<server>([\s\S]*?)</server>", xml):
        block = sm.group(1)
        idm = re.search(r"<id>([^<]+)</id>", block)
        if not idm:
            continue
        sid = idm.group(1).strip()
        if not sid:
            continue
        user_m = re.search(r"<username>([^<]*)</username>", block)
        pass_m = re.search(r"<password>([^<]*)</password>", block)
        entry: Dict[str, str] = {}
        if user_m:
            entry["username"] = user_m.group(1)
        if pass_m:
            entry["password"] = pass_m.group(1)
        if entry:
            servers[sid] = entry
    return servers


def _load_settings_xml_servers() -> Dict[str, Dict[str, str]]:
    """Read ``~/.m2/settings.xml`` (or ``$M2_HOME/conf/settings.xml`` is NOT
    consulted — user settings only). Missing/unreadable → empty map."""
    path = os.path.join(os.path.expanduser("~"), ".m2", "settings.xml")
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return _parse_settings_xml_servers(fh.read())
    except OSError:
        return {}


def _resolve_creds_from_settings(identifier: str) -> Optional[Dict[str, str]]:
    """Match a Maven ``settings.xml`` ``<server><id>`` to ``identifier``."""
    if not identifier or "://" in identifier:
        return None
    servers = _load_settings_xml_servers()
    entry = servers.get(identifier)
    if not entry:
        # Case-insensitive id match — Maven ids are conventionally exact, but
        # a mismatched case should not silently drop working credentials.
        lower = identifier.lower()
        for sid, val in servers.items():
            if sid.lower() == lower:
                entry = val
                break
    if not entry:
        return None
    return _creds_from_user_secret(
        entry.get("username"), entry.get("password"), None
    )


def _parse_gradle_properties(text: str) -> Dict[str, str]:
    """Minimal ``gradle.properties`` parser: ``key=value`` lines, ``#`` comments,
    no interpolation. Values keep surrounding spaces stripped."""
    props: Dict[str, str] = {}
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith("!"):
            continue
        if "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        key = key.strip()
        if key:
            props[key] = value.strip()
    return props


def _load_gradle_properties() -> Dict[str, str]:
    """Read ``~/.gradle/gradle.properties``. Missing/unreadable → empty map."""
    path = os.path.join(os.path.expanduser("~"), ".gradle", "gradle.properties")
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return _parse_gradle_properties(fh.read())
    except OSError:
        return {}


def _resolve_creds_from_gradle_properties(identifier: str) -> Optional[Dict[str, str]]:
    """Match common Gradle property naming for a repo id:

    - ``{id}Username`` / ``{id}Password`` (Gradle docs style)
    - ``{id}User`` / ``{id}Password``
    - ``{id}Token`` (Bearer; or Basic password when paired with Username)
    """
    if not identifier or "://" in identifier:
        return None
    props = _load_gradle_properties()
    if not props:
        return None
    # Preserve the identifier's own camel/Pascal form for key lookup, and also
    # try a lowercased-first-letter variant (`nexus` + `Username`).
    bases = [identifier]
    if identifier[0].isupper():
        bases.append(identifier[0].lower() + identifier[1:])
    elif identifier[0].islower():
        bases.append(identifier[0].upper() + identifier[1:])
    for base in bases:
        user = props.get(base + "Username") or props.get(base + "User")
        password = props.get(base + "Password")
        token = props.get(base + "Token")
        creds = _creds_from_user_secret(user, password, token)
        if creds:
            return creds
    return None


def resolve_repo_credentials(entry: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Resolve Basic/Bearer credentials for a discovered repo entry (#291).

    Returns ``{"type": "basic", "username", "password"}`` or
    ``{"type": "bearer", "token"}``, or ``None`` when nothing matches.
    Never reads credentials from build files. Never logs secret values.
    """
    for ident in _repo_id_candidates(entry):
        for resolver in (
            _resolve_creds_from_env,
            _resolve_creds_from_settings,
            _resolve_creds_from_gradle_properties,
        ):
            creds = resolver(ident)
            if creds:
                return creds
    return None


def _authorization_header(creds: Dict[str, str]) -> str:
    """Build an ``Authorization`` header value from a resolve_repo_credentials result."""
    if creds.get("type") == "bearer":
        return f"Bearer {creds['token']}"
    raw = f"{creds['username']}:{creds['password']}"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _repo_request_headers(entry: Dict[str, Any]) -> Dict[str, str]:
    """UA headers plus optional Authorization for ``entry`` (#291)."""
    creds = resolve_repo_credentials(entry)
    if not creds:
        return _make_headers()
    return _make_headers({"Authorization": _authorization_header(creds)})


def _repo_http_get(
    entry: Dict[str, Any],
    url: str,
    ttl_seconds: Optional[float] = None,
) -> Tuple[int, bytes]:
    """GET a Maven-repo URL with per-repo auth headers. When ``ttl_seconds`` is
    set, uses ``http_get_cached`` (auth-bearing responses still bypass the
    disk cache)."""
    headers = _repo_request_headers(entry)
    if ttl_seconds is None:
        return http_get(url, headers)
    return http_get_cached(url, ttl_seconds, headers)


def _auth_required_message(entry: Dict[str, Any], status: int) -> str:
    """Clear, secret-free signal when a private repo rejects the request."""
    label = _strip_userinfo(entry.get("name") or entry.get("url") or "repository")
    return f"auth required for {label} (HTTP {status})"


# ---------------------------------------------------------------------------
# Maven mirrors + closed/offline mode (#294)
# ---------------------------------------------------------------------------
# Closed-perimeter builds redirect mavenCentral()/google()/gradlePluginPortal()
# via settings.xml <mirror><mirrorOf>…</mirrorOf> (and optionally
# MAVEN_MCP_REPOSITORY_BASE / MAVEN_MCP_OFFLINE). Without this, every lookup
# hits unreachable public hosts and hangs on timeouts.

# Well-known public repo URL → Maven-style repository id(s) used by mirrorOf.
_PUBLIC_REPO_MIRROR_IDS = {
    MAVEN_CENTRAL_URL.rstrip("/"): ("central", "Maven Central"),
    GOOGLE_MAVEN_URL.rstrip("/"): ("google", "Google Maven"),
    GRADLE_PLUGIN_PORTAL_URL.rstrip("/"): ("gradle-plugins", "Gradle Plugin Portal"),
}


def _env_flag(name: str) -> bool:
    """True when env ``name`` is a truthy toggle (1/true/on/yes)."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "on", "yes")


def _offline_enabled() -> bool:
    """``MAVEN_MCP_OFFLINE`` — disable all public well-known repo contact (#294)."""
    return _env_flag("MAVEN_MCP_OFFLINE")


def _repository_base() -> Optional[str]:
    """``MAVEN_MCP_REPOSITORY_BASE`` — replace public well-known URLs with this
    base (trailing slash normalised away for storage; callers re-rstrip)."""
    raw = (os.environ.get("MAVEN_MCP_REPOSITORY_BASE") or "").strip()
    return raw.rstrip("/") if raw else None


def _parse_settings_xml_mirrors(xml: str) -> List[Dict[str, str]]:
    """Parse ``<mirrors><mirror>`` entries into
    ``[{id, url, mirrorOf}]`` (declaration order). Regex-only. Comment-stripped
    so a commented-out mirror cannot contribute."""
    mirrors: List[Dict[str, str]] = []
    xml = re.sub(r"<!--.*?-->", "", xml, flags=re.DOTALL)
    for mm in re.finditer(r"<mirror>([\s\S]*?)</mirror>", xml):
        block = mm.group(1)
        idm = re.search(r"<id>([^<]+)</id>", block)
        urlm = re.search(r"<url>([^<]+)</url>", block)
        ofm = re.search(r"<mirrorOf>([^<]+)</mirrorOf>", block)
        if not urlm or not ofm:
            continue
        url = urlm.group(1).strip()
        mirror_of = ofm.group(1).strip()
        if not url or not mirror_of:
            continue
        mid = idm.group(1).strip() if idm else url
        mirrors.append({"id": mid or url, "url": url.rstrip("/"), "mirrorOf": mirror_of})
    return mirrors


def _settings_xml_paths() -> List[str]:
    """Candidate settings.xml paths in Maven precedence order for #294:
    ``MAVEN_MCP_SETTINGS`` (-s override) → ``~/.m2/settings.xml`` →
    ``$M2_HOME/conf/settings.xml`` / ``$MAVEN_HOME/conf/settings.xml``.
    First readable file wins (user override replaces global, not merges — MVP)."""
    paths: List[str] = []
    override = (os.environ.get("MAVEN_MCP_SETTINGS") or "").strip()
    if override:
        paths.append(os.path.expanduser(override))
        return paths
    paths.append(os.path.join(os.path.expanduser("~"), ".m2", "settings.xml"))
    for home_var in ("M2_HOME", "MAVEN_HOME"):
        home = (os.environ.get(home_var) or "").strip()
        if home:
            paths.append(os.path.join(home, "conf", "settings.xml"))
    return paths


def _load_settings_xml_mirrors() -> List[Dict[str, str]]:
    """Load mirrors from the first readable settings.xml (see ``_settings_xml_paths``)."""
    for path in _settings_xml_paths():
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                return _parse_settings_xml_mirrors(fh.read())
        except OSError:
            continue
    return []


def _repo_mirror_ids(entry: Dict[str, Any]) -> List[str]:
    """Ids that ``mirrorOf`` may match for ``entry``: declared name (when not a
    URL), plus well-known aliases derived from the URL (``central`` for Maven
    Central, etc.)."""
    ids: List[str] = []
    name = (entry.get("name") or "").strip()
    url = (entry.get("url") or "").strip().rstrip("/")
    if name and "://" not in name:
        ids.append(name)
    aliases = _PUBLIC_REPO_MIRROR_IDS.get(url)
    if aliases:
        for a in aliases:
            if a not in ids:
                ids.append(a)
    # Host-only fallback so a custom name still matches mirrorOf=hostname.
    host = _repo_host(url)
    if host and host not in ids:
        ids.append(host)
    return ids


def _is_external_repo_url(url: str) -> bool:
    """Maven ``external:*``: not localhost / loopback and not a ``file:`` URL."""
    if _is_file_url(url):
        return False
    host = _repo_host(url)
    if not host:
        return False
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost"):
        return False
    return True


def _mirror_of_matches(mirror_of: str, entry: Dict[str, Any]) -> bool:
    """Maven ``mirrorOf`` pattern matching: comma-separated tokens, ``*``,
    ``external:*``, ``external:http:*``, explicit ids, and ``!id`` exclusions.
    A pattern matches when at least one positive token matches and no exclusion
    token matches (Maven DefaultMirrorSelector semantics, simplified)."""
    tokens = [t.strip() for t in (mirror_of or "").split(",") if t.strip()]
    if not tokens:
        return False
    repo_ids = {i.lower() for i in _repo_mirror_ids(entry)}
    url = (entry.get("url") or "").strip()
    scheme = ""
    try:
        scheme = (urllib.parse.urlsplit(url).scheme or "").lower()
    except ValueError:
        scheme = ""

    excluded = False
    positive_match = False
    has_positive = False
    for tok in tokens:
        if tok.startswith("!"):
            excl = tok[1:].strip().lower()
            if excl == "*":
                excluded = True
            elif excl in repo_ids:
                excluded = True
            continue
        has_positive = True
        low = tok.lower()
        if tok == "*":
            positive_match = True
        elif low == "external:*":
            if _is_external_repo_url(url):
                positive_match = True
        elif low == "external:http:*":
            if scheme == "http" and _is_external_repo_url(url):
                positive_match = True
        elif low in repo_ids:
            positive_match = True
    if excluded:
        return False
    if not has_positive:
        # Only exclusions → nothing is mirrored (degenerate pattern).
        return False
    return positive_match


def _select_mirror(
    entry: Dict[str, Any], mirrors: List[Dict[str, str]]
) -> Optional[Dict[str, str]]:
    """First settings.xml mirror whose ``mirrorOf`` matches ``entry``, or None."""
    for mirror in mirrors:
        if _mirror_of_matches(mirror.get("mirrorOf", ""), entry):
            return mirror
    return None


def _apply_mirror_to_entry(
    entry: Dict[str, Any], mirrors: List[Dict[str, str]]
) -> Dict[str, Any]:
    """Rewrite ``entry`` URL/name to the matching mirror. Mirror ``id`` becomes
    ``name`` so #291 credential lookup hits ``<servers><server><id>`` for the
    mirror. Unmatched entries are returned unchanged (shallow copy)."""
    out = dict(entry)
    if not mirrors or _is_file_url(out.get("url") or ""):
        return out
    mirror = _select_mirror(out, mirrors)
    if not mirror:
        return out
    out["url"] = mirror["url"]
    out["name"] = mirror["id"]
    out["mirrored"] = True
    return out


def _is_well_known_public_url(url: str) -> bool:
    """True when ``url`` is one of the static public well-known bases."""
    return url.rstrip("/") in _PUBLIC_REPO_MIRROR_IDS


def _rewrite_public_url(url: str, repository_base: Optional[str]) -> str:
    """Replace a well-known public URL with ``repository_base`` when set."""
    if repository_base and _is_well_known_public_url(url):
        return repository_base
    return url


def _gradle_init_script_paths() -> List[str]:
    """``~/.gradle/init.gradle[.kts]`` and ``~/.gradle/init.d/*`` scripts."""
    root = os.path.join(os.path.expanduser("~"), ".gradle")
    paths: List[str] = []
    for name in ("init.gradle", "init.gradle.kts"):
        paths.append(os.path.join(root, name))
    init_d = os.path.join(root, "init.d")
    try:
        for fn in sorted(os.listdir(init_d)):
            if fn.endswith((".gradle", ".gradle.kts")):
                paths.append(os.path.join(init_d, fn))
    except OSError:
        pass
    return paths


_INIT_MAVEN_URL_RE = re.compile(
    r"""(?x)
    (?:
        # maven\s*\(\s*(?:url\s*=\s*)?["'](https?://[^"']+)["']
        maven\s*\(\s*(?:url\s*=\s*)?["'](https?://[^"']+)["']
      |
        # url\s*=\s*(?:uri\s*\(\s*)?["'](https?://[^"']+)["']
        \burl\s*=\s*(?:uri\s*\(\s*)?["'](https?://[^"']+)["']
      |
        # Groovy: url\s+["'](https?://[^"']+)["']
        \burl\s+["'](https?://[^"']+)["']
    )
    """
)


def _parse_gradle_init_mirror_urls(text: str) -> List[str]:
    """Extract http(s) Maven repo URLs from a Gradle init script. Used only when
    the script also references a well-known shorthand (mavenCentral/google/
    gradlePluginPortal) — a heuristic for closed-contour redirect init scripts
    (#294, "where feasible")."""
    if not re.search(
        r"\b(?:mavenCentral|google|gradlePluginPortal)\s*\(", text
    ):
        # Also accept scripts that clear/replace repositories without naming
        # the shorthand — require at least one maven { url } style URL then.
        if "maven" not in text:
            return []
    urls: List[str] = []
    seen = set()
    for m in _INIT_MAVEN_URL_RE.finditer(text):
        url = next(g for g in m.groups() if g).rstrip("/")
        if url not in seen and not _is_well_known_public_url(url):
            seen.add(url)
            urls.append(url)
    return urls


def _load_gradle_init_mirrors() -> List[Dict[str, str]]:
    """Feasible Gradle init-script mirror detection (#294): when an init script
    declares exactly one non-public maven URL (typical Nexus/Artifactory
    redirect), treat it as a catch-all ``mirrorOf=*`` mirror. Multi-URL scripts
    are left alone — too ambiguous for a regex MVP."""
    found: List[str] = []
    for path in _gradle_init_script_paths():
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                found.extend(_parse_gradle_init_mirror_urls(fh.read()))
        except OSError:
            continue
    # Dedup preserving order.
    uniq: List[str] = []
    seen = set()
    for u in found:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    if len(uniq) != 1:
        return []
    return [{"id": "gradle-init-mirror", "url": uniq[0], "mirrorOf": "*"}]


def _load_mirrors() -> List[Dict[str, str]]:
    """settings.xml mirrors first; if none, fall back to a single Gradle init
    catch-all mirror when detectable. settings.xml wins entirely when present
    so a corporate Maven mirror is not diluted by init-script heuristics."""
    mirrors = _load_settings_xml_mirrors()
    if mirrors:
        return mirrors
    return _load_gradle_init_mirrors()


# ---------------------------------------------------------------------------
# Repository resolution
# ---------------------------------------------------------------------------

def group_path(group_id: str) -> str:
    return group_id.replace(".", "/")


def _metadata_url(base: str, group_id: str, artifact_id: str) -> str:
    return f"{base.rstrip('/')}/{group_path(group_id)}/{artifact_id}/maven-metadata.xml"


def _pom_url(base: str, group_id: str, artifact_id: str, version: str) -> str:
    gp = group_path(group_id)
    return f"{base.rstrip('/')}/{gp}/{artifact_id}/{version}/{artifact_id}-{version}.pom"


class ResolutionContext:
    """Repository-resolution context built ONCE at the handler boundary and
    threaded down to every resolver. ``scoped_repos`` is the
    ``discover_repositories`` result and doubles as the per-invocation memo (no
    separate cache map). Closed-mode fields (#294) — ``offline``,
    ``repository_base``, ``mirrors`` — and ``public_fallback`` are read from
    the environment at construction, never sniffed in leaf functions."""

    def __init__(
        self,
        project_path: str,
        scoped_repos: Dict[str, List[Dict[str, str]]],
        public_fallback: bool,
        offline: bool = False,
        repository_base: Optional[str] = None,
        mirrors: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        self.project_path = project_path
        self.scoped_repos = scoped_repos
        self.public_fallback = public_fallback
        self.offline = offline
        self.repository_base = repository_base
        self.mirrors = list(mirrors) if mirrors else []


def _public_fallback_enabled() -> bool:
    """MAVEN_MCP_PUBLIC_FALLBACK toggle. Default OFF (closed-mode #294 wants it
    off); when ON, public repos are appended even for projects that declare
    their own repositories (escape hatch for implicit/inherited-repo builds)."""
    return _env_flag("MAVEN_MCP_PUBLIC_FALLBACK")


def build_resolution_context(args: Dict) -> "ResolutionContext":
    """Build a ResolutionContext from a tool-call args dict at the handler
    boundary. project_path defaults to the current working directory; closed-
    mode toggles and mirrors are read here once, not in the leaf resolvers."""
    project_path = args.get("projectPath") or os.getcwd()
    return ResolutionContext(
        project_path,
        discover_repositories(project_path),
        _public_fallback_enabled(),
        offline=_offline_enabled(),
        repository_base=_repository_base(),
        mirrors=_load_mirrors(),
    )


def _public_repos(group_id: str, artifact_id: str) -> List[Tuple[str, str]]:
    """Static well-known routing (most-specific first): Gradle Plugin Portal for
    plugin markers, Google Maven for the AndroidX/Google group prefixes, Maven
    Central always last. Used as the public fallback when the project declares no
    HTTP-queryable repository for the coordinate's scope."""
    repos: List[Tuple[str, str]] = []
    if artifact_id.endswith(".gradle.plugin"):
        repos.append(("Gradle Plugin Portal", GRADLE_PLUGIN_PORTAL_URL))
    if any(group_id.startswith(p) for p in GOOGLE_MAVEN_GROUPS):
        repos.append(("Google Maven", GOOGLE_MAVEN_URL))
    repos.append(("Maven Central", MAVEN_CENTRAL_URL))
    return repos


def _finalize_repo_entries(
    entries: List[Dict[str, Any]], ctx: "ResolutionContext"
) -> List[Dict[str, Any]]:
    """Apply ``MAVEN_MCP_REPOSITORY_BASE`` rewrite, settings.xml / init-script
    mirrors, then drop remaining well-known public URLs when ``offline`` (#294).
    Dedupes by URL (first-seen wins) so a catch-all mirror collapsing several
    public shorthands does not probe the same host repeatedly."""
    out: List[Dict[str, Any]] = []
    for entry in entries:
        e = dict(entry)
        e["url"] = _rewrite_public_url(e["url"], ctx.repository_base)
        if ctx.repository_base and _is_well_known_public_url(entry["url"]):
            # Name becomes the base host so #291 cred lookup can match it.
            host = _repo_host(ctx.repository_base) or ctx.repository_base
            e["name"] = host
        e = _apply_mirror_to_entry(e, ctx.mirrors)
        if ctx.offline and _is_well_known_public_url(e["url"]):
            continue
        out.append(e)
    return _dedup_repos(out)


def _repos_for(
    group_id: str, artifact_id: str, ctx: "ResolutionContext"
) -> List[Dict[str, Any]]:
    """Project-first repository resolution. ``ctx`` is REQUIRED — a public-only
    default would silently resurrect #310. Returns rich entries
    ``{name, url, scope, is_public_fallback}``, most-specific first.

    Coordinate kind: a ``.gradle.plugin`` marker artifact resolves in the plugin
    scope, everything else in the dependency scope. If that scope declares >=1
    HTTP-queryable repository (mavenLocal's ``file://`` marker does NOT count) the
    declared repos are returned EXACTLY, with no implicit public append — the
    #299/#310 core. Otherwise the static public routing is the fallback. When
    ``ctx.public_fallback`` is ON the public repos are appended even for a
    declared scope (deduped by URL).

    Closed mode (#294): ``ctx.mirrors`` rewrite matched repo URLs (settings.xml
    ``mirrorOf`` / Gradle init heuristic); ``ctx.repository_base`` replaces
    well-known public URLs; ``ctx.offline`` drops any remaining public hosts so
    they are never contacted."""
    scope = "plugin" if artifact_id.endswith(".gradle.plugin") else "dependency"
    declared = ctx.scoped_repos.get(scope, [])
    # mavenLocal / file:// markers are non-queryable; scheme check is
    # case-insensitive so ``FILE://`` cannot bypass the guard (#348).
    queryable = [r for r in declared if not _is_file_url(r["url"])]

    # When offline with no repository_base and no mirrors, public fallbacks are
    # suppressed entirely — contacting repo1.maven.org would only hang.
    allow_public = not (
        ctx.offline and not ctx.repository_base and not ctx.mirrors
    )
    public_entries: List[Dict[str, Any]] = []
    if allow_public:
        public_entries = [
            {"name": name, "url": url, "scope": scope, "is_public_fallback": True}
            for name, url in _public_repos(group_id, artifact_id)
        ]

    if not queryable:
        return _finalize_repo_entries(public_entries, ctx)

    # Content/group filtering (#320): a repo with an attached `includeGroup` /
    # `includeGroupByRegex` filter is only consulted for a coordinate whose
    # groupId actually matches — mirrors Gradle's own content filtering so a
    # group-scoped repo (JitPack scoped to `com.github.*`, a filtered Google
    # Maven declaration, etc.) is never queried for a group the real build
    # would never route to it (the #299 false-availability class). Unfiltered
    # repos are unaffected — the filter is opt-in per repo, not a new default
    # restriction. If filtering excludes every declared repo, the scope is
    # still treated as "declared" (not empty) — no unconditional public
    # fallback, only the same opt-in `ctx.public_fallback` append as below.
    matched = [r for r in queryable if _repo_matches_group(r, group_id)]

    entries = [
        {"name": r["name"], "url": r["url"], "scope": scope, "is_public_fallback": False}
        for r in matched
    ]
    if ctx.public_fallback and allow_public:
        entries.extend(public_entries)
        return _finalize_repo_entries(_dedup_repos(entries), ctx)
    return _finalize_repo_entries(entries, ctx)


def _parse_metadata_xml(xml: str, group_id: str, artifact_id: str) -> Dict[str, Any]:
    versions = re.findall(r"<version>([^<]+)</version>", xml)
    latest = (re.search(r"<latest>([^<]+)</latest>", xml) or [None, None])[1]
    release = (re.search(r"<release>([^<]+)</release>", xml) or [None, None])[1]
    last_updated = (re.search(r"<lastUpdated>([^<]+)</lastUpdated>", xml) or [None, None])[1]
    return {
        "groupId": group_id,
        "artifactId": artifact_id,
        "versions": versions,
        "latest": latest,
        "release": release,
        "lastUpdated": last_updated,
    }


def _strip_userinfo(url: str) -> str:
    """Redact ``user:pass@`` userinfo from a repo URL before it reaches
    tool-facing JSON (#317 security review). Repo URLs are captured verbatim
    from build files, so a discouraged hardcoded
    ``url = "https://user:pass@host/repo"`` would otherwise echo the literal
    credential into MCP output. Output-boundary only — the raw, credentialed
    URL is still what actually gets HTTP-fetched; this never touches the
    fetch path, only what is reported back."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        # A malformed host (e.g. an unterminated bracketed IPv6 literal) can
        # still carry userinfo that urlsplit never gets to parse out — fail
        # open would leak it verbatim. A first-`@`-only regex (the previous
        # approach) under-redacts when the userinfo itself contains an
        # unescaped `@` (e.g. `user:pa@ss@host` — malformed input exactly
        # like what triggers this fallback): it would strip only up to the
        # FIRST `@`, leaving a trailing password fragment (`ss@host`) in the
        # output. Instead, locate the `scheme://` prefix, take the authority
        # up to the next `/` (or end of string), and drop everything up to
        # and including the LAST `@` in that authority — that reliably
        # removes all userinfo regardless of how many `@` it contains.
        scheme_match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*://)", url)
        if not scheme_match:
            # No identifiable scheme boundary — fall back to stripping
            # everything up to the last `@` globally as a safety net.
            return url.rsplit("@", 1)[-1] if "@" in url else url
        scheme = scheme_match.group(1)
        rest = url[len(scheme):]
        slash_idx = rest.find("/")
        authority = rest if slash_idx == -1 else rest[:slash_idx]
        remainder = "" if slash_idx == -1 else rest[slash_idx:]
        if "@" not in authority:
            return url
        return f"{scheme}{authority.rsplit('@', 1)[-1]}{remainder}"
    if "@" not in parsed.netloc:
        return url
    host = parsed.netloc.rsplit("@", 1)[-1]
    return urllib.parse.urlunsplit((parsed.scheme, f"***@{host}", parsed.path, parsed.query, parsed.fragment))


def _to_resolved_from(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Project a repo entry (from _repos_for/_public_repos) into the public resolvedFrom shape."""
    return {
        "url": _strip_userinfo(entry["url"]),
        "scope": entry["scope"],
        "viaPublicFallback": entry["is_public_fallback"],
    }


def fetch_metadata(group_id: str, artifact_id: str, ctx: "ResolutionContext") -> Dict[str, Any]:
    """Query every repo in ``ctx`` and MERGE results across those answering 200:
    version sets are unioned, deduped and sorted ascending so a private repo's
    extra versions are not lost to a first-hit short-circuit (#311); ``lastUpdated``
    carries the most-recent value across answering repos. If NO repo answers (all
    404/error) a ``ValueError`` is raised with the same message as the legacy
    first-hit code, so unwrapped callers keep working. The single-repo result is
    identical to the legacy path (union/sort of one ascending set = itself).
    Intentionally diverges from the retired TS ``resolveAll``: no proxy-dedup."""
    repos = _repos_for(group_id, artifact_id, ctx)
    merged_versions: List[str] = []
    last_updated: Optional[str] = None
    answered = False
    # An empty `repos` list has no entry to set a last_err from — default to an
    # explicit reason instead of leaving this None (which would surface as the
    # confusing "...: None"). Two causes since #320/#294: content/group filtering
    # excluded every declared repo, or offline/closed mode dropped all public
    # hosts with no mirror / REPOSITORY_BASE replacement.
    if not repos:
        if ctx.offline and not ctx.repository_base and not ctx.mirrors:
            last_err = (
                "no queryable repositories (offline/closed mode with no mirror "
                "or MAVEN_MCP_REPOSITORY_BASE)"
            )
        else:
            last_err = (
                "no repository in scope (declared repo(s) excluded by "
                "content/group filtering)"
            )
    else:
        last_err = None
    # First repo (in _repos_for order: declared repos before any public-fallback
    # append) that answers 200 — surfaced as resolvedFrom for #317 provenance.
    resolved_from: Optional[Dict[str, Any]] = None
    for entry in repos:
        url = _metadata_url(entry["url"], group_id, artifact_id)
        try:
            status, body = _repo_http_get(entry, url, TTL_METADATA)
            if status == 200:
                # "answered" is gated on HTTP 200 itself, not on a non-empty
                # version list — a 200 with empty <versions> still counts as a
                # reachable repo, matching the legacy first-hit contract.
                answered = True
                if resolved_from is None:
                    resolved_from = _to_resolved_from(entry)
                parsed = _parse_metadata_xml(body.decode("utf-8", errors="replace"), group_id, artifact_id)
                merged_versions.extend(parsed["versions"])
                lu = parsed.get("lastUpdated")
                if lu and (last_updated is None or lu > last_updated):
                    last_updated = lu
            elif status in (401, 403):
                # Private/corporate repos reject unauthenticated (or wrong-cred)
                # probes with 401/403 — surface a clear "auth required" signal
                # rather than a bare HTTP code (#291). Never include secrets.
                last_err = _auth_required_message(entry, status)
            else:
                # entry["name"] can be the literal repo URL for maven("url")
                # declarations (name == url); redact before it reaches the
                # exception message, which flows into tool-facing "error" fields.
                last_err = f"HTTP {status} from {_strip_userinfo(entry['name'])}"
        except Exception as e:
            # Never interpolate str(e) here: a userinfo URL (https://user:pass@host)
            # makes urlopen raise http.client.InvalidURL — NOT a urllib.error.URLError,
            # so it lands in this generic branch — whose message embeds the raw
            # password (e.g. "nonnumeric port: 'pass@host'"), a string shape
            # _strip_userinfo cannot redact (it only redacts a value that IS a bare
            # scheme://user:pass@host URL, not a credential fragment embedded in
            # free text). Build the message from known-safe components instead:
            # the exception type name plus the already-redacted repo name.
            last_err = f"{type(e).__name__} from {_strip_userinfo(entry['name'])}"
    if not answered:
        raise ValueError(f"Could not fetch metadata for {group_id}:{artifact_id}: {last_err}")
    versions = sorted(set(merged_versions), key=functools.cmp_to_key(compare_versions))
    return {
        "groupId": group_id,
        "artifactId": artifact_id,
        "versions": versions,
        "latest": find_latest_version(versions, "PREFER_STABLE"),
        "release": find_latest_version(versions, "STABLE_ONLY"),
        "lastUpdated": last_updated,
        "resolvedFrom": resolved_from,
    }


def check_version_in_repos(group_id: str, artifact_id: str, version: str, ctx: "ResolutionContext") -> Optional[Dict[str, Any]]:
    """Returns the matching repo entry (name/url/scope/is_public_fallback) if version exists, else None."""
    repos = _repos_for(group_id, artifact_id, ctx)
    for entry in repos:
        url = _metadata_url(entry["url"], group_id, artifact_id)
        try:
            status, body = _repo_http_get(entry, url, TTL_METADATA)
            if status == 200:
                xml = body.decode("utf-8", errors="replace")
                versions = re.findall(r"<version>([^<]+)</version>", xml)
                if version in versions:
                    return entry
        except Exception:
            continue
    return None


def fetch_pom(group_id: str, artifact_id: str, version: str, ctx: "ResolutionContext") -> Optional[str]:
    repos = _repos_for(group_id, artifact_id, ctx)
    for entry in repos:
        url = _pom_url(entry["url"], group_id, artifact_id, version)
        try:
            status, body = _repo_http_get(entry, url, TTL_POM)
            if status == 200:
                return body.decode("utf-8", errors="replace")
        except Exception:
            continue
    return None


def check_relocation(
    group_id: str, artifact_id: str, version: str, ctx: "ResolutionContext"
) -> Optional[Dict[str, str]]:
    """Fetch a resolved coordinate's POM and report Maven relocation, if any
    (#284). Returns None when the POM can't be fetched (repo miss, transport
    failure — degrades silently, same as any other optional POM-derived field)
    or carries no `<relocation>` block. Reuses `fetch_pom`'s cache (POM TTL 7
    days), so this is one extra cached network call on top of whatever the
    caller already made to resolve `version` — not a new resolution pass."""
    pom = fetch_pom(group_id, artifact_id, version, ctx)
    if pom is None:
        return None
    return extract_relocation_from_pom(pom, group_id, artifact_id, version)


# ---------------------------------------------------------------------------
# BOM / platform expansion (#286)
# ---------------------------------------------------------------------------

def _parse_pom_properties(pom_xml: str) -> Dict[str, str]:
    """Parse `<properties>` children via regex. Returns {name: value}."""
    xml = _strip_xml_comments(pom_xml)
    props_m = re.search(r"<properties>([\s\S]*?)</properties>", xml)
    if not props_m:
        return {}
    props: Dict[str, str] = {}
    for m in re.finditer(r"<([a-zA-Z0-9_.-]+)>([^<]*)</\1>", props_m.group(1)):
        props[m.group(1)] = m.group(2).strip()
    return props


def _pom_project_property_defaults(
    pom_xml: str, bom_version: Optional[str] = None
) -> Dict[str, str]:
    """Build project.* / bare groupId/artifactId/version property defaults from
    a POM's own coordinates (with parent fallback for groupId/version)."""
    coords = _parse_maven_project_coords(pom_xml)
    parent = _parse_maven_parent(pom_xml)
    gid = coords.get("groupId") or (parent.get("groupId") if parent else None)
    aid = coords.get("artifactId")
    ver = (
        coords.get("version")
        or bom_version
        or (parent.get("version") if parent else None)
    )
    defaults: Dict[str, str] = {}
    if gid:
        defaults["project.groupId"] = gid
        defaults["groupId"] = gid
    if aid:
        defaults["project.artifactId"] = aid
        defaults["artifactId"] = aid
    if ver:
        defaults["project.version"] = ver
        defaults["version"] = ver
    return defaults


def _interpolate_pom_props(value: Optional[str], props: Dict[str, str]) -> Optional[str]:
    """Multi-pass `${name}` substitution. Returns None when value is None.
    Leaves unresolved `${...}` fragments intact for the caller to skip."""
    if value is None:
        return None
    if "${" not in value:
        return value
    result = value
    for _ in range(10):
        if "${" not in result:
            break

        def _repl(m: re.Match) -> str:
            return props.get(m.group(1), m.group(0))

        new = re.sub(r"\$\{([^}]+)\}", _repl, result)
        if new == result:
            break
        result = new
    return result


def _collect_bom_properties(
    pom_xml: str,
    bom_version: str,
    ctx: "ResolutionContext",
    depth: int = 0,
) -> Dict[str, str]:
    """Merge parent POM properties under child (child wins). Parent is fetched
    by GAV via `fetch_pom` — remote BOMs have no local relativePath."""
    props: Dict[str, str] = {}
    parent = _parse_maven_parent(pom_xml)
    if (
        parent
        and parent.get("groupId")
        and parent.get("artifactId")
        and parent.get("version")
        and depth < MAX_BOM_DEPTH
    ):
        parent_pom = fetch_pom(
            parent["groupId"], parent["artifactId"], parent["version"], ctx
        )
        if parent_pom:
            props.update(
                _collect_bom_properties(
                    parent_pom, parent["version"], ctx, depth + 1
                )
            )
    props.update(_pom_project_property_defaults(pom_xml, bom_version))
    props.update(_parse_pom_properties(pom_xml))
    return props


def parse_dependency_management(
    pom_xml: str, props: Optional[Dict[str, str]] = None
) -> List[Dict]:
    """Parse `<dependencyManagement><dependencies><dependency>…` entries (#286).

    Each entry: groupId, artifactId, version, scope (default compile),
    type (default jar), isImportBom (scope==import and type==pom).
    Strips XML comments first. When ``props`` is omitted, interpolates using
    this POM's own `<properties>` plus project.* defaults (no network).
    """
    xml = _strip_xml_comments(pom_xml)
    dm_m = re.search(
        r"<dependencyManagement>([\s\S]*?)</dependencyManagement>", xml
    )
    if not dm_m:
        return []
    deps_m = re.search(r"<dependencies>([\s\S]*?)</dependencies>", dm_m.group(1))
    block = deps_m.group(1) if deps_m else dm_m.group(1)
    if props is None:
        props = {}
        props.update(_pom_project_property_defaults(pom_xml))
        props.update(_parse_pom_properties(pom_xml))
    results: List[Dict] = []
    for m in re.finditer(r"<dependency>([\s\S]*?)</dependency>", block):
        dep_block = m.group(1)
        gid_m = re.search(r"<groupId>([^<]+)</groupId>", dep_block)
        aid_m = re.search(r"<artifactId>([^<]+)</artifactId>", dep_block)
        if not gid_m or not aid_m:
            continue
        group_id = _interpolate_pom_props(gid_m.group(1).strip(), props)
        artifact_id = _interpolate_pom_props(aid_m.group(1).strip(), props)
        if not group_id or not artifact_id:
            continue
        if "${" in group_id or "${" in artifact_id:
            continue
        ver_m = re.search(r"<version>([^<]+)</version>", dep_block)
        version = (
            _interpolate_pom_props(ver_m.group(1).strip(), props) if ver_m else None
        )
        if version is not None and "${" in version:
            version = None
        scope_m = re.search(r"<scope>([^<]+)</scope>", dep_block)
        scope = scope_m.group(1).strip() if scope_m else "compile"
        type_m = re.search(r"<type>([^<]+)</type>", dep_block)
        dep_type = type_m.group(1).strip() if type_m else "jar"
        results.append({
            "groupId": group_id,
            "artifactId": artifact_id,
            "version": version,
            "scope": scope,
            "type": dep_type,
            "isImportBom": scope == "import" and dep_type == "pom",
        })
    return results


def expand_bom(
    group_id: str,
    artifact_id: str,
    version: str,
    ctx: "ResolutionContext",
    *,
    _depth: int = 0,
    _seen: Optional[set] = None,
) -> List[Dict]:
    """Fetch a BOM POM and return managed ``[{groupId, artifactId, version}]``.

    Import-scope BOMs are expanded recursively and merged with Maven's
    first-wins ordering (document order; do not overwrite an existing GA).
    Direct managed entries in the current BOM follow the same first-wins rule.
    Depth-capped and cycle-guarded on ``g:a:v``. Missing POM / unresolved
    ``${}`` versions are skipped — never raises (#286).
    """
    if _seen is None:
        _seen = set()
    key = f"{group_id}:{artifact_id}:{version}"
    if _depth > MAX_BOM_DEPTH or key in _seen:
        return []
    _seen.add(key)
    pom = fetch_pom(group_id, artifact_id, version, ctx)
    if not pom:
        return []
    props = _collect_bom_properties(pom, version, ctx, _depth)
    entries = parse_dependency_management(pom, props=props)
    managed: List[Dict] = []
    managed_keys: set = set()
    for entry in entries:
        if entry["isImportBom"]:
            if not entry.get("version"):
                continue
            nested = expand_bom(
                entry["groupId"],
                entry["artifactId"],
                entry["version"],
                ctx,
                _depth=_depth + 1,
                _seen=_seen,
            )
            for item in nested:
                ga = (item["groupId"], item["artifactId"])
                if ga in managed_keys:
                    continue
                managed_keys.add(ga)
                managed.append(item)
            continue
        if not entry.get("version"):
            continue
        ga = (entry["groupId"], entry["artifactId"])
        if ga in managed_keys:
            continue
        managed_keys.add(ga)
        managed.append({
            "groupId": entry["groupId"],
            "artifactId": entry["artifactId"],
            "version": entry["version"],
        })
    return managed


def apply_bom_managed_versions(scan: Dict, ctx: "ResolutionContext") -> Dict:
    """Apply BOM/platform managed versions onto scanned dependencies (#286).

    Expands each ``isPlatform`` dependency via ``expand_bom`` in declaration
    order (first-wins), then lets local Maven non-import ``dependencyManagement``
    pins override imported managed versions. Versionless non-platform deps gain
    ``effectiveVersion`` + ``managedBy``. Explicit versions win unless the
    contributing platform was ``enforcedPlatform``.
    """
    managed_map: Dict[Tuple[str, str], Dict] = {}

    for dep in scan.get("dependencies") or []:
        if not dep.get("isPlatform"):
            continue
        ver = dep.get("version")
        gid, aid = dep.get("groupId"), dep.get("artifactId")
        if not gid or not aid or not ver:
            continue
        bom_ref = {"groupId": gid, "artifactId": aid, "version": ver}
        kind = dep.get("platformKind") or "platform"
        for item in expand_bom(gid, aid, ver, ctx):
            ga = (item["groupId"], item["artifactId"])
            if ga in managed_map:
                continue
            managed_map[ga] = {
                "version": item["version"],
                "managedBy": dict(bom_ref),
                "platformKind": kind,
            }

    # Local non-import pins override imported managed versions (Maven direct
    # declaration override). First local pin for a GA wins among local pins.
    local_applied: set = set()
    for pin in scan.get("managedPins") or []:
        gid, aid, ver = pin.get("groupId"), pin.get("artifactId"), pin.get("version")
        if not gid or not aid or not ver:
            continue
        ga = (gid, aid)
        if ga in local_applied:
            continue
        local_applied.add(ga)
        managed_map[ga] = {
            "version": ver,
            "managedBy": {"groupId": gid, "artifactId": aid, "version": ver},
            "platformKind": None,
        }

    for dep in scan.get("dependencies") or []:
        if dep.get("isPlatform"):
            continue
        gid, aid = dep.get("groupId"), dep.get("artifactId")
        if not gid or not aid:
            continue
        info = managed_map.get((gid, aid))
        if not info:
            continue
        explicit = dep.get("version")
        if explicit:
            if (
                info.get("platformKind") == "enforcedPlatform"
                and explicit != info["version"]
            ):
                dep["effectiveVersion"] = info["version"]
                dep["managedBy"] = info["managedBy"]
            continue
        dep["effectiveVersion"] = info["version"]
        dep["managedBy"] = info["managedBy"]
    return scan


# ---------------------------------------------------------------------------
# deps.dev transitive graphs + conflict detection (#287)
# ---------------------------------------------------------------------------

def _depsdev_package_name(group_id: str, artifact_id: str) -> str:
    """Maven package name on deps.dev is ``groupId:artifactId``."""
    return f"{group_id}:{artifact_id}"


def _split_maven_package_name(name: str) -> Optional[Tuple[str, str]]:
    """Split a deps.dev Maven ``name`` (``g:a``) into groupId/artifactId.

    Returns ``None`` when the name is not a two-part Maven coordinate (e.g.
    bundled npm-style encodings). Callers skip those nodes.
    """
    if not name or ":" not in name:
        return None
    parts = name.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _depsdev_dependencies_url(group_id: str, artifact_id: str, version: str) -> str:
    """Build the GetDependencies URL. Path segments are percent-encoded."""
    name = _depsdev_package_name(group_id, artifact_id)
    return (
        f"{DEPSDEV_API}/systems/MAVEN/packages/"
        f"{urllib.parse.quote(name, safe='')}/versions/"
        f"{urllib.parse.quote(version, safe='')}:dependencies"
    )


def fetch_depsdev_dependencies(
    group_id: str,
    artifact_id: str,
    version: str,
) -> Dict[str, Any]:
    """Fetch a resolved Maven dependency graph from deps.dev GetDependencies.

    Returns a normalised dict::

        {
          "ok": bool,
          "status": int | None,          # HTTP status when a response arrived
          "error": str | None,           # human-readable degrade reason
          "graphError": str | None,      # deps.dev graph-level error field
          "nodes": [{groupId, artifactId, version, relation, errors}],
          "edges": [{from, to, requirement}],
          "partial": bool,               # True when truncated or degraded
          "truncated": bool,             # True when node/edge cap applied
        }

    Never raises for network/HTTP/parse failures — callers get ``ok=False``
    with an ``error`` string (graceful degradation AC). Oversized bodies still
    raise via ``http_get`` / ``ResponseTooLargeError`` only if the transport
    layer itself raises after retries; those are caught and mapped to ``ok=False``.
    """
    empty: Dict[str, Any] = {
        "ok": False,
        "status": None,
        "error": None,
        "graphError": None,
        "nodes": [],
        "edges": [],
        "partial": True,
        "truncated": False,
    }
    url = _depsdev_dependencies_url(group_id, artifact_id, version)
    try:
        status, body = http_get_cached(url, TTL_DEPSDEV)
    except Exception as e:
        # Transport / size-cap / scheme failures — degrade, never raise.
        out = dict(empty)
        out["error"] = f"{type(e).__name__}: deps.dev unreachable"
        return out

    out = dict(empty)
    out["status"] = status
    if status != 200 or not body:
        out["error"] = (
            f"deps.dev returned HTTP {status}"
            if status is not None
            else "deps.dev returned empty response"
        )
        return out

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        out["error"] = f"deps.dev response not JSON: {type(e).__name__}"
        return out

    raw_nodes = payload.get("nodes") or []
    raw_edges = payload.get("edges") or []
    graph_error = payload.get("error") or None
    if isinstance(graph_error, str) and not graph_error.strip():
        graph_error = None

    # Build original-index → output-index for successfully parsed Maven nodes.
    # deps.dev may emit non-Maven name encodings; skipping those shifts indices,
    # so edges must be remapped. Truncation drops nodes beyond the fan-out cap.
    orig_to_out: Dict[int, int] = {}
    out_nodes: List[Dict[str, Any]] = []
    truncated = False
    for i, raw in enumerate(raw_nodes):
        if len(out_nodes) >= MAX_TRANSITIVE_GRAPH_NODES:
            truncated = True
            break
        vk = raw.get("versionKey") or {}
        split = _split_maven_package_name(vk.get("name") or "")
        if not split:
            continue
        gid, aid = split
        node_errors = raw.get("errors") or []
        if not isinstance(node_errors, list):
            node_errors = [str(node_errors)]
        orig_to_out[i] = len(out_nodes)
        out_nodes.append({
            "groupId": gid,
            "artifactId": aid,
            "version": vk.get("version") or "",
            "relation": raw.get("relation") or "",
            "errors": [str(e) for e in node_errors if e],
        })
    if len(raw_nodes) > MAX_TRANSITIVE_GRAPH_NODES:
        truncated = True

    edges: List[Dict[str, Any]] = []
    for raw in raw_edges:
        try:
            frm = int(raw.get("fromNode"))
            to = int(raw.get("toNode"))
        except (TypeError, ValueError):
            continue
        if frm not in orig_to_out or to not in orig_to_out:
            if frm >= MAX_TRANSITIVE_GRAPH_NODES or to >= MAX_TRANSITIVE_GRAPH_NODES:
                truncated = True
            continue
        edges.append({
            "from": orig_to_out[frm],
            "to": orig_to_out[to],
            "requirement": raw.get("requirement") or "",
        })

    out.update({
        "ok": True,
        "error": None,
        "graphError": graph_error,
        "nodes": out_nodes,
        "edges": edges,
        "partial": bool(truncated or graph_error or any(n.get("errors") for n in out_nodes)),
        "truncated": truncated,
    })
    return out


def _edge_depth_map(edges: List[Dict], root_index: int = 0) -> Dict[int, int]:
    """BFS depth from ``root_index`` over directed ``from → to`` edges.

    Used for Maven nearest-wins mediation: the shallowest path wins. Nodes
    unreachable from the root get no entry (callers treat them as infinite depth).
    """
    adj: Dict[int, List[int]] = {}
    for e in edges:
        adj.setdefault(e["from"], []).append(e["to"])
    depths: Dict[int, int] = {root_index: 0}
    queue: List[int] = [root_index]
    head = 0
    while head < len(queue):
        cur = queue[head]
        head += 1
        for nxt in adj.get(cur, []):
            if nxt in depths:
                continue
            depths[nxt] = depths[cur] + 1
            queue.append(nxt)
    return depths


def resolve_conflict_version(
    versions: List[str],
    strategy: str,
    *,
    depths_by_version: Optional[Dict[str, int]] = None,
) -> Optional[str]:
    """Pick the version a build system would mediate to among ``versions``.

    - ``highest-wins`` (Gradle): highest by ``compare_versions``.
    - ``nearest-wins`` (Maven): shallowest depth wins; ties broken by highest
      version (Maven's actual tie-break is declaration order, which we do not
      have — documented limitation).
    """
    uniq = sorted(set(v for v in versions if v), key=functools.cmp_to_key(compare_versions))
    if not uniq:
        return None
    if strategy == "highest-wins":
        return uniq[-1]
    # nearest-wins
    if not depths_by_version:
        # No depth info — fall back to highest (honest degrade).
        return uniq[-1]
    best_v = None
    best_depth = None
    for v in uniq:
        d = depths_by_version.get(v)
        if d is None:
            continue
        if best_depth is None or d < best_depth or (
            d == best_depth and compare_versions(v, best_v or "") > 0
        ):
            best_v = v
            best_depth = d
    return best_v if best_v is not None else uniq[-1]


def _conflict_risk(versions: List[str], resolved_to: Optional[str]) -> str:
    """Heuristic risk label for a multi-version GA conflict.

    - ``high``: major-version divergence among candidates, or resolved version
      is not the highest (classic nearest-wins silent downgrade).
    - ``medium``: minor divergence.
    - ``low``: patch-only / unknown.
    """
    if not versions or not resolved_to:
        return "low"
    uniq = list(dict.fromkeys(versions))
    highest = max(uniq, key=functools.cmp_to_key(compare_versions))
    if resolved_to != highest:
        return "high"
    kinds = set()
    for v in uniq:
        if v == resolved_to:
            continue
        kinds.add(get_upgrade_type(v, resolved_to) if compare_versions(resolved_to, v) > 0
                  else get_upgrade_type(resolved_to, v))
    if "major" in kinds:
        return "high"
    if "minor" in kinds:
        return "medium"
    return "low"


def strategy_for_build_system(build_system: str) -> str:
    """Map detected build system to mediation strategy label."""
    if build_system == "maven":
        return "nearest-wins"
    # Gradle (and unknown → Gradle-like highest-wins as the safer default for
    # modern JVM builds; callers can override via buildSystem arg).
    return "highest-wins"


def get_transitive_graph(
    group_id: str,
    artifact_id: str,
    version: str,
) -> Dict[str, Any]:
    """Resolved transitive graph for one GAV via deps.dev (#287)."""
    fetched = fetch_depsdev_dependencies(group_id, artifact_id, version)
    result: Dict[str, Any] = {
        "groupId": group_id,
        "artifactId": artifact_id,
        "version": version,
        "nodes": [
            {"groupId": n["groupId"], "artifactId": n["artifactId"], "version": n["version"]}
            for n in fetched["nodes"]
        ],
        "edges": [
            {"from": e["from"], "to": e["to"]}
            for e in fetched["edges"]
        ],
        "partial": fetched["partial"],
        "truncated": fetched["truncated"],
    }
    if fetched.get("graphError"):
        result["graphError"] = fetched["graphError"]
    if not fetched["ok"]:
        result["partial"] = True
        result["error"] = fetched.get("error") or "deps.dev unavailable"
        # Surface node-level errors when present even on ok path above; here
        # the graph is empty.
    else:
        # Attach per-node errors only when any exist (keep happy-path lean).
        node_errors = []
        for i, n in enumerate(fetched["nodes"]):
            if n.get("errors"):
                node_errors.append({"index": i, "errors": n["errors"]})
        if node_errors:
            result["nodeErrors"] = node_errors[:MAX_DEPSDEV_ERRORS_REPORTED]
    return result


def detect_dependency_conflicts(
    project_path: str,
    build_system: Optional[str] = None,
    ctx: Optional["ResolutionContext"] = None,
) -> Dict[str, Any]:
    """Detect GAs resolved at ≥2 versions across direct deps' transitive graphs.

    For each versioned direct dependency (capped at ``MAX_CONFLICT_SCAN_ROOTS``),
    fetches the deps.dev graph and unions every ``g:a → {versions…}`` seen.
    When a GA appears at multiple versions, reports the conflict with the
    version the active build system's mediation strategy would pick.

    This is an approximation of a full project resolve: deps.dev resolves each
    root in isolation (no project-wide dependencyManagement / resolutionStrategy
    / enforcedPlatform). Documented in ``notes``.
    """
    if ctx is None:
        ctx = build_resolution_context({"projectPath": project_path})
    scan = scan_project(project_path)
    apply_bom_managed_versions(scan, ctx)

    detected_bs = scan.get("buildSystem") or "unknown"
    bs = (build_system or detected_bs or "unknown").lower()
    if bs not in ("maven", "gradle"):
        # unknown → treat as gradle highest-wins (documented).
        strategy = strategy_for_build_system(bs)
        bs_label = detected_bs
    else:
        strategy = strategy_for_build_system(bs)
        bs_label = bs

    def _eff(dep: Dict) -> Optional[str]:
        return dep.get("version") or dep.get("effectiveVersion")

    roots: List[Dict] = []
    for dep in scan.get("dependencies") or []:
        if dep.get("isPlatform"):
            continue
        ver = _eff(dep)
        gid, aid = dep.get("groupId"), dep.get("artifactId")
        if not gid or not aid or not ver:
            continue
        roots.append({"groupId": gid, "artifactId": aid, "version": ver})

    # Dedupe identical GAV roots (same direct declared twice across modules).
    seen_roots: set = set()
    unique_roots: List[Dict] = []
    for r in roots:
        key = (r["groupId"], r["artifactId"], r["version"])
        if key in seen_roots:
            continue
        seen_roots.add(key)
        unique_roots.append(r)

    truncated_roots = len(unique_roots) > MAX_CONFLICT_SCAN_ROOTS
    unique_roots = unique_roots[:MAX_CONFLICT_SCAN_ROOTS]

    # ga -> { version -> {sources: [root gav…], minDepth: int|None } }
    ga_versions: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
    errors: List[str] = []
    graphs_ok = 0
    graphs_failed = 0

    for root in unique_roots:
        fetched = fetch_depsdev_dependencies(
            root["groupId"], root["artifactId"], root["version"]
        )
        root_label = f"{root['groupId']}:{root['artifactId']}:{root['version']}"
        if not fetched["ok"]:
            graphs_failed += 1
            if len(errors) < MAX_DEPSDEV_ERRORS_REPORTED:
                errors.append(f"{root_label}: {fetched.get('error') or 'unavailable'}")
            continue
        graphs_ok += 1
        if fetched.get("graphError") and len(errors) < MAX_DEPSDEV_ERRORS_REPORTED:
            errors.append(f"{root_label}: graph error: {fetched['graphError']}")

        depths = _edge_depth_map(fetched["edges"], 0)
        for idx, node in enumerate(fetched["nodes"]):
            ga = (node["groupId"], node["artifactId"])
            ver = node["version"]
            if not ver:
                continue
            bucket = ga_versions.setdefault(ga, {})
            info = bucket.setdefault(ver, {"sources": [], "minDepth": None})
            if root_label not in info["sources"]:
                info["sources"].append(root_label)
            d = depths.get(idx)
            if d is not None and (info["minDepth"] is None or d < info["minDepth"]):
                info["minDepth"] = d

    conflicts: List[Dict[str, Any]] = []
    for (gid, aid), ver_map in sorted(ga_versions.items()):
        versions = list(ver_map.keys())
        if len(versions) < 2:
            continue
        depths_by_version = {
            v: ver_map[v]["minDepth"]
            for v in versions
            if ver_map[v]["minDepth"] is not None
        }
        resolved = resolve_conflict_version(
            versions, strategy, depths_by_version=depths_by_version
        )
        sources: List[Dict[str, Any]] = []
        for v in sorted(versions, key=functools.cmp_to_key(compare_versions)):
            sources.append({
                "version": v,
                "via": ver_map[v]["sources"][:10],
                "minDepth": ver_map[v]["minDepth"],
            })
        conflicts.append({
            "groupId": gid,
            "artifactId": aid,
            "versions": sorted(versions, key=functools.cmp_to_key(compare_versions)),
            "resolvedTo": resolved,
            "strategy": strategy,
            "risk": _conflict_risk(versions, resolved),
            "sources": sources,
        })

    # Sort conflicts by risk then GA for stable output.
    risk_order = {"high": 0, "medium": 1, "low": 2}
    conflicts.sort(
        key=lambda c: (
            risk_order.get(c["risk"], 9),
            c["groupId"],
            c["artifactId"],
        )
    )

    notes = [
        "Conflict detection unions deps.dev graphs for each direct dependency "
        + "resolved in isolation — not a full project-wide Maven/Gradle resolve.",
        "Maven nearest-wins uses BFS depth from each direct root; declaration-"
        + "order tie-breaks inside the same depth are approximated by highest version.",
        "Gradle highest-wins ignores project ResolutionStrategy / strict versions / "
        + "enforcedPlatform overrides.",
        "Private/unpublished coordinates and deps.dev coverage gaps degrade per-root "
        + "(see errors[]); remaining roots still contribute.",
    ]
    if truncated_roots:
        notes.append(
            f"Direct roots truncated to {MAX_CONFLICT_SCAN_ROOTS} "
            + f"(MAX_CONFLICT_SCAN_ROOTS); results are partial."
        )

    return {
        "buildSystem": bs_label,
        "strategy": strategy,
        "conflicts": conflicts,
        "scannedRoots": len(unique_roots),
        "graphsFetched": graphs_ok,
        "graphsFailed": graphs_failed,
        "partial": bool(truncated_roots or graphs_failed or errors),
        "errors": errors,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Version compatibility matrices (#285)
# ---------------------------------------------------------------------------

SPRING_BOOT_BOM_GROUP = "org.springframework.boot"
SPRING_BOOT_BOM_ARTIFACT = "spring-boot-dependencies"
COMPAT_MATRICES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compat-matrices.json")
MAX_COMPAT_DEPENDENCIES = 100

_COMPAT_MATRICES_CACHE: Optional[Dict] = None


def _load_compat_matrices() -> Dict:
    """Load shipped compat-matrices.json (cached for the process lifetime)."""
    global _COMPAT_MATRICES_CACHE
    if _COMPAT_MATRICES_CACHE is not None:
        return _COMPAT_MATRICES_CACHE
    with open(COMPAT_MATRICES_PATH, "r", encoding="utf-8") as fh:
        _COMPAT_MATRICES_CACHE = json.load(fh)
    return _COMPAT_MATRICES_CACHE


def _major_minor_line(version: str) -> str:
    """Return ``major.minor`` for matrix line matching (e.g. 8.7.3 → 8.7)."""
    segs = _parse_segments(version)
    if len(segs) >= 2:
        return f"{segs[0]}.{segs[1]}"
    if segs:
        return str(segs[0])
    return version


def _version_gte(a: str, b: str) -> bool:
    return compare_versions(a, b) >= 0


def _version_lte(a: str, b: str) -> bool:
    return compare_versions(a, b) <= 0


def _version_in_closed_range(version: str, vmin: str, vmax: str) -> bool:
    return _version_gte(version, vmin) and _version_lte(version, vmax)


def _find_agp_entry(agp_version: str, entries: List[Dict]) -> Optional[Dict]:
    line = _major_minor_line(agp_version)
    for entry in entries:
        if entry.get("agp") == line:
            return entry
    for entry in entries:
        if entry.get("agp") == agp_version:
            return entry
    return None


def _find_kgp_entry(kotlin_version: str, entries: List[Dict]) -> Optional[Dict]:
    for entry in entries:
        kmin = entry.get("kgpMin") or ""
        kmax = entry.get("kgpMax") or ""
        if kmin and kmax and _version_in_closed_range(kotlin_version, kmin, kmax):
            return entry
    return None


def _nearest_agp_suggestion(agp_version: str, entries: List[Dict]) -> Optional[Dict]:
    """Pick the closest AGP matrix row by major.minor distance for suggestions."""
    if not entries:
        return None
    target = _parse_segments(agp_version)
    best = None
    best_dist = None
    for entry in entries:
        segs = _parse_segments(entry["agp"])
        # Lexicographic distance on padded major.minor
        a = (target + [0, 0])[:2]
        b = (segs + [0, 0])[:2]
        dist = abs(a[0] - b[0]) * 1000 + abs(a[1] - b[1])
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best = entry
    return best


def check_android_kotlin_compatibility(android: Dict, matrices: Dict) -> Tuple[List[Dict], List[str]]:
    """Validate AGP/Gradle/Kotlin/JDK against shipped matrices.

    Returns (conflicts, notes).
    """
    conflicts: List[Dict] = []
    notes: List[str] = []
    agp = (android.get("agp") or "").strip() or None
    gradle = (android.get("gradle") or "").strip() or None
    kotlin = (android.get("kotlin") or "").strip() or None
    jdk_raw = android.get("jdk")
    jdk: Optional[int] = None
    if jdk_raw is not None and jdk_raw != "":
        try:
            jdk = int(str(jdk_raw).strip())
        except (TypeError, ValueError):
            notes.append(f"android.jdk={jdk_raw!r} is not an integer; JDK check skipped.")

    agp_entries = matrices.get("agpEntries") or []
    kgp_entries = matrices.get("kotlinGradlePluginEntries") or []
    agp_entry = _find_agp_entry(agp, agp_entries) if agp else None

    if agp and agp_entry is None:
        nearest = _nearest_agp_suggestion(agp, agp_entries)
        suggestion = None
        if nearest:
            suggestion = {
                "agp": nearest["agp"],
                "gradle": nearest["minGradle"],
                "jdk": nearest["minJdk"],
            }
        conflicts.append({
            "kind": "agp_unknown",
            "requested": {"agp": agp, "gradle": gradle, "kotlin": kotlin, "jdk": jdk},
            "expected": None,
            "suggestion": suggestion,
            "reference": (nearest or {}).get("referenceUrl")
            or "https://developer.android.com/build/releases/about-agp",
        })
    elif agp_entry is not None:
        ref = agp_entry.get("referenceUrl") or "https://developer.android.com/build/releases/about-agp"
        suggestion = {
            "agp": agp_entry["agp"],
            "gradle": agp_entry["minGradle"],
            "jdk": agp_entry["minJdk"],
        }
        if gradle and not _version_gte(gradle, agp_entry["minGradle"]):
            conflicts.append({
                "kind": "agp_gradle",
                "requested": {"agp": agp, "gradle": gradle},
                "expected": {"minGradle": agp_entry["minGradle"]},
                "suggestion": suggestion,
                "reference": ref,
            })
        if jdk is not None and jdk < int(agp_entry["minJdk"]):
            conflicts.append({
                "kind": "agp_jdk",
                "requested": {"agp": agp, "jdk": jdk},
                "expected": {"minJdk": agp_entry["minJdk"]},
                "suggestion": suggestion,
                "reference": ref,
            })

    if kotlin:
        kgp_entry = _find_kgp_entry(kotlin, kgp_entries)
        if kgp_entry is None:
            # Suggest the nearest band by kgpMin distance.
            nearest_k = None
            best_dist = None
            for entry in kgp_entries:
                a = _parse_segments(kotlin)
                b = _parse_segments(entry["kgpMin"])
                pad = max(len(a), len(b), 3)
                a = (a + [0] * pad)[:pad]
                b = (b + [0] * pad)[:pad]
                d = sum(abs(x - y) for x, y in zip(a, b))
                if best_dist is None or d < best_dist:
                    best_dist = d
                    nearest_k = entry
            suggestion = None
            if nearest_k:
                suggestion = {
                    "kotlin": f"{nearest_k['kgpMin']}-{nearest_k['kgpMax']}",
                    "gradle": f"{nearest_k['gradleMin']}-{nearest_k['gradleMax']}",
                    "agp": f"{nearest_k['agpMin']}-{nearest_k['agpMax']}",
                }
            conflicts.append({
                "kind": "kotlin_unknown",
                "requested": {"kotlin": kotlin, "gradle": gradle, "agp": agp},
                "expected": None,
                "suggestion": suggestion,
                "reference": (nearest_k or {}).get("referenceUrl")
                or "https://kotlinlang.org/docs/gradle-configure-project.html",
            })
        else:
            ref = kgp_entry.get("referenceUrl") or (
                "https://kotlinlang.org/docs/gradle-configure-project.html"
            )
            suggestion = {
                "kotlin": f"{kgp_entry['kgpMin']}-{kgp_entry['kgpMax']}",
                "gradle": f"{kgp_entry['gradleMin']}-{kgp_entry['gradleMax']}",
                "agp": f"{kgp_entry['agpMin']}-{kgp_entry['agpMax']}",
            }
            if gradle and not _version_in_closed_range(
                gradle, kgp_entry["gradleMin"], kgp_entry["gradleMax"]
            ):
                conflicts.append({
                    "kind": "kotlin_gradle",
                    "requested": {"kotlin": kotlin, "gradle": gradle},
                    "expected": {
                        "gradleMin": kgp_entry["gradleMin"],
                        "gradleMax": kgp_entry["gradleMax"],
                    },
                    "suggestion": suggestion,
                    "reference": ref,
                })
            if agp and not _version_in_closed_range(
                agp, kgp_entry["agpMin"], kgp_entry["agpMax"]
            ):
                conflicts.append({
                    "kind": "kotlin_agp",
                    "requested": {"kotlin": kotlin, "agp": agp},
                    "expected": {
                        "agpMin": kgp_entry["agpMin"],
                        "agpMax": kgp_entry["agpMax"],
                    },
                    "suggestion": suggestion,
                    "reference": ref,
                })

    if not agp and not kotlin:
        notes.append(
            "android block provided without agp or kotlin; nothing to check against the matrix."
        )
    return conflicts, notes


def check_spring_boot_bom_compatibility(
    spring_boot: str,
    dependencies: List[Dict],
    ctx: "ResolutionContext",
) -> Tuple[List[Dict], List[str]]:
    """Compare requested dependency versions against spring-boot-dependencies BOM."""
    conflicts: List[Dict] = []
    notes: List[str] = []
    managed = expand_bom(
        SPRING_BOOT_BOM_GROUP, SPRING_BOOT_BOM_ARTIFACT, spring_boot, ctx
    )
    if not managed:
        notes.append(
            f"Could not expand {SPRING_BOOT_BOM_GROUP}:{SPRING_BOOT_BOM_ARTIFACT}:{spring_boot}; "
            "Spring Boot BOM checks skipped."
        )
        return conflicts, notes
    managed_map = {
        (m["groupId"], m["artifactId"]): m["version"] for m in managed
    }
    ref = (
        "https://docs.spring.io/spring-boot/docs/current/reference/html/"
        "dependency-versions.html"
    )
    for dep in dependencies:
        gid = dep.get("groupId")
        aid = dep.get("artifactId")
        requested = dep.get("version")
        if not gid or not aid or not requested:
            continue
        expected = managed_map.get((gid, aid))
        if expected is None:
            continue
        if requested == expected:
            continue
        conflicts.append({
            "kind": "spring_boot_bom",
            "requested": {
                "groupId": gid,
                "artifactId": aid,
                "version": requested,
            },
            "expected": {
                "groupId": gid,
                "artifactId": aid,
                "version": expected,
                "managedBy": {
                    "groupId": SPRING_BOOT_BOM_GROUP,
                    "artifactId": SPRING_BOOT_BOM_ARTIFACT,
                    "version": spring_boot,
                },
            },
            "suggestion": {
                "groupId": gid,
                "artifactId": aid,
                "version": expected,
            },
            "reference": ref,
        })
    return conflicts, notes


def check_javax_jakarta_migration(
    spring_boot: Optional[str],
    dependencies: List[Dict],
    matrices: Dict,
) -> Tuple[List[Dict], List[str]]:
    """Flag javax.* EE coordinates when Spring Boot ≥ 3."""
    conflicts: List[Dict] = []
    notes: List[str] = []
    if not spring_boot:
        return conflicts, notes
    # Major-version gate: Boot 3 milestones/RCs (3.0.0-M1) compare < 3.0.0
    # under compare_versions but already require jakarta.*.
    boot_major = (_parse_segments(spring_boot) or [0])[0]
    if boot_major < 3:
        return conflicts, notes
    jmap = matrices.get("jakartaMap") or {}
    ref = (
        "https://github.com/spring-projects/spring-boot/wiki/"
        "Spring-Boot-3.0-Migration-Guide"
    )
    for dep in dependencies:
        gid = dep.get("groupId") or ""
        aid = dep.get("artifactId") or ""
        key = f"{gid}:{aid}"
        replacement = jmap.get(key)
        if replacement:
            jg, ja = replacement.split(":", 1)
            conflicts.append({
                "kind": "javax_to_jakarta",
                "requested": {
                    "groupId": gid,
                    "artifactId": aid,
                    "version": dep.get("version"),
                },
                "expected": {"groupId": jg, "artifactId": ja},
                "suggestion": {"groupId": jg, "artifactId": ja},
                "reference": ref,
            })
            continue
        # Unmapped javax.* still flagged (no concrete replacement known).
        if gid.startswith("javax."):
            conflicts.append({
                "kind": "javax_to_jakarta",
                "requested": {
                    "groupId": gid,
                    "artifactId": aid,
                    "version": dep.get("version"),
                },
                "expected": None,
                "suggestion": None,
                "reference": ref,
            })
    return conflicts, notes


def check_version_compatibility(
    *,
    spring_boot: Optional[str] = None,
    android: Optional[Dict] = None,
    dependencies: Optional[List[Dict]] = None,
    ctx: Optional["ResolutionContext"] = None,
) -> Dict:
    """Core compatibility check used by the MCP tool (#285)."""
    matrices = _load_compat_matrices()
    conflicts: List[Dict] = []
    notes: List[str] = list((matrices.get("_meta") or {}).get("limitations") or [])
    deps = list(dependencies or [])
    if len(deps) > MAX_COMPAT_DEPENDENCIES:
        deps = deps[:MAX_COMPAT_DEPENDENCIES]
        notes.append(
            f"dependencies truncated to {MAX_COMPAT_DEPENDENCIES} items "
            "(handler-enforced cap)."
        )

    if android:
        c, n = check_android_kotlin_compatibility(android, matrices)
        conflicts.extend(c)
        notes.extend(n)

    if spring_boot:
        if ctx is None:
            notes.append(
                "No resolution context; Spring Boot BOM expansion skipped."
            )
        else:
            c, n = check_spring_boot_bom_compatibility(spring_boot, deps, ctx)
            conflicts.extend(c)
            notes.extend(n)
        c, n = check_javax_jakarta_migration(spring_boot, deps, matrices)
        conflicts.extend(c)
        notes.extend(n)
    elif deps and any(
        (d.get("groupId") or "").startswith("javax.") for d in deps
    ):
        notes.append(
            "javax.* coordinates present but springBoot was not set; "
            "javax→jakarta migration check skipped (requires Spring Boot ≥ 3)."
        )

    if not spring_boot and not android and not deps:
        notes.append(
            "No springBoot, android, or dependencies provided; nothing to check."
        )

    # De-dupe identical limitation notes that we always attach — keep order,
    # but drop exact duplicate strings from the dynamic notes path.
    seen_notes = set()
    unique_notes: List[str] = []
    for note in notes:
        if note in seen_notes:
            continue
        seen_notes.add(note)
        unique_notes.append(note)

    return {
        "compatible": len(conflicts) == 0,
        "conflicts": conflicts,
        "notes": unique_notes,
    }


# ---------------------------------------------------------------------------
# Version classification & comparison
# ---------------------------------------------------------------------------

def classify_version(version: str) -> str:
    for pattern, stability in STABILITY_PATTERNS:
        if pattern.search(version):
            return stability
    return "stable"


# Digits attached to known prerelease tokens only — free-text qualifier digits
# (e.g. "0.6.x-compat") must not be treated as ordinal prerelease numbers (#331).
_PRERELEASE_ORDINAL_RE = re.compile(
    r"(?:alpha|a(?=\d)|beta|b(?=\d)|milestone|m(?=\d)|rc|cr|snapshot)[-.]?(\d+)",
    re.IGNORECASE,
)


def _split_core_and_qualifier(version: str) -> Tuple[str, str]:
    """Split a version into numeric core and qualifier suffix.

    Qualifier begins at the earliest of: ``-`` / ``+``, a ``.`` whose next
    segment is non-numeric (``.Final`` / ``.RELEASE``), or a non-digit glued
    onto the core (``1.0.0legacy`` / ``1.0.0_legacy``). Pure numeric dotted
    tails (``1.0.0.1``) stay in the core.
    """
    if not version:
        return "", ""
    i = 0
    n = len(version)
    while i < n and version[i].isdigit():
        i += 1
    while i < n and version[i] == ".":
        j = i + 1
        while j < n and version[j].isdigit():
            j += 1
        if j == i + 1:
            # Non-numeric segment after '.' — qualifier boundary (#331).
            return version[:i], version[i:]
        i = j
    if i < n:
        return version[:i], version[i:]
    return version, ""


def _parse_segments(version: str) -> List[int]:
    core, _qual = _split_core_and_qualifier(version)
    parts = []
    for p in core.split("."):
        if not p:
            continue
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts or [0]


def _extract_prerelease_numbers(version: str) -> List[int]:
    _core, qual = _split_core_and_qualifier(version)
    if not qual:
        return []
    return [int(m.group(1)) for m in _PRERELEASE_ORDINAL_RE.finditer(qual)]


def _compare_int_lists(a: List[int], b: List[int]) -> int:
    max_len = max(len(a), len(b), 1)
    for i in range(max_len):
        ai = a[i] if i < len(a) else 0
        bi = b[i] if i < len(b) else 0
        if ai != bi:
            return -1 if ai < bi else 1
    return 0


def compare_versions(a: str, b: str) -> int:
    """Returns negative if a < b, positive if a > b, 0 if equal."""
    core_diff = _compare_int_lists(_parse_segments(a), _parse_segments(b))
    if core_diff != 0:
        return core_diff
    weight_diff = PRERELEASE_WEIGHT.get(classify_version(a), 5) - PRERELEASE_WEIGHT.get(classify_version(b), 5)
    if weight_diff != 0:
        return weight_diff
    has_suffix_a = bool(_split_core_and_qualifier(a)[1])
    has_suffix_b = bool(_split_core_and_qualifier(b)[1])
    if has_suffix_a != has_suffix_b:
        # #325/#331: same core, same stability class, but only one side carries
        # a qualifier at all — the bare version always ranks higher.
        return 1 if not has_suffix_a else -1
    tail_diff = _compare_int_lists(_extract_prerelease_numbers(a), _extract_prerelease_numbers(b))
    if tail_diff != 0:
        return tail_diff
    return -1 if a < b else (1 if a > b else 0)


def find_latest_version(versions: List[str], filter_mode: str = "PREFER_STABLE") -> Optional[str]:
    if not versions:
        return None
    if filter_mode == "ALL":
        return versions[-1]
    # Scan from the end for last stable
    stable = None
    for v in reversed(versions):
        if classify_version(v) == "stable":
            stable = v
            break
    if filter_mode == "STABLE_ONLY":
        return stable
    # PREFER_STABLE: stable if found, otherwise last version
    return stable if stable is not None else versions[-1]


def find_latest_version_for_current(versions: List[str], current_version: str) -> Optional[str]:
    """Highest version newer-or-equal to current at acceptable stability, else None.

    A candidate qualifies iff it is newer-than-or-equal to current AND ranks at
    least as stable on snapshot < alpha < beta < milestone < rc < stable; an
    up-to-date dependency thus returns current itself (upgradeType "none"),
    never a less-stable SNAPSHOT/RC as an upgrade from a more stable current
    (#312). None only when nothing at acceptable stability is >= current.
    """
    current_rank = PRERELEASE_WEIGHT.get(classify_version(current_version), 5)
    for v in reversed(versions):
        if compare_versions(v, current_version) >= 0 and PRERELEASE_WEIGHT.get(classify_version(v), 5) >= current_rank:
            return v
    return None


def get_upgrade_type(current: str, latest: str) -> str:
    if compare_versions(latest, current) <= 0:
        return "none"
    cur = _parse_segments(current)
    lat = _parse_segments(latest)
    max_len = max(len(cur), len(lat))
    while len(cur) < max_len:
        cur.append(0)
    while len(lat) < max_len:
        lat.append(0)
    if lat[0] != cur[0]:
        return "major"
    if len(lat) > 1 and len(cur) > 1 and lat[1] != cur[1]:
        return "minor"
    if len(lat) > 2 and len(cur) > 2 and lat[2] != cur[2]:
        return "patch"
    return "patch"


# ---------------------------------------------------------------------------
# String distance & Solr query escaping
# ---------------------------------------------------------------------------

def _levenshtein(a: str, b: str) -> int:
    """Plain Levenshtein edit distance (insert/delete/substitute, each cost 1).

    NOT Damerau: an adjacent transposition is two substitutions, so
    ``_levenshtein("ab", "ba") == 2``. Iterative two-row DP, stdlib only.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def _similarity(a: str, b: str) -> float:
    """Normalized edit-distance similarity in [0, 1].

    ``1 - _levenshtein(a, b) / max(len(a), len(b), 1)``. Two empty strings score
    1.0 (the ``max(..., 1)`` keeps the divisor non-zero so 0/1 = 0). Levenshtein
    never exceeds the longer length, so the result needs no clamping.
    """
    return 1.0 - _levenshtein(a, b) / max(len(a), len(b), 1)


# Lucene/Solr query metacharacters; ``&&`` / ``||`` operators are handled by
# escaping each ``&`` / ``|``. Whitespace is escaped separately (below) so a
# bareword operator like ``OR`` cannot survive as a whitespace-delimited token.
_SOLR_SPECIAL = set('+-&|!(){}[]^"~*?:\\/')


def _solr_escape(token: str) -> str:
    """Backslash-escape Solr/Lucene query metacharacters and whitespace.

    A token passed straight into a Solr query could otherwise be parsed as query
    syntax (``*`` wildcard, ``:`` field separator, a bareword ``OR``). Each
    special char and each whitespace char is prefixed with a backslash, so the
    whole token is interpreted literally as a single term.
    """
    out = []
    for ch in token:
        if ch in _SOLR_SPECIAL or ch.isspace():
            out.append("\\")
        out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# GitHub utilities
# ---------------------------------------------------------------------------

GITHUB_REPO_RE = re.compile(r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def _strip_xml_comments(xml: str) -> str:
    prev = None
    while prev != xml:
        prev = xml
        xml = re.sub(r"<!--[\s\S]*?-->", "", xml)
    return xml


def extract_github_repo_from_pom(pom_xml: str) -> Optional[Dict[str, str]]:
    xml = _strip_xml_comments(pom_xml)

    def _parse_github_url(url: str) -> Optional[Dict[str, str]]:
        m = GITHUB_REPO_RE.search(url)
        if not m:
            return None
        owner = m.group(1)
        repo = m.group(2).rstrip("/")
        repo = re.sub(r"\.git$", "", repo)
        repo = repo.split("/")[0]
        return {"owner": owner, "repo": repo}

    scm_match = re.search(r"<scm>([\s\S]*?)</scm>", xml)
    if scm_match:
        block = scm_match.group(1)
        for tag in ("url", "connection", "developerConnection"):
            m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", block)
            if m:
                r = _parse_github_url(m.group(1))
                if r:
                    return r

    # Fallback: root <url>
    without_scm = re.sub(r"<scm>[\s\S]*?</scm>", "", xml)
    m = re.search(r"<url>\s*(.*?)\s*</url>", without_scm)
    if m:
        return _parse_github_url(m.group(1))
    return None


def extract_scm_url_from_pom(pom_xml: str) -> Optional[str]:
    xml = _strip_xml_comments(pom_xml)

    def _clean(v: str) -> str:
        return re.sub(r"^scm:[a-z]+:", "", v, flags=re.IGNORECASE)

    scm_match = re.search(r"<scm>([\s\S]*?)</scm>", xml)
    if scm_match:
        block = scm_match.group(1)
        for tag in ("url", "connection", "developerConnection"):
            m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", block)
            if m and m.group(1):
                return _clean(m.group(1).strip())

    without_scm = re.sub(r"<scm>[\s\S]*?</scm>", "", xml)
    m = re.search(r"<url>\s*(.*?)\s*</url>", without_scm)
    if m and m.group(1):
        return m.group(1).strip()
    return None


def extract_licenses_from_pom(pom_xml: str) -> List[str]:
    xml = _strip_xml_comments(pom_xml)
    block_m = re.search(r"<licenses>([\s\S]*?)</licenses>", xml)
    if not block_m:
        return []
    names = []
    for m in re.finditer(r"<license>([\s\S]*?)</license>", block_m.group(1)):
        name_m = re.search(r"<name>\s*(.*?)\s*</name>", m.group(1))
        if name_m and name_m.group(1):
            names.append(name_m.group(1).strip())
    return names


def extract_relocation_from_pom(
    pom_xml: str, group_id: str, artifact_id: str, version: str
) -> Optional[Dict[str, str]]:
    """Extract Maven artifact relocation (`<distributionManagement><relocation>`)
    from a POM (#284). Returns None when there is no `<relocation>` block.

    Per Maven's relocation spec, any of groupId/artifactId/version absent
    inside `<relocation>` means "unchanged from the original coordinate" for
    that field — e.g. a relocation POM specifying only a new `<artifactId>`
    means the groupId/version carry over. The missing fields are filled in
    from the original coordinate here so callers get a complete, directly-usable
    coordinate rather than a partial one they would have to merge themselves.

    The `<relocation>` search is scoped to inside `<distributionManagement>`
    only — Maven Shade Plugin's `<configuration><relocations><relocation>`
    (package relocation for shading, an unrelated concept) also uses the
    `<relocation>` tag, so an unscoped search would false-positive on a POM
    that shades dependencies but never relocates its own coordinates."""
    xml = _strip_xml_comments(pom_xml)
    dm_m = re.search(
        r"<distributionManagement>([\s\S]*?)</distributionManagement>", xml
    )
    if not dm_m:
        return None
    reloc_m = re.search(r"<relocation>([\s\S]*?)</relocation>", dm_m.group(1))
    if not reloc_m:
        return None
    block = reloc_m.group(1)
    gid_m = re.search(r"<groupId>([^<]+)</groupId>", block)
    aid_m = re.search(r"<artifactId>([^<]+)</artifactId>", block)
    ver_m = re.search(r"<version>([^<]+)</version>", block)
    return {
        "groupId": gid_m.group(1).strip() if gid_m else group_id,
        "artifactId": aid_m.group(1).strip() if aid_m else artifact_id,
        "version": ver_m.group(1).strip() if ver_m else version,
    }


def _gradle_plugin_marker_plugin_id(group_id: str, artifact_id: str) -> Optional[str]:
    """Returns the plugin id if (group_id, artifact_id) is a Gradle plugin marker
    coordinate (`{pluginId}:{pluginId}.gradle.plugin`), else None. Stricter than the
    `.gradle.plugin`-suffix-only check used for repo-scope routing (_repos_for) —
    that check stays suffix-only by design (see CLAUDE.md); this one additionally
    requires group_id == pluginId, which is the actual marker shape, since it
    drives POM-dependency resolution, not just repo routing."""
    suffix = ".gradle.plugin"
    if not artifact_id.endswith(suffix):
        return None
    plugin_id = artifact_id[: -len(suffix)]
    if not plugin_id or group_id != plugin_id:
        return None
    return plugin_id


def resolve_plugin_marker_implementation(
    group_id: str, artifact_id: str, version: Optional[str], ctx: "ResolutionContext"
) -> Optional[Dict[str, str]]:
    """Gradle plugin marker artifacts are minimal POMs whose only purpose is a
    single <dependency> pointing at the real implementation artifact — OSV indexes
    the implementation, not the marker, so callers must resolve markers before
    querying vulnerabilities (#290). Returns {groupId, artifactId, version} of the
    resolved implementation, or None when the coordinate isn't a marker, or
    resolution fails for any reason (missing version, POM fetch failure, no/
    incomplete <dependency> block, unresolved ${...} property) — callers MUST
    degrade gracefully on None, never raise."""
    if not _gradle_plugin_marker_plugin_id(group_id, artifact_id):
        return None
    if not version:
        return None
    pom = fetch_pom(group_id, artifact_id, version, ctx)
    if not pom:
        return None
    xml = _strip_xml_comments(pom)
    # Drop any <dependencyManagement> block before searching: it holds version
    # pins, not the marker's real implementation dependency, and an unscoped
    # search would match a <dependency> inside it first if one is present.
    # NOTE: duplicates _parse_maven_deps' dependency-block extraction (~1508)
    # with slightly different field requirements; not unified to keep this fix
    # minimal — candidate for a future shared single-dependency-block parser.
    xml = re.sub(r"<dependencyManagement>[\s\S]*?</dependencyManagement>", "", xml)
    dep_m = re.search(r"<dependency>([\s\S]*?)</dependency>", xml)
    if not dep_m:
        return None
    block = dep_m.group(1)
    gid_m = re.search(r"<groupId>([^<]+)</groupId>", block)
    aid_m = re.search(r"<artifactId>([^<]+)</artifactId>", block)
    ver_m = re.search(r"<version>([^<]+)</version>", block)
    if not gid_m or not aid_m or not ver_m:
        return None
    impl_group_id = gid_m.group(1).strip()
    impl_artifact_id = aid_m.group(1).strip()
    impl_version = ver_m.group(1).strip()
    if not impl_group_id or not impl_artifact_id or not impl_version:
        return None
    if impl_version.startswith("${"):
        return None
    return {"groupId": impl_group_id, "artifactId": impl_artifact_id, "version": impl_version}


def guess_github_repo(group_id: str, artifact_id: str) -> Optional[Dict[str, str]]:
    for prefix in ("com.github.", "io.github."):
        if group_id.startswith(prefix) and len(group_id) > len(prefix):
            rest = group_id[len(prefix):]
            owner = rest.split(".")[0]
            return {"owner": owner, "repo": artifact_id}
    return None


def scm_host(url: str) -> str:
    if not url:
        return "other"
    scp_m = re.match(r"^[^/@]+@([^:/]+):", url)
    if scp_m:
        host = scp_m.group(1).lower()
    else:
        m = re.match(r"https?://([^/]+)", url)
        host = m.group(1).lower() if m else ""
    if host in ("github.com",) or host.endswith(".github.com"):
        return "github"
    if host in ("gitlab.com",) or host.endswith(".gitlab.com"):
        return "gitlab"
    if host in ("bitbucket.org",) or host.endswith(".bitbucket.org"):
        return "bitbucket"
    return "other"


def _gh_get(path: str) -> Optional[Any]:
    url = f"{GITHUB_API}{path}"
    try:
        status, body = http_get(url, _github_headers())
        if status == 200:
            return json.loads(body)
    except Exception:
        pass  # Network or parse error — caller treats None as "unavailable"
    return None


def gh_repo_exists(owner: str, repo: str) -> bool:
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    try:
        status, _ = http_get(url, _github_headers())
        return status == 200
    except Exception:
        return False


def gh_fetch_repo(owner: str, repo: str) -> Optional[Dict]:
    return _gh_get(f"/repos/{owner}/{repo}")


def gh_fetch_releases(owner: str, repo: str) -> List[Dict]:
    data = _gh_get(f"/repos/{owner}/{repo}/releases?per_page=100")
    return data if isinstance(data, list) else []


def gh_fetch_user(login: str) -> Optional[Dict]:
    return _gh_get(f"/users/{login}")


def gh_fetch_issue_stats(owner: str, repo: str) -> Optional[Dict]:
    def search_count(state: str) -> Optional[int]:
        q = urllib.parse.quote(f"repo:{owner}/{repo} type:issue state:{state}")
        data = _gh_get(f"/search/issues?q={q}&per_page=1")
        if data and isinstance(data.get("total_count"), int):
            return data["total_count"]
        return None

    def median_days_to_close() -> Optional[int]:
        q = urllib.parse.quote(f"repo:{owner}/{repo} type:issue state:closed")
        data = _gh_get(f"/search/issues?q={q}&sort=updated&order=desc&per_page=30")
        if not data or not isinstance(data.get("items"), list):
            return None
        durations = []
        for item in data["items"]:
            ca = item.get("created_at")
            cl = item.get("closed_at")
            if ca and cl:
                import datetime
                try:
                    t_created = _parse_iso(ca)
                    t_closed = _parse_iso(cl)
                    diff = (t_closed - t_created).total_seconds()
                    if diff >= 0:
                        durations.append(diff)
                except Exception:
                    pass  # Skip malformed date strings in issue timeline
        if not durations:
            return None
        durations.sort()
        mid = len(durations) // 2
        if len(durations) % 2 == 1:
            median_sec = durations[mid]
        else:
            median_sec = (durations[mid - 1] + durations[mid]) / 2
        return round(median_sec / 86400)

    open_count = search_count("open")
    closed_count = search_count("closed")
    if open_count is None and closed_count is None:
        return None
    total = (open_count or 0) + (closed_count or 0)
    close_ratio = (closed_count / total) if (open_count is not None and closed_count is not None and total > 0) else None
    median_days = median_days_to_close()
    return {
        "open": open_count,
        "closed": closed_count,
        "closeRatio": close_ratio,
        "medianDaysToClose": median_days,
    }


def _parse_iso(s: str):
    import datetime
    # Handle Z suffix
    s = s.replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        # Fallback for Python 3.6 which doesn't support +00:00 in fromisoformat
        return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def _months_since(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        import datetime
        dt = _parse_iso(iso)
        # datetime.utcnow() is deprecated on Python 3.12+; now(timezone.utc) is the
        # replacement. tzinfo is stripped so `now` stays offset-naive: `dt` is forced
        # naive just below, and subtracting a naive from an aware datetime raises
        # TypeError. The wall-clock UTC value is identical to the old utcnow(), so the
        # months delta is unchanged.
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        # Make both offset-naive for comparison
        if hasattr(dt, 'utcoffset') and dt.utcoffset() is not None:
            dt = dt.replace(tzinfo=None)
        delta = now - dt
        return int(delta.days / 30)
    except Exception:
        return None


def _summarize_releases(releases: List[Dict]) -> Dict:
    import datetime
    times = []
    for r in releases:
        if r.get("draft") or r.get("prerelease"):
            continue
        pub = r.get("published_at")
        if not pub:
            continue
        try:
            dt = _parse_iso(pub)
            times.append((dt, pub))
        except Exception:
            pass  # Skip releases with unparseable published_at dates
    times.sort(key=lambda x: x[0], reverse=True)
    count = len(times)
    if count == 0:
        return {"last": None, "cadenceDays": None, "count": 0}
    last = times[0][1]
    if count < 2:
        return {"last": last, "cadenceDays": None, "count": count}
    gaps = []
    for i in range(len(times) - 1):
        diff = (times[i][0] - times[i + 1][0]).total_seconds()
        gaps.append(diff)
    gaps.sort()
    mid = len(gaps) // 2
    if len(gaps) % 2 == 1:
        median_sec = gaps[mid]
    else:
        median_sec = (gaps[mid - 1] + gaps[mid]) / 2
    return {"last": last, "cadenceDays": round(median_sec / 86400), "count": count}


def discover_github_repo(group_id: str, artifact_id: str, version: str, ctx: "ResolutionContext") -> Optional[Dict[str, str]]:
    """Try POM SCM, then guess from groupId. Returns {owner, repo} or None."""
    pom = fetch_pom(group_id, artifact_id, version, ctx)
    if pom:
        r = extract_github_repo_from_pom(pom)
        if r:
            return r
    guess = guess_github_repo(group_id, artifact_id)
    if guess and gh_repo_exists(guess["owner"], guess["repo"]):
        return guess
    return None


# ---------------------------------------------------------------------------
# GitHub changelog / releases for get_dependency_changes
# ---------------------------------------------------------------------------

def _filter_version_range(versions: List[str], from_v: str, to_v: str) -> List[str]:
    """Return versions between from_v (exclusive) and to_v (inclusive)."""
    result = []
    for v in versions:
        gt_from = compare_versions(v, from_v) > 0
        le_to = compare_versions(v, to_v) <= 0
        if gt_from and le_to:
            result.append(v)
    return result


def _get_dependency_changes_impl(group_id: str, artifact_id: str, from_version: str, to_version: str, ctx: "ResolutionContext") -> Dict:
    base = {
        "groupId": group_id,
        "artifactId": artifact_id,
        "fromVersion": from_version,
        "toVersion": to_version,
        "changes": [],
    }
    try:
        metadata = fetch_metadata(group_id, artifact_id, ctx)
    except Exception as e:
        return {**base, "error": str(e)}
    base["resolvedFrom"] = metadata.get("resolvedFrom")

    versions_in_range = _filter_version_range(metadata["versions"], from_version, to_version)
    if not versions_in_range:
        return {**base, "error": f"No versions found between {from_version} and {to_version}"}

    gh_repo = discover_github_repo(group_id, artifact_id, to_version, ctx)
    if not gh_repo:
        return {**base, "repositoryNotFound": True}

    owner, repo = gh_repo["owner"], gh_repo["repo"]
    releases = gh_fetch_releases(owner, repo)

    # Build a map from version string to release info
    release_map: Dict[str, Dict] = {}
    for rel in releases:
        tag = rel.get("tag_name", "")
        # Try to match tag to version: strip leading 'v' or prefix
        candidate = re.sub(r"^[^0-9]*", "", tag)
        if candidate in versions_in_range:
            release_map[candidate] = rel
        elif tag in versions_in_range:
            release_map[tag] = rel

    changes = []
    for v in versions_in_range:
        rel = release_map.get(v)
        if rel:
            change = {"version": v}
            if rel.get("html_url"):
                change["releaseUrl"] = rel["html_url"]
            if rel.get("body"):
                change["body"] = rel["body"]
            changes.append(change)
        else:
            changes.append({"version": v})

    return {
        **base,
        "repositoryUrl": f"https://github.com/{owner}/{repo}",
        "changes": changes,
    }


# ---------------------------------------------------------------------------
# OSV vulnerability client
# ---------------------------------------------------------------------------

def _cvss_to_severity(score: float) -> str:
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW"


def _extract_severity(vuln: Dict) -> Optional[str]:
    raw = (vuln.get("database_specific") or {}).get("severity", "")
    if raw:
        normalized = raw.upper()
        if normalized == "MODERATE":
            normalized = "MEDIUM"
        if normalized in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            return normalized
    for sev in (vuln.get("severity") or []):
        if sev.get("type") in ("CVSS_V3", "CVSS_V4"):
            try:
                return _cvss_to_severity(float(sev["score"]))
            except (ValueError, TypeError, KeyError):
                pass
    return None


def _extract_fixed_version(vuln: Dict) -> Optional[str]:
    for affected in (vuln.get("affected") or []):
        for rng in (affected.get("ranges") or []):
            if rng.get("type") != "ECOSYSTEM":
                continue
            for event in (rng.get("events") or []):
                if "fixed" in event:
                    return event["fixed"]
    return None


def _extract_url(vuln: Dict) -> str:
    for ref in (vuln.get("references") or []):
        if ref.get("type") == "ADVISORY":
            return ref.get("url", "")
    return f"https://osv.dev/vulnerability/{vuln['id']}"


def _is_malicious_id(vuln_id: str) -> bool:
    """OSSF Malicious Packages reports ingested into OSV.dev use the ``MAL-``
    id prefix (documented OSSF/OSV convention, empirically confirmed live
    against a real Maven typosquat report -- see plan.md#322 Verification &
    Sources). This is a best-effort CONVENTION, not a schema-guaranteed
    contract: ``False`` means "not currently flagged under this convention",
    never "verified non-malicious" (mirrors how `likelyHallucination`'s "never
    means safe" caveat travels with that field)."""
    return vuln_id.startswith("MAL-")


def _fetch_osv_vuln(vuln_id: str) -> Optional[Dict]:
    """GET /v1/vulns/{id}. Returns the parsed vuln dict, or None on any failure."""
    url = f"{OSV_VULN_API}/{urllib.parse.quote(vuln_id, safe='-._')}"
    try:
        status, body = http_get(url)
        if status != 200:
            return None
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _hydrate_osv_vulns(vuln_ids: List[str]) -> Dict[str, Dict]:
    """Fetch full OSV records for unique IDs (first-seen order), capped.

    Returns id → full vuln dict for successful hydrations only. IDs skipped by
    the cap or failed fetches are absent — callers keep the bare querybatch
    entry for those. Counts each network attempt toward MAX_OSV_VULN_HYDRATIONS
    (same operational-bound pattern as MAX_GATED_SOLR_CALLS_PER_BATCH).
    """
    out: Dict[str, Dict] = {}
    seen: set = set()
    attempts = 0
    for vid in vuln_ids:
        if not vid or vid in seen:
            continue
        seen.add(vid)
        if attempts >= MAX_OSV_VULN_HYDRATIONS:
            continue
        attempts += 1
        full = _fetch_osv_vuln(vid)
        if full is not None:
            out[vid] = full
    return out


def _vuln_info_from_osv(v: Dict) -> Dict:
    """Build the public per-vuln dict from a (possibly hydrated) OSV record."""
    vuln_id = v.get("id", "")
    vuln_info: Dict = {
        "id": vuln_id,
        "summary": v.get("summary", ""),
        "url": _extract_url(v),
        "malicious": _is_malicious_id(vuln_id),
    }
    sev = _extract_severity(v)
    if sev:
        vuln_info["severity"] = sev
    fixed = _extract_fixed_version(v)
    if fixed:
        vuln_info["fixedVersion"] = fixed
    return vuln_info


def query_osv_batch(deps: List[Dict]) -> List[Dict]:
    """deps: list of {groupId, artifactId, version}. Returns list of {groupId, artifactId, version, vulnerabilities}.

    Chunks into ≤OSV_QUERYBATCH_MAX queries per POST (OSV.dev documented limit)
    and concatenates per-chunk results in input order. A failed chunk degrades
    only that slice to empty vulnerabilities — siblings still resolve.

    /v1/querybatch returns only ``{id, modified}`` per vuln; severity, summary,
    references, and fixed-version ranges require a follow-up GET /v1/vulns/{id}
    (#338). Unique IDs are hydrated once per call (deduped, first-seen order),
    capped at MAX_OSV_VULN_HYDRATIONS; failed/capped IDs keep the bare entry
    (id + malicious still work; severity may be absent).
    """
    if not deps:
        return []
    # Phase 1: querybatch chunks → (dep, bare vulns_raw) pairs.
    bare_pairs: List[Tuple[Dict, List[Dict]]] = []
    for start in range(0, len(deps), OSV_QUERYBATCH_MAX):
        bare_pairs.extend(
            _query_osv_batch_chunk_bare(deps[start:start + OSV_QUERYBATCH_MAX])
        )
    # Phase 2: hydrate unique IDs across the whole batch (one GET per id).
    ids_ordered: List[str] = []
    for _, vulns_raw in bare_pairs:
        for v in vulns_raw:
            vid = v.get("id") or ""
            if vid:
                ids_ordered.append(vid)
    hydrated = _hydrate_osv_vulns(ids_ordered)
    # Phase 3: merge hydrated records and extract public fields.
    out: List[Dict] = []
    for dep, vulns_raw in bare_pairs:
        vulns = []
        for v in vulns_raw:
            vid = v.get("id") or ""
            full = hydrated.get(vid, v)
            if full.get("withdrawn") is not None:
                continue
            # Prefer hydrated id when present; bare querybatch always has id.
            if not full.get("id") and vid:
                full = {**full, "id": vid}
            vulns.append(_vuln_info_from_osv(full))
        out.append({**dep, "vulnerabilities": vulns})
    return out


def _query_osv_batch_chunk_bare(deps: List[Dict]) -> List[Tuple[Dict, List[Dict]]]:
    """POST one ≤OSV_QUERYBATCH_MAX querybatch; return (dep, vulns_raw) pairs.

    On non-200 / error every dep gets an empty vulns_raw list. Does not hydrate
    or filter withdrawn — that happens after /v1/vulns/{id} merge.
    """
    queries = [
        {"package": {"name": f"{d['groupId']}:{d['artifactId']}", "ecosystem": "Maven"}, "version": d["version"]}
        for d in deps
    ]
    try:
        status, body = http_post_json(OSV_API, {"queries": queries})
        if status != 200:
            return [(d, []) for d in deps]
        data = json.loads(body)
        results = data.get("results", [])
        out: List[Tuple[Dict, List[Dict]]] = []
        for i, dep in enumerate(deps):
            vulns_raw = (results[i].get("vulns") or []) if i < len(results) else []
            out.append((dep, list(vulns_raw)))
        return out
    except Exception:
        return [(d, []) for d in deps]


# ---------------------------------------------------------------------------
# Maven Central search
# ---------------------------------------------------------------------------

def search_maven_central(query: str, limit: int = 10, use_cache: bool = True) -> List[Dict]:
    try:
        url = f"{SEARCH_API}?q={urllib.parse.quote(query)}&rows={limit}&wt=json"
        status, body = http_get_cached(url, TTL_SEARCH) if use_cache else http_get(url)
        if status != 200:
            return []
        data = json.loads(body)
        docs = data.get("response", {}).get("docs", [])
        return [
            {
                "groupId": d.get("g", ""),
                "artifactId": d.get("a", ""),
                "latestVersion": d.get("latestVersion", ""),
                "versionCount": d.get("versionCount", 0),
            }
            for d in docs
        ]
    except Exception:
        return []


def _fetch_gav_timestamp(group_id: str, artifact_id: str, version: str) -> Optional[int]:
    """Fetch the Solr ``gav``-core doc's ``timestamp`` (epoch millis) for one
    exact (groupId, artifactId, version) -- used only as a gated, best-effort
    "recent first-publish" enrichment for `typosquatRisk` (#322).

    NOT a call site against `search_maven_central()`: that helper hard-codes an
    implicit-default-core request and its response transform only extracts
    g/a/latestVersion/versionCount -- it has no `core` param and would silently
    drop `timestamp` even if Solr returned it. This is different request shape
    against the same host, hence a new function.

    All three interpolated values go through `_solr_escape` -- `verify_coordinates`
    is a directly callable MCP tool (not gated by the hook's own charset
    pre-filter), and Maven Central version strings are not guaranteed
    alnum-only, so missing escaping here would be a Solr query-syntax
    injection/match-broadening risk. Returns None on any non-200/parse failure
    (silent degrade, never raise).
    """
    query = 'g:"%s" AND a:"%s" AND v:"%s"' % (
        _solr_escape(group_id), _solr_escape(artifact_id), _solr_escape(version),
    )
    try:
        url = f"{SEARCH_API}?q={urllib.parse.quote(query)}&core=gav&rows=1&wt=json"
        status, body = http_get_cached(url, TTL_SEARCH)
        if status != 200:
            return None
        data = json.loads(body)
        docs = data.get("response", {}).get("docs", [])
        if not docs:
            return None
        return docs[0].get("timestamp")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dependency scanning (local file system)
# ---------------------------------------------------------------------------

def _is_excluded_path(path: str) -> bool:
    excluded = (".gradle" + os.sep, "build" + os.sep, ".idea" + os.sep)
    # Normalize to use os.sep
    np = path.replace("/", os.sep)
    for ex in excluded:
        if ex in np:
            return True
    # Also check directory components directly
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part in (".gradle", "build", ".idea"):
            return True
    return False


def _is_test_configuration(config: str) -> bool:
    if config.startswith("test"):
        return True
    return bool(re.search(r"[a-z]Test", config))


def _parse_toml_catalog(content: str) -> Dict:
    """Returns {libraries: {alias: {groupId, artifactId, version}}, plugins: {alias: {id, version}}}"""
    libraries: Dict[str, Dict] = {}
    plugins: Dict[str, Dict] = {}
    versions: Dict[str, str] = {}

    m = re.search(r"\[versions\]([\s\S]*?)(?=\n\[|$)", content)
    if m:
        for lm in re.finditer(r"^(\S+)\s*=\s*\"([^\"]+)\"", m.group(1), re.MULTILINE):
            versions[lm.group(1)] = lm.group(2)

    m = re.search(r"\[libraries\]([\s\S]*?)(?=\n\[|$)", content)
    if m:
        for lm in re.finditer(r"^(\S+)\s*=\s*\{([^}]+)\}", m.group(1), re.MULTILINE):
            alias = lm.group(1)
            props = lm.group(2)
            group_id = None
            artifact_id = None
            version = None

            mod_m = re.search(r'module\s*=\s*"([^"]+):([^"]+)"', props)
            if mod_m:
                group_id = mod_m.group(1)
                artifact_id = mod_m.group(2)

            g_m = re.search(r'group\s*=\s*"([^"]+)"', props)
            n_m = re.search(r'name\s*=\s*"([^"]+)"', props)
            if g_m and n_m:
                group_id = g_m.group(1)
                artifact_id = n_m.group(1)

            vref_m = re.search(r'version\.ref\s*=\s*"([^"]+)"', props)
            if vref_m:
                version = versions.get(vref_m.group(1))
            else:
                vinline_m = re.search(r'\bversion\s*=\s*"([^"]+)"', props)
                if vinline_m:
                    version = vinline_m.group(1)

            if group_id and artifact_id:
                libraries[alias] = {"groupId": group_id, "artifactId": artifact_id, "version": version}

        # Shorthand: alias = "group:artifact:version" or "group:artifact"
        for lm in re.finditer(r'^(\S+)\s*=\s*"([^"]+):([^":]+)(?::([^"]+))?"', m.group(1), re.MULTILINE):
            alias = lm.group(1)
            if alias not in libraries:
                gid = lm.group(2)
                aid = lm.group(3)
                ver = lm.group(4)
                libraries[alias] = {"groupId": gid, "artifactId": aid, "version": ver}

    m = re.search(r"\[plugins\]([\s\S]*?)(?=\n\[|$)", content)
    if m:
        plugins_section = m.group(1)
        # Shorthand: alias = "id:version"
        for lm in re.finditer(r'^(\S+)\s*=\s*"([^":]+):([^"]+)"', plugins_section, re.MULTILINE):
            plugins[lm.group(1)] = {"id": lm.group(2), "version": lm.group(3)}
        # Inline table
        for lm in re.finditer(r"^(\S+)\s*=\s*\{([^}]+)\}", plugins_section, re.MULTILINE):
            alias = lm.group(1)
            if alias in plugins:
                continue
            props = lm.group(2)
            id_m = re.search(r'\bid\s*=\s*"([^"]+)"', props)
            if not id_m:
                continue
            plugin_id = id_m.group(1)
            version = None
            vref_m = re.search(r'version\.ref\s*=\s*"([^"]+)"', props)
            if vref_m:
                version = versions.get(vref_m.group(1))
            else:
                vinline_m = re.search(r'\bversion\s*=\s*"([^"]+)"', props)
                if vinline_m:
                    version = vinline_m.group(1)
            plugins[alias] = {"id": plugin_id, "version": version}

    return {"libraries": libraries, "plugins": plugins}


def _parse_gradle_deps(content: str, source_file: str) -> List[Dict]:
    """Returns list of dep dicts with keys: groupId, artifactId, version,
    configuration, catalogRef, isPlatform, platformKind."""
    deps = []
    config_pattern = _GRADLE_CONFIGURATION_PATTERN

    # String notation: implementation("group:artifact:version")
    # Optional platform()/enforcedPlatform() wrapper around the quoted GAV (#346/#286).
    # Version stops at ':' (classifier) or '@' (extension); trailing
    # `:classifier` / `@ext` / `:classifier@ext` are optional and discarded.
    string_re = re.compile(
        rf'\b({config_pattern})\s*[( ]\s*'
        rf'(?:(enforcedPlatform|platform)\s*\(\s*)?'
        rf'["\']'
        rf'([^"\':\s]+):([^"\':\s]+)'
        rf'(?::([^"\':@]+))?(?::[^"\'@]+)?(?:@[^"\']+)?["\']',
    )
    for m in string_re.finditer(content):
        platform_kind = m.group(2)  # "platform" | "enforcedPlatform" | None
        deps.append({
            "groupId": m.group(3),
            "artifactId": m.group(4),
            "version": m.group(5),
            "configuration": m.group(1),
            "catalogRef": None,
            "isPlatform": platform_kind is not None,
            "platformKind": platform_kind,
        })

    # Catalog accessor: implementation(libs.foo.bar) or
    # implementation(platform(libs.foo.bar)) / enforcedPlatform(libs...) (#286).
    catalog_re = re.compile(
        rf'\b({config_pattern})\s*\(\s*'
        rf'(?:(enforcedPlatform|platform)\s*\(\s*)?'
        rf'([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9.]+)\s*\)',
    )
    for m in catalog_re.finditer(content):
        platform_kind = m.group(2)
        deps.append({
            "groupId": None,
            "artifactId": None,
            "version": None,
            "configuration": m.group(1),
            "catalogRef": f"{m.group(3)}.{m.group(4)}",
            "isPlatform": platform_kind is not None,
            "platformKind": platform_kind,
        })

    return deps


# Gradle `kotlin("X")` shorthand expands to the `org.jetbrains.kotlin.X` plugin
# id. Well-known shorthands are mapped explicitly; any other arg falls back to
# the generic `org.jetbrains.kotlin.<arg>` form.
_KOTLIN_SHORTHAND_MAP = {
    "jvm": "org.jetbrains.kotlin.jvm",
    "android": "org.jetbrains.kotlin.android",
    "kapt": "org.jetbrains.kotlin.kapt",
    "plugin.serialization": "org.jetbrains.kotlin.plugin.serialization",
    "multiplatform": "org.jetbrains.kotlin.multiplatform",
    "plugin.compose": "org.jetbrains.kotlin.plugin.compose",
    "native.cocoapods": "org.jetbrains.kotlin.native.cocoapods",
    "plugin.parcelize": "org.jetbrains.kotlin.plugin.parcelize",
}


def _parse_gradle_plugins_block(content: str, is_settings: bool = False) -> List[Dict]:
    """Parse plugins {} DSL blocks. Returns list of {pluginId, version, catalogRef}."""
    results = []
    # Find plugins { } blocks
    plugins_re = re.compile(r'\bplugins\s*\{([^}]*)\}', re.DOTALL)
    for block_m in plugins_re.finditer(content):
        block = block_m.group(1)
        # id("plugin.id") version "1.0" — Kotlin/Groovy DSL with parentheses.
        id_ver_re = re.compile(r'\bid\s*\(\s*["\']([^"\']+)["\']\s*\)(?:\s+version\s+["\']([^"\']+)["\'])?')
        for m in id_ver_re.finditer(block):
            results.append({"pluginId": m.group(1), "version": m.group(2), "catalogRef": None, "settingsBlock": is_settings})
        # id 'plugin.id' version '1.0' — Groovy DSL without parentheses (space
        # separator). `\s+` after `id` excludes the parenthesised form above, so
        # no declaration is matched twice.
        id_noparen_re = re.compile(r'\bid\s+["\']([^"\']+)["\'](?:\s+version\s+["\']([^"\']+)["\'])?')
        for m in id_noparen_re.finditer(block):
            results.append({"pluginId": m.group(1), "version": m.group(2), "catalogRef": None, "settingsBlock": is_settings})
        # kotlin("jvm") version "1.9.0" — shorthand mapped to org.jetbrains.kotlin.<arg>.
        kotlin_re = re.compile(r'\bkotlin\s*\(\s*["\']([^"\']+)["\']\s*\)(?:\s+version\s+["\']([^"\']+)["\'])?')
        for m in kotlin_re.finditer(block):
            arg = m.group(1)
            plugin_id = _KOTLIN_SHORTHAND_MAP.get(arg, f"org.jetbrains.kotlin.{arg}")
            results.append({"pluginId": plugin_id, "version": m.group(2), "catalogRef": None, "settingsBlock": is_settings})
        # alias(libs.plugins.foo)
        alias_re = re.compile(r'\balias\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\.plugins\.([a-zA-Z0-9.]+)\s*\)')
        for m in alias_re.finditer(block):
            ref = f"{m.group(1)}.plugins.{m.group(2)}"
            results.append({"pluginId": None, "version": None, "catalogRef": ref, "settingsBlock": is_settings})
    return results


def _parse_buildscript_classpath(content: str) -> List[Dict]:
    """Parse buildscript { dependencies { classpath(...) } } using brace-balanced blocks.

    Uses `_find_block` so nested `repositories { }` / `dependencies { }` do not truncate
    the buildscript body at the first `}` (brace-naive non-greedy regex did).
    """
    results = []
    # Same classifier/@ext stripping as `_parse_gradle_deps` string notation.
    cp_re = re.compile(
        r'\bclasspath\s*\(["\']'
        r'([^"\':\s]+):([^"\':\s]+)'
        r'(?::([^"\':@]+))?(?::[^"\'@]+)?(?:@[^"\']+)?["\']'
    )
    pos = 0
    while True:
        found = _find_block(content, "buildscript", pos)
        if not found:
            break
        bs_body, _start, end = found
        deps = _find_block(bs_body, "dependencies")
        scan = deps[0] if deps else bs_body
        for m in cp_re.finditer(scan):
            results.append(
                {"groupId": m.group(1), "artifactId": m.group(2), "version": m.group(3)}
            )
        pos = end
    return results


def _parse_settings_modules(content: str) -> List[str]:
    """Extract include(":module") / include ':module' declarations from settings.gradle[.kts].

    Accepts parenthesised and Groovy space-form calls, and every quoted argument in a
    multi-module statement (`include(":app", ":core")` / `include ':app', ':core'`).
    `includeBuild` is not matched (`\\binclude\\b` requires a word boundary after
    `include`).
    """
    results = []
    for m in re.finditer(r"\binclude\b\s*", content):
        rest = content[m.end() :]
        if rest.startswith("("):
            end = rest.find(")")
            args = rest[1:] if end == -1 else rest[1:end]
        else:
            nl = rest.find("\n")
            args = rest if nl == -1 else rest[:nl]
            comment = args.find("//")
            if comment != -1:
                args = args[:comment]
        for q in re.finditer(r"""["']([^"']+)["']""", args):
            results.append(q.group(1))
    return results


def _parse_settings_catalogs(content: str) -> List[Dict]:
    """Extract version catalog descriptors from settings.gradle[.kts]. Returns [{name, tomlPath}]."""
    results = []
    # versionCatalogs { libs { from(files("gradle/libs.versions.toml")) } }
    vc_re = re.compile(r'\bversionCatalogs\s*\{([\s\S]*?)\}(?=\s*\}|\s*$)', re.DOTALL)
    for vc_m in vc_re.finditer(content):
        block = vc_m.group(1)
        # Groovy DSL: name { from(files("path")) }
        entry_re = re.compile(r'(\w+)\s*\{[^}]*from\s*\(\s*files?\s*\(\s*"([^"]+)"\s*\)', re.DOTALL)
        for m in entry_re.finditer(block):
            results.append({"name": m.group(1), "tomlPath": m.group(2)})
        # Kotlin DSL: create("name") { from(files("path")) }. The `create(` literal
        # is not matched by the Groovy `\w+\s*\{` form above, so the two never
        # double-count. A bodyless create("name") with no from(files(...)) yields
        # no descriptor — scan_project() then supplies the default libs catalog.
        create_re = re.compile(
            r'create\s*\(\s*["\']([^"\']+)["\']\s*\)\s*\{[^}]*from\s*\(\s*files?\s*\(\s*["\']([^"\']+)["\']\s*\)',
            re.DOTALL,
        )
        for m in create_re.finditer(block):
            results.append({"name": m.group(1), "tomlPath": m.group(2)})
    return results


def _parse_maven_deps(content: str) -> List[Dict]:
    """Parse regular Maven dependencies (not dependencyManagement).

    Strips `<dependencyManagement>` blocks first so managed pins / import BOMs
    are not returned as ordinary deps (#286). Bare `<dependency>` snippets
    (unit-test fixtures without a wrapping `<project>`) still parse.
    """
    xml = _strip_xml_comments(content)
    xml = re.sub(
        r"<dependencyManagement>[\s\S]*?</dependencyManagement>", "", xml
    )
    deps = []
    for m in re.finditer(r"<dependency>([\s\S]*?)</dependency>", xml):
        block = m.group(1)
        gid_m = re.search(r"<groupId>([^<]+)</groupId>", block)
        aid_m = re.search(r"<artifactId>([^<]+)</artifactId>", block)
        if not gid_m or not aid_m:
            continue
        group_id = gid_m.group(1).strip()
        artifact_id = aid_m.group(1).strip()
        ver_m = re.search(r"<version>([^<]+)</version>", block)
        version = ver_m.group(1).strip() if ver_m else None
        if version and version.startswith("${"):
            version = None
        scope_m = re.search(r"<scope>([^<]+)</scope>", block)
        scope = scope_m.group(1).strip() if scope_m else "compile"
        configuration = SCOPE_TO_CONFIG.get(scope, "implementation")
        deps.append({
            "groupId": group_id,
            "artifactId": artifact_id,
            "version": version,
            "configuration": configuration,
        })
    return deps


def _parse_maven_modules(content: str) -> List[str]:
    modules = []
    for m in re.finditer(r"<module>([^<]+)</module>", content):
        modules.append(m.group(1).strip())
    return modules


# ---------------------------------------------------------------------------
# Repository discovery (project-declared repos) — discovery layer only.
# A hand-written brace scanner is required because regex cannot balance nested
# `{ }` blocks; scoping correctness (plugin vs dependency repos) depends on it.
# ---------------------------------------------------------------------------

# Gradle shorthand repository accessors → (function name, friendly name, URL).
_GRADLE_SHORTHANDS = (
    ("mavenCentral", "Maven Central", MAVEN_CENTRAL_URL),
    ("google", "Google Maven", GOOGLE_MAVEN_URL),
    ("gradlePluginPortal", "Gradle Plugin Portal", GRADLE_PLUGIN_PORTAL_URL),
)

# Container blocks whose nested repositories belong to the PLUGIN scope.
_GRADLE_PLUGIN_CONTAINERS = ("pluginManagement", "buildscript")
# Container block whose nested repositories belong to the DEPENDENCY scope.
_GRADLE_DEP_CONTAINER = "dependencyResolutionManagement"

# Gradle's own default when `repositoriesMode` is not declared (#318).
_DEFAULT_REPOSITORIES_MODE = "PREFER_PROJECT"
# Matches `repositoriesMode.set(RepositoriesMode.X)` (Kotlin/Groovy DSL call
# form, the only form Groovy supports) and `repositoriesMode = RepositoriesMode.X`
# (Kotlin DSL property-assignment sugar), with or without the `RepositoriesMode.`
# qualifier — mirrors the fully-qualified-vs-bare tolerance already used for
# other enum-valued settings in this file.
_REPOSITORIES_MODE_RE = re.compile(
    r"\brepositoriesMode\s*(?:\.\s*set\s*\(|=)\s*(?:RepositoriesMode\.)?"
    r"(PREFER_PROJECT|FAIL_ON_PROJECT_REPOS)\b"
)


def _parse_repositories_mode(block_body: str) -> Optional[str]:
    """Extract `repositoriesMode` from a `dependencyResolutionManagement { }`
    body. Returns None when not declared (caller applies Gradle's own default,
    PREFER_PROJECT)."""
    m = _REPOSITORIES_MODE_RE.search(block_body)
    return m.group(1) if m else None


def _maven_local_url() -> str:
    """file:// marker for mavenLocal(); never HTTP-queried, just recorded."""
    return "file://" + os.path.expanduser(os.path.join("~", ".m2", "repository"))


# Gradle repository content filtering (#320): `content { includeGroup(...) }` /
# `content { includeGroupByRegex(...) }` inside a `maven {}` block, or the
# `exclusiveContent { forRepository { maven {...} }; filter { includeGroup(...) } }`
# shorthand, scope a repo declaration to only the group(s) it actually serves
# (e.g. JitPack scoped to `com.github.*`). Multiple calls in one block are
# OR-matched — a repo can allow more than one group.
_INCLUDE_GROUP_RE = re.compile(r"\bincludeGroup\s*\(\s*[\"']([^\"']+)[\"']\s*\)")
_INCLUDE_GROUP_REGEX_RE = re.compile(r"\bincludeGroupByRegex\s*\(\s*[\"']([^\"']+)[\"']\s*\)")


def _parse_group_filters(block_body: str) -> List[Dict[str, str]]:
    """Extract `includeGroup`/`includeGroupByRegex` calls from a `content {}` or
    `filter {}` block body into ``[{"type": "exact"|"regex", "value": ...}]``."""
    filters: List[Dict[str, str]] = []
    for m in _INCLUDE_GROUP_RE.finditer(block_body):
        filters.append({"type": "exact", "value": m.group(1)})
    for m in _INCLUDE_GROUP_REGEX_RE.finditer(block_body):
        # A normal (non-raw) Kotlin/Groovy string literal requires a doubled
        # backslash to produce one literal backslash character, so the
        # idiomatic on-disk form of this call is
        # includeGroupByRegex("com\\.github\\..*") (Gradle's own docs use
        # exactly this shape for JitPack). Collapsing doubled backslashes here
        # recovers the single-backslash Java/Kotlin regex the string decodes
        # to at compile time; a pattern already written with single
        # backslashes (e.g. inside a raw/triple-quoted string) has no `\\` to
        # collapse and passes through unchanged.
        pattern = m.group(1).replace("\\\\", "\\")
        filters.append({"type": "regex", "value": pattern})
    return filters


def _repo_matches_group(entry: Dict[str, Any], group_id: str) -> bool:
    """True when `entry` carries no `group_filters` (unfiltered repos are queried
    for every group, unchanged from pre-#320 behavior), or when `group_id`
    matches at least one attached filter: exact equality for `includeGroup`,
    full-string regex match for `includeGroupByRegex` (mirrors Gradle's own
    `Pattern.matches` semantics — a partial match is not enough). An invalid
    regex is treated as non-matching rather than raising."""
    filters = entry.get("group_filters")
    if not filters:
        return True
    for f in filters:
        if f["type"] == "exact":
            if f["value"] == group_id:
                return True
        else:
            try:
                if re.fullmatch(f["value"], group_id):
                    return True
            except re.error:
                continue
    return False


def _skip_string_literal(content: str, i: int) -> int:
    """`content[i]` is an opening quote; return the index just past its match.
    Handles backslash escapes; an unterminated string consumes to end."""
    quote = content[i]
    n = len(content)
    i += 1
    while i < n:
        c = content[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        i += 1
    return n


def _scan_balanced(content: str, brace_idx: int) -> Tuple[str, int]:
    """Given the index of an opening `{`, walk a brace-depth counter and return
    (body_without_outer_braces, index_just_past_the_closing_brace). Braces inside
    string literals (`"`/`'`) and `//` line comments are ignored. An unbalanced
    block returns the remainder of the content."""
    n = len(content)
    body_start = brace_idx + 1
    depth = 0
    i = brace_idx
    while i < n:
        c = content[i]
        if c == '"' or c == "'":
            i = _skip_string_literal(content, i)
            continue
        if c == "/" and i + 1 < n and content[i + 1] == "/":
            nl = content.find("\n", i)
            i = n if nl == -1 else nl
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return content[body_start:i], i + 1
        i += 1
    return content[body_start:], n


def _find_block(content: str, header: str, start: int = 0) -> Optional[Tuple[str, int, int]]:
    """Locate the first `header { ... }` block at/after `start`. Returns
    (body, header_start_index, index_past_closing_brace) or None.

    The header token is matched on word boundaries (so `maven` does not match
    `mavenCentral`, and `maven(...)` calls are skipped — only `maven {` counts).
    Limitation: the header search itself is NOT string/comment-aware (only the
    body brace-scan is), so a commented-out `// pluginManagement {` header could
    still be picked up; real builds rarely comment out container headers."""
    pattern = re.compile(r"\b" + re.escape(header) + r"\b")
    pos = start
    n = len(content)
    while True:
        m = pattern.search(content, pos)
        if not m:
            return None
        i = m.end()
        while i < n and content[i] in " \t\r\n":
            i += 1
        if i < n and content[i] == "{":
            body, after = _scan_balanced(content, i)
            return body, m.start(), after
        pos = m.end()


def _extract_block(content: str, header: str) -> Optional[str]:
    """Return the balanced `{ ... }` body of the first `header` block, or None
    if no such block exists. String/comment-aware (see `_scan_balanced`)."""
    found = _find_block(content, header)
    return found[0] if found else None


def _excise_spans(content: str, spans: List[Tuple[int, int]]) -> str:
    """Return `content` with the given [start, end) ranges removed (merging
    overlaps). Used to drop already-consumed container blocks before searching
    for the bare top-level `repositories {}`."""
    if not spans:
        return content
    out = []
    last = 0
    for s, e in sorted(spans):
        if s < last:
            last = max(last, e)
            continue
        out.append(content[last:s])
        last = e
    out.append(content[last:])
    return "".join(out)


def _dedup_repos(entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Dedup RepoEntry dicts by URL, preserving first-seen (declaration) order."""
    seen = set()
    out = []
    for e in entries:
        if e["url"] in seen:
            continue
        seen.add(e["url"])
        out.append(e)
    return out


def _parse_gradle_repos(block_body: str) -> List[Dict[str, str]]:
    """Parse a Gradle `repositories { ... }` body into RepoEntry dicts
    ``{"name", "url"}`` (scope is filled in by the caller). Handles shorthand
    accessors, explicit `maven("url")` / `maven(url = "url")` calls, and
    `maven { ... }` blocks (whose URL is extracted from the balanced body via the
    brace scanner — NOT a brace-naive regex, so `maven { credentials{…}; url=… }`
    is handled). A `maven { }` block's nested `content { includeGroup(...) }` /
    `includeGroupByRegex(...)`, and the `exclusiveContent { forRepository { maven
    {...} }; filter {...} }` shorthand, are both captured onto the entry as an
    optional `group_filters` list (#320 — see *Repository resolution* in
    CLAUDE.md). Deduped by URL, declaration order preserved."""
    entries: List[Dict[str, str]] = []

    for fn, name, url in _GRADLE_SHORTHANDS:
        if re.search(r"\b" + fn + r"\s*\(\s*\)", block_body):
            entries.append({"name": name, "url": url})
    if re.search(r"\bmavenLocal\s*\(\s*\)", block_body):
        entries.append({"name": "Maven Local", "url": _maven_local_url()})

    # exclusiveContent { forRepository { maven {...} }; filter { includeGroup(...) } }
    # — same net effect as `maven { content {...} }` (a repo + a group filter),
    # different syntax shape. Handled BEFORE the bare `maven { ... }` scan below
    # and its span excised from the content that scan sees — otherwise the
    # `maven {}` nested inside `forRepository {}` would ALSO be picked up there
    # as an unfiltered top-level repo, duplicating the entry and losing its
    # group filter.
    exclusive_spans: List[Tuple[int, int]] = []
    pos = 0
    while True:
        found = _find_block(block_body, "exclusiveContent", pos)
        if not found:
            break
        body, start, after = found
        exclusive_spans.append((start, after))
        pos = after
        for_repo_body = _extract_block(body, "forRepository")
        if for_repo_body is None:
            continue
        maven_found = _find_block(for_repo_body, "maven")
        if not maven_found:
            continue
        maven_body, _mstart, _mafter = maven_found
        um = re.search(r"\burl\b\s*(?:=\s*)?(?:uri\s*\(\s*)?[\"']([^\"']+)[\"']", maven_body)
        if not um:
            continue
        url = um.group(1)
        nm = re.search(r"\bname\s*=\s*[\"']([^\"']+)[\"']", maven_body)
        entry = {"name": nm.group(1) if nm else url, "url": url}
        filter_body = _extract_block(body, "filter")
        if filter_body is not None:
            filters = _parse_group_filters(filter_body)
            if filters:
                entry["group_filters"] = filters
        entries.append(entry)
    block_body_sans_exclusive = _excise_spans(block_body, exclusive_spans)

    # Explicit maven("url") and maven(url = "url") (optionally wrapped in uri()).
    for m in re.finditer(
        r"\bmaven\s*\(\s*(?:url\s*=\s*)?(?:uri\s*\(\s*)?[\"']([^\"']+)[\"']",
        block_body_sans_exclusive,
    ):
        entries.append({"name": m.group(1), "url": m.group(1)})

    # maven { ... } blocks — extract each balanced body, then find its URL, plus
    # an optional nested `content { includeGroup(...) }` group filter (#320).
    pos = 0
    while True:
        found = _find_block(block_body_sans_exclusive, "maven", pos)
        if not found:
            break
        body, _start, after = found
        um = re.search(r"\burl\b\s*(?:=\s*)?(?:uri\s*\(\s*)?[\"']([^\"']+)[\"']", body)
        if um:
            url = um.group(1)
            # Optional `name = "…"` (Kotlin DSL) / `name "…"` — used as the
            # credential-lookup id (#291). Falls back to the URL when absent
            # (same as before), so host-based env matching still works.
            nm = re.search(
                r"\bname\s*(?:=\s*[\"']([^\"']+)[\"']|[\"']([^\"']+)[\"'])",
                body,
            )
            name = (nm.group(1) or nm.group(2)) if nm else url
            entry = {"name": name, "url": url}
            content_body = _extract_block(body, "content")
            if content_body is not None:
                filters = _parse_group_filters(content_body)
                if filters:
                    entry["group_filters"] = filters
            entries.append(entry)
        pos = after

    return _dedup_repos(entries)


def _parse_maven_repos(pom_xml: str) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Parse a Maven POM into (dependency repos, plugin repos). `<repositories>`
    entries are dependency-scoped, `<pluginRepositories>` entries plugin-scoped.
    Per repo: `<url>` is the URL, `<id>` the name (falling back to the URL)."""

    def parse_container(container: str, entry: str) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        cm = re.search(r"<" + container + r">([\s\S]*?)</" + container + r">", pom_xml)
        if not cm:
            return out
        block = cm.group(1)
        for em in re.finditer(r"<" + entry + r">([\s\S]*?)</" + entry + r">", block):
            rb = em.group(1)
            um = re.search(r"<url>([^<]+)</url>", rb)
            if not um:
                continue
            url = um.group(1).strip()
            idm = re.search(r"<id>([^<]+)</id>", rb)
            name = idm.group(1).strip() if idm else url
            out.append({"name": name, "url": url})
        return out

    deps = parse_container("repositories", "repository")
    plugins = parse_container("pluginRepositories", "pluginRepository")
    return deps, plugins


def _read_build_file(path: str) -> str:
    """Read a build file as UTF-8 text; returns "" if unreadable."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


# Maven's own default when a <parent> declares no <relativePath> (#319).
_DEFAULT_PARENT_RELATIVE_PATH = "../pom.xml"
# Nesting depth cap for the local parent-POM chain — guards against a
# cyclic/malformed <parent> reference looping forever (#319).
_MAX_PARENT_CHAIN_DEPTH = 5


def _parse_maven_parent(pom_xml: str) -> Optional[Dict[str, Optional[str]]]:
    """Extract the `<parent>` coordinate (groupId/artifactId/version) and its
    `relativePath` from a POM. Returns None when there is no `<parent>` block.
    `relativePath` defaults to Maven's own `../pom.xml` when the tag is absent;
    an explicit but EMPTY `<relativePath/>` means "do not resolve locally, look
    the parent up in the repositories" (Maven convention) and is reported as
    `relativePath: None`."""
    xml = _strip_xml_comments(pom_xml)
    m = re.search(r"<parent>([\s\S]*?)</parent>", xml)
    if not m:
        return None
    block = m.group(1)
    gid_m = re.search(r"<groupId>([^<]+)</groupId>", block)
    aid_m = re.search(r"<artifactId>([^<]+)</artifactId>", block)
    if not gid_m or not aid_m:
        return None
    ver_m = re.search(r"<version>([^<]+)</version>", block)
    # Matches both the self-closing `<relativePath/>` form (no capture group
    # participates -> group(1) is None) and `<relativePath>...</relativePath>`
    # (possibly empty). Maven treats both an explicit empty value and a
    # self-closed tag the same way: "skip local lookup".
    rel_m = re.search(r"<relativePath\s*/>|<relativePath>([^<]*)</relativePath>", block)
    if rel_m is None:
        relative_path: Optional[str] = _DEFAULT_PARENT_RELATIVE_PATH
    else:
        relative_path = (rel_m.group(1) or "").strip() or None
    return {
        "groupId": gid_m.group(1).strip(),
        "artifactId": aid_m.group(1).strip(),
        "version": ver_m.group(1).strip() if ver_m else None,
        "relativePath": relative_path,
    }


def _parse_maven_project_coords(pom_xml: str) -> Dict[str, Optional[str]]:
    """Extract a POM's OWN groupId/artifactId/version — i.e. not its parent's,
    and not one nested inside <dependencies>/<build>/<profiles> (which carry
    their own groupId/artifactId/version tags that would otherwise be the
    first match). Container blocks that can shadow the project's own
    coordinate are stripped before searching. Used to verify a locally
    resolved parent POM's identity actually matches the child's `<parent>`
    declaration (#319)."""
    xml = _strip_xml_comments(pom_xml)
    for tag in ("parent", "dependencies", "dependencyManagement", "build", "profiles"):
        xml = re.sub(r"<" + tag + r">[\s\S]*?</" + tag + r">", "", xml)
    gid_m = re.search(r"<groupId>([^<]+)</groupId>", xml)
    aid_m = re.search(r"<artifactId>([^<]+)</artifactId>", xml)
    ver_m = re.search(r"<version>([^<]+)</version>", xml)
    return {
        "groupId": gid_m.group(1).strip() if gid_m else None,
        "artifactId": aid_m.group(1).strip() if aid_m else None,
        "version": ver_m.group(1).strip() if ver_m else None,
    }


def _parse_maven_active_profile_repos(
    pom_xml: str,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Extract `<repositories>`/`<pluginRepositories>` declared inside
    `<profiles><profile>` blocks whose `<activation><activeByDefault>true</...>`
    is set (#319). Only `activeByDefault` is evaluated — property/JDK/OS
    activation conditions are a much larger scope and are deferred (see
    plugins/maven-mcp/CLAUDE.md Documented limitations)."""
    xml = _strip_xml_comments(pom_xml)
    profiles_m = re.search(r"<profiles>([\s\S]*?)</profiles>", xml)
    if not profiles_m:
        return [], []
    dep_entries: List[Dict[str, str]] = []
    plugin_entries: List[Dict[str, str]] = []
    for pm in re.finditer(r"<profile>([\s\S]*?)</profile>", profiles_m.group(1)):
        block = pm.group(1)
        activation_m = re.search(r"<activation>([\s\S]*?)</activation>", block)
        if not activation_m:
            continue
        if not re.search(r"<activeByDefault>\s*true\s*</activeByDefault>", activation_m.group(1)):
            continue
        deps, plugins = _parse_maven_repos(block)
        dep_entries.extend(deps)
        plugin_entries.extend(plugins)
    return dep_entries, plugin_entries


def _resolve_parent_chain_repos(
    pom_path: str,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Walk the LOCAL parent-POM chain (child -> parent -> grandparent, ...)
    starting from `pom_path`, merging `<repositories>`/`<pluginRepositories>`
    declared in each locally-resolvable parent POM (#319). A parent is
    resolved from the filesystem only — this is the common multi-module
    reactor-build case and needs no network. Stops (gracefully, no raise) as
    soon as a hop is not locally resolvable: no `<parent>`, no/empty
    `relativePath`, the resolved path missing, or its own coordinate not
    matching the child's `<parent>` declaration. Depth-capped at
    `_MAX_PARENT_CHAIN_DEPTH` and cycle-guarded via realpath, so a
    cyclic/malformed `<parent>` reference cannot loop forever."""
    dep_entries: List[Dict[str, str]] = []
    plugin_entries: List[Dict[str, str]] = []
    current_path = pom_path
    visited = set()
    for _ in range(_MAX_PARENT_CHAIN_DEPTH):
        real = os.path.realpath(current_path)
        if real in visited:
            break
        visited.add(real)
        content = _read_build_file(current_path)
        if not content:
            break
        parent = _parse_maven_parent(content)
        if not parent or not parent["relativePath"]:
            break
        parent_path = os.path.normpath(
            os.path.join(os.path.dirname(current_path), parent["relativePath"])
        )
        if os.path.isdir(parent_path):
            parent_path = os.path.join(parent_path, "pom.xml")
        if not os.path.exists(parent_path):
            break  # not locally resolvable — network fetch is out of scope here (#319)
        parent_content = _read_build_file(parent_path)
        if not parent_content:
            break
        coords = _parse_maven_project_coords(parent_content)
        if coords["artifactId"] and coords["artifactId"] != parent["artifactId"]:
            break  # resolved file's own identity doesn't match the <parent> reference
        if coords["groupId"] and parent["groupId"] and coords["groupId"] != parent["groupId"]:
            break
        if coords["version"] and parent["version"] and coords["version"] != parent["version"]:
            break
        # Mirrors the local-pom guard in discover_repositories: _parse_maven_repos
        # regex-searches for the FIRST <repositories>/<pluginRepositories> block
        # anywhere in the content, unaware of <profiles> nesting, so a parent POM
        # that also has profiles must have them stripped first — otherwise an
        # (in)active profile's repos could leak in or shadow the parent's own
        # top-level ones. A parent's own ACTIVE profile repos are not collected
        # while walking the chain — documented as a residual gap (#319).
        parent_content_sans_profiles = re.sub(r"<profiles>[\s\S]*?</profiles>", "", parent_content)
        deps, plugins = _parse_maven_repos(parent_content_sans_profiles)
        dep_entries.extend(deps)
        plugin_entries.extend(plugins)
        current_path = parent_path
    return dep_entries, plugin_entries


def discover_repositories(project_root: str) -> Dict[str, List[Dict[str, str]]]:
    """Discover project-declared repositories, scoped into plugin vs dependency.

    Returns ``{"dependency": [RepoEntry], "plugin": [RepoEntry]}`` where each
    RepoEntry tags itself with ``"scope"``. Gradle is preferred; the POM is read
    only when NO Gradle build/settings file exists (gradle-first / pom-exclusive).
    Only the project_root build files are read — submodules are out of scope."""
    result: Dict[str, List[Dict[str, str]]] = {"dependency": [], "plugin": []}

    gradle_files = GRADLE_BUILD_FILES + GRADLE_SETTINGS_FILES
    gradle_present = any(
        os.path.exists(os.path.join(project_root, f)) for f in gradle_files
    )

    if gradle_present:
        plugin_entries: List[Dict[str, str]] = []
        # Split by declaration site so repositoriesMode (#318) can decide which
        # side wins instead of always unioning both into one dependency list.
        settings_dep_entries: List[Dict[str, str]] = []  # dependencyResolutionManagement { repositories {} }
        project_dep_entries: List[Dict[str, str]] = []  # bare top-level repositories {}
        repos_mode = _DEFAULT_REPOSITORIES_MODE
        for fname in GRADLE_SETTINGS_FILES + GRADLE_BUILD_FILES:
            path = os.path.join(project_root, fname)
            if not os.path.exists(path):
                continue
            content = _read_build_file(path)
            consumed: List[Tuple[int, int]] = []
            for header in _GRADLE_PLUGIN_CONTAINERS + (_GRADLE_DEP_CONTAINER,):
                found = _find_block(content, header)
                if not found:
                    continue
                body, start, after = found
                consumed.append((start, after))
                if header == _GRADLE_DEP_CONTAINER:
                    mode = _parse_repositories_mode(body)
                    if mode is not None:
                        repos_mode = mode
                repos_body = _extract_block(body, "repositories")
                if repos_body is None:
                    continue
                parsed = _parse_gradle_repos(repos_body)
                if header == _GRADLE_DEP_CONTAINER:
                    settings_dep_entries.extend(parsed)
                else:
                    plugin_entries.extend(parsed)
            # Excise consumed container spans BEFORE the bare top-level
            # repositories{} search, else a buildscript/pluginManagement-nested
            # `repositories` would be mis-read as dependency scope.
            stripped = _excise_spans(content, consumed)
            bare = _extract_block(stripped, "repositories")
            if bare is not None:
                project_dep_entries.extend(_parse_gradle_repos(bare))
        result["plugin"] = _dedup_repos(plugin_entries)
        if repos_mode == "FAIL_ON_PROJECT_REPOS":
            # A real Gradle build would fail outright if the project also
            # declared its own repositories{} under this mode — only
            # settings-level repos are ever valid, so project repos are
            # dropped here even when present, never unioned in.
            dep_entries = settings_dep_entries
        elif project_dep_entries:
            # PREFER_PROJECT (Gradle's default): a module's own repositories{}
            # supersedes dependencyResolutionManagement entirely for that
            # module — settings repos are a fallback default, not an addition.
            dep_entries = project_dep_entries
        else:
            dep_entries = settings_dep_entries
        result["dependency"] = _dedup_repos(dep_entries)
    else:
        pom_path = os.path.join(project_root, "pom.xml")
        if os.path.exists(pom_path):
            content = _read_build_file(pom_path)
            # `_parse_maven_repos` regex-searches for the FIRST `<repositories>`
            # anywhere in the content, unaware of `<profiles>` nesting — strip
            # `<profiles>` first so a profile's repos (active or not) are only
            # ever picked up via `_parse_maven_active_profile_repos` below,
            # never double-counted (or wrongly included when inactive) here.
            content_sans_profiles = re.sub(r"<profiles>[\s\S]*?</profiles>", "", content)
            deps, plugins = _parse_maven_repos(content_sans_profiles)
            # Repos declared in the local pom.xml only are frequently empty for
            # a child module — real Maven projects commonly declare them in the
            # parent POM and/or an active profile instead (#319).
            profile_deps, profile_plugins = _parse_maven_active_profile_repos(content)
            parent_deps, parent_plugins = _resolve_parent_chain_repos(pom_path)
            result["dependency"] = _dedup_repos(deps + profile_deps + parent_deps)
            result["plugin"] = _dedup_repos(plugins + profile_plugins + parent_plugins)

    for scope, repos in result.items():
        for entry in repos:
            entry["scope"] = scope
    return result


def _detect_build_system(project_root: str) -> str:
    for f in GRADLE_BUILD_FILES + GRADLE_SETTINGS_FILES:
        if os.path.exists(os.path.join(project_root, f)):
            return "gradle"
    if os.path.exists(os.path.join(project_root, "gradle", "libs.versions.toml")):
        return "gradle"
    if os.path.exists(os.path.join(project_root, "pom.xml")):
        return "maven"
    return "unknown"


def _scan_maven_recursive(
    module_path: str,
    label: Optional[str],
    acc: List[Dict],
    depth: int,
    managed_pins: Optional[List[Dict]] = None,
) -> None:
    pom_path = os.path.join(module_path, "pom.xml")
    if not os.path.exists(pom_path):
        return
    with open(pom_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    for dep in _parse_maven_deps(content):
        acc.append({
            "groupId": dep["groupId"],
            "artifactId": dep["artifactId"],
            "version": dep["version"],
            "source": {"kind": "module-direct", "file": "pom.xml", "module": label},
            "usages": [{"module": label, "configuration": dep["configuration"]}],
        })
    # Import-scope BOMs → platform-tagged deps; non-import pins → managedPins (#286).
    for entry in parse_dependency_management(content):
        if entry["isImportBom"] and entry.get("version"):
            acc.append({
                "groupId": entry["groupId"],
                "artifactId": entry["artifactId"],
                "version": entry["version"],
                "isPlatform": True,
                "platformKind": "platform",
                "source": {"kind": "module-direct", "file": "pom.xml", "module": label},
                "usages": [{"module": label, "configuration": "import"}],
            })
        elif not entry["isImportBom"] and entry.get("version") and managed_pins is not None:
            managed_pins.append({
                "groupId": entry["groupId"],
                "artifactId": entry["artifactId"],
                "version": entry["version"],
                "module": label,
            })
    if depth >= MAX_MODULE_DEPTH:
        return
    for sub in _parse_maven_modules(content):
        child_path = os.path.join(module_path, sub)
        child_label = sub if label is None else f"{label}/{sub}"
        _scan_maven_recursive(
            child_path, child_label, acc, depth + 1, managed_pins
        )


def _module_path_to_dir(project_root: str, module_path: str) -> str:
    parts = module_path.lstrip(":").split(":")
    parts = [p for p in parts if p]
    return os.path.join(project_root, *parts)


# Known-dead Gradle repository shorthands (#284). jcenter() has been read-only
# since 2021 and was fully sunset 15 Aug 2024 (blog.gradle.org/jcenter-shutdown)
# — a project still declaring it can no longer resolve anything from it. This
# is a standalone content scan, deliberately NOT wired into `_parse_gradle_repos`
# / `discover_repositories`: those feed live repository resolution
# (`_repos_for` / `fetch_metadata`), and adding a known-dead entry there would
# require also teaching the declared-vs-public-fallback contract to treat it as
# non-queryable — out of scope here. Flagging is purely informational, surfaced
# only via `scan_project_dependencies`.
_DEAD_GRADLE_REPO_SHORTHANDS = (
    ("jcenter", "jcenter() is dead — JCenter has been read-only since 2021 and was fully sunset 15 Aug 2024. Migrate to mavenCentral() or google()."),
)


def _detect_dead_repo_hints(content: str, file_name: str, module: Optional[str]) -> List[Dict[str, Optional[str]]]:
    """Scan a build/settings file's raw content for known-dead repository
    shorthands. Not scoped to a parsed `repositories { }` block — the shorthand
    call is unambiguous wherever it textually appears in a Gradle file, and a
    simple regex keeps this a lightweight, independent signal (no XML/Kotlin
    parser dependency, consistent with the rest of the project). Known gap:
    unlike `extract_relocation_from_pom`, this does NOT strip `//`/`/* */`
    comments first, so a commented-out `jcenter()` left over from a migration
    still surfaces a hint — acceptable false-positive for a purely informational
    signal, not worth a Kotlin/Groovy comment-stripping pass for."""
    hints = []
    for fn, message in _DEAD_GRADLE_REPO_SHORTHANDS:
        if re.search(r"\b" + fn + r"\s*\(\s*\)", content):
            hints.append({"repository": fn, "file": file_name, "module": module, "message": message})
    return hints


def scan_project(project_root: str) -> Dict:
    """Returns {buildSystem, dependencies: [...ScannedDependency],
    deadRepositoryHints: [...], managedPins: [...]}."""
    build_system = _detect_build_system(project_root)
    dependencies: List[Dict] = []
    dead_repo_hints: List[Dict] = []
    managed_pins: List[Dict] = []

    if build_system == "gradle":
        # Step 1: Read settings file
        settings_result = None
        for f in GRADLE_SETTINGS_FILES:
            p = os.path.join(project_root, f)
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    settings_result = {"content": fh.read(), "file": f}
                dead_repo_hints.extend(_detect_dead_repo_hints(settings_result["content"], f, None))
                break

        # Step 2: Determine catalog descriptors
        if settings_result:
            descriptors = _parse_settings_catalogs(settings_result["content"])
            if not descriptors:
                # Default if not declared explicitly
                default_toml = os.path.join(project_root, "gradle", "libs.versions.toml")
                if os.path.exists(default_toml):
                    descriptors = [{"name": "libs", "tomlPath": "gradle/libs.versions.toml"}]
        else:
            default_toml = os.path.join(project_root, "gradle", "libs.versions.toml")
            descriptors = [{"name": "libs", "tomlPath": "gradle/libs.versions.toml"}] if os.path.exists(default_toml) else []

        # Step 3: Load catalogs
        catalogs: Dict[str, Dict] = {}  # name -> {tomlPath, parsed}
        for desc in descriptors:
            toml_path = os.path.join(project_root, desc["tomlPath"])
            if not os.path.exists(toml_path):
                continue
            with open(toml_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            catalogs[desc["name"]] = {"tomlPath": desc["tomlPath"], "parsed": _parse_toml_catalog(content)}

        # Step 4: Emit catalog entries with empty usages
        # catalog_entry_map: "catalogName.lib.alias" -> dep dict (shared reference)
        catalog_entry_map: Dict[str, Dict] = {}
        for catalog_name, catalog_data in catalogs.items():
            toml_path = catalog_data["tomlPath"]
            parsed = catalog_data["parsed"]
            for alias, entry in parsed["libraries"].items():
                dep = {
                    "groupId": entry["groupId"],
                    "artifactId": entry["artifactId"],
                    "version": entry["version"],
                    "source": {"kind": "catalog-library", "catalogName": catalog_name, "tomlPath": toml_path, "alias": alias},
                    "usages": [],
                }
                dependencies.append(dep)
                catalog_entry_map[f"{catalog_name}.lib.{alias}"] = dep
                dashed = alias.replace(".", "-")
                if dashed != alias:
                    catalog_entry_map[f"{catalog_name}.lib.{dashed}"] = dep
            for alias, entry in parsed["plugins"].items():
                plugin_id = entry["id"]
                dep = {
                    "groupId": plugin_id,
                    "artifactId": f"{plugin_id}.gradle.plugin",
                    "version": entry["version"],
                    "source": {"kind": "catalog-plugin", "catalogName": catalog_name, "tomlPath": toml_path, "alias": alias},
                    "usages": [],
                }
                dependencies.append(dep)
                catalog_entry_map[f"{catalog_name}.plugin.{alias}"] = dep
                dashed = alias.replace(".", "-")
                if dashed != alias:
                    catalog_entry_map[f"{catalog_name}.plugin.{dashed}"] = dep

        def _parse_catalog_ref(ref: str):
            dot_idx = ref.find(".")
            if dot_idx == -1:
                return None
            return ref[:dot_idx], ref[dot_idx + 1:]

        def process_build_file_deps(content: str, file_name: str, module: Optional[str]) -> None:
            for dep in _parse_gradle_deps(content, file_name):
                if dep["catalogRef"]:
                    parsed = _parse_catalog_ref(dep["catalogRef"])
                    if not parsed:
                        continue
                    catalog_name, alias = parsed
                    if catalog_name not in catalogs:
                        continue
                    dashed_alias = alias.replace(".", "-")
                    entry = catalog_entry_map.get(f"{catalog_name}.lib.{alias}") or \
                            catalog_entry_map.get(f"{catalog_name}.lib.{dashed_alias}")
                    if entry:
                        entry["usages"].append({"module": module, "configuration": dep["configuration"]})
                        if dep.get("isPlatform"):
                            entry["isPlatform"] = True
                            # Prefer enforcedPlatform if any usage wraps it that way.
                            if (
                                dep.get("platformKind") == "enforcedPlatform"
                                or not entry.get("platformKind")
                            ):
                                entry["platformKind"] = dep.get("platformKind")
                elif dep["groupId"] and dep["artifactId"]:
                    entry = {
                        "groupId": dep["groupId"],
                        "artifactId": dep["artifactId"],
                        "version": dep["version"],
                        "source": {"kind": "module-direct", "file": file_name, "module": module},
                        "usages": [{"module": module, "configuration": dep["configuration"]}],
                    }
                    if dep.get("isPlatform"):
                        entry["isPlatform"] = True
                        entry["platformKind"] = dep.get("platformKind")
                    dependencies.append(entry)

        def process_plugins_block(content: str, file_name: str, module: Optional[str], is_settings: bool) -> None:
            for decl in _parse_gradle_plugins_block(content, is_settings):
                if decl["catalogRef"]:
                    parsed = _parse_catalog_ref(decl["catalogRef"])
                    if not parsed:
                        continue
                    catalog_name, alias_path = parsed
                    if catalog_name not in catalogs:
                        continue
                    plugins_prefix = "plugins."
                    if not alias_path.startswith(plugins_prefix):
                        continue
                    plugin_alias = alias_path[len(plugins_prefix):]
                    dashed = plugin_alias.replace(".", "-")
                    entry = catalog_entry_map.get(f"{catalog_name}.plugin.{plugin_alias}") or \
                            catalog_entry_map.get(f"{catalog_name}.plugin.{dashed}")
                    if entry:
                        entry["usages"].append({"module": module, "configuration": "plugin-dsl"})
                elif decl["pluginId"] and decl["pluginId"] != "(unresolved)":
                    settings_block = True if decl.get("settingsBlock") else None
                    source = {"kind": "plugins-dsl", "file": file_name, "module": module}
                    if settings_block:
                        source["settingsBlock"] = True
                    dependencies.append({
                        "groupId": decl["pluginId"],
                        "artifactId": f"{decl['pluginId']}.gradle.plugin",
                        "version": decl["version"],
                        "source": source,
                        "usages": [{"module": module, "configuration": "plugin-dsl"}],
                    })

        def process_buildscript_classpath(content: str, file_name: str) -> None:
            for dep in _parse_buildscript_classpath(content):
                dependencies.append({
                    "groupId": dep["groupId"],
                    "artifactId": dep["artifactId"],
                    "version": dep["version"],
                    "source": {"kind": "buildscript-classpath", "file": file_name},
                    "usages": [{"module": None, "configuration": "classpath"}],
                })

        # Step 5: Scan module build files
        modules = _parse_settings_modules(settings_result["content"]) if settings_result else []
        for module_path in modules:
            dir_path = _module_path_to_dir(project_root, module_path)
            for build_file in GRADLE_BUILD_FILES:
                path = os.path.join(dir_path, build_file)
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                process_build_file_deps(content, build_file, module_path)
                process_plugins_block(content, build_file, module_path, False)
                dead_repo_hints.extend(_detect_dead_repo_hints(content, build_file, module_path))
                break

        # Step 6: Scan root build file
        for build_file in GRADLE_BUILD_FILES:
            path = os.path.join(project_root, build_file)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            process_build_file_deps(content, build_file, None)
            process_plugins_block(content, build_file, None, False)
            process_buildscript_classpath(content, build_file)
            dead_repo_hints.extend(_detect_dead_repo_hints(content, build_file, None))
            break

        # Step 7: Scan settings for pluginManagement plugins {}
        if settings_result:
            process_plugins_block(settings_result["content"], settings_result["file"], None, True)

        # Step 8: Discover buildSrc/ and build-logic/ convention-plugin builds.
        # Neither directory is ever listed in settings.gradle include(...), so
        # Step 5 never touches them — no double-scan risk. catalogRef entries
        # are skipped: resolving them against the root catalog would be wrong
        # provenance scope (accepted limitation, not a bug).
        def emit_direct_deps(content: str, rel_file: str, kind: str) -> None:
            for dep in _parse_gradle_deps(content, rel_file):
                if dep["catalogRef"] or not (dep["groupId"] and dep["artifactId"]):
                    continue
                entry = {
                    "groupId": dep["groupId"],
                    "artifactId": dep["artifactId"],
                    "version": dep["version"],
                    "source": {"kind": kind, "file": rel_file, "module": None},
                    "usages": [{"module": None, "configuration": dep["configuration"]}],
                }
                if dep.get("isPlatform"):
                    entry["isPlatform"] = True
                    entry["platformKind"] = dep.get("platformKind")
                dependencies.append(entry)

        def scan_convention_plugins(src_kotlin_dir: str) -> None:
            if not os.path.isdir(src_kotlin_dir):
                return
            for dirpath, _dirnames, filenames in os.walk(src_kotlin_dir):
                for name in sorted(filenames):
                    if not name.endswith(".gradle.kts"):
                        continue
                    abs_path = os.path.join(dirpath, name)
                    rel_file = os.path.relpath(abs_path, project_root).replace(os.sep, "/")
                    with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    emit_direct_deps(content, rel_file, "convention-plugin")

        buildsrc_dir = os.path.join(project_root, "buildSrc")
        if os.path.isdir(buildsrc_dir):
            for build_file in GRADLE_BUILD_FILES:
                path = os.path.join(buildsrc_dir, build_file)
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                emit_direct_deps(content, f"buildSrc/{build_file}", "buildsrc")
                break
            scan_convention_plugins(os.path.join(buildsrc_dir, "src", "main", "kotlin"))

        build_logic_dir = os.path.join(project_root, "build-logic")
        if os.path.isdir(build_logic_dir):
            for sub in sorted(os.listdir(build_logic_dir)):
                sub_dir = os.path.join(build_logic_dir, sub)
                if not os.path.isdir(sub_dir):
                    continue
                for build_file in GRADLE_BUILD_FILES:
                    path = os.path.join(sub_dir, build_file)
                    if not os.path.exists(path):
                        continue
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    emit_direct_deps(content, f"build-logic/{sub}/{build_file}", "convention-plugin")
                    break
                scan_convention_plugins(os.path.join(sub_dir, "src", "main", "kotlin"))

    elif build_system == "maven":
        _scan_maven_recursive(
            project_root, None, dependencies, 0, managed_pins
        )

    return {
        "buildSystem": build_system,
        "dependencies": dependencies,
        "deadRepositoryHints": dead_repo_hints,
        "managedPins": managed_pins,
    }


def _source_file_path(source: Dict) -> str:
    kind = source.get("kind", "")
    if kind in ("catalog-library", "catalog-plugin"):
        return source.get("tomlPath", "")
    return source.get("file", "")


def flatten_scan_result(scan: Dict) -> Dict:
    deps = []
    for dep in scan["dependencies"]:
        source_file = _source_file_path(dep["source"])
        source_kind = dep["source"]["kind"]
        usages = dep.get("usages", [])

        def _flat_entry(configuration: str, module: Optional[str]) -> Dict:
            entry = {
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "version": dep["version"],
                "configuration": configuration,
                "module": module,
                "source": source_file,
                "sourceKind": source_kind,
            }
            if dep.get("isPlatform"):
                entry["isPlatform"] = True
                entry["platformKind"] = dep.get("platformKind")
            if dep.get("effectiveVersion") is not None:
                entry["effectiveVersion"] = dep["effectiveVersion"]
            if dep.get("managedBy") is not None:
                entry["managedBy"] = dep["managedBy"]
            return entry

        if not usages:
            deps.append(_flat_entry("(unused)", None))
        else:
            for usage in usages:
                deps.append(
                    _flat_entry(
                        usage.get("configuration", ""),
                        usage.get("module"),
                    )
                )
    return {
        "buildSystem": scan["buildSystem"],
        "dependencies": deps,
        "deadRepositoryHints": scan.get("deadRepositoryHints", []),
    }


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def handle_get_latest_version(args: Dict) -> Any:
    group_id = args["groupId"]
    artifact_id = args["artifactId"]
    filter_mode = args.get("stabilityFilter", "PREFER_STABLE")
    ctx = build_resolution_context(args)
    metadata = fetch_metadata(group_id, artifact_id, ctx)
    selected = find_latest_version(metadata["versions"], filter_mode)
    if not selected:
        raise ValueError(f"No stable version found for {group_id}:{artifact_id}")
    result = {
        "groupId": group_id,
        "artifactId": artifact_id,
        "latestVersion": selected,
        "stability": classify_version(selected),
        "allVersionsCount": len(metadata["versions"]),
        "resolvedFrom": metadata.get("resolvedFrom"),
    }
    # #284: the latest version of a relocated artifact is typically the
    # relocation stub itself (Maven relocation POMs stop receiving further
    # releases past that point), so this is the natural place to surface it.
    relocated_to = check_relocation(group_id, artifact_id, selected, ctx)
    if relocated_to:
        result["relocatedTo"] = relocated_to
    return result


def handle_check_version_exists(args: Dict) -> Any:
    group_id = args["groupId"]
    artifact_id = args["artifactId"]
    version = args["version"]
    ctx = build_resolution_context(args)
    entry = check_version_in_repos(group_id, artifact_id, version, ctx)
    if entry:
        result = {
            "groupId": group_id,
            "artifactId": artifact_id,
            "version": version,
            "exists": True,
            "stability": classify_version(version),
            # entry["name"] can be the literal repo URL (maven("url") declarations
            # set name == url), so it goes through the same userinfo redaction as
            # resolvedFrom.url.
            "repository": _strip_userinfo(entry["name"]),
            "resolvedFrom": _to_resolved_from(entry),
        }
        # #284: a specific version being checked may itself be a relocation stub.
        relocated_to = check_relocation(group_id, artifact_id, version, ctx)
        if relocated_to:
            result["relocatedTo"] = relocated_to
        return result
    return {
        "groupId": group_id,
        "artifactId": artifact_id,
        "version": version,
        "exists": False,
    }


def handle_check_multiple_dependencies(args: Dict) -> Any:
    ctx = build_resolution_context(args)
    results = []
    for dep in args["dependencies"]:
        # resolved_from is captured as soon as fetch_metadata succeeds, so a
        # downstream "no version found" still carries provenance (#317 finding 1:
        # a repo did answer, so resolvedFrom is known even on a not-found result).
        resolved_from = None
        try:
            metadata = fetch_metadata(dep["groupId"], dep["artifactId"], ctx)
            resolved_from = metadata.get("resolvedFrom")
            latest = find_latest_version(metadata["versions"], "PREFER_STABLE")
            if not latest:
                raise ValueError("No version found")
            results.append({
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "latestVersion": latest,
                "stability": classify_version(latest),
                "resolvedFrom": resolved_from,
            })
        except Exception as e:
            error_entry = {
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "latestVersion": "",
                "stability": "",
                "error": str(e),
            }
            if resolved_from is not None:
                error_entry["resolvedFrom"] = resolved_from
            results.append(error_entry)
    return {"results": results}


def handle_compare_dependency_versions(args: Dict) -> Any:
    ctx = build_resolution_context(args)
    results = []
    for dep in args["dependencies"]:
        # resolved_from is captured as soon as fetch_metadata succeeds, so a
        # downstream "no matching version" still carries provenance (#317 finding 1:
        # a repo did answer, so resolvedFrom is known even on a not-found result).
        resolved_from = None
        try:
            metadata = fetch_metadata(dep["groupId"], dep["artifactId"], ctx)
            resolved_from = metadata.get("resolvedFrom")
            latest = find_latest_version_for_current(metadata["versions"], dep["currentVersion"])
            if not latest:
                raise ValueError("No matching version found")
            upgrade_type = get_upgrade_type(dep["currentVersion"], latest)
            results.append({
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "currentVersion": dep["currentVersion"],
                "latestVersion": latest,
                "latestStability": classify_version(latest),
                "upgradeType": upgrade_type,
                "upgradeAvailable": upgrade_type != "none",
                "resolvedFrom": resolved_from,
            })
        except Exception as e:
            error_entry = {
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "currentVersion": dep.get("currentVersion", ""),
                "latestVersion": "",
                "latestStability": "",
                "upgradeType": "none",
                "upgradeAvailable": False,
                "error": str(e),
            }
            if resolved_from is not None:
                error_entry["resolvedFrom"] = resolved_from
            results.append(error_entry)
    summary = {
        "total": len(results),
        "upgradeable": sum(1 for r in results if r.get("upgradeAvailable")),
        "major": sum(1 for r in results if r.get("upgradeType") == "major"),
        "minor": sum(1 for r in results if r.get("upgradeType") == "minor"),
        "patch": sum(1 for r in results if r.get("upgradeType") == "patch"),
    }
    return {"results": results, "summary": summary}


def handle_get_dependency_changes(args: Dict) -> Any:
    ctx = build_resolution_context(args)
    return _get_dependency_changes_impl(
        args["groupId"],
        args["artifactId"],
        args["fromVersion"],
        args["toVersion"],
        ctx,
    )


def handle_expand_bom(args: Dict) -> Any:
    ctx = build_resolution_context(args)
    group_id = args["groupId"]
    artifact_id = args["artifactId"]
    version = args["version"]
    managed = expand_bom(group_id, artifact_id, version, ctx)
    return {
        "groupId": group_id,
        "artifactId": artifact_id,
        "version": version,
        "managed": managed,
    }


def handle_get_transitive_graph(args: Dict) -> Any:
    """MCP handler for ``get_transitive_graph`` (#287)."""
    return get_transitive_graph(args["groupId"], args["artifactId"], args["version"])


def handle_detect_dependency_conflicts(args: Dict) -> Any:
    """MCP handler for ``detect_dependency_conflicts`` (#287)."""
    project_path = args.get("projectPath") or os.getcwd()
    build_system = args.get("buildSystem")
    ctx = build_resolution_context(args)
    return detect_dependency_conflicts(project_path, build_system=build_system, ctx=ctx)


def handle_scan_project_dependencies(args: Dict) -> Any:
    project_path = args.get("projectPath") or os.getcwd()
    ctx = build_resolution_context(args)
    scan = scan_project(project_path)
    apply_bom_managed_versions(scan, ctx)
    return flatten_scan_result(scan)


def handle_get_dependency_vulnerabilities(args: Dict) -> Any:
    original_deps = args["dependencies"]
    # Caps are ENFORCED here, before any network I/O — an MCP inputSchema's
    # maxItems is advisory client metadata the server never validates, so the
    # bound on outbound fan-out (each dep -> OSV query, plus optional marker
    # POM fetch) lives in code. Truncate an over-long batch (same pattern as
    # verify_coordinates).
    if len(original_deps) > MAX_VULN_DEPENDENCIES:
        original_deps = original_deps[:MAX_VULN_DEPENDENCIES]
    # Only build a ResolutionContext (filesystem read of the project's build
    # files, see discover_repositories) when at least one requested dependency
    # is actually a plugin-marker shape — preserves the original zero-FS-I/O,
    # single-network-call contract for ordinary (non-marker) requests (#290
    # purity fix: this used to run unconditionally for every caller).
    has_marker = any(
        _gradle_plugin_marker_plugin_id(dep["groupId"], dep["artifactId"])
        for dep in original_deps
    )
    ctx: Optional["ResolutionContext"] = None
    if has_marker:
        try:
            ctx = build_resolution_context(args)
        except Exception:
            ctx = None  # degrade: markers stay unresolved, queried as-is below

    query_deps = []
    resolutions = []
    for dep in original_deps:
        resolved = (
            resolve_plugin_marker_implementation(
                dep["groupId"], dep["artifactId"], dep.get("version"), ctx
            )
            if ctx is not None
            else None
        )
        resolutions.append(resolved)
        query_deps.append(resolved if resolved else dep)

    # NOTE: unlike handle_audit_project_dependencies, this does not dedupe
    # identical (groupId, artifactId, version) requests before querying OSV —
    # known minor inefficiency, left as a follow-up rather than risking a
    # larger restructure here.
    raw = query_osv_batch(query_deps)
    results = []
    for i, r in enumerate(raw):
        entry = dict(r)
        if resolutions[i]:
            entry["groupId"] = original_deps[i]["groupId"]
            entry["artifactId"] = original_deps[i]["artifactId"]
            entry["version"] = original_deps[i]["version"]
            entry["resolvedImplementation"] = resolutions[i]
        entry["vulnerabilityCount"] = len(entry["vulnerabilities"])
        results.append(entry)
    return {"results": results}


def handle_get_dependency_health(args: Dict) -> Any:
    ctx = build_resolution_context(args)
    results = []
    for dep in args["dependencies"]:
        group_id = dep["groupId"]
        artifact_id = dep["artifactId"]
        requested_version = dep.get("version")
        result: Dict[str, Any] = {
            "groupId": group_id,
            "artifactId": artifact_id,
            "versionCount": 0,
            "repository": None,
            "scm": None,
            "github": None,
            "signals": [],
        }
        try:
            metadata = fetch_metadata(group_id, artifact_id, ctx)
        except Exception as e:
            result["healthError"] = str(e)
            results.append(result)
            continue
        result["resolvedFrom"] = metadata.get("resolvedFrom")

        versions = metadata["versions"]
        result["versionCount"] = len(versions)
        result["lastPublishedToMaven"] = metadata.get("lastUpdated")
        latest_version = find_latest_version(versions, "PREFER_STABLE") or (versions[-1] if versions else None)
        result["latestVersion"] = latest_version
        result["stability"] = classify_version(latest_version) if latest_version else None

        target_version = requested_version or latest_version
        if not find_latest_version(versions, "STABLE_ONLY"):
            result["signals"].append("no stable release")

        gh_repo = None
        pom_licenses: List[str] = []
        if target_version:
            pom = fetch_pom(group_id, artifact_id, target_version, ctx)
            if pom:
                gh_repo = extract_github_repo_from_pom(pom)
                pom_licenses = extract_licenses_from_pom(pom)
                scm_url = extract_scm_url_from_pom(pom)
                if scm_url:
                    result["scm"] = {"url": scm_url, "host": scm_host(scm_url)}

        cached_repo_meta = None
        if not gh_repo:
            guess = guess_github_repo(group_id, artifact_id)
            if guess:
                cached_repo_meta = gh_fetch_repo(guess["owner"], guess["repo"])
                if cached_repo_meta:
                    gh_repo = guess

        if not gh_repo:
            if not pom_licenses:
                result["signals"].append("no license declared")
            scm = result.get("scm")
            if scm and scm["host"] != "github":
                result["signals"].append(f"SCM hosted on {scm['host']}; GitHub metrics unavailable")
            else:
                result["signals"].append("no public GitHub repository found")
                result["healthError"] = "GitHub repository not found; activity metrics unavailable"
            results.append(result)
            continue

        owner = gh_repo["owner"]
        repo = gh_repo["repo"]
        result["repository"] = {"owner": owner, "repo": repo, "url": f"https://github.com/{owner}/{repo}"}
        if not result.get("scm"):
            result["scm"] = {"url": result["repository"]["url"], "host": "github"}

        repo_meta = cached_repo_meta or gh_fetch_repo(owner, repo)
        if not repo_meta:
            if not pom_licenses:
                result["signals"].append("no license declared")
            result["healthError"] = "GitHub repository metadata unavailable (rate limit or network)"
            results.append(result)
            continue

        releases = gh_fetch_releases(owner, repo)
        issue_stats = gh_fetch_issue_stats(owner, repo)
        release_summary = _summarize_releases(releases)

        owner_login = (repo_meta.get("owner") or {}).get("login") or owner
        owner_info = gh_fetch_user(owner_login)

        spdx = (repo_meta.get("license") or {}).get("spdx_id")
        license_val = spdx if (spdx and spdx != "NOASSERTION") else (pom_licenses[0] if pom_licenses else None)

        result["github"] = {
            "stars": repo_meta.get("stargazers_count", 0),
            "forks": repo_meta.get("forks_count", 0),
            "openIssues": repo_meta.get("open_issues_count", 0),
            "archived": bool(repo_meta.get("archived")),
            "ownerType": (repo_meta.get("owner") or {}).get("type", "unknown"),
            "ownerPublicRepos": (owner_info or {}).get("public_repos"),
            "ownerAccountCreatedAt": (owner_info or {}).get("created_at"),
            "lastCommit": repo_meta.get("pushed_at"),
            "lastRelease": release_summary["last"],
            "releaseCount": release_summary["count"],
            "releaseCadenceDays": release_summary["cadenceDays"],
            "license": license_val,
            "createdAt": repo_meta.get("created_at"),
            "issues": issue_stats,
        }

        gh = result["github"]
        if gh["archived"]:
            result["signals"].append("repository archived")
        commit_months = _months_since(gh["lastCommit"])
        if commit_months is not None and commit_months >= 12:
            result["signals"].append(f"no commits in {commit_months} months")
        release_months = _months_since(gh["lastRelease"])
        if release_months is not None and release_months >= 18:
            result["signals"].append(f"no release in {release_months} months")
        if not license_val:
            result["signals"].append("no license declared")
        if issue_stats:
            cr = issue_stats.get("closeRatio")
            open_count = issue_stats.get("open") or 0
            if cr is not None and cr < 0.5 and open_count >= 50:
                result["signals"].append("high open-issue backlog, low close ratio")
            mtc = issue_stats.get("medianDaysToClose")
            if mtc is not None and mtc >= 180:
                result["signals"].append(f"slow issue response (median {mtc} days to close)")

        results.append(result)
    return {"results": results}


def handle_search_artifacts(args: Dict) -> Any:
    query = args["query"]
    # Coerce + clamp before the Solr URL is built — schema bounds are advisory
    # only (same reasoning as verify_coordinates' suggestLimit clamp).
    try:
        limit = int(args.get("limit", SEARCH_LIMIT_DEFAULT))
    except (TypeError, ValueError):
        limit = SEARCH_LIMIT_DEFAULT
    limit = max(1, min(limit, SEARCH_LIMIT_MAX))
    results = search_maven_central(query, limit)
    return {"results": results}


def handle_audit_project_dependencies(args: Dict) -> Any:
    project_path = args.get("projectPath") or os.getcwd()
    include_vulns = args.get("includeVulnerabilities", True)
    if include_vulns is None:
        include_vulns = True
    production_only = args.get("productionOnly", True)
    if production_only is None:
        production_only = True

    ctx = build_resolution_context(args)
    scan = scan_project(project_path)
    apply_bom_managed_versions(scan, ctx)

    def is_included_in_production(dep: Dict) -> bool:
        source = dep["source"]
        kind = source.get("kind", "")
        usages = dep.get("usages", [])
        if kind in ("catalog-library", "catalog-plugin"):
            if not usages:
                return True  # unused catalog entries always included
            return any(not _is_test_configuration(u.get("configuration", "")) for u in usages)
        if not usages:
            return False
        return not _is_test_configuration(usages[0].get("configuration", ""))

    filtered = scan["dependencies"] if not production_only else [
        d for d in scan["dependencies"] if is_included_in_production(d)
    ]

    def _effective_version(dep: Dict) -> Optional[str]:
        return dep.get("version") or dep.get("effectiveVersion")

    deps_with_version = [d for d in filtered if _effective_version(d)]
    deps_without_version = [d for d in filtered if not _effective_version(d)]

    audit_deps: List[Dict] = []

    # Memoize metadata fetches per GA
    metadata_cache: Dict[str, Any] = {}

    for dep in deps_with_version:
        current_version = _effective_version(dep)
        ga_key = f"{dep['groupId']}:{dep['artifactId']}"
        # resolved_from is captured as soon as fetch_metadata succeeds, so an
        # unexpected downstream failure still carries provenance — mirrors the
        # #317 finding 1 fix applied to handle_check_multiple_dependencies /
        # handle_compare_dependency_versions.
        resolved_from = None
        try:
            if ga_key not in metadata_cache:
                metadata_cache[ga_key] = fetch_metadata(dep["groupId"], dep["artifactId"], ctx)
            metadata = metadata_cache[ga_key]
            resolved_from = metadata.get("resolvedFrom")
            latest = find_latest_version_for_current(metadata["versions"], current_version)
            upgrade_type = get_upgrade_type(current_version, latest) if latest else "none"
            entry = {
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "currentVersion": current_version,
                "latestVersion": latest,
                "upgradeType": upgrade_type,
                "source": dep["source"],
                "usages": dep.get("usages", []),
                "module": (dep.get("usages") or [{}])[0].get("module"),
                "configuration": (dep.get("usages") or [{}])[0].get("configuration"),
                "resolvedFrom": resolved_from,
            }
            if dep.get("effectiveVersion") is not None:
                entry["effectiveVersion"] = dep["effectiveVersion"]
            if dep.get("managedBy") is not None:
                entry["managedBy"] = dep["managedBy"]
            if dep.get("isPlatform"):
                entry["isPlatform"] = True
                entry["platformKind"] = dep.get("platformKind")
            audit_deps.append(entry)
        except Exception as e:
            # str(e) is safe here: fetch_metadata's own messages are redacted
            # at the source (see fetch_metadata), and find_latest_version_for_
            # current/get_upgrade_type are pure version-string functions that
            # never embed a repo URL.
            error_entry = {
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "currentVersion": current_version,
                "source": dep["source"],
                "usages": dep.get("usages", []),
                "module": (dep.get("usages") or [{}])[0].get("module"),
                "configuration": (dep.get("usages") or [{}])[0].get("configuration"),
                "error": str(e),
            }
            if resolved_from is not None:
                error_entry["resolvedFrom"] = resolved_from
            if dep.get("effectiveVersion") is not None:
                error_entry["effectiveVersion"] = dep["effectiveVersion"]
            if dep.get("managedBy") is not None:
                error_entry["managedBy"] = dep["managedBy"]
            audit_deps.append(error_entry)

    for dep in deps_without_version:
        entry = {
            "groupId": dep["groupId"],
            "artifactId": dep["artifactId"],
            "source": dep["source"],
            "usages": dep.get("usages", []),
            "module": (dep.get("usages") or [{}])[0].get("module"),
            "configuration": (dep.get("usages") or [{}])[0].get("configuration"),
        }
        if dep.get("isPlatform"):
            entry["isPlatform"] = True
            entry["platformKind"] = dep.get("platformKind")
        audit_deps.append(entry)

    # Vulnerability check — deduplicate per GAV
    if include_vulns and deps_with_version:
        gav_map: Dict[str, List[Dict]] = {}
        for a in audit_deps:
            if not a.get("currentVersion"):
                continue
            key = f"{a['groupId']}:{a['artifactId']}:{a['currentVersion']}"
            gav_map.setdefault(key, []).append(a)

        unique_gavs = []
        unique_keys = []
        resolved_impls: Dict[str, Optional[Dict]] = {}
        for key, entries in gav_map.items():
            first = entries[0]
            resolved = resolve_plugin_marker_implementation(
                first["groupId"], first["artifactId"], first["currentVersion"], ctx
            )
            resolved_impls[key] = resolved
            unique_gavs.append(resolved if resolved else {
                "groupId": first["groupId"],
                "artifactId": first["artifactId"],
                "version": first["currentVersion"],
            })
            unique_keys.append(key)

        vuln_results = query_osv_batch(unique_gavs)
        for i, key in enumerate(unique_keys):
            targets = gav_map.get(key, [])
            mapped_vulns = [
                {
                    "id": v["id"],
                    "severity": v.get("severity"),
                    "fixedVersion": v.get("fixedVersion"),
                    # Forwarded explicitly (#322): this dict is a narrower
                    # reconstruction of query_osv_batch's vuln_info, not a
                    # pass-through, so a new vuln_info field does not reach here
                    # for free.
                    "malicious": v.get("malicious", False),
                }
                for v in vuln_results[i].get("vulnerabilities", [])
            ]
            resolved = resolved_impls.get(key)
            for target in targets:
                target["vulnerabilities"] = mapped_vulns
                if resolved:
                    target["resolvedImplementation"] = resolved

    summary = {
        "total": len(audit_deps),
        "upgradeable": sum(1 for d in audit_deps if d.get("upgradeType") and d["upgradeType"] != "none"),
        "vulnerable": sum(1 for d in audit_deps if d.get("vulnerabilities")),
        "major": sum(1 for d in audit_deps if d.get("upgradeType") == "major"),
        "minor": sum(1 for d in audit_deps if d.get("upgradeType") == "minor"),
        "patch": sum(1 for d in audit_deps if d.get("upgradeType") == "patch"),
    }

    return {"buildSystem": scan["buildSystem"], "dependencies": audit_deps, "summary": summary}


# ---------------------------------------------------------------------------
# Tool definitions (for tools/list and initialize)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# verify_coordinates — existence tri-state + did-you-mean suggestions
# ---------------------------------------------------------------------------

# A candidate whose raw similarity to the requested coordinate reaches this
# threshold makes an ABSENT coordinate read as a slopsquat-shaped hallucination
# (one-edit-from-a-real-name). Named so it stays calibratable; the boundary is
# pinned by tests, so it must not be inlined.
HALLUCINATION_THRESHOLD = 0.8

# Breadth of the Solr candidate pool fetched per absent coordinate. Larger than
# the default suggestLimit so the hallucination flag (computed over the FULL
# pre-truncation set) can still fire on a high-similarity candidate that the
# low-popularity penalty later pushes out of the emitted top-N.
_SUGGEST_SEARCH_ROWS = 20

# Order-only de-weighting of very-low-versionCount candidates. Subtracted from
# the similarity score in the SORT KEY only (never folded into the emitted raw
# `score` or the flag) so a brand-new single-version near-miss — the
# attacker-registered slopsquat shape — cannot outrank a high-popularity real
# coordinate that sits at slightly lower raw similarity.
_LOW_POPULARITY_PENALTY = 0.5


def _suggestion_rank(suggestion: Dict[str, Any]) -> float:
    """Sort key for did-you-mean candidates: raw similarity minus a penalty that
    decays with versionCount (1/(versionCount+1)). Order only — the emitted
    `score` stays the raw `_similarity`."""
    version_count = suggestion.get("versionCount", 0) or 0
    return suggestion["score"] - _LOW_POPULARITY_PENALTY / (version_count + 1)


# ---------------------------------------------------------------------------
# typosquatRisk (heuristic layer 2 on top of an EXISTING coordinate, #322)
# ---------------------------------------------------------------------------

# Detection-calibration constants: proposed starting points, NOT proven against
# a labeled dataset -- same caveat as HALLUCINATION_THRESHOLD above when it was
# first introduced. Calibratable, not inlined.
LOW_VERSION_COUNT_THRESHOLD = 2
GROUP_MISMATCH_SIMILARITY = 0.95
GROUP_MISMATCH_POPULARITY_RATIO = 5
RECENT_PUBLISH_DAYS_THRESHOLD = 30

# Operational load-bound (NOT a detection threshold, so it does not carry the
# same labeled-dataset caveat as the four constants above). Caps gated Solr
# calls (group-mismatch + recent-first-publish combined) across ONE
# handle_verify_coordinates batch invocation: gating behind low_version_count
# narrows AVERAGE load but a cold-cache/large-batch run where MANY coordinates
# simultaneously qualify is not bounded by gating alone.
MAX_GATED_SOLR_CALLS_PER_BATCH = 20


def _compute_typosquat_risk(
    group_id: str,
    artifact_id: str,
    version_count: int,
    versions: List[str],
    gated_calls: List[int],
) -> Dict[str, Any]:
    """Heuristic typosquat/popularity signal for an ``exists`` coordinate.

    A candidate to verify, not a verdict -- false-positive-prone by
    construction (a legitimately new/niche library also has a low version
    count). Framed as cautiously as `suggestions`. Never folded into
    `likelyHallucination`, which stays absent-only (separate field, separate
    computation, no shared code path).

    ``gated_calls`` is a per-batch counter (a 1-element list used as a mutable
    cell) SHARED across every coordinate in one `handle_verify_coordinates`
    call. Callers MUST pass a list created FRESH at the top of that call, never
    a module-level global: server.py runs as a long-lived stdio process, so a
    global counter would accumulate gated-call usage across the entire process
    lifetime instead of resetting per batch.

    Coverage boundary: `group_mismatch` targets identical/near-identical-name
    impersonation (`GROUP_MISMATCH_SIMILARITY`, near-identical, not merely
    similar). `low_version_count` alone is the fallback signal for an attacker
    who ALSO edits the artifactId (a 1-edit-distance typo), which may score
    below the similarity threshold.

    Accepted residual risk: `group_mismatch` and `recent_first_publish` are
    BOTH gated behind the same `low_version_count` precondition, so an attacker
    can publish a few trivial version bumps immediately after a typosquat lands
    (Central has no publish review gate) to push `version_count` above
    `LOW_VERSION_COUNT_THRESHOLD` and suppress ALL of Layer 2 at once -- for
    exactly the OSSF-reporting-lag window Layer 2 exists to cover. Accepted,
    not re-architected: Layer 2 stays advisory-only (`ask`, never `deny`), so
    Layer 1's authoritative `deny` path (independent of version count) is
    unaffected.
    """
    reasons: List[str] = []
    if version_count <= LOW_VERSION_COUNT_THRESHOLD:
        reasons.append("low_version_count")

    popular_match: Optional[Dict[str, Any]] = None
    # Group-mismatch and recent-first-publish share ONE precondition:
    # low_version_count must have already fired. GATED (not
    # unconditional-per-`exists`-coordinate) because search.maven.org has a
    # documented rate-limiting/403-lockout history under bulk load and
    # _request_with_retry does not retry 403 -- an unconditional query on the
    # dominant `exists` case in a real batch risked degrading the shared
    # endpoint for the EXISTING did-you-mean/search_artifacts paths too.
    #
    # MAX_GATED_SOLR_CALLS_PER_BATCH bounds the number of actual outbound Solr
    # HTTP calls, not the number of gated-in coordinates -- each gated-in
    # coordinate can issue up to TWO Solr calls (group-mismatch search +
    # recent-first-publish timestamp fetch), so the cap is checked and the
    # counter incremented separately before EACH call, not once per
    # coordinate. Counting per-coordinate instead would silently allow up to
    # 2x the named/documented call budget in exactly the cold-cache/
    # large-batch scenario this cap exists to bound.
    if "low_version_count" in reasons:
        if gated_calls[0] < MAX_GATED_SOLR_CALLS_PER_BATCH:
            gated_calls[0] += 1
            candidates = search_maven_central(_solr_escape(artifact_id), _SUGGEST_SEARCH_ROWS, use_cache=True)
            for cand in candidates:
                cand_g = cand.get("groupId", "")
                cand_a = cand.get("artifactId", "")
                if cand_g == group_id:
                    continue
                if _similarity(artifact_id.lower(), cand_a.lower()) < GROUP_MISMATCH_SIMILARITY:
                    continue
                cand_vc = cand.get("versionCount", 0) or 0
                if popular_match is None or cand_vc > popular_match["versionCount"]:
                    popular_match = {"groupId": cand_g, "artifactId": cand_a, "versionCount": cand_vc}
            if popular_match is not None and popular_match["versionCount"] > GROUP_MISMATCH_POPULARITY_RATIO * version_count:
                reasons.append("group_mismatch")
            else:
                # A coincidentally-shared name with COMPARABLE popularity on
                # both sides must not flag -- discard the candidate entirely
                # (popularMatch is only ever emitted alongside a fired
                # group_mismatch reason).
                popular_match = None

        # Recent-first-publish: a gated, best-effort ENRICHMENT on top of an
        # already-fired signal, never a signal on its own -- it never turns
        # signal:false into signal:true by itself. versions[0] is the
        # semver-MINIMUM of a deduplicated union across repos (`versions` is
        # sorted by compare_versions), NOT necessarily the chronologically-
        # first-published version -- the two coincide only when version
        # numbers happen to increase monotonically with release time. A
        # reasonable, but imperfect, first-publish proxy under this
        # <=LOW_VERSION_COUNT_THRESHOLD-version gate. Cap checked
        # independently of the group-mismatch call above (its own Solr call).
        if versions and gated_calls[0] < MAX_GATED_SOLR_CALLS_PER_BATCH:
            gated_calls[0] += 1
            ts = _fetch_gav_timestamp(group_id, artifact_id, versions[0])
            if ts is not None:
                now_ms = time.time() * 1000
                if now_ms - ts <= RECENT_PUBLISH_DAYS_THRESHOLD * 86400 * 1000:
                    reasons.append("recent_first_publish")

    risk: Dict[str, Any] = {
        "signal": bool(reasons),
        "reasons": reasons,
        "versionCount": version_count,
    }
    if popular_match is not None:
        risk["popularMatch"] = popular_match
    return risk


def _verify_one(
    group_id: str,
    artifact_id: str,
    version: Optional[str],
    suggest_limit: int,
    ctx: "ResolutionContext",
    gated_calls: List[int],
) -> Dict[str, Any]:
    """Verify a single coordinate. Runs its OWN per-repo existence probe (not
    fetch_metadata's raise, which conflates absent vs unreachable and drops the
    answering repo). Classifies existence as a tri-state and, only when ABSENT,
    queries Maven Central for popularity-aware did-you-mean candidates. When
    EXISTS, additionally computes `typosquatRisk` (#322 Layer 2) -- see
    `_compute_typosquat_risk`. ``gated_calls`` is the per-batch Solr-call
    counter shared across the whole `handle_verify_coordinates` invocation;
    callers must pass a list created fresh at the top of that call."""
    union_versions = set()
    first_answering_repo: Optional[str] = None
    any_200 = False
    saw_404 = False
    # Any non-200/non-404 HTTP status (401/403/429/5xx) OR a raised transport
    # error: the repo MIGHT hold the artifact, so absence cannot be asserted.
    saw_unverifiable = False
    for entry in _repos_for(group_id, artifact_id, ctx):
        url = _metadata_url(entry["url"], group_id, artifact_id)
        try:
            # Auth headers attached when credentials resolve for this repo
            # (#291); public repos stay UA-only. Live every call (no cache) —
            # same anti-steering contract as before.
            status, body = _repo_http_get(entry, url)
        except (urllib.error.URLError, socket.timeout, http.client.InvalidURL):
            # Transport failure (offline / DNS / read timeout) — verification
            # unavailable for THIS repo; contributes "unknown", never "absent".
            # http.client.InvalidURL (NOT a urllib.error.URLError subclass) is
            # what a userinfo repo URL (https://user:pass@host) raises during
            # request construction — same fetch_metadata credential-leak class
            # (#317 security review): without this clause it would escape to
            # handle_verify_coordinates's outer `except Exception as e: str(e)`
            # and embed the raw password in the "error" field. Treated as an
            # ordinary unverifiable-repo transport failure, never stringified.
            saw_unverifiable = True
            continue
        if status == 200:
            any_200 = True
            if first_answering_repo is None:
                first_answering_repo = entry["name"]
            parsed = _parse_metadata_xml(
                body.decode("utf-8", errors="replace"), group_id, artifact_id
            )
            # UNION versions across EVERY 200-answering repo (matches the #311
            # cross-repo merge) — a first-hit short-circuit would lose versions a
            # private repo holds.
            union_versions.update(parsed["versions"])
        elif status == 404:
            saw_404 = True
        else:
            # 401/403 (auth required / forbidden) and other non-404 statuses
            # remain "unknown" — the private repo might hold the artifact.
            saw_unverifiable = True

    if any_200:
        existence_status = "exists"
    elif saw_404 and not saw_unverifiable:
        # ABSENT only when EVERY probed repo returned a definitive 404.
        existence_status = "absent"
    else:
        existence_status = "unknown"

    versions = sorted(union_versions, key=functools.cmp_to_key(compare_versions))
    latest = find_latest_version(versions, "PREFER_STABLE")

    result: Dict[str, Any] = {
        "groupId": group_id,
        "artifactId": artifact_id,
        "existenceStatus": existence_status,
        "gaExists": existence_status == "exists",
        "likelyHallucination": False,
    }
    if version is not None:
        result["version"] = version
        # Membership in the UNION (not first-hit): a version present only in the
        # second answering repo still counts.
        result["gavExists"] = version in union_versions
    # Guard against a 200 with an empty <versions> list: latest is None, so
    # classify_version is never called on None and stability is omitted.
    if latest:
        result["stability"] = classify_version(latest)
    if first_answering_repo is not None:
        # first_answering_repo can be the literal repo URL (maven("url")
        # declarations set name == url) — same userinfo redaction as resolvedFrom.
        result["repository"] = _strip_userinfo(first_answering_repo)

    if existence_status == "exists":
        # Layer 2 (#322): only ever computed for EXISTS -- never for
        # absent/unknown -- and a SEPARATE field from likelyHallucination,
        # which stays absent-only with no shared code path or threshold.
        result["typosquatRisk"] = _compute_typosquat_risk(
            group_id, artifact_id, len(union_versions), versions, gated_calls
        )

    if existence_status == "absent":
        req_ga = (group_id + ":" + artifact_id).lower()
        req_a = artifact_id.lower()
        # Escape Solr metacharacters before the token reaches the query so a
        # crafted artifactId can't be parsed as Solr syntax to broaden the match
        # set (a suggestion-steering vector).
        candidates = search_maven_central(_solr_escape(artifact_id), _SUGGEST_SEARCH_ROWS, use_cache=False)
        scored = []
        flag = False
        for cand in candidates:
            cand_g = cand.get("groupId", "")
            cand_a = cand.get("artifactId", "")
            cand_ga = (cand_g + ":" + cand_a).lower()
            # Raw similarity: surface a candidate whose artifactId matches even if
            # the group differs (max == min edit distance over the two forms).
            score = max(_similarity(req_ga, cand_ga), _similarity(req_a, cand_a.lower()))
            # Threshold-gate BOTH the flag and the emitted list: a free-text Solr
            # hit with weak similarity is not evidence of hallucination, and
            # emitting it would make any non-empty-suggestions consumer (the
            # #283 pre-edit hook historically) de-facto deny-on-bare-absent for
            # private/new coordinates whose artifactId shares a common token.
            if score >= HALLUCINATION_THRESHOLD:
                flag = True
                scored.append({
                    "groupId": cand_g,
                    "artifactId": cand_a,
                    "score": score,
                    "versionCount": cand.get("versionCount", 0) or 0,
                })
        # Flag is computed over the FULL pre-truncation/pre-penalty set above, so
        # de-weighting a high-similarity low-popularity near-miss out of the
        # emitted top-N never silently suppresses it. An empty list means "no
        # close match" — same threshold as likelyHallucination.
        result["likelyHallucination"] = flag
        scored.sort(key=_suggestion_rank, reverse=True)
        result["suggestions"] = scored[:suggest_limit]

    return result


def handle_verify_coordinates(args: Dict) -> Any:
    """Batch-verify Maven coordinates: tri-state existence (exists / absent /
    unknown) plus did-you-mean suggestions for absent ones. Output never asserts
    "safe" — a published typosquat reports exists and is not flagged (#322)."""
    dependencies = args.get("dependencies") or []
    # Caps are ENFORCED here, before any network I/O — an MCP inputSchema's
    # maxItems/maximum is advisory client metadata the server never validates, so
    # the bound on outbound fan-out (each dep -> up-to-N-repo probe + a search)
    # lives in code. Truncate an over-long batch; clamp suggestLimit.
    if len(dependencies) > 100:
        dependencies = dependencies[:100]
    try:
        suggest_limit = int(args.get("suggestLimit", 3))
    except (TypeError, ValueError):
        suggest_limit = 3
    suggest_limit = max(0, min(suggest_limit, 10))

    ctx = build_resolution_context(args)
    # Per-batch gated-Solr-call counter (#322): a 1-element list used as a
    # mutable cell, created FRESH here -- a LOCAL variable, NEVER module-level
    # state. server.py is a long-lived stdio process; a global counter would
    # accumulate across the entire process lifetime instead of resetting per
    # batch. Shared across every coordinate in THIS call only.
    gated_calls = [0]
    results = []
    for dep in dependencies:
        group_id = dep.get("groupId", "")
        artifact_id = dep.get("artifactId", "")
        version = dep.get("version")
        try:
            results.append(_verify_one(group_id, artifact_id, version, suggest_limit, ctx, gated_calls))
        except Exception as e:
            # Per-item isolation for an UNEXPECTED failure (distinct from a probe
            # transport error, which _verify_one already folds into "unknown"):
            # this one coordinate degrades to an error entry; siblings resolve.
            item: Dict[str, Any] = {
                "groupId": group_id,
                "artifactId": artifact_id,
                "existenceStatus": "unknown",
                "gaExists": False,
                "likelyHallucination": False,
                "error": str(e),
            }
            if version is not None:
                item["version"] = version
            results.append(item)
    return {"results": results}



def handle_check_version_compatibility(args: Dict) -> Any:
    """Validate Spring Boot BOM / Android-Kotlin-Gradle-JDK / javax→jakarta (#285)."""
    spring_boot = args.get("springBoot")
    android = args.get("android")
    dependencies = args.get("dependencies") or []
    if not isinstance(dependencies, list):
        dependencies = []
    # Cap before any network I/O (BOM expand) — same rationale as verify_coordinates.
    if len(dependencies) > MAX_COMPAT_DEPENDENCIES:
        dependencies = dependencies[:MAX_COMPAT_DEPENDENCIES]
    ctx = None
    if spring_boot:
        ctx = build_resolution_context(args)
    return check_version_compatibility(
        spring_boot=spring_boot,
        android=android if isinstance(android, dict) else None,
        dependencies=dependencies,
        ctx=ctx,
    )



TOOLS = [
    {
        "name": "get_latest_version",
        "description": "Get the latest version of a Maven artifact from Maven Central, Google Maven, or Gradle Plugin Portal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "groupId": {"type": "string", "description": "Maven group ID"},
                "artifactId": {"type": "string", "description": "Maven artifact ID"},
                "stabilityFilter": {
                    "type": "string",
                    "enum": ["PREFER_STABLE", "STABLE_ONLY", "ALL"],
                    "description": "Version stability filter. Default: PREFER_STABLE",
                },
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
            },
            "required": ["groupId", "artifactId"],
        },
    },
    {
        "name": "check_version_exists",
        "description": "Check if a specific version of a Maven artifact exists in any known repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "groupId": {"type": "string"},
                "artifactId": {"type": "string"},
                "version": {"type": "string"},
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
            },
            "required": ["groupId", "artifactId", "version"],
        },
    },
    {
        "name": "check_multiple_dependencies",
        "description": "Batch lookup of latest versions for multiple Maven dependencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dependencies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "groupId": {"type": "string"},
                            "artifactId": {"type": "string"},
                        },
                        "required": ["groupId", "artifactId"],
                    },
                },
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
            },
            "required": ["dependencies"],
        },
    },
    {
        "name": "compare_dependency_versions",
        "description": "Compare current dependency versions against the latest available and determine upgrade types (major/minor/patch).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dependencies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "groupId": {"type": "string"},
                            "artifactId": {"type": "string"},
                            "currentVersion": {"type": "string"},
                        },
                        "required": ["groupId", "artifactId", "currentVersion"],
                    },
                },
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
            },
            "required": ["dependencies"],
        },
    },
    {
        "name": "get_dependency_changes",
        "description": "Get changelog/release notes for a dependency between two versions by fetching GitHub releases.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "groupId": {"type": "string"},
                "artifactId": {"type": "string"},
                "fromVersion": {"type": "string", "description": "Starting version (exclusive)"},
                "toVersion": {"type": "string", "description": "Target version (inclusive)"},
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
            },
            "required": ["groupId", "artifactId", "fromVersion", "toVersion"],
        },
    },
    {
        "name": "scan_project_dependencies",
        "description": "Scan a local project directory to extract declared dependencies from build files (Gradle, Maven). Applies BOM/platform managed versions (effectiveVersion/managedBy) via network POM fetch when platforms are declared.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectPath": {"type": "string", "description": "Path to the project root. Defaults to current working directory."},
            },
        },
    },
    {
        "name": "expand_bom",
        "description": "Expand a Maven BOM (Bill of Materials) into its managed dependency versions. Recursively expands import-scope BOMs with first-wins ordering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "groupId": {"type": "string", "description": "BOM group ID"},
                "artifactId": {"type": "string", "description": "BOM artifact ID"},
                "version": {"type": "string", "description": "BOM version"},
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
            },
            "required": ["groupId", "artifactId", "version"],
        },
    },
    {
        "name": "get_transitive_graph",
        "description": "Fetch the resolved transitive dependency graph for a Maven GAV via deps.dev GetDependencies. Returns nodes (g/a/v) and edges (from/to indices). Partial results are flagged when deps.dev is unreachable, returns errors, or the graph is truncated by the node cap.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "groupId": {"type": "string", "description": "Maven group ID"},
                "artifactId": {"type": "string", "description": "Maven artifact ID"},
                "version": {"type": "string", "description": "Maven version"},
            },
            "required": ["groupId", "artifactId", "version"],
        },
    },
    {
        "name": "detect_dependency_conflicts",
        "description": "Detect version conflicts by unioning deps.dev transitive graphs for each direct project dependency. Flags GAs appearing at ≥2 versions and reports the version Maven nearest-wins or Gradle highest-wins would pick. Approximation of a full project resolve — see notes[] for limitations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectPath": {"type": "string", "description": "Path to the project root. Defaults to current working directory."},
                "buildSystem": {
                    "type": "string",
                    "enum": ["maven", "gradle"],
                    "description": "Override detected build system for mediation strategy (nearest-wins vs highest-wins). Defaults to auto-detect.",
                },
            },
        },
    },
    {
        "name": "check_version_compatibility",
        "description": "Check whether a set of versions is mutually compatible. Validates (1) dependency versions against the Spring Boot BOM (spring-boot-dependencies) when springBoot is set, (2) AGP↔Gradle↔JDK and Kotlin Gradle plugin↔Gradle/AGP ranges from a shipped matrix file, and (3) javax→jakarta EE coordinate migration when Spring Boot ≥ 3. Returns conflicts with suggested compatible versions and reference URLs. v1 coverage is intentionally bounded — see notes[] / AGENTS.md; matrices are not scraped at runtime and must be refreshed via the documented procedure in compat-matrices.json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "springBoot": {
                    "type": "string",
                    "description": "Spring Boot version. When set, expands org.springframework.boot:spring-boot-dependencies and checks dependencies[] against managed versions; also enables javax→jakarta checks when ≥ 3.0.0.",
                },
                "android": {
                    "type": "object",
                    "description": "Android / Kotlin toolchain versions to validate against the shipped AGP and KGP matrices.",
                    "properties": {
                        "agp": {"type": "string", "description": "Android Gradle Plugin version"},
                        "gradle": {"type": "string", "description": "Gradle version"},
                        "kotlin": {"type": "string", "description": "Kotlin Gradle plugin version"},
                        "jdk": {"type": "integer", "description": "JDK major version used to run the build"},
                    },
                },
                "dependencies": {
                    "type": "array",
                    "maxItems": 100,
                    "description": "Dependencies to check against the Spring Boot BOM and/or javax→jakarta map.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "groupId": {"type": "string"},
                            "artifactId": {"type": "string"},
                            "version": {"type": "string"},
                        },
                        "required": ["groupId", "artifactId"],
                    },
                },
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories for BOM fetch. Defaults to the current working directory."},
            },
        },
    },
    {
        "name": "get_dependency_vulnerabilities",
        "description": "Check dependencies for known vulnerabilities using the OSV.dev database.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dependencies": {
                    "type": "array",
                    "maxItems": 100,
                    "items": {
                        "type": "object",
                        "properties": {
                            "groupId": {"type": "string"},
                            "artifactId": {"type": "string"},
                            "version": {"type": "string"},
                        },
                        "required": ["groupId", "artifactId", "version"],
                    },
                },
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
            },
            "required": ["dependencies"],
        },
    },
    {
        "name": "get_dependency_health",
        "description": "Get health signals for Maven dependencies: version info, GitHub activity, issue stats, license, and maintenance signals.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dependencies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "groupId": {"type": "string"},
                            "artifactId": {"type": "string"},
                            "version": {"type": "string"},
                        },
                        "required": ["groupId", "artifactId"],
                    },
                },
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
            },
            "required": ["dependencies"],
        },
    },
    {
        "name": "search_artifacts",
        "description": "Search Maven Central for artifacts by keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100, "description": "Maximum number of results. Default 10, clamped to [1, 100]."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "audit_project_dependencies",
        "description": "Orchestrates a full dependency audit: scans project build files, checks for available updates, and optionally queries OSV.dev for vulnerabilities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
                "includeVulnerabilities": {"type": "boolean", "description": "Include OSV vulnerability check (default true)"},
                "productionOnly": {"type": "boolean", "description": "Exclude test-scope dependencies (default true)"},
            },
        },
    },
    {
        "name": "verify_coordinates",
        "description": "Verify whether Maven coordinates exist (tri-state: exists / absent / unknown) and, for absent ones, suggest the closest real coordinates. Detects hallucinated / slopsquat-shaped names an LLM may invent. Existence is NOT a safety guarantee: a published typosquat reports exists and is not flagged. Suggestions are candidates to verify, not endorsements.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dependencies": {
                    "type": "array",
                    "maxItems": 100,
                    "items": {
                        "type": "object",
                        "properties": {
                            "groupId": {"type": "string"},
                            "artifactId": {"type": "string"},
                            "version": {"type": "string", "description": "Optional. When given, gavExists reports whether this exact version exists."},
                        },
                        "required": ["groupId", "artifactId"],
                    },
                },
                "suggestLimit": {"type": "integer", "default": 3, "maximum": 10, "description": "Maximum did-you-mean suggestions per absent coordinate. Default 3, capped at 10."},
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
            },
            "required": ["dependencies"],
        },
    },
]

TOOL_HANDLERS = {
    "get_latest_version": handle_get_latest_version,
    "check_version_exists": handle_check_version_exists,
    "check_multiple_dependencies": handle_check_multiple_dependencies,
    "compare_dependency_versions": handle_compare_dependency_versions,
    "get_dependency_changes": handle_get_dependency_changes,
    "scan_project_dependencies": handle_scan_project_dependencies,
    "expand_bom": handle_expand_bom,
    "get_transitive_graph": handle_get_transitive_graph,
    "detect_dependency_conflicts": handle_detect_dependency_conflicts,
    "check_version_compatibility": handle_check_version_compatibility,
    "get_dependency_vulnerabilities": handle_get_dependency_vulnerabilities,
    "get_dependency_health": handle_get_dependency_health,
    "search_artifacts": handle_search_artifacts,
    "audit_project_dependencies": handle_audit_project_dependencies,
    "verify_coordinates": handle_verify_coordinates,
}


# ---------------------------------------------------------------------------
# MCP JSON-RPC 2.0 dispatcher
# ---------------------------------------------------------------------------

def _write_response(response: Any) -> None:
    # `response` is a single response object, or a list of them for a batch.
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _handle_initialize(msg_id: Any, params: Dict) -> Dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    }


def _handle_tools_list(msg_id: Any, params: Dict) -> Dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {"tools": TOOLS},
    }


def _handle_tools_call(msg_id: Any, params: Dict) -> Dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
        }
    try:
        result = handler(arguments)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result)}],
            },
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32603, "message": str(e)},
        }


def _handle_ping(msg_id: Any, params: Dict) -> Dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": {}}


def _dispatch_message(msg: Any) -> Optional[Dict]:
    """Dispatch one JSON-RPC message; return the response object, or None.

    None means "no response" (a notification). A non-dict message (string,
    number, boolean, null, or an array — top-level arrays are batches and
    are routed to _dispatch_batch by dispatch()/main() before reaching
    here, so an array HERE is a nested one inside a batch) gets a -32600
    Invalid Request response instead of crashing the server (#343).
    """
    if not isinstance(msg, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request: expected a JSON object"},
        }

    method = msg.get("method", "")
    msg_id = msg.get("id")  # None for notifications
    params = msg.get("params") or {}

    # Notifications — no response
    if msg_id is None:
        return None

    if not isinstance(params, dict):
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32602, "message": "Invalid params: expected an object"},
        }

    if method == "initialize":
        return _handle_initialize(msg_id, params)
    if method == "tools/list":
        return _handle_tools_list(msg_id, params)
    if method == "tools/call":
        return _handle_tools_call(msg_id, params)
    if method == "ping":
        return _handle_ping(msg_id, params)
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def dispatch(msg: Any) -> None:
    if isinstance(msg, list):
        _dispatch_batch(msg)
        return
    response = _dispatch_message(msg)
    if response is not None:
        _write_response(response)


def _dispatch_batch(batch: List[Any]) -> None:
    """Handle a JSON-RPC 2.0 batch request (a JSON array of messages)."""
    if not batch:
        # Per JSON-RPC 2.0, an empty batch gets a single error object, not an array.
        _write_response({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request: empty batch"},
        })
        return
    responses = []
    for item in batch:
        try:
            response = _dispatch_message(item)
        except Exception as e:
            item_id = item.get("id") if isinstance(item, dict) else None
            response = None
            if item_id is not None:
                response = {
                    "jsonrpc": "2.0",
                    "id": item_id,
                    "error": {"code": -32603, "message": f"Internal error: {e}"},
                }
        if response is not None:
            responses.append(response)
    # An all-notifications batch gets no response at all, per spec.
    if responses:
        _write_response(responses)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            _write_response({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            })
            continue
        try:
            dispatch(msg)  # routes top-level arrays to _dispatch_batch
        except Exception as e:
            msg_id = msg.get("id") if isinstance(msg, dict) else None
            if msg_id is not None:
                _write_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32603, "message": f"Internal error: {e}"},
                })


if __name__ == "__main__":
    main()

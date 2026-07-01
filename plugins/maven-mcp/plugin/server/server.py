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
SEARCH_API = "https://search.maven.org/solrsearch/select"

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

PRODUCTION_CONFIGURATIONS = {
    "implementation", "api", "compileOnly", "runtimeOnly",
}
NON_PRODUCTION_CONFIGURATIONS = {
    "testImplementation", "testCompileOnly", "testRuntimeOnly",
    "kapt", "ksp", "annotationProcessor",
}
ALL_CONFIGURATIONS = PRODUCTION_CONFIGURATIONS | NON_PRODUCTION_CONFIGURATIONS

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


def _request_with_retry(req: urllib.request.Request) -> Tuple[int, bytes]:
    """Issue ``req`` with bounded retry/backoff on transient failures.

    Tri-state contract (relied on by the resolution layer and verify_coordinates):
    returns ``(status, body)`` for ANY HTTP response — including a persistent
    429/5xx after retries are exhausted — and only re-raises the last transport
    error (URLError / socket.timeout) when EVERY attempt failed at the transport
    level without ever obtaining an HTTP response. A 4xx (incl. 404) is never
    turned into a raise. Retry is fully internal and transparent to callers.
    """
    deadline = time.monotonic() + HTTP_TOTAL_RETRY_BUDGET
    last_result: Optional[Tuple[int, bytes]] = None
    last_exc: Optional[BaseException] = None
    for attempt in range(HTTP_MAX_ATTEMPTS):
        retry_after: Optional[float] = None
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                status, body = resp.status, resp.read()
                if not _is_retryable_status(status):
                    return status, body
                # A retryable status surfaced as a success object (rare — urllib
                # normally raises HTTPError for 4xx/5xx); remember it and retry.
                last_result = (status, body)
                retry_after = _parse_retry_after(getattr(resp, "headers", None))
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
    when every attempt hit a transport error."""
    req = urllib.request.Request(url, headers=headers or _make_headers())
    return _request_with_retry(req)


def http_post_json(url: str, payload: Any, headers: Optional[Dict[str, str]] = None) -> Tuple[int, bytes]:
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


def http_get_cached(url: str, ttl_seconds: float) -> Tuple[int, bytes]:
    """Cached GET: returns a cached (200, body) on hit, else delegates to http_get.

    No ``headers`` parameter — callers use the default UA-only headers, and
    accepting auth-bearing headers not folded into the cache key would be a
    latent footgun (cached response served for a different caller's credentials).

    Sensitive hosts (api.github.com, api.osv.dev) bypass to raw http_get via
    a static denylist: belt-and-suspenders against future mis-wiring.  Private
    Maven repo hosts are NOT blocked — this is a blocklist, not an allowlist.

    A cache hit short-circuits ABOVE the #306 retry layer: the response is
    returned directly without ever calling http_get (and thus without consuming
    any retry budget).  Non-200 responses and propagating transport errors are
    never cached; the caller receives them exactly as http_get would return/raise.
    """
    host = urllib.parse.urlparse(url).hostname or ""
    if host in _CACHE_DENYLIST:
        return http_get(url)
    result = _file_cache.get(url, ttl_seconds)
    if result is not None:
        return result
    status, body = http_get(url)
    if status == 200:
        _file_cache.set(url, status, body)
    return (status, body)


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
    separate cache map); ``public_fallback`` is read from
    MAVEN_MCP_PUBLIC_FALLBACK at construction, never sniffed in leaf functions."""

    def __init__(
        self,
        project_path: str,
        scoped_repos: Dict[str, List[Dict[str, str]]],
        public_fallback: bool,
    ) -> None:
        self.project_path = project_path
        self.scoped_repos = scoped_repos
        self.public_fallback = public_fallback


def _public_fallback_enabled() -> bool:
    """MAVEN_MCP_PUBLIC_FALLBACK toggle. Default OFF (closed-mode #294 wants it
    off); when ON, public repos are appended even for projects that declare
    their own repositories (escape hatch for implicit/inherited-repo builds)."""
    return os.environ.get("MAVEN_MCP_PUBLIC_FALLBACK", "").strip().lower() in (
        "1", "true", "on", "yes",
    )


def build_resolution_context(args: Dict) -> "ResolutionContext":
    """Build a ResolutionContext from a tool-call args dict at the handler
    boundary. project_path defaults to the current working directory; the toggle
    is read here once, not in the leaf resolvers."""
    project_path = args.get("projectPath") or os.getcwd()
    return ResolutionContext(
        project_path, discover_repositories(project_path), _public_fallback_enabled()
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
    declared scope (deduped by URL)."""
    scope = "plugin" if artifact_id.endswith(".gradle.plugin") else "dependency"
    declared = ctx.scoped_repos.get(scope, [])
    queryable = [r for r in declared if not r["url"].startswith("file://")]

    public_entries = [
        {"name": name, "url": url, "scope": scope, "is_public_fallback": True}
        for name, url in _public_repos(group_id, artifact_id)
    ]

    if queryable:
        entries = [
            {"name": r["name"], "url": r["url"], "scope": scope, "is_public_fallback": False}
            for r in queryable
        ]
        if ctx.public_fallback:
            entries.extend(public_entries)
            return _dedup_repos(entries)
        return entries
    return public_entries


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
    last_err = None
    # First repo (in _repos_for order: declared repos before any public-fallback
    # append) that answers 200 — surfaced as resolvedFrom for #317 provenance.
    resolved_from: Optional[Dict[str, Any]] = None
    for entry in repos:
        url = _metadata_url(entry["url"], group_id, artifact_id)
        try:
            status, body = http_get_cached(url, TTL_METADATA)
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
            status, body = http_get_cached(url, TTL_METADATA)
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
            status, body = http_get_cached(url, TTL_POM)
            if status == 200:
                return body.decode("utf-8", errors="replace")
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Version classification & comparison
# ---------------------------------------------------------------------------

def classify_version(version: str) -> str:
    for pattern, stability in STABILITY_PATTERNS:
        if pattern.search(version):
            return stability
    return "stable"


def _parse_segments(version: str) -> List[int]:
    core = re.split(r"[-+]", version, maxsplit=1)[0]
    parts = []
    for p in core.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts or [0]


def _extract_prerelease_numbers(version: str) -> List[int]:
    cut = -1
    for ch in ("-", "+"):
        idx = version.find(ch)
        if idx != -1 and (cut == -1 or idx < cut):
            cut = idx
    if cut == -1:
        return []
    suffix = version[cut + 1:]
    return [int(m) for m in re.findall(r"\d+", suffix)]


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
    has_suffix_a = "-" in a or "+" in a
    has_suffix_b = "-" in b or "+" in b
    if has_suffix_a != has_suffix_b:
        # #325: same core, same stability class, but only one side carries a
        # qualifier suffix at all — the bare version always ranks higher.
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


def query_osv_batch(deps: List[Dict]) -> List[Dict]:
    """deps: list of {groupId, artifactId, version}. Returns list of {groupId, artifactId, version, vulnerabilities}."""
    if not deps:
        return []
    queries = [
        {"package": {"name": f"{d['groupId']}:{d['artifactId']}", "ecosystem": "Maven"}, "version": d["version"]}
        for d in deps
    ]
    try:
        status, body = http_post_json(OSV_API, {"queries": queries})
        if status != 200:
            return [{**d, "vulnerabilities": []} for d in deps]
        data = json.loads(body)
        results = data.get("results", [])
        out = []
        for i, dep in enumerate(deps):
            vulns_raw = (results[i].get("vulns") or []) if i < len(results) else []
            vulns_raw = [v for v in vulns_raw if v.get("withdrawn") is None]
            vulns = []
            for v in vulns_raw:
                vuln_info = {
                    "id": v.get("id", ""),
                    "summary": v.get("summary", ""),
                    "url": _extract_url(v),
                }
                vuln_info["malicious"] = _is_malicious_id(v.get("id", ""))
                sev = _extract_severity(v)
                if sev:
                    vuln_info["severity"] = sev
                fixed = _extract_fixed_version(v)
                if fixed:
                    vuln_info["fixedVersion"] = fixed
                vulns.append(vuln_info)
            out.append({**dep, "vulnerabilities": vulns})
        return out
    except Exception:
        return [{**d, "vulnerabilities": []} for d in deps]


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
    """Returns list of dep dicts with keys: groupId, artifactId, version, configuration, catalogRef."""
    deps = []
    config_pattern = "|".join(re.escape(c) for c in sorted(ALL_CONFIGURATIONS, key=len, reverse=True))

    # String notation: implementation("group:artifact:version")
    string_re = re.compile(
        rf'\b({config_pattern})\s*[( ]\s*["\']([^"\':\s]+):([^"\':\s]+)(?::([^"\']+))?["\']',
    )
    for m in string_re.finditer(content):
        deps.append({
            "groupId": m.group(2),
            "artifactId": m.group(3),
            "version": m.group(4),
            "configuration": m.group(1),
            "catalogRef": None,
        })

    # Catalog accessor: implementation(libs.foo.bar)
    catalog_re = re.compile(
        rf'\b({config_pattern})\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9.]+)\s*\)',
    )
    for m in catalog_re.finditer(content):
        deps.append({
            "groupId": None,
            "artifactId": None,
            "version": None,
            "configuration": m.group(1),
            "catalogRef": f"{m.group(2)}.{m.group(3)}",
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
    """Parse buildscript { dependencies { classpath(...) } }"""
    results = []
    bs_re = re.compile(r'\bbuildscript\s*\{([\s\S]*?)\}', re.DOTALL)
    for bs_m in bs_re.finditer(content):
        block = bs_m.group(1)
        cp_re = re.compile(r'\bclasspath\s*\(["\']([^"\':\s]+):([^"\':\s]+)(?::([^"\']+))?["\']')
        for m in cp_re.finditer(block):
            results.append({"groupId": m.group(1), "artifactId": m.group(2), "version": m.group(3)})
    return results


def _parse_settings_modules(content: str) -> List[str]:
    """Extract include(":module") declarations from settings.gradle[.kts]."""
    results = []
    for m in re.finditer(r'\binclude\s*\(\s*["\']([^"\']+)["\']\s*\)', content):
        results.append(m.group(1))
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
    deps = []
    for m in re.finditer(r"<dependency>([\s\S]*?)</dependency>", content):
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
        deps.append({"groupId": group_id, "artifactId": artifact_id, "version": version, "configuration": configuration})
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
    is handled). Deduped by URL, declaration order preserved."""
    entries: List[Dict[str, str]] = []

    for fn, name, url in _GRADLE_SHORTHANDS:
        if re.search(r"\b" + fn + r"\s*\(\s*\)", block_body):
            entries.append({"name": name, "url": url})
    if re.search(r"\bmavenLocal\s*\(\s*\)", block_body):
        entries.append({"name": "Maven Local", "url": _maven_local_url()})

    # Explicit maven("url") and maven(url = "url") (optionally wrapped in uri()).
    for m in re.finditer(
        r"\bmaven\s*\(\s*(?:url\s*=\s*)?(?:uri\s*\(\s*)?[\"']([^\"']+)[\"']",
        block_body,
    ):
        entries.append({"name": m.group(1), "url": m.group(1)})

    # maven { ... } blocks — extract each balanced body, then find its URL.
    pos = 0
    while True:
        found = _find_block(block_body, "maven", pos)
        if not found:
            break
        body, _start, after = found
        um = re.search(r"\burl\b\s*(?:=\s*)?(?:uri\s*\(\s*)?[\"']([^\"']+)[\"']", body)
        if um:
            entries.append({"name": um.group(1), "url": um.group(1)})
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


def _scan_maven_recursive(module_path: str, label: Optional[str], acc: List[Dict], depth: int) -> None:
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
    if depth >= MAX_MODULE_DEPTH:
        return
    for sub in _parse_maven_modules(content):
        child_path = os.path.join(module_path, sub)
        child_label = sub if label is None else f"{label}/{sub}"
        _scan_maven_recursive(child_path, child_label, acc, depth + 1)


def _module_path_to_dir(project_root: str, module_path: str) -> str:
    parts = module_path.lstrip(":").split(":")
    parts = [p for p in parts if p]
    return os.path.join(project_root, *parts)


def scan_project(project_root: str) -> Dict:
    """Returns {buildSystem, dependencies: [...ScannedDependency]}."""
    build_system = _detect_build_system(project_root)
    dependencies: List[Dict] = []

    if build_system == "gradle":
        # Step 1: Read settings file
        settings_result = None
        for f in GRADLE_SETTINGS_FILES:
            p = os.path.join(project_root, f)
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    settings_result = {"content": fh.read(), "file": f}
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
                elif dep["groupId"] and dep["artifactId"]:
                    dependencies.append({
                        "groupId": dep["groupId"],
                        "artifactId": dep["artifactId"],
                        "version": dep["version"],
                        "source": {"kind": "module-direct", "file": file_name, "module": module},
                        "usages": [{"module": module, "configuration": dep["configuration"]}],
                    })

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
                dependencies.append({
                    "groupId": dep["groupId"],
                    "artifactId": dep["artifactId"],
                    "version": dep["version"],
                    "source": {"kind": kind, "file": rel_file, "module": None},
                    "usages": [{"module": None, "configuration": dep["configuration"]}],
                })

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
        _scan_maven_recursive(project_root, None, dependencies, 0)

    return {"buildSystem": build_system, "dependencies": dependencies}


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
        if not usages:
            deps.append({
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "version": dep["version"],
                "configuration": "(unused)",
                "module": None,
                "source": source_file,
                "sourceKind": source_kind,
            })
        else:
            for usage in usages:
                deps.append({
                    "groupId": dep["groupId"],
                    "artifactId": dep["artifactId"],
                    "version": dep["version"],
                    "configuration": usage.get("configuration", ""),
                    "module": usage.get("module"),
                    "source": source_file,
                    "sourceKind": source_kind,
                })
    return {"buildSystem": scan["buildSystem"], "dependencies": deps}


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
    return {
        "groupId": group_id,
        "artifactId": artifact_id,
        "latestVersion": selected,
        "stability": classify_version(selected),
        "allVersionsCount": len(metadata["versions"]),
        "resolvedFrom": metadata.get("resolvedFrom"),
    }


def handle_check_version_exists(args: Dict) -> Any:
    group_id = args["groupId"]
    artifact_id = args["artifactId"]
    version = args["version"]
    ctx = build_resolution_context(args)
    entry = check_version_in_repos(group_id, artifact_id, version, ctx)
    if entry:
        return {
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


def handle_scan_project_dependencies(args: Dict) -> Any:
    project_path = args.get("projectPath") or os.getcwd()
    scan = scan_project(project_path)
    return flatten_scan_result(scan)


def handle_get_dependency_vulnerabilities(args: Dict) -> Any:
    original_deps = args["dependencies"]
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
    limit = args.get("limit", 10)
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

    deps_with_version = [d for d in filtered if d.get("version")]
    deps_without_version = [d for d in filtered if not d.get("version")]

    audit_deps: List[Dict] = []

    # Memoize metadata fetches per GA
    metadata_cache: Dict[str, Any] = {}

    for dep in deps_with_version:
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
            latest = find_latest_version_for_current(metadata["versions"], dep["version"])
            upgrade_type = get_upgrade_type(dep["version"], latest) if latest else "none"
            audit_deps.append({
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "currentVersion": dep["version"],
                "latestVersion": latest,
                "upgradeType": upgrade_type,
                "source": dep["source"],
                "usages": dep.get("usages", []),
                "module": (dep.get("usages") or [{}])[0].get("module"),
                "configuration": (dep.get("usages") or [{}])[0].get("configuration"),
                "resolvedFrom": resolved_from,
            })
        except Exception as e:
            # str(e) is safe here: fetch_metadata's own messages are redacted
            # at the source (see fetch_metadata), and find_latest_version_for_
            # current/get_upgrade_type are pure version-string functions that
            # never embed a repo URL.
            error_entry = {
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "currentVersion": dep["version"],
                "source": dep["source"],
                "usages": dep.get("usages", []),
                "module": (dep.get("usages") or [{}])[0].get("module"),
                "configuration": (dep.get("usages") or [{}])[0].get("configuration"),
                "error": str(e),
            }
            if resolved_from is not None:
                error_entry["resolvedFrom"] = resolved_from
            audit_deps.append(error_entry)

    for dep in deps_without_version:
        audit_deps.append({
            "groupId": dep["groupId"],
            "artifactId": dep["artifactId"],
            "source": dep["source"],
            "usages": dep.get("usages", []),
            "module": (dep.get("usages") or [{}])[0].get("module"),
            "configuration": (dep.get("usages") or [{}])[0].get("configuration"),
        })

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
    # Group-mismatch and recent-first-publish share ONE gate: low_version_count
    # must have already fired AND the per-batch cap must not yet be reached.
    # GATED (not unconditional-per-`exists`-coordinate) because
    # search.maven.org has a documented rate-limiting/403-lockout history under
    # bulk load and _request_with_retry does not retry 403 -- an unconditional
    # query on the dominant `exists` case in a real batch risked degrading the
    # shared endpoint for the EXISTING did-you-mean/search_artifacts paths too.
    if "low_version_count" in reasons and gated_calls[0] < MAX_GATED_SOLR_CALLS_PER_BATCH:
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
            # A coincidentally-shared name with COMPARABLE popularity on both
            # sides must not flag -- discard the candidate entirely (popularMatch
            # is only ever emitted alongside a fired group_mismatch reason).
            popular_match = None

        # Recent-first-publish: a gated, best-effort ENRICHMENT on top of an
        # already-fired signal, never a signal on its own -- it never turns
        # signal:false into signal:true by itself. versions[0] is the
        # semver-MINIMUM of a deduplicated union across repos (`versions` is
        # sorted by compare_versions), NOT necessarily the chronologically-
        # first-published version -- the two coincide only when version
        # numbers happen to increase monotonically with release time. A
        # reasonable, but imperfect, first-publish proxy under this
        # <=LOW_VERSION_COUNT_THRESHOLD-version gate.
        if versions:
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
            status, body = http_get(url)
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
        # emitted top-N never silently suppresses it.
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
        "description": "Scan a local project directory to extract declared dependencies from build files (Gradle, Maven).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectPath": {"type": "string", "description": "Path to the project root. Defaults to current working directory."},
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
                "limit": {"type": "integer", "description": "Maximum number of results (default 10)"},
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
    "get_dependency_vulnerabilities": handle_get_dependency_vulnerabilities,
    "get_dependency_health": handle_get_dependency_health,
    "search_artifacts": handle_search_artifacts,
    "audit_project_dependencies": handle_audit_project_dependencies,
    "verify_coordinates": handle_verify_coordinates,
}


# ---------------------------------------------------------------------------
# MCP JSON-RPC 2.0 dispatcher
# ---------------------------------------------------------------------------

def _write_response(response: Dict) -> None:
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _handle_initialize(msg_id: Any, params: Dict) -> None:
    _write_response({
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    })


def _handle_tools_list(msg_id: Any, params: Dict) -> None:
    _write_response({
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {"tools": TOOLS},
    })


def _handle_tools_call(msg_id: Any, params: Dict) -> None:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        _write_response({
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
        })
        return
    try:
        result = handler(arguments)
        _write_response({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result)}],
            },
        })
    except Exception as e:
        _write_response({
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32603, "message": str(e)},
        })


def _handle_ping(msg_id: Any, params: Dict) -> None:
    _write_response({"jsonrpc": "2.0", "id": msg_id, "result": {}})


def dispatch(msg: Dict) -> None:
    method = msg.get("method", "")
    msg_id = msg.get("id")  # None for notifications
    params = msg.get("params") or {}

    # Notifications — no response
    if msg_id is None:
        return

    if method == "initialize":
        _handle_initialize(msg_id, params)
    elif method == "tools/list":
        _handle_tools_list(msg_id, params)
    elif method == "tools/call":
        _handle_tools_call(msg_id, params)
    elif method == "ping":
        _handle_ping(msg_id, params)
    else:
        _write_response({
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        })


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
            dispatch(msg)
        except Exception as e:
            msg_id = msg.get("id")
            if msg_id is not None:
                _write_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32603, "message": f"Internal error: {e}"},
                })


if __name__ == "__main__":
    main()

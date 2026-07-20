#!/usr/bin/env python3
"""
Maven MCP server — MCP stdio (JSON-RPC 2.0) over stdin/stdout.
No external dependencies; Python 3.9+ standard library only.
"""

import base64
import concurrent.futures
import datetime
import email.utils
import functools
import hashlib
import http.client
import ipaddress
import json
import logging
import os
import random
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
import zlib
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_NAME = "maven-mcp"
SERVER_VERSION = "0.25.0"
USER_AGENT = "maven-mcp/0.25.0"
HTTP_TIMEOUT = 15
# Short timeout for enrichment APIs (OSV / GitHub / deps.dev / android.com).
# Closed contours must fail fast rather than hang on the full HTTP_TIMEOUT (#296).
HTTP_TIMEOUT_EXTERNAL = 3

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

# Default public enrichment endpoints. Overridable via MAVEN_MCP_*_BASE (#296).
GITHUB_API_DEFAULT = "https://api.github.com"
OSV_API_DEFAULT = "https://api.osv.dev/v1/querybatch"
OSV_VULN_API_DEFAULT = "https://api.osv.dev/v1/vulns"
DEPSDEV_API_DEFAULT = "https://api.deps.dev/v3"
# Back-compat aliases — tests and docs historically referenced these names.
# Prefer the *_url() / *_base() resolvers at call sites so env overrides apply.
GITHUB_API = GITHUB_API_DEFAULT
OSV_API = OSV_API_DEFAULT
OSV_VULN_API = OSV_VULN_API_DEFAULT
# OSV.dev documents a maximum of 1000 queries per /v1/querybatch request.
# query_osv_batch chunks above this so a large monorepo audit cannot fail as a unit.
OSV_QUERYBATCH_MAX = 1000
# /v1/querybatch returns only {id, modified} per vuln — severity/summary/fixed
# require a follow-up GET /v1/vulns/{id} (#338). Cap bounds worst-case fan-out
# per query_osv_batch call (unique IDs, first-seen order); excess stay bare.
MAX_OSV_VULN_HYDRATIONS = 100
SEARCH_API = "https://search.maven.org/solrsearch/select"
# search_artifacts limit: coerced to int and clamped in the handler before the
# Solr URL is built (MCP schema bounds are advisory client metadata only).
SEARCH_LIMIT_DEFAULT = 10
SEARCH_LIMIT_MAX = 100
# get_dependency_vulnerabilities dependency-list cap — same bound and rationale
# as verify_coordinates (enforced in-handler before any network I/O).
MAX_VULN_DEPENDENCIES = 100
# get_dependency_license batch cap — same bound/rationale as vuln/verify.
MAX_LICENSE_DEPENDENCIES = 100

# Persistent file cache TTLs and capacity (see FileCache below).
TTL_POM = 7 * 86400     # 7 days — release POMs are immutable once published
TTL_METADATA = 3600     # 1 hour — version lists change, but not constantly
TTL_SEARCH = 3600       # 1 hour — Maven Central Solr search index
# Negative-cache TTL for a definitive HTTP 404 (#404): a known-absent
# coordinate is not re-fetched within this window. Kept far shorter than the
# positive TTLs above — an absent artifact can become present the moment it
# is published, unlike a resolved metadata/POM document, which is immutable.
TTL_NEGATIVE_404 = 300  # 5 minutes

CACHE_MAX_ENTRIES = 2000

# Belt-and-suspenders denylist for http_get_cached.  Private Maven repo hosts
# are NOT listed — this is a blocklist (not an allowlist) so project-declared
# repos at any host are still cached via the call-site-discipline path.
_CACHE_DENYLIST = frozenset({"api.github.com", "api.osv.dev"})

GRADLE_BUILD_FILES = ["build.gradle.kts", "build.gradle"]
GRADLE_SETTINGS_FILES = ["settings.gradle.kts", "settings.gradle"]
GRADLE_RESOLVE_TIMEOUT = 120
_GRADLE_RESOLVE_CONFIGURATIONS = (
    "releaseRuntimeClasspath",
    "runtimeClasspath",
    "releaseCompileClasspath",
    "compileClasspath",
)
MAX_MODULE_DEPTH = 5
# Cap recursive BOM import / parent-property fetches (#286).
MAX_BOM_DEPTH = 5

# deps.dev GetDependencies (#287). Caching is allowed by their ToS; TTL matches
# metadata/search (version graphs change, but not constantly).
DEPSDEV_API = DEPSDEV_API_DEFAULT
TTL_DEPSDEV = 3600  # 1 hour
# Fan-out / size caps — Wave 0 hardening: never unbounded network or memory.
MAX_TRANSITIVE_GRAPH_NODES = 2000
MAX_CONFLICT_SCAN_ROOTS = 50
MAX_DEPSDEV_ERRORS_REPORTED = 20
# License compliance across transitive trees (#289): GetDependencies for the
# graph + GetVersion per unique node for SPDX licenses. Caps bound fan-out.
MAX_LICENSE_COMPLIANCE_ROOTS = 20
MAX_LICENSE_COMPLIANCE_NODES = 500

# Bounded parallel fan-out (#400): the batch tools below resolve N coordinates
# (and, for a few, M repos/roots per coordinate) over the network. Each such
# loop is executed via `_map_parallel`, which creates and tears down its OWN
# ThreadPoolExecutor per call (never a module-global executor in this
# long-lived stdio process). The bound is deliberately modest — some target
# hosts (search.maven.org in particular) have a documented rate-limit/403-
# lockout history under bulk load (see MAX_GATED_SOLR_CALLS_PER_BATCH below),
# so higher concurrency is not free. Calibratable starting point, not proven
# against a labeled benchmark.
MAX_PARALLEL_FETCHES = 8

# R2c (perf review of #400): handle_get_dependency_health's per-dependency
# fan-out makes SEVERAL api.github.com calls each (gh_repo_exists/fetch_repo/
# fetch_releases/issue-stats/discover, plus the rate-limited Search API for
# issue stats, plus a deps.dev Scorecard call) — GitHub's SECONDARY rate
# limiter specifically penalizes CONCURRENT requests (independent of the
# primary per-hour quota, which is 60/h unauthenticated, 5000/h with
# GITHUB_TOKEN — see the Environment section), so running this fan-out at the
# same width as CDN-metadata/deps.dev/OSV lookups (MAX_PARALLEL_FETCHES) risks
# tripping it. A smaller, dedicated bound keeps this ONE fan-out gentler on
# GitHub without slowing down the other seven, which have no such penalty.
MAX_GITHUB_PARALLEL_FETCHES = 3

# Overall wall-clock budget (#402), in seconds, for a single tool invocation
# whose fan-out is otherwise unbounded by any MAX_* cap (audit_project_
# dependencies scans a whole project; check_license_compliance's per-node
# GetVersion fetch can run up to MAX_LICENSE_COMPLIANCE_NODES times). When the
# deadline is reached mid-batch, the tool returns whatever it already gathered
# with `partial: true` instead of blocking indefinitely. Calibratable starting
# point — deliberately smaller than MAX_LICENSE_COMPLIANCE_NODES/MAX_PARALLEL_
# FETCHES sequential-worst-case, so a degenerate batch fails fast with partial
# data rather than running to real completion.
TOOL_DEADLINE = 30.0

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
    # Accept-Encoding: gzip (#403) — Maven metadata/POM/search bodies are
    # 50-200KB text/XML/JSON and compress ~70-80%; _read_response_body
    # transparently inflates a gzip-encoded response. A caller-supplied
    # `extra` can still override this, same as any other default header.
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
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
    """Raise ``URLError`` unless ``url`` uses an allowed http(s) scheme and is
    not a link-local/cloud-metadata literal IP address.

    Checked before Request construction so the default opener never honors
    ``file://`` / ``ftp://`` / other non-HTTP schemes (#348). The link-local
    check (GHSA-m84v-qqqm-6fr4 follow-up) closes the INITIAL-request half of
    that SSRF class — a build file can declare ``url = "http://169.254.169.254/…"``
    directly, no redirect needed — reusing ``_is_link_local_redirect_target``
    (defined later in this module; Python resolves it at call time, not at
    this function's definition time) so both the initial request and every
    redirect hop (``_SecureRedirectHandler.redirect_request``, which calls
    this same function) share one check. RFC1918/loopback stay allowed —
    private-repo mode legitimately targets internal hosts (#290/#298).

    Known residuals (not closed here, deliberately not over-engineered):
    DNS-rebind — a hostname that RESOLVES to a link-local/metadata IP is not
    caught, since only literal IP hosts are inspected (resolving every host
    would add a DNS round-trip to every request for a narrow threat); and
    obfuscated IP encodings (integer/octal/hex forms like ``0xA9FEA9FE`` or
    ``2852039166``) that ``ipaddress`` rejects as invalid but a libc resolver
    would still accept — these are not literal dotted-quad/colon-hex strings
    so ``ipaddress.ip_address()`` raises ``ValueError`` and the check no-ops.
    """
    scheme = _url_scheme(url)
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise urllib.error.URLError(
            f"URL scheme not allowed: {scheme or '(none)'} (only http/https)"
        )
    host = _repo_host(url)
    if _is_link_local_redirect_target(host):
        raise urllib.error.URLError(
            f"Link-local/metadata address blocked: {host}"
        )


def _is_file_url(url: str) -> bool:
    """True when ``url`` is a ``file:`` URL (scheme compared case-insensitively)."""
    return _url_scheme(url) == "file"


class ResponseTooLargeError(urllib.error.URLError):
    """Raised when an HTTP response body exceeds ``HTTP_MAX_RESPONSE_BYTES``.

    Not retried: re-fetching an oversized body cannot help and would only
    amplify memory pressure (#350).
    """


def _response_header(resp: Any, name: str) -> str:
    """Case-insensitively read a single response header, or ``""`` if absent."""
    headers = getattr(resp, "headers", None)
    if headers is None:
        return ""
    get = getattr(headers, "get", None)
    raw = get(name) if callable(get) else None
    return (raw or "").strip()


def _inflate_gzip_capped(data: bytes, cap: int) -> bytes:
    """Incrementally inflate a gzip payload, aborting once the DECOMPRESSED
    size would exceed ``cap`` (#403 zip-bomb guard).

    A small compressed body can expand enormously (empirically ~750x for a
    highly repetitive payload) — ``Content-Length`` only ever describes the
    size on the wire, so it cannot be trusted to bound the inflated size.
    ``zlib.decompressobj``'s ``max_length`` argument stops production of
    output at the cap without ever materializing the full inflated buffer, so
    a hostile stream cannot force a large allocation even transiently; once
    the cap is exceeded this stops feeding the decompressor further input.
    """
    decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)  # 16+wbits = expect gzip header/trailer
    try:
        out = decompressor.decompress(data, cap + 1)
        while decompressor.unconsumed_tail and len(out) <= cap:
            out += decompressor.decompress(decompressor.unconsumed_tail, cap + 1 - len(out))
        if len(out) <= cap:
            out += decompressor.flush()
    except zlib.error as e:
        # Malformed/corrupt gzip body — treat like any other transport-level
        # problem so it flows through the existing retry contract instead of
        # escaping as a novel exception type callers don't expect.
        raise urllib.error.URLError(f"invalid gzip response body: {e}")
    if len(out) > cap:
        raise ResponseTooLargeError(
            f"HTTP response too large: decompressed gzip body exceeds {cap} bytes"
        )
    return out


def _read_response_body(resp: Any) -> bytes:
    """Read ``resp`` body with an explicit size cap (#350).

    Short-circuits on an oversized ``Content-Length`` before allocating, then
    reads at most ``HTTP_MAX_RESPONSE_BYTES + 1`` bytes and raises
    ``ResponseTooLargeError`` if the body exceeds the cap. Chunked / missing
    Content-Length still cannot grow without bound because of the read cap.

    A ``Content-Encoding: gzip`` response (sent when the server honors the
    ``Accept-Encoding: gzip`` request header from ``_make_headers``, #403) is
    transparently inflated after the raw-bytes cap above has already applied
    to the WIRE size. The cap is enforced a SECOND time against the
    DECOMPRESSED size (``_inflate_gzip_capped``) — a small compressed body can
    still expand far past ``HTTP_MAX_RESPONSE_BYTES`` (zip bomb), and
    Content-Length only ever describes the wire size, never the inflated one.
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
    if _response_header(resp, "Content-Encoding").lower() == "gzip":
        body = _inflate_gzip_capped(body, HTTP_MAX_RESPONSE_BYTES)
    return body


def _request_with_retry(
    req: urllib.request.Request,
    timeout: Optional[float] = None,
) -> Tuple[int, bytes]:
    """Issue ``req`` with bounded retry/backoff on transient failures.

    Tri-state contract (relied on by the resolution layer and verify_coordinates):
    returns ``(status, body)`` for ANY HTTP response — including a persistent
    429/5xx after retries are exhausted — and only re-raises the last transport
    error (URLError / socket.timeout) when EVERY attempt failed at the transport
    level without ever obtaining an HTTP response. A 4xx (incl. 404) is never
    turned into a raise. Retry is fully internal and transparent to callers.
    Oversized bodies raise ``ResponseTooLargeError`` immediately (not retried).
    ``timeout`` defaults to ``HTTP_TIMEOUT``; enrichment APIs pass
    ``HTTP_TIMEOUT_EXTERNAL`` (#296).
    """
    if timeout is None:
        timeout = HTTP_TIMEOUT
    deadline = time.monotonic() + HTTP_TOTAL_RETRY_BUDGET
    last_result: Optional[Tuple[int, bytes]] = None
    last_exc: Optional[BaseException] = None
    for attempt in range(HTTP_MAX_ATTEMPTS):
        retry_after: Optional[float] = None
        try:
            with _urlopen(req, timeout) as resp:
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


def http_get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> Tuple[int, bytes]:
    """Returns (status_code, body_bytes). Retries transient failures internally
    (see _request_with_retry); raises urllib.error.URLError / socket.timeout only
    when every attempt hit a transport error. Non-http(s) schemes are rejected
    before any network/filesystem open (#348)."""
    _assert_http_url(url)
    req = urllib.request.Request(url, headers=headers or _make_headers())
    return _request_with_retry(req, timeout=timeout)


def http_post_json(
    url: str,
    payload: Any,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> Tuple[int, bytes]:
    _assert_http_url(url)
    data = json.dumps(payload).encode()
    h = _make_headers({"Content-Type": "application/json"})
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    return _request_with_retry(req, timeout=timeout)


def http_post_bytes(
    url: str,
    data: bytes,
    content_type: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> Tuple[int, bytes]:
    """POST raw bytes (e.g. Artifactory AQL ``text/plain`` body)."""
    _assert_http_url(url)
    h = _make_headers({"Content-Type": content_type})
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    return _request_with_retry(req, timeout=timeout)


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
    - Only status == 200 or 404 is ever written (#404 negative cache);
      429/5xx and other error bodies are never cached.
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

    def get(
        self, url: str, ttl: float, negative_ttl: Optional[float] = None
    ) -> Optional[Tuple[int, bytes]]:
        """Return (status, body) if a fresh entry exists, else None.

        TTL check is strictly >, so exactly-at-TTL is a HIT. A cached negative
        (404) entry (#404) is freshness-checked against ``negative_ttl``
        instead of ``ttl`` when given, since a definitive-absence result must
        expire much sooner than a positive metadata/POM/search hit — an
        absent artifact can become present the moment it is published.
        Callers that never write 404 entries can omit ``negative_ttl`` and
        this behaves exactly as before.
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
            status = entry["status"]
            effective_ttl = ttl if (status == 200 or negative_ttl is None) else negative_ttl
            if _now() - entry["ts"] > effective_ttl:
                return None
            return (status, base64.b64decode(entry["body_b64"]))
        except Exception:
            return None

    def set(self, url: str, status: int, body: bytes) -> None:
        """Write url->body to cache. No-op for a non-cacheable status, disabled,
        or dir failure.

        Cacheable statuses are 200 (positive) and 404 (negative — #404, a
        clean/definitive absence). Every other status — 429/5xx (transient;
        `_request_with_retry` already exhausted its own retry budget before
        returning one of these) and any other 4xx — must always re-hit the
        network on the next call and is never written.
        """
        if status not in (200, 404):
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
            "status": status,
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
    timeout: Optional[float] = None,
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
    any retry budget).

    A definitive HTTP 404 is ALSO cached — a negative cache (#404): a known-
    absent coordinate is not re-fetched on every call within ``TTL_NEGATIVE_404``,
    which is intentionally far shorter than ``ttl_seconds`` since a 404 can turn
    into a 200 the moment the artifact is published. 429/5xx and any raised
    transport error are never cached — matching ``FileCache.set``'s own
    allow-list — and propagate to the caller exactly as ``http_get`` would
    return/raise, same as before this change.
    """
    if _headers_have_authorization(headers):
        return http_get(url, headers, timeout=timeout)
    host = urllib.parse.urlparse(url).hostname or ""
    if host in _CACHE_DENYLIST:
        return http_get(url, headers, timeout=timeout)
    result = _file_cache.get(url, ttl_seconds, negative_ttl=TTL_NEGATIVE_404)
    if result is not None:
        return result
    status, body = http_get(url, headers, timeout=timeout)
    if status in (200, 404):
        _file_cache.set(url, status, body)
    return (status, body)


# ---------------------------------------------------------------------------
# Bounded parallel fan-out (#400)
# ---------------------------------------------------------------------------

def _map_parallel(
    items: List[Any],
    fn: Callable[[Any], Any],
    max_workers: int = MAX_PARALLEL_FETCHES,
    deadline: Optional[float] = None,
) -> Tuple[List[Any], bool]:
    """Run ``fn(item)`` for every item in ``items`` on a bounded
    ThreadPoolExecutor created and torn down within THIS call — never a
    module-global executor in this long-lived stdio process.

    Returns ``(results, partial)``:
      - ``results`` is INDEX-MAPPED to ``items`` (same order as the input),
        never completion order. Every "first/Nth in order" contract a caller
        already relies on (``resolvedFrom`` provenance, capability-signal
        first-wins, error-list ordering, …) is therefore unaffected by which
        worker thread happens to finish first.
      - ``partial`` is True only when ``deadline`` was given and was reached
        before every item finished; unfinished slots are left as ``None`` —
        the caller decides how to render them (see #402 call sites).

    PER-ITEM ISOLATION is the caller's responsibility: ``fn`` must catch its
    own exceptions and return an error-shaped result, exactly mirroring the
    try/except-and-append-in-order pattern every one of these loops already
    had before this helper existed. An exception ``fn`` does NOT catch
    propagates out of ``future.result()`` and thus out of this call — i.e.
    the whole batch fails, matching what the equivalent sequential loop would
    have done if it also had no try/except around that step.

    ``len(items) <= 1`` skips the executor entirely: nothing to parallelize,
    and it avoids thread-pool startup overhead for the common single-item
    call (batch tools are very frequently called with exactly one dependency).
    """
    n = len(items)
    if n == 0:
        return [], False
    if n == 1:
        return [fn(items[0])], False

    results: List[Any] = [None] * n
    workers = max(1, min(max_workers, n))
    partial = False
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    future_map: Dict[concurrent.futures.Future, int] = {}
    try:
        future_map = {executor.submit(fn, item): i for i, item in enumerate(items)}
        pending = set(future_map)
        while pending:
            timeout: Optional[float] = None
            if deadline is not None:
                remaining = deadline - _now()
                if remaining <= 0:
                    partial = True
                    break
                timeout = remaining
            done, pending = concurrent.futures.wait(
                pending, timeout=timeout, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                results[future_map[future]] = future.result()
            if deadline is not None and not done:
                # wait()'s own timeout elapsed with nothing finished yet.
                partial = True
                break
    finally:
        # Bounded shutdown (#402): never block THIS call past the deadline
        # waiting on already-running futures — Python cannot kill a running
        # thread, so cancel() only drops NOT-YET-STARTED futures from the
        # queue (no new work begins after the deadline) and `wait=False` lets
        # this call return promptly; any in-flight worker still finishes
        # naturally in the background (bounded by its own HTTP timeout) and
        # the pool's worker threads exit on their own once idle post-shutdown
        # — never leaked past process lifetime, just not joined by this call.
        for future in future_map:
            future.cancel()
        executor.shutdown(wait=not partial)
    return results, partial


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


def _name_pin_host(name: str) -> Optional[str]:
    """``MAVEN_REPO_<NAME>_HOST`` — pins a name/id-keyed credential to one
    destination host (GHSA-m2hv-xh72-cccw). ``name`` (Maven ``<id>`` / Gradle
    ``name = "…"``) comes from the untrusted, scanned build file, so unlike
    the hostname (always derived from the same ``url`` a request is actually
    sent to) it cannot be trusted on its own — a malicious build file could
    otherwise set ``name`` to any string a *different*, trusted host's secret
    happens to be keyed under, redirecting that secret to an attacker URL.
    Returns the pinned hostname (lowercased) or ``None`` when unset.
    """
    key = _sanitize_cred_key(name)
    if not key:
        return None
    raw = os.environ.get(f"{_CRED_ENV_PREFIX}{key}_HOST")
    return (raw or "").strip().lower() or None


def resolve_repo_credentials(entry: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Resolve Basic/Bearer credentials for a discovered repo entry (#291).

    Returns ``{"type": "basic", "username", "password"}`` or
    ``{"type": "bearer", "token"}``, or ``None`` when nothing matches.
    Never reads credentials from build files. Never logs secret values.

    Credential-misbinding guard (GHSA-m2hv-xh72-cccw): a secret must only
    ever be sent to the host it was configured for. Host-keyed resolution
    (``ident == host``) is safe unconditionally — the identifier is derived
    from the SAME ``url`` the request targets, so it cannot diverge from the
    real destination. Name/id-keyed resolution uses a string the untrusted
    build file controls independently of ``url``, so it is only honored when
    the user has pinned that name to this exact destination host via
    ``MAVEN_REPO_<NAME>_HOST`` (see ``_name_pin_host``); otherwise it is
    skipped (logged once, secret-free) and resolution falls through to the
    next candidate (typically the host).

    Mirror exception (#294 regression fix, R2b): when ``entry["mirrored"]``
    is set, ``entry["name"]`` is the settings.xml mirror's OWN ``<id>`` and
    ``entry["url"]`` is the mirror's OWN url — both written by
    ``_apply_mirror_to_entry`` from ``ctx.mirrors`` (loaded from the user's
    own ``~/.m2/settings.xml`` / ``~/.gradle/init.gradle*``, never from the
    scanned project's build files). That name is therefore just as trusted
    as the host, not an untrusted build-file string, so it does not need a
    ``_HOST`` pin. This key is set in exactly one place in this module —
    ``_apply_mirror_to_entry`` — always alongside that url/name overwrite.
    No parser that reads the scanned project's build files (Gradle/Maven repo
    parsers, ``discover_repositories``) ever sets or reads this key, so an
    attacker-controlled build file cannot forge it.
    """
    host = _repo_host(entry.get("url") or "")
    resolvers = (
        _resolve_creds_from_env,
        _resolve_creds_from_settings,
        _resolve_creds_from_gradle_properties,
    )
    for ident in _repo_id_candidates(entry):
        creds = None
        for resolver in resolvers:
            creds = resolver(ident)
            if creds:
                break
        if not creds:
            continue
        if ident == host or entry.get("mirrored"):
            return creds
        pinned_host = _name_pin_host(ident)
        if pinned_host and pinned_host == host:
            return creds
        _logger.warning(
            "Skipping name/id-keyed credential for %r: set MAVEN_REPO_%s_HOST=%s "
            "to trust it for this destination (GHSA-m2hv-xh72-cccw)",
            ident, _sanitize_cred_key(ident), host or "<unresolved-host>",
        )
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


# ---------------------------------------------------------------------------
# External enrichment services — air-gapped degradation (#296)
# ---------------------------------------------------------------------------
# OSV / GitHub / deps.dev / developer.android.com are unreachable in closed
# contours. Offline mode short-circuits them (unless an endpoint override points
# at an internal mirror). Transport failures mark capabilityUnavailable=
# "unreachable" with a short timeout so tools do not hang.

_ANDROID_DOCS_DEFAULT = "https://developer.android.com"


def _env_url_base(name: str, default: str) -> str:
    """Read an absolute URL base from env, stripping a trailing slash."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default.rstrip("/")
    return raw.rstrip("/")


def _url_host(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _github_api_base() -> str:
    """GitHub API root (``MAVEN_MCP_GITHUB_BASE``; GHE uses ``…/api/v3``)."""
    return _env_url_base("MAVEN_MCP_GITHUB_BASE", GITHUB_API_DEFAULT)


def _osv_api_root() -> str:
    """OSV API root (``MAVEN_MCP_OSV_BASE``). Accepts either ``https://host`` or
    ``https://host/v1``; querybatch/vulns paths are derived from this."""
    raw = _env_url_base("MAVEN_MCP_OSV_BASE", "https://api.osv.dev")
    if raw.endswith("/querybatch"):
        raw = raw[: -len("/querybatch")].rstrip("/")
    return raw


def _osv_querybatch_url() -> str:
    root = _osv_api_root()
    if root.endswith("/v1"):
        return f"{root}/querybatch"
    return f"{root}/v1/querybatch"


def _osv_vuln_url(vuln_id: str) -> str:
    root = _osv_api_root()
    quoted = urllib.parse.quote(vuln_id, safe="-._")
    if root.endswith("/v1"):
        return f"{root}/vulns/{quoted}"
    return f"{root}/v1/vulns/{quoted}"


def _depsdev_api_base() -> str:
    """deps.dev v3 API root (``MAVEN_MCP_DEPSDEV_BASE``)."""
    return _env_url_base("MAVEN_MCP_DEPSDEV_BASE", DEPSDEV_API_DEFAULT)


def _android_docs_base() -> str:
    """developer.android.com root (``MAVEN_MCP_ANDROID_DOCS_BASE``)."""
    return _env_url_base("MAVEN_MCP_ANDROID_DOCS_BASE", _ANDROID_DOCS_DEFAULT)


def _external_override_active(service: str) -> bool:
    """True when an env override points away from the public default host."""
    if service == "osv":
        return _url_host(_osv_api_root()) != "api.osv.dev"
    if service == "github":
        return _url_host(_github_api_base()) != "api.github.com"
    if service == "depsdev":
        return _url_host(_depsdev_api_base()) != "api.deps.dev"
    if service == "android_docs":
        return _url_host(_android_docs_base()) != "developer.android.com"
    return False


def _external_capability(service: str) -> Optional[str]:
    """Return ``"offline"`` when this enrichment service must be skipped.

    ``MAVEN_MCP_OFFLINE`` short-circuits public defaults. An endpoint override
    whose host differs from the public default is treated as an internal mirror
    and remains callable (still under ``HTTP_TIMEOUT_EXTERNAL``).
    """
    if not _offline_enabled():
        return None
    if _external_override_active(service):
        return None
    return "offline"


def _with_capability(result: Dict[str, Any], capability: Optional[str]) -> Dict[str, Any]:
    """Attach ``capabilityUnavailable`` when set; leave result otherwise unchanged."""
    if capability:
        result["capabilityUnavailable"] = capability
    return result


# ---------------------------------------------------------------------------
# TLS (internal CA) + HTTP(S) proxy (#298)
# ---------------------------------------------------------------------------
# Closed contours often terminate TLS with a private CA and route egress via
# an HTTP proxy. Defaults stay secure: verification ON, no proxy unless env
# says so. Escape hatch MAVEN_MCP_INSECURE_TLS is explicit and warned.

# Mutable TLS state (dict, not rebinding module globals) so CodeQL does not
# flag the memo/warn flags as unused globals under ``global`` writes.
_TLS_STATE: Dict[str, Any] = {
    "insecure_warned": False,
    "ssl_context_cache": None,  # Optional[Tuple[str, ssl.SSLContext]]
}

# Guards a first-build race on _TLS_STATE["ssl_context_cache"] under the #400
# ThreadPoolExecutor: without it, N concurrent cache-miss callers (e.g. cold
# start + the first parallel batch) would each independently build their own
# ssl.SSLContext (redundant CA-bundle loading, not a correctness bug — dict
# writes are atomic — but wasted work every time). Double-checked below so
# the overwhelmingly common cache-HIT path stays lock-free.
_TLS_LOCK = threading.Lock()


def _insecure_tls_enabled() -> bool:
    """``MAVEN_MCP_INSECURE_TLS`` — disable TLS verification (off by default)."""
    return _env_flag("MAVEN_MCP_INSECURE_TLS")


def _ca_cert_files() -> List[str]:
    """Ordered CA bundle paths to trust in addition to the system store.

    ``MAVEN_MCP_CA_CERT`` is the primary knob; ``SSL_CERT_FILE`` and
    ``NODE_EXTRA_CA_CERTS`` are also honored so existing enterprise / Node
    tooling env can be reused without a second copy of the bundle.
    """
    paths: List[str] = []
    for name in ("MAVEN_MCP_CA_CERT", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS"):
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            continue
        expanded = os.path.expanduser(raw)
        if expanded not in paths:
            paths.append(expanded)
    return paths


def _warn_insecure_tls_once() -> None:
    if _TLS_STATE["insecure_warned"]:
        return
    _TLS_STATE["insecure_warned"] = True
    _logger.warning(
        "MAVEN_MCP_INSECURE_TLS is enabled: TLS certificate verification is "
        "DISABLED for all HTTP(S) requests. Use only as an explicit escape "
        "hatch; prefer MAVEN_MCP_CA_CERT with your internal CA bundle."
    )


def _ssl_config_fingerprint() -> str:
    parts = ["insecure=%s" % ("1" if _insecure_tls_enabled() else "0")]
    for p in _ca_cert_files():
        try:
            st = os.stat(p)
            parts.append("%s:%s:%s" % (p, st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append("%s:missing" % p)
    return "|".join(parts)


def _reset_ssl_context_cache() -> None:
    """Test helper: drop the memoized SSL context."""
    _TLS_STATE["ssl_context_cache"] = None
    _TLS_STATE["insecure_warned"] = False


def _ssl_context() -> "ssl.SSLContext":
    """SSL context for outbound HTTPS: system CAs + optional internal bundle.

    Verification stays ON unless ``MAVEN_MCP_INSECURE_TLS`` is explicitly set.

    Thread-safe (#400): the fast path (cache hit) reads ``_TLS_STATE`` without
    the lock — a dict read is atomic and the worst case on a stale read is
    falling through to the locked slow path. The slow (rebuild) path
    re-checks under ``_TLS_LOCK`` so a build that races another thread's
    build in flight reuses ITS result instead of doing the work twice.
    """
    fp = _ssl_config_fingerprint()
    cached = _TLS_STATE["ssl_context_cache"]
    if cached is not None and cached[0] == fp:
        return cached[1]
    with _TLS_LOCK:
        cached = _TLS_STATE["ssl_context_cache"]
        if cached is not None and cached[0] == fp:
            return cached[1]
        if _insecure_tls_enabled():
            _warn_insecure_tls_once()
            ctx = ssl._create_unverified_context()
        else:
            ctx = ssl.create_default_context()
            for ca_path in _ca_cert_files():
                if not os.path.isfile(ca_path):
                    _logger.warning(
                        "CA certificate path not found (%s); ignoring", ca_path
                    )
                    continue
                try:
                    ctx.load_verify_locations(cafile=ca_path)
                except (ssl.SSLError, OSError) as e:
                    _logger.warning(
                        "Failed to load CA bundle %s: %s", ca_path, type(e).__name__
                    )
        _TLS_STATE["ssl_context_cache"] = (fp, ctx)
        return ctx


def _env_proxy_url(scheme: str) -> Optional[str]:
    """Read proxy URL for ``scheme`` from env (uppercase then lowercase)."""
    upper = "%s_PROXY" % scheme.upper()
    lower = "%s_proxy" % scheme.lower()
    raw = (os.environ.get(upper) or os.environ.get(lower) or "").strip()
    return raw or None


def _explicit_env_proxies() -> Optional[Dict[str, str]]:
    """Proxies from HTTP(S)_PROXY / ALL_PROXY when any is set; else ``None``.

    Returning ``None`` leaves urllib's default discovery alone (no custom
    ``ProxyHandler``). When set, we build an opener that prefers these env
    vars (predictable in closed contours).
    """
    http = _env_proxy_url("http")
    https = _env_proxy_url("https")
    all_proxy = _env_proxy_url("all")
    if not http and not https and not all_proxy:
        return None
    proxies: Dict[str, str] = {}
    if http or all_proxy:
        proxies["http"] = http or all_proxy  # type: ignore[assignment]
    if https or http or all_proxy:
        # Prefer HTTPS_PROXY; fall back to HTTP_PROXY / ALL_PROXY for CONNECT.
        proxies["https"] = https or http or all_proxy  # type: ignore[assignment]
    return proxies


def _no_proxy_list() -> List[str]:
    raw = (os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _hostname_matches_no_proxy(host: str, pattern: str) -> bool:
    """Match ``host`` against a single NO_PROXY entry."""
    host = (host or "").lower().rstrip(".")
    pattern = (pattern or "").lower().strip()
    if not host or not pattern:
        return False
    if pattern == "*":
        return True
    pat = pattern[1:] if pattern.startswith(".") else pattern
    if host == pat:
        return True
    return host.endswith("." + pat)


def _proxy_bypass_host(host: str) -> bool:
    """True when ``host`` is excluded by ``NO_PROXY`` / ``no_proxy``."""
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    for entry in _no_proxy_list():
        if _hostname_matches_no_proxy(host, entry):
            return True
    return False


def _urlopen(req: urllib.request.Request, timeout: float):
    """Open ``req`` with TLS context + optional explicit proxy env (#298).

    Tests patch ``urllib.request.urlopen``; the no-custom-proxy path calls it
    directly so existing mocks keep working. When HTTP(S)_PROXY is set and the
    host is not excluded by NO_PROXY, a dedicated opener applies
    ``ProxyHandler`` + ``HTTPSHandler(context=…)``.
    """
    url = req.full_url
    scheme = _url_scheme(url)
    context = _ssl_context() if scheme == "https" else None
    proxies = _explicit_env_proxies()
    host = _url_host(url) if proxies else ""
    use_proxy = bool(proxies) and bool(host) and not _proxy_bypass_host(host)
    if use_proxy:
        handlers: List[Any] = [urllib.request.ProxyHandler(proxies)]
        if context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=context))
        opener = urllib.request.build_opener(*handlers)
        return opener.open(req, timeout=timeout)
    if context is not None:
        return urllib.request.urlopen(req, timeout=timeout, context=context)
    return urllib.request.urlopen(req, timeout=timeout)


# ---------------------------------------------------------------------------
# Secure redirect handling (GHSA-xj4p-wm6r-4q3j / GHSA-m84v-qqqm-6fr4)
# ---------------------------------------------------------------------------
# urllib's default HTTPRedirectHandler forwards every header except
# Content-Length/Content-Type to a redirect target verbatim (including
# Authorization, even cross-host or on an https->http downgrade), and only
# rejects a redirect scheme outside {http, https, ftp, ''} — it never
# inspects the destination host at all. A private repo (or api.github.com
# with GITHUB_TOKEN) that 302s can therefore leak credentials to another
# host, downgrade to plaintext, or steer a follow-up request at a cloud
# metadata endpoint (169.254.169.254) or link-local address.

# Proxy-Authorization deliberately excluded: urllib.request.Request stores it
# capitalized as "Proxy-authorization" (Request.add_header does key.capitalize()),
# so remove_header("Proxy-Authorization") here would never match anyway — and
# even if it did, proxy auth is scoped to the PROXY connection, not the target
# host, so it is correct for it to persist across a redirect through the same
# proxy (R2d cleanup — this key was a no-op, not a security gap).
_CREDENTIAL_HEADERS = ("Authorization", "Cookie")


def _is_link_local_redirect_target(host: str) -> bool:
    """True when ``host`` is a literal link-local/metadata IP address.

    Covers IPv4 169.254.0.0/16 (including the 169.254.169.254 cloud-metadata
    endpoint) and IPv6 fe80::/10. RFC1918 (10/8, 172.16/12, 192.168/16) and
    loopback are deliberately NOT blocked — private-repo mode legitimately
    targets internal hosts (#290/#298). Best-effort: only a literal IP is
    checked; a redirect ``Location`` that is a hostname is not resolved here
    (the literal-IP metadata case is the concrete threat this closes).

    Despite the name, this is not redirect-only: ``_assert_http_url`` also
    calls it, so the SAME check covers the initial request too (a build file
    declaring ``url = "http://169.254.169.254/…"`` directly, no redirect
    needed — GHSA-m84v-qqqm-6fr4 follow-up). Kept under this name rather than
    renamed, to keep this fix's diff to the call site.
    """
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_link_local
    except ValueError:
        return False  # a hostname, not an IP literal


class _SecureRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validates the redirect target and strips credential headers on
    every hop (installed globally below — see the assignment after this
    class). ``redirect_request`` receives the fully-resolved absolute
    ``newurl`` before a new Request is issued, so raising here blocks the
    hop entirely instead of only warning after the fact.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # FIX (GHSA-m84v-qqqm-6fr4): only http/https may survive a redirect —
        # the base handler still allows ftp:// — and link-local/metadata IP
        # literals are blocked outright. _assert_http_url now covers BOTH the
        # initial request and every redirect hop (R2c follow-up), so the
        # link-local check that used to live here as a second, separate call
        # was removed — this single call raises for either failure mode.
        _assert_http_url(newurl)
        new_host = _repo_host(newurl)

        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is None:
            return None

        # FIX (GHSA-xj4p-wm6r-4q3j): strip credential headers whenever the
        # redirect crosses hosts (unconditionally, defense in depth) or
        # downgrades https -> http (same host or not — cleartext either way).
        old_host = _repo_host(req.full_url)
        old_scheme = _url_scheme(req.full_url)
        new_scheme = _url_scheme(newurl)
        if old_host != new_host or (old_scheme == "https" and new_scheme == "http"):
            for header in _CREDENTIAL_HEADERS:
                new_req.remove_header(header)
        return new_req


# Installed as a module-level swap (not passed to individual build_opener()
# calls) so it also protects REAL, un-mocked urllib.request.urlopen() calls:
# urlopen() builds its own opener internally via build_opener(), which
# resolves HTTPRedirectHandler through urllib.request's module globals at
# CALL time (verified against the installed stdlib) — so swapping the name
# here is picked up by every opener built anywhere in the process, including
# _urlopen()'s own proxy branch above, without changing any call site. Tests
# that patch urllib.request.urlopen directly replace the whole function and
# never construct a handler at all, so this is inert for the mocked suite.
if urllib.request.HTTPRedirectHandler is not _SecureRedirectHandler:
    urllib.request.HTTPRedirectHandler = _SecureRedirectHandler


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
        pass  # init.d missing or unreadable — no init-script mirrors to load
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
    public_entries: List[Dict[str, Any]] = []
    if (not ctx.offline) or ctx.repository_base or ctx.mirrors:
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
    if ctx.public_fallback and public_entries:
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
    base = _depsdev_api_base()
    return (
        f"{base}/systems/MAVEN/packages/"
        f"{urllib.parse.quote(name, safe='')}/versions/"
        f"{urllib.parse.quote(version, safe='')}:dependencies"
    )


def _depsdev_version_url(group_id: str, artifact_id: str, version: str) -> str:
    """Build the GetVersion URL (licenses live here, not on GetDependencies)."""
    name = _depsdev_package_name(group_id, artifact_id)
    base = _depsdev_api_base()
    return (
        f"{base}/systems/MAVEN/packages/"
        f"{urllib.parse.quote(name, safe='')}/versions/"
        f"{urllib.parse.quote(version, safe='')}"
    )


def _depsdev_project_url(owner: str, repo: str) -> str:
    """Build the deps.dev v3 GetProject URL for a GitHub repository (#411).

    ``projectKey`` embeds literal ``/`` separators (``github.com/{owner}/{repo}``)
    and is percent-encoded as a SINGLE path segment — verified live against
    api.deps.dev: mixed-case owner/repo is accepted and normalized server-side,
    but an uppercase host segment is rejected with HTTP 400 "invalid project
    key", which is why the ``github.com`` literal here is always lowercase.
    """
    key = f"github.com/{owner}/{repo}"
    base = _depsdev_api_base()
    return f"{base}/projects/{urllib.parse.quote(key, safe='')}"


def fetch_depsdev_licenses(
    group_id: str,
    artifact_id: str,
    version: str,
) -> Dict[str, Any]:
    """Fetch SPDX license strings for one GAV via deps.dev GetVersion (#289).

    Returns ``{ok, status, licenses, error}``. Never raises for network/HTTP/
    parse failures — callers degrade to an empty license list + error.
    ``licenses`` are the raw deps.dev strings (SPDX expressions or
    ``non-standard``); empty means deps.dev had no license metadata.
    """
    empty: Dict[str, Any] = {
        "ok": False,
        "status": None,
        "licenses": [],
        "error": None,
    }
    cap = _external_capability("depsdev")
    if cap:
        out = dict(empty)
        out["error"] = "deps.dev unavailable (offline/closed mode)"
        out["capabilityUnavailable"] = cap
        return out
    url = _depsdev_version_url(group_id, artifact_id, version)
    try:
        status, body = http_get_cached(
            url, TTL_DEPSDEV, timeout=HTTP_TIMEOUT_EXTERNAL
        )
    except Exception as e:
        out = dict(empty)
        out["error"] = f"{type(e).__name__}: deps.dev unreachable"
        out["capabilityUnavailable"] = "unreachable"
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

    raw = payload.get("licenses") or []
    if not isinstance(raw, list):
        raw = [str(raw)]
    licenses = [str(x).strip() for x in raw if str(x).strip()]
    out.update({"ok": True, "licenses": licenses, "error": None})
    return out


def fetch_depsdev_scorecard(owner: str, repo: str) -> Dict[str, Any]:
    """Fetch the OpenSSF Scorecard for a GitHub repo via deps.dev GetProject (#411).

    Returns ``{ok, status, scorecard, error}``. ``scorecard`` is the trimmed
    ``{overallScore, date, checks, generatedBy}`` shape when deps.dev has one on
    file; ``None`` when the deps.dev call itself succeeded but no scorecard is
    available. deps.dev's project index does not cover every GitHub repository —
    verified live against api.deps.dev: a 404 plain-text ``"project not found"``
    body is the common response for a repo deps.dev has not indexed (e.g.
    small/personal repos), not a transport failure, so it degrades to
    ``scorecard: None`` rather than an error callers should alarm on.

    Never raises for network/HTTP/parse failures — mirrors
    fetch_depsdev_licenses / fetch_depsdev_dependencies: callers degrade to no
    scorecard plus an error/capabilityUnavailable.
    """
    empty: Dict[str, Any] = {"ok": False, "status": None, "scorecard": None, "error": None}
    cap = _external_capability("depsdev")
    if cap:
        out = dict(empty)
        out["error"] = "deps.dev unavailable (offline/closed mode)"
        out["capabilityUnavailable"] = cap
        return out
    url = _depsdev_project_url(owner, repo)
    try:
        status, body = http_get_cached(
            url, TTL_DEPSDEV, timeout=HTTP_TIMEOUT_EXTERNAL
        )
    except Exception as e:
        out = dict(empty)
        out["error"] = f"{type(e).__name__}: deps.dev unreachable"
        out["capabilityUnavailable"] = "unreachable"
        return out

    out = dict(empty)
    out["status"] = status
    if status != 200 or not body:
        # Covers the empirically-confirmed 404 "project not found" case (a repo
        # deps.dev has not indexed) alongside genuine transport/HTTP failures —
        # both simply mean "no scorecard data", never a crash.
        out["error"] = (
            f"deps.dev returned HTTP {status}" if status is not None
            else "deps.dev returned empty response"
        )
        return out

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        out["error"] = f"deps.dev response not JSON: {type(e).__name__}"
        return out

    out["ok"] = True
    raw_sc = payload.get("scorecard")
    if not isinstance(raw_sc, dict):
        return out  # project known to deps.dev, but no scorecard on file

    checks: List[Dict[str, Any]] = []
    for c in (raw_sc.get("checks") or []):
        if isinstance(c, dict) and c.get("name"):
            checks.append({
                "name": c.get("name"),
                "score": c.get("score"),
                "reason": c.get("reason"),
            })
    out["scorecard"] = {
        "overallScore": raw_sc.get("overallScore"),
        "date": raw_sc.get("date"),
        "checks": checks,
        "generatedBy": "OpenSSF",
    }
    return out


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
    cap = _external_capability("depsdev")
    if cap:
        out = dict(empty)
        out["error"] = "deps.dev unavailable (offline/closed mode)"
        out["capabilityUnavailable"] = cap
        return out
    url = _depsdev_dependencies_url(group_id, artifact_id, version)
    try:
        status, body = http_get_cached(
            url, TTL_DEPSDEV, timeout=HTTP_TIMEOUT_EXTERNAL
        )
    except Exception as e:
        # Transport / size-cap / scheme failures — degrade, never raise.
        out = dict(empty)
        out["error"] = f"{type(e).__name__}: deps.dev unreachable"
        out["capabilityUnavailable"] = "unreachable"
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
    if fetched.get("capabilityUnavailable"):
        result["capabilityUnavailable"] = fetched["capabilityUnavailable"]
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


def _detect_conflicts_from_gradle_scan(scan: Dict[str, Any]) -> Dict[str, Any]:
    """Detect version conflicts from Gradle-resolved scan usages (highest-wins)."""
    strategy = strategy_for_build_system("gradle")
    bs_label = scan.get("buildSystem") or "gradle"

    # ga -> version -> {sources: [usage labels…]}
    ga_versions: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
    for dep in scan.get("dependencies") or []:
        if dep.get("isPlatform"):
            continue
        gid, aid = dep.get("groupId"), dep.get("artifactId")
        ver = dep.get("version") or dep.get("effectiveVersion")
        if not gid or not aid or not ver:
            continue
        usages = dep.get("usages") or [{"module": None, "configuration": ""}]
        for usage in usages:
            module = usage.get("module")
            config = usage.get("configuration", "")
            label = f"{module}:{config}" if module else (config or "gradle-resolved")
            bucket = ga_versions.setdefault((gid, aid), {})
            info = bucket.setdefault(ver, {"sources": []})
            if label not in info["sources"]:
                info["sources"].append(label)

    conflicts: List[Dict[str, Any]] = []
    for (gid, aid), ver_map in sorted(ga_versions.items()):
        versions = list(ver_map.keys())
        if len(versions) < 2:
            continue
        resolved = resolve_conflict_version(versions, strategy)
        sources: List[Dict[str, Any]] = []
        for v in sorted(versions, key=functools.cmp_to_key(compare_versions)):
            sources.append({
                "version": v,
                "via": ver_map[v]["sources"][:10],
                "minDepth": None,
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

    risk_order = {"high": 0, "medium": 1, "low": 2}
    conflicts.sort(
        key=lambda c: (
            risk_order.get(c["risk"], 9),
            c["groupId"],
            c["artifactId"],
        )
    )

    notes = [
        "Conflict detection derived from Gradle-resolved dependency scan usages "
        + "(highest-wins mediation).",
        "Compares versions of the same groupId:artifactId seen across module/"
        + "configuration usages in the resolved tree.",
        "Does not model ResolutionStrategy, strict versions, or enforcedPlatform "
        + "overrides beyond what Gradle already reported.",
    ]
    return {
        "buildSystem": bs_label,
        "strategy": strategy,
        "conflicts": conflicts,
        "scannedRoots": 0,
        "graphsFetched": 0,
        "graphsFailed": 0,
        "partial": False,
        "errors": [],
        "notes": notes,
    }


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
    if scan.get("resolvedBy") == "gradle":
        return _detect_conflicts_from_gradle_scan(scan)
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
    capability: Optional[str] = None

    # #400: fetch every root's transitive graph in parallel (pure, independent
    # per-root network calls; no shared state touched) — then aggregate
    # SEQUENTIALLY below in the ORIGINAL root order, exactly as before. Unlike
    # check_license_compliance's per-node walk, this aggregation (min-depth,
    # append-to-sources) has no order-sensitive "upgrade in place" logic, so
    # keeping it sequential is purely for a minimal/obviously-correct diff,
    # not a correctness requirement.
    def _fetch_conflict_root_graph(root: Dict[str, str]) -> Dict[str, Any]:
        return fetch_depsdev_dependencies(
            root["groupId"], root["artifactId"], root["version"]
        )

    root_graphs, _partial = _map_parallel(
        unique_roots, _fetch_conflict_root_graph, max_workers=MAX_PARALLEL_FETCHES,
    )

    for root, fetched in zip(unique_roots, root_graphs):
        root_label = f"{root['groupId']}:{root['artifactId']}:{root['version']}"
        if fetched.get("capabilityUnavailable") and capability is None:
            capability = fetched["capabilityUnavailable"]
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

    out = {
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
    return _with_capability(out, capability)


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


def extract_licenses_from_pom(pom_xml: str) -> List[Dict[str, Optional[str]]]:
    """Extract ``<licenses><license>`` entries from a POM (#300).

    Returns a list of ``{name, url}`` dicts. ``name`` comes from ``<name>``;
    ``url`` from ``<url>`` (either may be None when the tag is absent/empty).
    Entries with neither name nor url are skipped. Regex-only — no XML parser.
    """
    xml = _strip_xml_comments(pom_xml)
    block_m = re.search(r"<licenses>([\s\S]*?)</licenses>", xml)
    if not block_m:
        return []
    entries: List[Dict[str, Optional[str]]] = []
    for m in re.finditer(r"<license>([\s\S]*?)</license>", block_m.group(1)):
        block = m.group(1)
        name_m = re.search(r"<name>\s*(.*?)\s*</name>", block)
        url_m = re.search(r"<url>\s*(.*?)\s*</url>", block)
        name = name_m.group(1).strip() if name_m and name_m.group(1) else None
        url = url_m.group(1).strip() if url_m and url_m.group(1) else None
        if name or url:
            entries.append({"name": name, "url": url})
    return entries


# ---------------------------------------------------------------------------
# License intelligence (#300) — SPDX normalize, categorize, interpret
# ---------------------------------------------------------------------------

# Canonical SPDX id -> category. Static lookup only; no external license API.
_LICENSE_CATEGORY_BY_SPDX: Dict[str, str] = {
    # permissive
    "MIT": "permissive",
    "Apache-2.0": "permissive",
    "Apache-1.1": "permissive",
    "Apache-1.0": "permissive",
    "BSD-2-Clause": "permissive",
    "BSD-3-Clause": "permissive",
    "BSD-3-Clause-Clear": "permissive",
    "BSD-4-Clause": "permissive",
    "ISC": "permissive",
    "0BSD": "permissive",
    "Unlicense": "permissive",
    "WTFPL": "permissive",
    "CC0-1.0": "permissive",
    "PostgreSQL": "permissive",
    "Zlib": "permissive",
    "BSL-1.0": "permissive",
    "NCSA": "permissive",
    "X11": "permissive",
    "Python-2.0": "permissive",
    "PSF-2.0": "permissive",
    "AFL-2.1": "permissive",
    "AFL-3.0": "permissive",
    "Artistic-2.0": "permissive",
    "MS-PL": "permissive",
    "PHP-3.01": "permissive",
    # weak copyleft
    "LGPL-2.0": "weak-copyleft",
    "LGPL-2.0-only": "weak-copyleft",
    "LGPL-2.0-or-later": "weak-copyleft",
    "LGPL-2.1": "weak-copyleft",
    "LGPL-2.1-only": "weak-copyleft",
    "LGPL-2.1-or-later": "weak-copyleft",
    "LGPL-3.0": "weak-copyleft",
    "LGPL-3.0-only": "weak-copyleft",
    "LGPL-3.0-or-later": "weak-copyleft",
    "MPL-1.1": "weak-copyleft",
    "MPL-2.0": "weak-copyleft",
    "EPL-1.0": "weak-copyleft",
    "EPL-2.0": "weak-copyleft",
    "CDDL-1.0": "weak-copyleft",
    "CDDL-1.1": "weak-copyleft",
    "CPL-1.0": "weak-copyleft",
    "IPL-1.0": "weak-copyleft",
    # strong copyleft
    "GPL-2.0": "strong-copyleft",
    "GPL-2.0-only": "strong-copyleft",
    "GPL-2.0-or-later": "strong-copyleft",
    "GPL-3.0": "strong-copyleft",
    "GPL-3.0-only": "strong-copyleft",
    "GPL-3.0-or-later": "strong-copyleft",
    # network copyleft
    "AGPL-3.0": "network-copyleft",
    "AGPL-3.0-only": "network-copyleft",
    "AGPL-3.0-or-later": "network-copyleft",
    "EUPL-1.1": "network-copyleft",
    "EUPL-1.2": "network-copyleft",
}

_LICENSE_CATEGORY_NOTES: Dict[str, str] = {
    "permissive": (
        "Permissive open-source license: generally allows use, modification, "
        "and redistribution with attribution; no copyleft obligation on your code."
    ),
    "weak-copyleft": (
        "Weak copyleft: modifications to this library itself may need to stay "
        "under the same license; linking from proprietary code is usually allowed."
    ),
    "strong-copyleft": (
        "Strong copyleft: distributing a combined work that includes this "
        "library typically requires releasing that work under a compatible copyleft license."
    ),
    "network-copyleft": (
        "Network copyleft: providing the software as a network service can "
        "trigger source-disclosure obligations similar to strong copyleft."
    ),
    "proprietary": (
        "Declared license is not a recognized open-source SPDX id; treat as "
        "proprietary/custom and review the license text before adopting."
    ),
    "unknown": (
        "No license was declared in the POM or on the linked GitHub repository; "
        "do not assume redistributable rights."
    ),
}

# Lowercased POM/GitHub license name fragments -> canonical SPDX.
# Longer / more specific keys are matched first via sorted length.
_LICENSE_NAME_TO_SPDX: Dict[str, str] = {
    "apache license, version 2.0": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0",
    "the apache software license, version 2.0": "Apache-2.0",
    "apache software license, version 2.0": "Apache-2.0",
    "apache software license - version 2.0": "Apache-2.0",
    "asl 2.0": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache 2": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "the apache license, version 2.0": "Apache-2.0",
    "apache license, version 1.1": "Apache-1.1",
    "mit license": "MIT",
    "the mit license": "MIT",
    "mit": "MIT",
    "bsd 2-clause license": "BSD-2-Clause",
    "bsd 2-clause \"simplified\" license": "BSD-2-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "simplified bsd license": "BSD-2-Clause",
    "bsd 3-clause license": "BSD-3-Clause",
    "bsd 3-clause \"new\" or \"revised\" license": "BSD-3-Clause",
    "the bsd 3-clause license": "BSD-3-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "revised bsd license": "BSD-3-Clause",
    "isc license": "ISC",
    "isc": "ISC",
    "unlicense": "Unlicense",
    "wtfpl": "WTFPL",
    "cc0 1.0 universal": "CC0-1.0",
    "cc0-1.0": "CC0-1.0",
    "mozilla public license version 2.0": "MPL-2.0",
    "mozilla public license 2.0": "MPL-2.0",
    "mpl 2.0": "MPL-2.0",
    "mpl-2.0": "MPL-2.0",
    "eclipse public license - v 2.0": "EPL-2.0",
    "eclipse public license - v 1.0": "EPL-1.0",
    "eclipse public license 2.0": "EPL-2.0",
    "eclipse public license 1.0": "EPL-1.0",
    "epl-2.0": "EPL-2.0",
    "epl-1.0": "EPL-1.0",
    "common development and distribution license (cddl) v1.0": "CDDL-1.0",
    "common development and distribution license 1.0": "CDDL-1.0",
    "cddl-1.0": "CDDL-1.0",
    "cddl 1.1": "CDDL-1.1",
    "cddl-1.1": "CDDL-1.1",
    "gnu lesser general public license, version 3": "LGPL-3.0-only",
    "gnu lesser general public license version 3": "LGPL-3.0-only",
    "gnu lesser general public license, version 2.1": "LGPL-2.1-only",
    "gnu lesser general public license version 2.1": "LGPL-2.1-only",
    "lgpl-3.0": "LGPL-3.0-only",
    "lgpl 3.0": "LGPL-3.0-only",
    "lgplv3": "LGPL-3.0-only",
    "lgpl-2.1": "LGPL-2.1-only",
    "lgpl 2.1": "LGPL-2.1-only",
    "lgplv2.1": "LGPL-2.1-only",
    "gnu general public license, version 3": "GPL-3.0-only",
    "gnu general public license version 3": "GPL-3.0-only",
    "gnu general public license, version 2": "GPL-2.0-only",
    "gnu general public license version 2": "GPL-2.0-only",
    "gpl-3.0": "GPL-3.0-only",
    "gpl 3.0": "GPL-3.0-only",
    "gplv3": "GPL-3.0-only",
    "gpl-2.0": "GPL-2.0-only",
    "gpl 2.0": "GPL-2.0-only",
    "gplv2": "GPL-2.0-only",
    "gnu affero general public license v3": "AGPL-3.0-only",
    "gnu affero general public license version 3": "AGPL-3.0-only",
    "agpl-3.0": "AGPL-3.0-only",
    "agpl 3.0": "AGPL-3.0-only",
    "agplv3": "AGPL-3.0-only",
    "european union public licence 1.2": "EUPL-1.2",
    "european union public license 1.2": "EUPL-1.2",
    "eupl-1.2": "EUPL-1.2",
    "eupl 1.2": "EUPL-1.2",
    "zlib license": "Zlib",
    "boost software license 1.0": "BSL-1.0",
    "bsl-1.0": "BSL-1.0",
}

_LICENSE_NAME_TO_SPDX_KEYS = sorted(_LICENSE_NAME_TO_SPDX.keys(), key=len, reverse=True)


def normalize_license_to_spdx(raw: Optional[str]) -> Optional[str]:
    """Map a POM/GitHub license string to a canonical SPDX id, or None."""
    if not raw:
        return None
    text = raw.strip()
    if not text or text.upper() in ("NOASSERTION", "NONE", "UNKNOWN", "SEE LICENSE", "SEE LICENSE IN LICENSE"):
        return None
    if text in _LICENSE_CATEGORY_BY_SPDX:
        return text
    # GitHub sometimes returns SPDX with "NOASSERTION"; already handled above.
    lower = re.sub(r"\s+", " ", text.lower())
    lower = lower.strip(" .;")
    if lower in _LICENSE_NAME_TO_SPDX:
        return _LICENSE_NAME_TO_SPDX[lower]
    for key in _LICENSE_NAME_TO_SPDX_KEYS:
        if key in lower:
            return _LICENSE_NAME_TO_SPDX[key]
    # Bare SPDX-looking token (e.g. already-canonical from GitHub).
    token = text.strip()
    if token in _LICENSE_CATEGORY_BY_SPDX:
        return token
    return None


def categorize_license(spdx_id: Optional[str], raw_name: Optional[str] = None) -> str:
    """Return license category for an SPDX id / raw name (#300)."""
    if spdx_id and spdx_id in _LICENSE_CATEGORY_BY_SPDX:
        return _LICENSE_CATEGORY_BY_SPDX[spdx_id]
    if spdx_id or (raw_name and raw_name.strip()):
        return "proprietary"
    return "unknown"


def license_category_notes(category: str) -> str:
    return _LICENSE_CATEGORY_NOTES.get(category, _LICENSE_CATEGORY_NOTES["unknown"])


def _license_result(
    group_id: str,
    artifact_id: str,
    version: Optional[str],
    spdx_id: Optional[str],
    name: Optional[str],
    url: Optional[str],
    category: str,
    source: Optional[str],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "groupId": group_id,
        "artifactId": artifact_id,
        "spdxId": spdx_id,
        "name": name,
        "url": url,
        "category": category,
        "notes": license_category_notes(category),
        "source": source,
    }
    if version is not None:
        out["version"] = version
    if error is not None:
        out["error"] = error
    return out


def resolve_dependency_license(
    group_id: str,
    artifact_id: str,
    version: Optional[str],
    ctx: "ResolutionContext",
) -> Dict[str, Any]:
    """Resolve license intelligence for one GAV (#300).

    Reuses the health-tool path: metadata → POM licenses → optional GitHub
    ``license.spdx_id``. Category/notes come from static tables only.
    """
    resolved_version = version
    resolved_from = None
    try:
        metadata = fetch_metadata(group_id, artifact_id, ctx)
        resolved_from = metadata.get("resolvedFrom")
        if not resolved_version:
            versions = metadata.get("versions") or []
            resolved_version = find_latest_version(versions, "PREFER_STABLE") or (
                versions[-1] if versions else None
            )
            if not resolved_version:
                result = _license_result(
                    group_id, artifact_id, None, None, None, None, "unknown", None,
                    error="No version found",
                )
                if resolved_from is not None:
                    result["resolvedFrom"] = resolved_from
                return result
    except Exception as e:
        return _license_result(
            group_id, artifact_id, version, None, None, None, "unknown", None,
            error=str(e),
        )

    pom_name: Optional[str] = None
    pom_url: Optional[str] = None
    pom_xml = fetch_pom(group_id, artifact_id, resolved_version, ctx) if resolved_version else None
    if pom_xml:
        pom_entries = extract_licenses_from_pom(pom_xml)
        if pom_entries:
            pom_name = pom_entries[0]["name"]
            pom_url = pom_entries[0]["url"]

    github_spdx: Optional[str] = None
    gh_repo = extract_github_repo_from_pom(pom_xml) if pom_xml else None
    if not gh_repo:
        guess = guess_github_repo(group_id, artifact_id)
        if guess:
            # Prefer a cheap existence check before fetching full repo metadata,
            # matching get_dependency_health's guess path cost profile.
            cached = gh_fetch_repo(guess["owner"], guess["repo"])
            if cached:
                gh_repo = guess
                spdx = (cached.get("license") or {}).get("spdx_id")
                if spdx and spdx != "NOASSERTION":
                    github_spdx = spdx
    if gh_repo and github_spdx is None:
        repo_meta = gh_fetch_repo(gh_repo["owner"], gh_repo["repo"])
        if repo_meta:
            spdx = (repo_meta.get("license") or {}).get("spdx_id")
            if spdx and spdx != "NOASSERTION":
                github_spdx = spdx

    # Prefer GitHub SPDX (already canonical) over POM name normalization.
    source: Optional[str] = None
    spdx_id: Optional[str] = None
    name: Optional[str] = pom_name
    url: Optional[str] = pom_url

    if github_spdx:
        spdx_id = normalize_license_to_spdx(github_spdx) or github_spdx
        source = "github"
        if not name:
            name = github_spdx
    elif pom_name:
        normalized = normalize_license_to_spdx(pom_name)
        if normalized:
            spdx_id = normalized
            source = "pom" if pom_name in _LICENSE_CATEGORY_BY_SPDX else "spdx-normalized"
        else:
            source = "pom"
    else:
        source = None

    category = categorize_license(spdx_id, name or github_spdx)
    result = _license_result(
        group_id, artifact_id, resolved_version, spdx_id, name, url, category, source,
    )
    if resolved_from is not None:
        result["resolvedFrom"] = resolved_from
    return result


# ---------------------------------------------------------------------------
# Transitive license compliance (#289)
# ---------------------------------------------------------------------------

# Categories treated as risky under a permissive projectLicense posture.
# Overridable via ``disallow`` (SPDX ids and/or category names).
_DEFAULT_DISALLOW_FOR_PERMISSIVE = frozenset({
    "strong-copyleft",
    "network-copyleft",
    "proprietary",
})

# Known category tokens accepted in ``disallow`` (case-insensitive match).
_LICENSE_CATEGORY_TOKENS = frozenset({
    "permissive",
    "weak-copyleft",
    "strong-copyleft",
    "network-copyleft",
    "proprietary",
    "unknown",
})

_LICENSE_COMPLIANCE_NOTES = [
    (
        "License data comes from deps.dev GetVersion (package metadata SPDX "
        "expressions), not from a full legal review of license text."
    ),
    (
        "GetDependencies does not include licenses; each unique GAV in the "
        "resolved graph requires a separate GetVersion call (cached, capped)."
    ),
    (
        "Graphs are resolved per root in isolation via deps.dev — not a full "
        "Maven/Gradle project resolve (exclusions, dependencyManagement, "
        "ResolutionStrategy, private coordinates are not modeled)."
    ),
    (
        "Verdicts are heuristic policy signals, not legal advice. Independently "
        "verify licenses before redistributing."
    ),
    (
        "deps.dev may return SPDX expressions (e.g. Apache-2.0 OR MIT) or "
        "'non-standard'; expression operators beyond a single id are treated "
        "conservatively (review when not an exact known SPDX id)."
    ),
]


def _normalize_disallow_token(raw: str) -> str:
    """Normalize a disallow entry to a category name or canonical SPDX id."""
    text = (raw or "").strip()
    if not text:
        return ""
    lower = text.lower()
    if lower in _LICENSE_CATEGORY_TOKENS:
        return lower
    # Accept hyphen/underscore variants of category names.
    compact = lower.replace("_", "-")
    if compact in _LICENSE_CATEGORY_TOKENS:
        return compact
    spdx = normalize_license_to_spdx(text)
    return spdx or text


def resolve_license_policy(
    project_license: Optional[str] = None,
    disallow: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build the effective disallow set for license compliance (#289).

    Default posture when ``projectLicense`` is permissive (or omitted with no
    custom ``disallow``): flag strong-copyleft, network-copyleft, and
    proprietary. Explicit ``disallow`` replaces the default set entirely.
    Unknown project licenses do not invent a default disallow list unless
    ``disallow`` is provided.
    """
    project_spdx = normalize_license_to_spdx(project_license) if project_license else None
    project_category = (
        categorize_license(project_spdx, project_license)
        if (project_spdx or project_license)
        else None
    )

    if disallow is not None:
        tokens = []
        seen = set()
        for item in disallow:
            tok = _normalize_disallow_token(str(item))
            if tok and tok not in seen:
                seen.add(tok)
                tokens.append(tok)
        source = "custom"
    elif project_category == "permissive" or (
        project_license is None and project_category is None
    ):
        # Omitted projectLicense → assume permissive posture (common OSS default
        # for this tool's audience). Explicit non-permissive projectLicense
        # without disallow → empty set (no invented policy).
        tokens = sorted(_DEFAULT_DISALLOW_FOR_PERMISSIVE)
        source = "default-permissive"
    else:
        tokens = []
        source = "none"

    return {
        "projectLicense": project_spdx or project_license,
        "projectCategory": project_category,
        "disallow": tokens,
        "policySource": source,
    }


def _is_spdx_expression(raw: str) -> bool:
    """True when ``raw`` looks like a compound SPDX expression, not a single id.

    deps.dev may return ``Apache-2.0 OR MIT``. Substring normalization would
    otherwise pick the first known id and falsely categorize as permissive.
    """
    upper = f" {raw.upper()} "
    return (
        " OR " in upper
        or " AND " in upper
        or " WITH " in upper
        or raw.strip().startswith("(")
    )


def _primary_license_from_depsdev(raw_licenses: List[str]) -> Dict[str, Any]:
    """Pick a primary SPDX/category from deps.dev license strings.

    Multi-license lists and SPDX expressions that are not a single known id
    degrade to category ``unknown`` with the raw expression preserved, so the
    compliance verdict becomes ``review`` rather than a false ``ok``.
    """
    if not raw_licenses:
        return {
            "spdxId": None,
            "name": None,
            "category": "unknown",
            "licenses": [],
        }
    # Prefer the first entry that is a single known SPDX id.
    for raw in raw_licenses:
        if raw.lower() == "non-standard":
            return {
                "spdxId": None,
                "name": raw,
                "category": "proprietary",
                "licenses": list(raw_licenses),
            }
        if _is_spdx_expression(raw):
            continue
        spdx = normalize_license_to_spdx(raw)
        if spdx and spdx in _LICENSE_CATEGORY_BY_SPDX and spdx == raw.strip():
            return {
                "spdxId": spdx,
                "name": spdx,
                "category": categorize_license(spdx, raw),
                "licenses": list(raw_licenses),
            }
        if spdx and spdx in _LICENSE_CATEGORY_BY_SPDX and not _is_spdx_expression(raw):
            # Exact table hit or simple alias (e.g. "MIT License") — not an expression.
            return {
                "spdxId": spdx,
                "name": raw if raw != spdx else spdx,
                "category": categorize_license(spdx, raw),
                "licenses": list(raw_licenses),
            }
    # Expression / unrecognized — keep raw, force review via unknown.
    primary = raw_licenses[0]
    return {
        "spdxId": None,
        "name": primary,
        "category": "unknown",
        "licenses": list(raw_licenses),
    }


def license_compliance_verdict(
    *,
    spdx_id: Optional[str],
    category: str,
    policy: Dict[str, Any],
    fetch_error: Optional[str] = None,
    missing_license: bool = False,
) -> Dict[str, str]:
    """Return ``{verdict, reason}`` for one node against the policy.

    - ``violation`` — category or SPDX id is in the disallow set.
    - ``review`` — missing/unknown license metadata, or fetch failure.
    - ``ok`` — known license not disallowed.
    """
    disallow = set(policy.get("disallow") or [])
    if fetch_error:
        return {
            "verdict": "review",
            "reason": f"license metadata unavailable: {fetch_error}",
        }
    if missing_license or category == "unknown" or not spdx_id:
        # Unknown / empty must never be a false ok (AC).
        if category in disallow or "unknown" in disallow:
            return {
                "verdict": "violation",
                "reason": f"disallowed category '{category}' (license unknown or undeclared)",
            }
        return {
            "verdict": "review",
            "reason": "no SPDX license declared by deps.dev; verify manually",
        }
    if category in disallow:
        return {
            "verdict": "violation",
            "reason": f"category '{category}' is disallowed by policy",
        }
    if spdx_id in disallow:
        return {
            "verdict": "violation",
            "reason": f"SPDX id '{spdx_id}' is disallowed by policy",
        }
    return {"verdict": "ok", "reason": "license allowed by policy"}


def check_license_compliance(
    dependencies: List[Dict[str, Any]],
    project_license: Optional[str] = None,
    disallow: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Aggregate transitive licenses and flag policy violations (#289).

    For each versioned root, fetches the deps.dev GetDependencies graph, then
    GetVersion licenses for each unique GAV (capped). Marks ``viaTransitive``
    from deps.dev ``relation`` (SELF/DIRECT → false, else true).

    #400/#402 concurrency note: the per-ROOT graph fetch below (bounded by
    MAX_LICENSE_COMPLIANCE_ROOTS, a pure independent network call per root) IS
    parallelized. The per-NODE license fetch/dedup walk (_ensure_license /
    _add_result, up to MAX_LICENSE_COMPLIANCE_NODES) deliberately stays
    SEQUENTIAL: its dedup is order-sensitive (`seen_result_keys`'s
    "first-seen wins for viaTransitive=false, upgrade in place otherwise"
    rule depends on processing roots/nodes in a fixed order) and its cache
    (`license_cache`) is mutated in lockstep with that walk — splitting fetch
    from decide to parallelize it safely would be a materially larger,
    higher-risk rewrite of this function's carefully-specified dedup
    semantics. Instead, TOOL_DEADLINE bounds the sequential node walk
    directly (see the `_now() >= deadline` checks below): a degenerate
    large-graph batch returns whatever was gathered so far with
    `partial: true` rather than blocking indefinitely — which is exactly what
    #402 asks for on this specific tool.
    """
    deadline = _now() + TOOL_DEADLINE
    deadline_hit = False
    policy = resolve_license_policy(project_license, disallow)
    roots = []
    for dep in dependencies or []:
        gid = dep.get("groupId")
        aid = dep.get("artifactId")
        ver = dep.get("version")
        if not gid or not aid or not ver:
            continue
        roots.append({"groupId": gid, "artifactId": aid, "version": ver})

    truncated_roots = len(roots) > MAX_LICENSE_COMPLIANCE_ROOTS
    roots = roots[:MAX_LICENSE_COMPLIANCE_ROOTS]

    # Dedup GetVersion calls across roots: g:a:v → license fetch result.
    license_cache: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []
    seen_result_keys: set = set()
    errors: List[str] = []
    partial = False
    truncated_nodes = False
    nodes_fetched = 0
    capability: Optional[str] = None

    def _gav_key(g: str, a: str, v: str) -> str:
        return f"{g}:{a}:{v}"

    def _ensure_license(g: str, a: str, v: str) -> Dict[str, Any]:
        nonlocal nodes_fetched, truncated_nodes, partial, capability
        key = _gav_key(g, a, v)
        if key in license_cache:
            return license_cache[key]
        if nodes_fetched >= MAX_LICENSE_COMPLIANCE_NODES:
            truncated_nodes = True
            partial = True
            entry = {
                "ok": False,
                "licenses": [],
                "error": (
                    f"GetVersion fan-out capped at {MAX_LICENSE_COMPLIANCE_NODES}"
                ),
            }
            license_cache[key] = entry
            return entry
        nodes_fetched += 1
        entry = fetch_depsdev_licenses(g, a, v)
        if entry.get("capabilityUnavailable") and capability is None:
            capability = entry["capabilityUnavailable"]
        license_cache[key] = entry
        return entry

    def _add_result(
        g: str,
        a: str,
        v: str,
        *,
        via_transitive: bool,
        relation: str,
        root: Dict[str, str],
    ) -> None:
        nonlocal partial
        key = _gav_key(g, a, v)
        # One row per unique GAV across all roots (first-seen wins for
        # viaTransitive=false — a direct hit beats a later transitive sighting).
        if key in seen_result_keys:
            # Upgrade viaTransitive False if we later see it as direct/self.
            if not via_transitive:
                for row in results:
                    if (
                        row["groupId"] == g
                        and row["artifactId"] == a
                        and row["version"] == v
                        and row.get("viaTransitive")
                    ):
                        row["viaTransitive"] = False
                        row["relation"] = relation or row.get("relation")
                        break
            return
        seen_result_keys.add(key)
        fetched = _ensure_license(g, a, v)
        primary = _primary_license_from_depsdev(fetched.get("licenses") or [])
        missing = not (fetched.get("licenses") or [])
        verdict_info = license_compliance_verdict(
            spdx_id=primary.get("spdxId"),
            category=primary.get("category") or "unknown",
            policy=policy,
            fetch_error=None if fetched.get("ok") else fetched.get("error"),
            missing_license=missing and fetched.get("ok", False),
        )
        if verdict_info["verdict"] != "ok":
            # review/violation are expected outcomes; do not mark partial solely
            # for policy hits. Partial is reserved for data/transport gaps.
            pass
        if not fetched.get("ok"):
            partial = True
        row: Dict[str, Any] = {
            "groupId": g,
            "artifactId": a,
            "version": v,
            "spdxId": primary.get("spdxId"),
            "license": primary.get("spdxId") or primary.get("name"),
            "licenses": primary.get("licenses") or [],
            "category": primary.get("category") or "unknown",
            "viaTransitive": via_transitive,
            "relation": relation or ("INDIRECT" if via_transitive else "DIRECT"),
            "verdict": verdict_info["verdict"],
            "reason": verdict_info["reason"],
            "root": {
                "groupId": root["groupId"],
                "artifactId": root["artifactId"],
                "version": root["version"],
            },
            "source": "deps.dev",
        }
        if fetched.get("error"):
            row["error"] = fetched["error"]
        results.append(row)

    # #400: fetch every root's transitive graph in parallel first (pure,
    # independent per-root network calls; no shared state touched) — then
    # walk roots+nodes SEQUENTIALLY below in the ORIGINAL order, exactly as
    # before, so the dedup/upgrade-in-place logic in _add_result stays
    # deterministic regardless of which root's fetch actually completed
    # first.
    def _fetch_root_graph(root: Dict[str, str]) -> Dict[str, Any]:
        return fetch_depsdev_dependencies(
            root["groupId"], root["artifactId"], root["version"],
        )

    root_graphs, root_fetch_partial = _map_parallel(
        roots, _fetch_root_graph, max_workers=MAX_PARALLEL_FETCHES, deadline=deadline,
    )
    if root_fetch_partial:
        deadline_hit = True

    for root, fetched in zip(roots, root_graphs):
        # R2a fix: this loop must NEVER `break` out early on a deadline —
        # doing so silently drops every root from that point on (the exact
        # bug: the deadline check used to fire immediately after synthesizing
        # a cut-off root's placeholder, before that root's own review row was
        # ever added, then `break` skipped ALL subsequent roots too, since a
        # once-exceeded deadline never un-expires). Instead: once the
        # deadline is exceeded — whether THIS root's own graph fetch was cut
        # off (`fetched is None`) or time simply ran out by the time we
        # reached this iteration (a prior root's node walk used the rest of
        # the budget) — this root degrades to a cheap review row (no further
        # network calls) and the loop continues to the NEXT root exactly the
        # same way. Every root in `roots` therefore always reaches the
        # bottom of one iteration and gets exactly one row.
        deadline_cutoff = fetched is None or _now() >= deadline
        if deadline_cutoff:
            deadline_hit = True
        cap = fetched.get("capabilityUnavailable") if fetched is not None else None
        if cap and capability is None:
            capability = cap
        if deadline_cutoff:
            err = (fetched or {}).get("error") if fetched is not None else None
            fetched = {
                "ok": False,
                "error": err or f"skipped: exceeded the {TOOL_DEADLINE}s tool deadline",
            }

        if not fetched.get("ok"):
            partial = True
            err = fetched.get("error") or "deps.dev unavailable"
            if len(errors) < MAX_DEPSDEV_ERRORS_REPORTED:
                errors.append(
                    f"{root['groupId']}:{root['artifactId']}:{root['version']}: {err}"
                )
            # Still emit a review row for the root itself so callers see it.
            _add_result(
                root["groupId"],
                root["artifactId"],
                root["version"],
                via_transitive=False,
                relation="SELF",
                root=root,
            )
            # Force review on the synthetic root row when graph fetch failed.
            for row in results:
                if (
                    row["groupId"] == root["groupId"]
                    and row["artifactId"] == root["artifactId"]
                    and row["version"] == root["version"]
                ):
                    if row["verdict"] == "ok":
                        row["verdict"] = "review"
                        row["reason"] = f"transitive graph unavailable: {err}"
                    break
            continue

        if fetched.get("graphError"):
            partial = True
            if len(errors) < MAX_DEPSDEV_ERRORS_REPORTED:
                errors.append(
                    f"{root['groupId']}:{root['artifactId']}:{root['version']}: "
                    f"graph error: {fetched['graphError']}"
                )
        if fetched.get("truncated") or fetched.get("partial"):
            partial = True

        for node in fetched.get("nodes") or []:
            if _now() >= deadline:
                # #402: bound the sequential per-node dedup/license-fetch
                # walk — see the concurrency note in this function's
                # docstring for why this loop stays sequential rather than
                # joining the #400 executor. Breaks only the NODE loop for
                # THIS root (nodes already added stay); the OUTER root loop
                # continues naturally to the next root, which will see
                # `deadline_cutoff=True` at the top of its own iteration and
                # degrade to a review row instead of attempting its nodes.
                deadline_hit = True
                break
            g = node.get("groupId") or ""
            a = node.get("artifactId") or ""
            v = node.get("version") or ""
            if not g or not a or not v:
                continue
            relation = (node.get("relation") or "").upper()
            via = relation not in ("SELF", "DIRECT", "")
            # Empty relation on the first node is typically SELF; treat unknown
            # non-empty as transitive to avoid under-flagging.
            if relation == "":
                via = False
            _add_result(g, a, v, via_transitive=via, relation=relation or "DIRECT", root=root)

    by_verdict = {"ok": 0, "review": 0, "violation": 0}
    by_category: Dict[str, int] = {}
    for row in results:
        v = row.get("verdict") or "review"
        by_verdict[v] = by_verdict.get(v, 0) + 1
        cat = row.get("category") or "unknown"
        by_category[cat] = by_category.get(cat, 0) + 1

    notes = list(_LICENSE_COMPLIANCE_NOTES)
    if truncated_roots:
        partial = True
        notes.append(
            f"Roots truncated to {MAX_LICENSE_COMPLIANCE_ROOTS} "
            f"(MAX_LICENSE_COMPLIANCE_ROOTS); results are partial."
        )
    if truncated_nodes:
        notes.append(
            f"GetVersion calls capped at {MAX_LICENSE_COMPLIANCE_NODES} "
            f"(MAX_LICENSE_COMPLIANCE_NODES); results are partial."
        )
    if deadline_hit:
        partial = True
        notes.append(
            f"Stopped early after exceeding the {TOOL_DEADLINE}s tool "
            f"deadline; remaining roots/nodes were not processed and "
            f"results are partial."
        )

    out: Dict[str, Any] = {
        "policy": policy,
        "summary": {
            "total": len(results),
            "byVerdict": by_verdict,
            "byCategory": by_category,
            "violationCount": by_verdict.get("violation", 0),
            "reviewCount": by_verdict.get("review", 0),
        },
        "results": results,
        "partial": partial,
        "notes": notes,
    }
    if errors:
        out["errors"] = errors
    return _with_capability(out, capability)


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
    if _external_capability("github"):
        return None
    if not path.startswith("/"):
        path = "/" + path
    url = f"{_github_api_base()}{path}"
    try:
        status, body = http_get(
            url, _github_headers(), timeout=HTTP_TIMEOUT_EXTERNAL
        )
        if status == 200:
            return json.loads(body)
    except Exception:
        pass  # Network or parse error — caller treats None as "unavailable"
    return None


def gh_repo_exists(owner: str, repo: str) -> bool:
    if _external_capability("github"):
        return False
    url = f"{_github_api_base()}/repos/{owner}/{repo}"
    try:
        status, _ = http_get(
            url, _github_headers(), timeout=HTTP_TIMEOUT_EXTERNAL
        )
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
# Changelog providers for get_dependency_changes (#308)
# Order: AndroidX docs → AGP docs → GitHub releases (mirrors retired TS resolver).
# ---------------------------------------------------------------------------

AGP_GROUP_ID = "com.android.tools.build"
AGP_RELEASES_BASE = "https://developer.android.com/build/releases"
ANDROIDX_RELEASES_BASE = "https://developer.android.com/jetpack/androidx/releases"
# Release-notes HTML pages change infrequently; match the retired TS 7-day TTL.
TTL_CHANGELOG_HTML = TTL_POM


def _agp_releases_base() -> str:
    return f"{_android_docs_base()}/build/releases"


def _androidx_releases_base() -> str:
    return f"{_android_docs_base()}/jetpack/androidx/releases"

_AGP_HEADING_RE = re.compile(
    r'<h3[^>]*\s+data-text="Android Gradle plugin ([\d][^\s"]*)"[^>]*>',
    re.IGNORECASE,
)
_ANDROIDX_VERSION_HEADING_RE = re.compile(
    r"<h[23][^>]*>\s*Version\s+([\d][^\s<]*)\s*</h[23]>",
    re.IGNORECASE,
)


def html_to_text(html: str) -> str:
    """Minimal HTML→text for Android docs release notes (stdlib only, #308).

    Mirrors the retired TS ``html/to-text``: list/br/p formatting, iterative tag
    strip (handles smuggled nested tags), then a small entity unescape set.
    """
    formatted = re.sub(r"<li[^>]*>", "- ", html, flags=re.IGNORECASE)
    formatted = re.sub(r"</li>", "\n", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"<br\s*/?>", "\n", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"</p>", "\n\n", formatted, flags=re.IGNORECASE)
    # Loop so forms like ``<<script>script>`` lose the outer tag first and the
    # inner tag becomes visible to the next pass (same as the TS stripTags loop).
    result = formatted
    while True:
        prev = result
        result = re.sub(r"<[^>]*>", "", result)
        if result == prev:
            break
    result = (
        result.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&amp;", "&")
    )
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def is_agp_artifact(group_id: str) -> bool:
    return group_id == AGP_GROUP_ID


def _agp_major_minor(version: str) -> Tuple[str, str]:
    parts = version.split(".")
    major = parts[0] if parts else ""
    minor = parts[1] if len(parts) > 1 else "0"
    return major, minor


def get_agp_releases_url(version: str) -> str:
    major, minor = _agp_major_minor(version)
    return f"{_agp_releases_base()}/agp-{major}-{minor}-0-release-notes"


def get_agp_version_url(version: str) -> str:
    return f"{get_agp_releases_url(version)}#fixed-issues-agp-{version}"


def parse_agp_release_notes(html: str) -> Dict[str, str]:
    """Parse AGP release-notes HTML into version → plain-text body."""
    headings: List[Tuple[str, int, int]] = []
    for match in _AGP_HEADING_RE.finditer(html):
        headings.append((match.group(1), match.start(), match.end()))
    sections: Dict[str, str] = {}
    for i, (version, _start, end) in enumerate(headings):
        content_end = headings[i + 1][1] if i + 1 < len(headings) else len(html)
        body = html_to_text(html[end:content_end])
        if body:
            sections[version] = body
    return sections


def is_androidx_artifact(group_id: str) -> bool:
    return group_id.startswith("androidx.")


def get_androidx_slug(group_id: str) -> str:
    return group_id[len("androidx.") :].replace(".", "-")


def get_androidx_releases_url(group_id: str) -> str:
    return f"{_androidx_releases_base()}/{get_androidx_slug(group_id)}"


def get_androidx_version_url(group_id: str, version: str) -> str:
    return f"{get_androidx_releases_url(group_id)}#{version}"


def parse_androidx_release_notes(html: str) -> Dict[str, str]:
    """Parse AndroidX release-notes HTML into version → plain-text body."""
    headings: List[Tuple[str, int, int]] = []
    for match in _ANDROIDX_VERSION_HEADING_RE.finditer(html):
        headings.append((match.group(1), match.start(), match.end()))
    sections: Dict[str, str] = {}
    for i, (version, _start, end) in enumerate(headings):
        content_end = headings[i + 1][1] if i + 1 < len(headings) else len(html)
        body = html_to_text(html[end:content_end])
        if body:
            sections[version] = body
    return sections


def _filter_version_range(versions: List[str], from_v: str, to_v: str) -> List[str]:
    """Return versions between from_v (exclusive) and to_v (inclusive)."""
    result = []
    for v in versions:
        gt_from = compare_versions(v, from_v) > 0
        le_to = compare_versions(v, to_v) <= 0
        if gt_from and le_to:
            result.append(v)
    return result


def _changelog_entries_from_sections(
    sections: Dict[str, str],
    version_url_fn: Callable[[str], str],
) -> Dict[str, Dict]:
    entries: Dict[str, Dict] = {}
    for version, body in sections.items():
        entries[version] = {"body": body, "releaseUrl": version_url_fn(version)}
    return entries


def _fetch_agp_changelog(to_version: str) -> Optional[Dict]:
    """Fetch/parse AGP developer.android.com release notes. None on failure."""
    if _external_capability("android_docs"):
        return None
    url = get_agp_releases_url(to_version)
    try:
        status, body = http_get_cached(
            url, TTL_CHANGELOG_HTML, timeout=HTTP_TIMEOUT_EXTERNAL
        )
    except Exception:
        return None
    if status != 200:
        return None
    try:
        sections = parse_agp_release_notes(body.decode("utf-8", errors="replace"))
    except Exception:
        return None
    if not sections:
        return None
    return {
        "repositoryUrl": url,
        "entries": _changelog_entries_from_sections(sections, get_agp_version_url),
    }


def _fetch_androidx_changelog(group_id: str) -> Optional[Dict]:
    """Fetch/parse AndroidX developer.android.com release notes. None on failure."""
    if _external_capability("android_docs"):
        return None
    url = get_androidx_releases_url(group_id)
    try:
        status, body = http_get_cached(
            url, TTL_CHANGELOG_HTML, timeout=HTTP_TIMEOUT_EXTERNAL
        )
    except Exception:
        return None
    if status != 200:
        return None
    try:
        sections = parse_androidx_release_notes(body.decode("utf-8", errors="replace"))
    except Exception:
        return None
    if not sections:
        return None
    return {
        "repositoryUrl": url,
        "entries": _changelog_entries_from_sections(
            sections, lambda v: get_androidx_version_url(group_id, v)
        ),
    }


def _fetch_github_changelog(
    group_id: str, artifact_id: str, to_version: str, ctx: "ResolutionContext"
) -> Optional[Dict]:
    """GitHub releases path (no CHANGELOG.md fallback — intentional Python MVP)."""
    gh_repo = discover_github_repo(group_id, artifact_id, to_version, ctx)
    if not gh_repo:
        return None
    owner, repo = gh_repo["owner"], gh_repo["repo"]
    releases = gh_fetch_releases(owner, repo)
    entries: Dict[str, Dict] = {}
    for rel in releases:
        tag = rel.get("tag_name", "")
        # Strip leading non-digits (v / release- / artifact- prefixes).
        candidate = re.sub(r"^[^0-9]*", "", tag)
        key = candidate if candidate else tag
        entry: Dict = {}
        if rel.get("html_url"):
            entry["releaseUrl"] = rel["html_url"]
        if rel.get("body"):
            entry["body"] = rel["body"]
        # Keep bare version keys even without body so range mapping stays stable.
        entries[key] = entry
        if tag != key:
            entries[tag] = entry
    return {
        "repositoryUrl": f"https://github.com/{owner}/{repo}",
        "entries": entries,
    }


def _resolve_changelog(
    group_id: str, artifact_id: str, to_version: str, ctx: "ResolutionContext"
) -> Optional[Dict]:
    """Provider selection: AndroidX → AGP → GitHub (first non-null wins)."""
    if is_androidx_artifact(group_id):
        result = _fetch_androidx_changelog(group_id)
        if result is not None:
            return result
    if is_agp_artifact(group_id):
        result = _fetch_agp_changelog(to_version)
        if result is not None:
            return result
    return _fetch_github_changelog(group_id, artifact_id, to_version, ctx)


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

    changelog = _resolve_changelog(group_id, artifact_id, to_version, ctx)
    if not changelog:
        out = {**base, "repositoryNotFound": True}
        # Offline with no internal mirrors: changelog providers were skipped.
        for svc in ("android_docs", "github"):
            cap = _external_capability(svc)
            if cap:
                out["capabilityUnavailable"] = cap
                break
        return out

    entries = changelog.get("entries") or {}
    changes = []
    for v in versions_in_range:
        entry = entries.get(v)
        if entry:
            change = {"version": v}
            if entry.get("releaseUrl"):
                change["releaseUrl"] = entry["releaseUrl"]
            if entry.get("body"):
                change["body"] = entry["body"]
            changes.append(change)
        else:
            changes.append({"version": v})

    out = {
        **base,
        "repositoryUrl": changelog["repositoryUrl"],
        "changes": changes,
    }
    if changelog.get("changelogUrl"):
        out["changelogUrl"] = changelog["changelogUrl"]
    return out


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
    if _external_capability("osv"):
        return None
    url = _osv_vuln_url(vuln_id)
    try:
        status, body = http_get(url, timeout=HTTP_TIMEOUT_EXTERNAL)
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


def _compute_safe_upgrade(vulnerabilities: List[Dict]) -> Optional[Dict[str, Any]]:
    """Synthesize the minimum version clearing every known CVE (#412).

    ADVISORY ONLY — a candidate to verify, never a guaranteed-safe pin: fixed
    versions are self-reported by upstream OSV advisories and can be wrong,
    stale, or simply unknown for a given CVE. Reuses each vuln's already-
    hydrated ``fixedVersion`` (query_osv_batch / _extract_fixed_version) — no
    new network call. The minimum version clearing every known vulnerability is
    the HIGHEST individual fixedVersion across them (a version must be >= every
    CVE's own fix boundary to clear all of them at once).

    Returns ``None`` when there is nothing to synthesize (no vulnerabilities —
    the dependency is already clear of every KNOWN CVE, so there is nothing to
    flag either). Never raises: an unparseable/missing fixed version degrades
    the result rather than crashing the handler.
    """
    if not vulnerabilities:
        return None

    fixed_versions: List[str] = []
    unresolved_ids: List[str] = []
    for v in vulnerabilities:
        fixed = v.get("fixedVersion")
        if isinstance(fixed, str) and fixed.strip():
            fixed_versions.append(fixed)
        else:
            unresolved_ids.append(v.get("id") or "unknown")

    if unresolved_ids:
        return {
            "fixesAllKnown": False,
            "reason": "no fixed version known for: " + ", ".join(unresolved_ids),
        }

    best_version = fixed_versions[0]
    try:
        for fixed in fixed_versions[1:]:
            if compare_versions(fixed, best_version) > 0:
                best_version = fixed
    except Exception:
        # Defensive only — compare_versions tolerates malformed input by design
        # (never raises), but a synthesized advisory field must never crash the
        # handler over a version string it cannot make sense of.
        return {
            "fixesAllKnown": False,
            "reason": "could not compare fixed-version strings across known CVEs",
        }

    return {"version": best_version, "fixesAllKnown": True}


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

    When OSV is offline/unreachable (#296), every entry still returns with an
    empty ``vulnerabilities`` list PLUS ``capabilityUnavailable`` so an empty
    result is never mistaken for "verified clean".
    """
    if not deps:
        return []
    cap = _external_capability("osv")
    if cap:
        return [
            {
                **d,
                "vulnerabilities": [],
                "capabilityUnavailable": cap,
            }
            for d in deps
        ]
    # Phase 1: querybatch chunks → (dep, bare vulns_raw) pairs.
    bare_pairs: List[Tuple[Dict, List[Dict]]] = []
    chunk_unreachable = False
    for start in range(0, len(deps), OSV_QUERYBATCH_MAX):
        chunk = deps[start:start + OSV_QUERYBATCH_MAX]
        pairs, unreachable = _query_osv_batch_chunk_bare(chunk)
        bare_pairs.extend(pairs)
        if unreachable:
            chunk_unreachable = True
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
        entry = {**dep, "vulnerabilities": vulns}
        if chunk_unreachable and not vulns:
            entry["capabilityUnavailable"] = "unreachable"
        out.append(entry)
    return out


def _query_osv_batch_chunk_bare(
    deps: List[Dict],
) -> Tuple[List[Tuple[Dict, List[Dict]]], bool]:
    """POST one ≤OSV_QUERYBATCH_MAX querybatch; return ((dep, vulns_raw)…, unreachable).

    On non-200 / error every dep gets an empty vulns_raw list. Does not hydrate
    or filter withdrawn — that happens after /v1/vulns/{id} merge.
    ``unreachable`` is True on transport failure (not on HTTP non-200).
    """
    queries = [
        {"package": {"name": f"{d['groupId']}:{d['artifactId']}", "ecosystem": "Maven"}, "version": d["version"]}
        for d in deps
    ]
    try:
        status, body = http_post_json(
            _osv_querybatch_url(), {"queries": queries}, timeout=HTTP_TIMEOUT_EXTERNAL
        )
        if status != 200:
            return [(d, []) for d in deps], False
        data = json.loads(body)
        results = data.get("results", [])
        out: List[Tuple[Dict, List[Dict]]] = []
        for i, dep in enumerate(deps):
            vulns_raw = (results[i].get("vulns") or []) if i < len(results) else []
            out.append((dep, list(vulns_raw)))
        return out, False
    except Exception:
        return [(d, []) for d in deps], True


# ---------------------------------------------------------------------------
# Maven Central search
# ---------------------------------------------------------------------------

def _search_capability_for_status(status: int) -> str:
    """Map a definitive non-200 Maven Central search response to a PRECISE
    capability reason (#416 polish). By the time a caller sees this status,
    ``_request_with_retry`` has already exhausted ``HTTP_MAX_ATTEMPTS`` on a
    retryable 429/5xx, so this is a DEFINITIVE final answer, never a
    mid-retry state.

    - ``429`` -> ``"rate_limited"``: Sonatype's actual, transient throttle.
    - ``403`` -> ``"blocked"``: search.maven.org's documented bulk-load
      LOCKOUT (see the #322 typosquatRisk gating rationale elsewhere in this
      file) — a definitive block, not a transient throttle. 403 is also NOT a
      retried status (`_is_retryable_status`), so it must not be silently
      dropped. Labeling it "rate_limited" would mislead a caller into an
      aggressive retry loop, which is exactly the wrong response to a lockout.
    - anything else (5xx, or any other non-200) -> ``"unreachable"``: a
      generic "could not use the search backend" signal — the same value
      already used elsewhere in this file for OSV/GitHub/deps.dev transport
      failures.
    """
    if status == 429:
        return "rate_limited"
    if status == 403:
        return "blocked"
    return "unreachable"


# R2b (perf/security review of #400): bounds CONCURRENT calls against
# search.maven.org specifically — a much tighter cap than MAX_PARALLEL_FETCHES
# (8). This host has a documented 403 bulk-load LOCKOUT that
# _request_with_retry does NOT retry, and both callers below fail-open on
# failure (search_maven_central -> [], _fetch_gav_timestamp -> None); for
# verify_coordinates in particular, a failed did-you-mean search silently
# turns likelyHallucination=False, which the write-time pre-edit-deps.sh hook
# then reads as "allow" — a fail-OPEN security path, not just a perf one.
# #322's own MAX_GATED_SOLR_CALLS_PER_BATCH already assumed near-sequential
# access to this host; parallelizing verify_coordinates' per-coordinate loop
# at the full executor width would let up to 8 coordinates hammer Solr at
# once and undermine that assumption. Acquired inside BOTH low-level
# functions that build a SEARCH_API request (_search_maven_central_with_
# capability and _fetch_gav_timestamp) — not just at verify_coordinates' two
# call sites — so every current and future caller against this host is
# covered automatically; repo-metadata probes (fetch_metadata/fetch_pom/etc,
# a different host per coordinate) are unaffected and keep the full
# MAX_PARALLEL_FETCHES concurrency.
MAX_CONCURRENT_SOLR_CALLS = 2
_SOLR_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT_SOLR_CALLS)


def _search_maven_central_with_capability(
    query: str, limit: int = 10, use_cache: bool = True
) -> Tuple[List[Dict], Optional[str]]:
    """Like ``search_maven_central`` but also reports a capability signal (#416)
    so a blocked/rate-limited search is never silently indistinguishable from a
    genuine zero-result search.

    Returns ``(results, capability)``. ``capability`` is precise (see
    ``_search_capability_for_status``): ``"rate_limited"`` for a persistent
    429, ``"blocked"`` for a definitive 403 lockout, ``"unreachable"`` for any
    other non-200 (5xx) or a transport exception (`urllib.error.URLError` /
    `socket.timeout`) after every retry attempt. ``None`` on success,
    including a legitimate empty result set — and ALSO on a 200 whose body
    fails to parse: a malformed-but-200 response is a PARSE bug, never a
    rate-limit/block signal, and must degrade to the same empty-results,
    no-capability outcome this had before #416 (logged via ``_logger``, never
    raised, never folded into the capability path). Never raises.
    """
    try:
        url = f"{SEARCH_API}?q={urllib.parse.quote(query)}&rows={limit}&wt=json"
        # R2b: bound CONCURRENT access to this host specifically (see
        # _SOLR_SEMAPHORE) — held only across the network round-trip itself.
        with _SOLR_SEMAPHORE:
            status, body = http_get_cached(url, TTL_SEARCH) if use_cache else http_get(url)
    except (urllib.error.URLError, socket.timeout) as e:
        # Transport failure after every retry attempt -- the search backend
        # could not be reached at all.
        _logger.warning("search_maven_central: request failed: %s", e)
        return [], "unreachable"
    if status != 200:
        return [], _search_capability_for_status(status)
    try:
        data = json.loads(body)
        docs = data.get("response", {}).get("docs", [])
        results = [
            {
                "groupId": d.get("g", ""),
                "artifactId": d.get("a", ""),
                "latestVersion": d.get("latestVersion", ""),
                "versionCount": d.get("versionCount", 0),
            }
            for d in docs
        ]
    except Exception as e:
        # A 200 with a malformed/unexpected-shape body is a PARSE bug, not a
        # rate-limit/block signal -- log it and degrade to the pre-#416
        # empty-results, no-capability outcome. Never crash the search.
        _logger.warning("search_maven_central: malformed response body: %s", e)
        return [], None
    return results, None


def search_maven_central(query: str, limit: int = 10, use_cache: bool = True) -> List[Dict]:
    """Did-you-mean / suggestion search against Maven Central Solr.

    Kept as a bare ``List[Dict]`` for its existing callers (verify_coordinates'
    did-you-mean suggestions and the #322 Layer 2 heuristics), which already
    treat a search failure as a silent degrade-to-nothing by design. A caller
    that needs to distinguish "genuinely zero results" from "search failed /
    rate-limited" (search_artifacts_with_backend, #416) uses
    ``_search_maven_central_with_capability`` instead.
    """
    return _search_maven_central_with_capability(query, limit, use_cache)[0]


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
        # R2b: bound CONCURRENT access to this host specifically (see
        # _SOLR_SEMAPHORE) — held only across the network round-trip itself.
        with _SOLR_SEMAPHORE:
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
# Repo-manager search backends (#295)
# ---------------------------------------------------------------------------
# Closed contours cannot reach search.maven.org. Nexus 3 and Artifactory expose
# their own search APIs on the same host as MAVEN_MCP_REPOSITORY_BASE / mirrors.
# Public Solr remains the default outside closed mode.

_SEARCH_BACKEND_TYPES = ("auto", "nexus", "artifactory", "central")


def _normalize_search_backend(raw: Optional[str]) -> str:
    """Clamp repositoryType / MAVEN_MCP_REPOSITORY_TYPE to a known value."""
    val = (raw or "").strip().lower()
    if val in _SEARCH_BACKEND_TYPES:
        return val
    return "auto"


def _repository_type_env() -> str:
    return _normalize_search_backend(os.environ.get("MAVEN_MCP_REPOSITORY_TYPE"))


def _closed_search_mode(ctx: "ResolutionContext") -> bool:
    """True when search should prefer a repo-manager backend over public Solr."""
    return bool(ctx.offline or ctx.repository_base or ctx.mirrors)


def _search_manager_base(ctx: "ResolutionContext") -> Optional[str]:
    """Maven-repo URL used to derive the manager API root (base, else first mirror)."""
    if ctx.repository_base:
        return ctx.repository_base.rstrip("/")
    if ctx.mirrors:
        url = (ctx.mirrors[0].get("url") or "").strip().rstrip("/")
        return url or None
    return None


def _manager_origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _nexus_api_root(base_url: str) -> str:
    """Nexus REST lives at the host origin (``/service/rest/v1/...``)."""
    return _manager_origin(base_url)


def _artifactory_api_root(base_url: str) -> str:
    """Artifactory REST is under ``.../artifactory/api/...``."""
    parts = urllib.parse.urlsplit(base_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path or ""
    idx = path.lower().find("/artifactory")
    if idx >= 0:
        return origin + path[: idx + len("/artifactory")]
    return origin + "/artifactory"


def _detect_manager_from_url(base_url: str) -> Optional[str]:
    """Heuristic manager type from URL path / host. Returns nexus|artifactory|None."""
    try:
        parts = urllib.parse.urlsplit(base_url)
    except ValueError:
        return None
    path = (parts.path or "").lower()
    host = (parts.hostname or "").lower()
    if "/artifactory" in path or "artifactory" in host or "jfrog" in host:
        return "artifactory"
    if "/repository/" in path or "nexus" in host:
        return "nexus"
    return None


def _detect_manager_from_headers(headers: Any) -> Optional[str]:
    """Inspect response headers for Nexus / JFrog markers."""
    if headers is None:
        return None
    get = getattr(headers, "get", None)
    if not callable(get):
        # Mapping-like
        def get(key, default=None):  # type: ignore[misc]
            key_l = key.lower()
            for k, v in dict(headers).items():
                if str(k).lower() == key_l:
                    return v
            return default
    keys = []
    try:
        keys = list(headers.keys())  # type: ignore[arg-type]
    except Exception:
        keys = []
    joined = " ".join(str(k) for k in keys).lower()
    server = str(get("Server") or get("server") or "").lower()
    if "nexus" in server or "x-nexus" in joined or any(
        str(k).lower().startswith("x-nexus") for k in keys
    ):
        return "nexus"
    if (
        "artifactory" in server
        or "jfrog" in server
        or "x-jfrog" in joined
        or "x-artifactory" in joined
        or any(
            str(k).lower().startswith(("x-jfrog", "x-artifactory")) for k in keys
        )
    ):
        return "artifactory"
    return None


def _http_head_or_get_headers(
    url: str, headers: Optional[Dict[str, str]] = None
) -> Tuple[Optional[int], Any]:
    """One-shot GET returning ``(status, headers)`` for manager detection.

    Uses the shared SSL/proxy stack via ``_urlopen`` but skips the retry layer —
    detection must be cheap and fail-open. Never raises.
    """
    try:
        _assert_http_url(url)
        req = urllib.request.Request(url, headers=headers or _make_headers())
        try:
            with _urlopen(req, timeout=HTTP_TIMEOUT_EXTERNAL) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                return int(status), getattr(resp, "headers", None)
        except urllib.error.HTTPError as e:
            return int(e.code), getattr(e, "headers", None)
    except Exception:
        return None, None


def detect_repository_manager(
    base_url: str,
    preferred: Optional[str] = None,
    probe: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Detect ``nexus`` / ``artifactory`` from override, URL shape, headers, or probe.

    Probe (when still unknown): Nexus ``/service/rest/v1/status`` then Artifactory
    ``/api/system/ping``, preferring ``X-Nexus-*`` / ``X-JFrog-*`` response headers
    when present. Failures degrade to None — never raise.
    """
    if preferred in ("nexus", "artifactory"):
        return preferred
    kind = _detect_manager_from_url(base_url)
    if kind:
        return kind
    if not probe:
        return None
    try:
        nexus_url = _nexus_api_root(base_url) + "/service/rest/v1/status"
        status, resp_headers = _http_head_or_get_headers(nexus_url, headers)
        hdr_kind = _detect_manager_from_headers(resp_headers)
        if hdr_kind:
            return hdr_kind
        if status == 200:
            return "nexus"
        art_url = _artifactory_api_root(base_url) + "/api/system/ping"
        status, resp_headers = _http_head_or_get_headers(art_url, headers)
        hdr_kind = _detect_manager_from_headers(resp_headers)
        if hdr_kind:
            return hdr_kind
        if status == 200:
            return "artifactory"
    except Exception:
        return None
    return None


def _search_auth_headers(base_url: str) -> Dict[str, str]:
    """UA (+ optional Authorization) for manager search against ``base_url`` (#291)."""
    host = _repo_host(base_url) or base_url
    entry = {"name": host, "url": base_url}
    return _repo_request_headers(entry)


def _parse_gav_query(query: str) -> Tuple[Optional[str], Optional[str]]:
    """Split ``group:artifact`` / ``g:a:v`` into (groupId, artifactId); else (None, None)."""
    q = query.strip()
    if ":" not in q:
        return None, None
    parts = [p.strip() for p in q.split(":")]
    if len(parts) >= 2 and parts[0] and parts[1]:
        # Reject bare Solr-style field queries like ``g:io.ktor`` only when the
        # left side is a single-letter Solr field — treat those as keyword.
        if len(parts[0]) == 1 and parts[0].isalpha():
            return None, None
        return parts[0], parts[1]
    return None, None


def _aggregate_ga_versions(
    rows: List[Tuple[str, str, str]],
    limit: int,
) -> List[Dict[str, Any]]:
    """Collapse (groupId, artifactId, version) rows into SearchArtifact dicts."""
    buckets: Dict[Tuple[str, str], List[str]] = {}
    order: List[Tuple[str, str]] = []
    for g, a, v in rows:
        if not g or not a:
            continue
        key = (g, a)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        if v and v not in buckets[key]:
            buckets[key].append(v)
    out: List[Dict[str, Any]] = []
    for key in order:
        versions = buckets[key]
        # Prefer semver-ish ordering via compare_versions when possible.
        try:
            versions_sorted = sorted(
                versions, key=functools.cmp_to_key(compare_versions)
            )
        except Exception:
            versions_sorted = list(versions)
        latest = find_latest_version(versions_sorted) if versions_sorted else ""
        out.append(
            {
                "groupId": key[0],
                "artifactId": key[1],
                "latestVersion": latest or (versions_sorted[-1] if versions_sorted else ""),
                "versionCount": len(versions_sorted),
            }
        )
        if len(out) >= limit:
            break
    return out


def _map_nexus_search_items(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    rows: List[Tuple[str, str, str]] = []
    for item in items:
        g = str(item.get("group") or "")
        a = str(item.get("name") or "")
        v = str(item.get("version") or "")
        rows.append((g, a, v))
    return _aggregate_ga_versions(rows, limit)


def search_nexus(
    base_url: str,
    query: str,
    limit: int = 10,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Search Nexus 3 ``GET /service/rest/v1/search`` (format=maven2)."""
    root = _nexus_api_root(base_url)
    g, a = _parse_gav_query(query)
    params: List[Tuple[str, str]] = [("format", "maven2")]
    if g and a:
        params.append(("maven.groupId", g))
        params.append(("maven.artifactId", a))
    else:
        # Free-text ``q`` plus name match — Nexus accepts either; ``q`` covers
        # keyword discovery that GAV filters cannot.
        params.append(("q", query))
        params.append(("name", query))
    url = root + "/service/rest/v1/search?" + urllib.parse.urlencode(params)
    hdrs = headers if headers is not None else _search_auth_headers(base_url)
    try:
        status, body = http_get(url, hdrs)
        if status != 200:
            return []
        data = json.loads(body)
        items = data.get("items") or []
        if not isinstance(items, list):
            return []
        return _map_nexus_search_items(items, limit)
    except Exception:
        return []


def _parse_artifactory_storage_uri(uri: str) -> Optional[Tuple[str, str, str]]:
    """Extract (groupId, artifactId, version) from an Artifactory storage/download URI."""
    if not uri:
        return None
    try:
        path = urllib.parse.urlsplit(uri).path or uri
    except ValueError:
        path = uri
    # .../repoKey/group/path/artifact/version/file
    # Strip /artifactory/api/storage/ or /artifactory/
    for marker in ("/api/storage/", "/artifactory/"):
        idx = path.lower().find(marker)
        if idx >= 0:
            path = path[idx + len(marker) :]
            break
    parts = [p for p in path.split("/") if p]
    if len(parts) < 4:
        return None
    # parts[0] = repoKey; then group dirs...; artifactId; version; filename
    version = parts[-2]
    artifact_id = parts[-3]
    group_parts = parts[1:-3]
    if not group_parts:
        return None
    group_id = ".".join(group_parts)
    return group_id, artifact_id, version


def _map_artifactory_gavc_results(payload: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    rows: List[Tuple[str, str, str]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri") or item.get("downloadUri") or item.get("downloadUrl") or ""
        parsed = _parse_artifactory_storage_uri(str(uri))
        if parsed:
            rows.append(parsed)
            continue
        # specific=true style may omit path group — skip incomplete rows
    return _aggregate_ga_versions(rows, limit)


def _map_artifactory_aql_results(payload: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    rows: List[Tuple[str, str, str]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        # AQL item: repo, path, name, ...
        path = str(item.get("path") or "")
        name = str(item.get("name") or "")
        repo = str(item.get("repo") or "repo")
        fake = f"https://example.invalid/artifactory/api/storage/{repo}/{path}/{name}"
        parsed = _parse_artifactory_storage_uri(fake)
        if parsed:
            rows.append(parsed)
    return _aggregate_ga_versions(rows, limit)


def _aql_escape(value: str) -> str:
    """Escape a value for inclusion in an AQL string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def search_artifactory(
    base_url: str,
    query: str,
    limit: int = 10,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Search Artifactory via GAVC (coordinate) or AQL (keyword)."""
    root = _artifactory_api_root(base_url)
    hdrs = headers if headers is not None else _search_auth_headers(base_url)
    g, a = _parse_gav_query(query)
    try:
        if g and a:
            params = urllib.parse.urlencode({"g": g, "a": a})
            url = f"{root}/api/search/gavc?{params}"
            status, body = http_get(url, hdrs)
            if status != 200:
                return []
            return _map_artifactory_gavc_results(json.loads(body), limit)
        # Keyword: match artifact name (and path segment) via AQL.
        esc = _aql_escape(query)
        # Bound result fan-out — Wave 0: never unbounded. Fetch extra rows so
        # GA aggregation still fills ``limit`` after collapsing versions.
        aql_limit = max(limit * 5, limit)
        aql = (
            'items.find({"$or":[{"name":{"$match":"*%s*"}},'
            '{"path":{"$match":"*%s*"}}]}).include("name","repo","path")'
            ".limit(%d)" % (esc, esc, aql_limit)
        )
        url = f"{root}/api/search/aql"
        status, body = http_post_bytes(
            url, aql.encode("utf-8"), "text/plain", headers=hdrs
        )
        if status != 200:
            return []
        return _map_artifactory_aql_results(json.loads(body), limit)
    except Exception:
        return []


def search_artifacts_with_backend(
    query: str,
    limit: int,
    ctx: "ResolutionContext",
    repository_type: str = "auto",
) -> Dict[str, Any]:
    """Route ``search_artifacts`` to Solr / Nexus / Artifactory.

    Returns ``{results, searchBackend?}`` or empty results with
    ``searchBackendUnavailable`` when no usable backend exists (non-fatal).
    """
    rtype = _normalize_search_backend(repository_type)
    base = _search_manager_base(ctx)
    closed = _closed_search_mode(ctx)

    def _unavailable(msg: str) -> Dict[str, Any]:
        return {"results": [], "searchBackendUnavailable": msg}

    # Explicit central — public Solr (unless offline with no override path).
    if rtype == "central":
        if ctx.offline:
            return _unavailable(
                "search backend not available: Maven Central Solr unreachable in offline mode"
            )
        results, capability = _search_maven_central_with_capability(query, limit)
        return _with_capability(
            {"results": results, "searchBackend": "central"}, capability
        )

    # Explicit nexus / artifactory require a manager base URL.
    if rtype in ("nexus", "artifactory"):
        if not base:
            return _unavailable(
                "search backend not available: set MAVEN_MCP_REPOSITORY_BASE "
                f"(or a settings.xml mirror) for repositoryType={rtype}"
            )
        hdrs = _search_auth_headers(base)
        if rtype == "nexus":
            return {
                "results": search_nexus(base, query, limit, hdrs),
                "searchBackend": "nexus",
            }
        return {
            "results": search_artifactory(base, query, limit, hdrs),
            "searchBackend": "artifactory",
        }

    # auto: public mode → Solr; closed mode → detect manager.
    if not closed:
        results, capability = _search_maven_central_with_capability(query, limit)
        return _with_capability(
            {"results": results, "searchBackend": "central"}, capability
        )

    if not base:
        return _unavailable(
            "search backend not available: offline/closed mode without "
            "MAVEN_MCP_REPOSITORY_BASE or a settings.xml mirror"
        )

    hdrs = _search_auth_headers(base)
    kind = detect_repository_manager(base, preferred=None, probe=True, headers=hdrs)
    if kind == "nexus":
        return {
            "results": search_nexus(base, query, limit, hdrs),
            "searchBackend": "nexus",
        }
    if kind == "artifactory":
        return {
            "results": search_artifactory(base, query, limit, hdrs),
            "searchBackend": "artifactory",
        }
    return _unavailable(
        "search backend not available: could not detect Nexus or Artifactory "
        "from the repository base (set repositoryType=nexus|artifactory)"
    )


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

    return {"libraries": libraries, "plugins": plugins, "versions": versions}



# ---------------------------------------------------------------------------
# Version catalog generate / validate (#288)
# ---------------------------------------------------------------------------
# Gradle version catalogs have strict, error-prone rules (no native update
# command). Agents editing gradle/libs.versions.toml by hand routinely break
# kebab→camel accessors, reserved alias segments, and plugin DSL usage.
# catalog_entry generates rule-correct entries and validates existing TOML.

# Alias shape from Gradle docs: [a-z]([a-zA-Z0-9_.\-])*
_CATALOG_ALIAS_RE = re.compile(r"^[a-z]([a-zA-Z0-9_.\-]*)$")
# Fully reserved alias names (any section).
_CATALOG_RESERVED_NAMES = frozenset({"extensions", "class", "convention"})
# Cannot be the first subgroup of a library/plugin alias (Gradle docs).
_CATALOG_RESERVED_FIRST_SEGMENTS = frozenset({"bundles", "versions", "plugins"})
# Conventional default catalog path (Gradle auto-imports this file).
_DEFAULT_CATALOG_PATH = "gradle/libs.versions.toml"


def _catalog_alias_segments(alias: str) -> List[str]:
    """Split a catalog alias into accessor segments.

    Dashes, underscores, and dots become segment boundaries. camelCase stays
    as a single segment (Gradle's way to avoid nested subgroup accessors —
    ``groovyCore`` → ``libs.groovyCore``, not ``libs.groovy.core``).
    """
    parts = re.split(r"[-_.]+", alias)
    return [p for p in parts if p]


def _catalog_normalize_accessor_key(alias: str) -> str:
    """Normalize alias to the type-safe accessor key (dot form, camelCase kept)."""
    return ".".join(_catalog_alias_segments(alias))


def _catalog_clash_key(alias: str) -> str:
    """Normalized key used to detect accessor name clashes.

    Gradle treats ``someAlias`` and ``some-alias`` as the same accessor
    (troubleshooting: accessor name clashes). Clash detection therefore splits
    camelCase in addition to ``-``/``_``/``.``, then lowercases — unlike the
    emitted accessor string, which preserves camelCase segments.
    """
    segments: List[str] = []
    for part in _catalog_alias_segments(alias):
        camel_bits = re.sub(r"([a-z0-9])([A-Z])", r"\1\n\2", part).split("\n")
        segments.extend(b.lower() for b in camel_bits if b)
    return ".".join(segments)


def _to_kebab_catalog_alias(raw: str) -> str:
    """Convert an artifactId / plugin-id fragment into a kebab-case alias."""
    s = raw.strip()
    # Split dotted plugin ids / group-ish names on dots first.
    s = s.replace(".", "-")
    # camelCase / PascalCase → kebab
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s)
    s = s.replace("_", "-")
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-").lower()
    # Alias must start with a letter.
    s = re.sub(r"^[^a-z]+", "", s)
    s = re.sub(r"[^a-z0-9_.\-]", "", s)
    return s


def _rewrite_reserved_catalog_alias(value: str) -> str:
    """Rewrite reserved whole-alias names and reserved first subgroups.

    ``extensions`` / ``class`` / ``convention`` are reserved as full alias names
    (Gradle docs). ``bundles`` / ``versions`` / ``plugins`` cannot be the first
    subgroup — ``versions-dependency`` becomes ``versionsDependency``.
    """
    if not value:
        return "lib"
    segs = _catalog_alias_segments(value)
    if not segs:
        return "lib"
    if value in _CATALOG_RESERVED_NAMES or value.lower() in _CATALOG_RESERVED_NAMES:
        return f"dep-{value}"
    if segs[0].lower() in _CATALOG_RESERVED_FIRST_SEGMENTS:
        if len(segs) == 1:
            return f"dep-{segs[0]}"
        rest = "".join(s[:1].upper() + s[1:] for s in segs[1:])
        return segs[0] + rest
    return value


def _sanitize_catalog_alias(alias: str, existing: Optional[set] = None) -> str:
    """Ensure alias is valid: format, reserved names/segments, unique."""
    existing = existing or set()
    candidate = _rewrite_reserved_catalog_alias(alias or "lib")
    # Enforce alias regex; fall back to stripped kebab.
    if not _CATALOG_ALIAS_RE.match(candidate):
        candidate = _to_kebab_catalog_alias(candidate) or "lib"
        if not _CATALOG_ALIAS_RE.match(candidate):
            candidate = "lib"
        candidate = _rewrite_reserved_catalog_alias(candidate)
        if not _CATALOG_ALIAS_RE.match(candidate):
            candidate = "lib"
    # Uniqueness against existing aliases (clash-key aware).
    base = candidate
    n = 2
    existing_norm = {_catalog_clash_key(a) for a in existing}
    while candidate in existing or _catalog_clash_key(candidate) in existing_norm:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _suggest_library_alias(group_id: str, artifact_id: str, existing: Optional[set] = None) -> str:
    raw = _to_kebab_catalog_alias(artifact_id) or _to_kebab_catalog_alias(group_id.split(".")[-1])
    return _sanitize_catalog_alias(raw, existing)


def _suggest_plugin_alias(plugin_id: str, existing: Optional[set] = None) -> str:
    parts = [p for p in plugin_id.split(".") if p]
    if len(parts) >= 2:
        raw = _to_kebab_catalog_alias("-".join(parts[-2:]))
    else:
        raw = _to_kebab_catalog_alias(plugin_id)
    return _sanitize_catalog_alias(raw, existing)


def _library_accessor(alias: str, catalog_name: str = "libs") -> str:
    return f"{catalog_name}.{_catalog_normalize_accessor_key(alias)}"


def _plugin_accessor(alias: str, catalog_name: str = "libs") -> str:
    # Plugins MUST be applied via alias(...), never id(libs.plugins...).
    return f"alias({catalog_name}.plugins.{_catalog_normalize_accessor_key(alias)})"


def _plugin_id_from_coordinate(group_id: str, artifact_id: str) -> str:
    """Derive a Gradle plugin id from a Maven-ish coordinate."""
    if artifact_id.endswith(".gradle.plugin"):
        # Marker artifact: {id}:{id}.gradle.plugin
        return group_id
    if artifact_id == group_id:
        return group_id
    # Prefer a dotted artifactId when it looks like a plugin id.
    if "." in artifact_id and not artifact_id.endswith((".jar", ".pom")):
        return artifact_id
    return group_id


def _extract_version_refs(content: str) -> List[Dict[str, str]]:
    """Return raw version.ref usages with section + alias (unresolved)."""
    refs: List[Dict[str, str]] = []
    for section in ("libraries", "plugins"):
        m = re.search(rf"\[{section}\]([\s\S]*?)(?=\n\[|$)", content)
        if not m:
            continue
        for lm in re.finditer(r"^(\S+)\s*=\s*\{([^}]+)\}", m.group(1), re.MULTILINE):
            alias = lm.group(1)
            vref = re.search(r'version\.ref\s*=\s*"([^"]+)"', lm.group(2))
            if vref:
                refs.append({"section": section, "alias": alias, "versionRef": vref.group(1)})
    return refs


def _validate_alias_name(alias: str, section: str) -> List[Dict[str, str]]:
    """Validate one catalog alias; return violation dicts."""
    violations: List[Dict[str, str]] = []
    if not _CATALOG_ALIAS_RE.match(alias):
        violations.append({
            "rule": "invalid_alias_format",
            "detail": (
                f"{section} alias {alias!r} does not match "
                f"[a-z]([a-zA-Z0-9_.-])* required by Gradle version catalogs"
            ),
        })
    if alias in _CATALOG_RESERVED_NAMES or alias.lower() in _CATALOG_RESERVED_NAMES:
        violations.append({
            "rule": "reserved_alias",
            "detail": (
                f"{section} alias {alias!r} is reserved "
                f"(extensions/class/convention cannot be used as aliases)"
            ),
        })
    segs = _catalog_alias_segments(alias)
    if segs and segs[0].lower() in _CATALOG_RESERVED_FIRST_SEGMENTS:
        violations.append({
            "rule": "reserved_first_segment",
            "detail": (
                f"{section} alias {alias!r} starts with reserved subgroup "
                f"{segs[0]!r}; bundles/versions/plugins cannot be the first "
                f"segment (use e.g. versionsDependency or dependency-versions)"
            ),
        })
    return violations


def generate_catalog_entry(
    group_id: str,
    artifact_id: str,
    version: Optional[str] = None,
    kind: str = "library",
    catalog_toml: Optional[str] = None,
    catalog_name: str = "libs",
    alias: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a rule-correct catalog entry + minimal diff suggestion (#288)."""
    kind = kind if kind in ("library", "plugin") else "library"
    parsed = _parse_toml_catalog(catalog_toml or "")
    existing_lib = set(parsed.get("libraries") or {})
    existing_plugin = set(parsed.get("plugins") or {})
    existing_versions = set((parsed.get("versions") or {}).keys())
    existing = existing_plugin if kind == "plugin" else existing_lib

    # Preferred alias before uniqueness suffix — used to detect version bumps
    # against an existing catalog entry (do not invent alias-2 when bumping).
    if kind == "plugin":
        plugin_id = _plugin_id_from_coordinate(group_id, artifact_id)
        preferred_raw = alias or _to_kebab_catalog_alias(
            "-".join([p for p in plugin_id.split(".") if p][-2:])
            if len([p for p in plugin_id.split(".") if p]) >= 2
            else plugin_id
        )
    else:
        plugin_id = None
        preferred_raw = alias or (
            _to_kebab_catalog_alias(artifact_id)
            or _to_kebab_catalog_alias(group_id.split(".")[-1])
        )
    preferred = _sanitize_catalog_alias(preferred_raw, existing=set())
    bump_existing = bool(catalog_toml and version and preferred in existing)
    chosen = preferred if bump_existing else _sanitize_catalog_alias(preferred_raw, existing)

    if kind == "plugin":
        accessor = _plugin_accessor(chosen, catalog_name)
        version_key = _sanitize_catalog_alias(
            _to_kebab_catalog_alias(chosen) or chosen, existing_versions
        )
        if version:
            lib_line = f'{chosen} = {{ id = "{plugin_id}", version.ref = "{version_key}" }}'
            ver_line = f'{version_key} = "{version}"'
            entry_toml = f"[versions]\n{ver_line}\n\n[plugins]\n{lib_line}\n"
            suggested = (
                f"# Minimal addition to {_DEFAULT_CATALOG_PATH}\n"
                f"[versions]\n{ver_line}\n\n[plugins]\n{lib_line}\n\n"
                f"# Apply in plugins {{ }} with:\n# {accessor}\n"
                f"# Do NOT write id({catalog_name}.plugins.{_catalog_normalize_accessor_key(chosen)})\n"
            )
        else:
            lib_line = f'{chosen} = {{ id = "{plugin_id}" }}'
            ver_line = None
            entry_toml = f"[plugins]\n{lib_line}\n"
            suggested = (
                f"# Minimal addition to {_DEFAULT_CATALOG_PATH}\n"
                f"[plugins]\n{lib_line}\n\n"
                f"# Apply in plugins {{ }} with:\n# {accessor}\n"
            )
        entry = {
            "section": "plugins",
            "alias": chosen,
            "id": plugin_id,
            "version": version,
            "versionRef": version_key if version else None,
            "tomlLine": lib_line,
            "versionLine": ver_line,
        }
    else:
        accessor = _library_accessor(chosen, catalog_name)
        version_key = _sanitize_catalog_alias(
            _to_kebab_catalog_alias(chosen) or chosen, existing_versions
        )
        module = f"{group_id}:{artifact_id}"
        if version:
            lib_line = f'{chosen} = {{ module = "{module}", version.ref = "{version_key}" }}'
            ver_line = f'{version_key} = "{version}"'
            entry_toml = f"[versions]\n{ver_line}\n\n[libraries]\n{lib_line}\n"
            suggested = (
                f"# Minimal addition to {_DEFAULT_CATALOG_PATH}\n"
                f"[versions]\n{ver_line}\n\n[libraries]\n{lib_line}\n\n"
                f"# Use in dependencies {{ }}:\n# implementation({accessor})\n"
            )
        else:
            lib_line = f'{chosen} = {{ module = "{module}" }}'
            ver_line = None
            entry_toml = f"[libraries]\n{lib_line}\n"
            suggested = (
                f"# Minimal addition to {_DEFAULT_CATALOG_PATH}\n"
                f"[libraries]\n{lib_line}\n\n"
                f"# Use in dependencies {{ }}:\n# implementation({accessor})\n"
            )
        entry = {
            "section": "libraries",
            "alias": chosen,
            "groupId": group_id,
            "artifactId": artifact_id,
            "version": version,
            "versionRef": version_key if version else None,
            "tomlLine": lib_line,
            "versionLine": ver_line,
        }

    # If the alias already exists in the provided catalog, prefer a version-only bump.
    if bump_existing:
        bump_lines = []
        # Prefer bumping version.ref target when present in raw TOML.
        section = "plugins" if kind == "plugin" else "libraries"
        raw_refs = [r for r in _extract_version_refs(catalog_toml) if r["alias"] == chosen and r["section"] == section]
        if raw_refs:
            vref = raw_refs[0]["versionRef"]
            bump_lines.append(f'# Update existing [versions] key only\n{vref} = "{version}"')
            suggested = "\n".join(bump_lines) + "\n"
            entry["updateKind"] = "version_ref_bump"
            entry["versionRef"] = vref
        else:
            # Inline version in the table/shorthand — replace just the version literal on that alias line.
            bump_lines.append(f"# Update version on existing [{section}] alias {chosen!r}")
            bump_lines.append(entry["tomlLine"])
            suggested = "\n".join(bump_lines) + "\n"
            entry["updateKind"] = "inline_or_line_replace"
        entry["tomlSnippet"] = suggested
    else:
        entry["updateKind"] = "add"
        entry["tomlSnippet"] = entry_toml

    # Report when a caller-supplied alias had to be rewritten; chosen alias is
    # always rule-correct so we do not re-emit validate findings against it.
    alias_violations: List[Dict[str, str]] = []
    if alias and alias != chosen:
        alias_violations.append({
            "rule": "alias_sanitized",
            "detail": f"requested alias {alias!r} was adjusted to valid alias {chosen!r}",
        })
        alias_violations.extend(_validate_alias_name(alias, entry["section"]))

    return {
        "alias": chosen,
        "accessor": accessor,
        "entry": entry,
        "suggestedDiff": suggested,
        "violations": alias_violations,
        "catalogPath": _DEFAULT_CATALOG_PATH,
        "notes": [
            "Gradle has no built-in command to update version catalogs; apply the minimal diff manually.",
            "Plugin catalog entries must be applied with alias(libs.plugins.*), never id(libs.plugins.*).",
            "Type-safe catalog accessors are not available inside subprojects {} or buildscript {} blocks.",
        ],
    }


def validate_catalog(
    catalog_toml: str,
    build_content: Optional[str] = None,
    catalog_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate catalog TOML (+ optional build script text) against Gradle rules (#288)."""
    violations: List[Dict[str, str]] = []
    if catalog_path:
        norm = catalog_path.replace("\\", "/").lstrip("./")
        base = os.path.basename(norm)
        # Default catalog must be exactly gradle/libs.versions.toml; other
        # *.versions.toml files are valid only when registered in settings.
        if base == "libs.versions.toml" and norm != _DEFAULT_CATALOG_PATH and not norm.endswith(
            "/" + _DEFAULT_CATALOG_PATH
        ):
            violations.append({
                "rule": "catalog_path",
                "detail": (
                    f"default catalog filename must be {_DEFAULT_CATALOG_PATH!r} "
                    f"(Gradle auto-imports only that path); got {catalog_path!r}"
                ),
            })
        elif not base.endswith(".versions.toml"):
            violations.append({
                "rule": "catalog_path",
                "detail": (
                    f"catalog file {catalog_path!r} should use a "
                    f"*.versions.toml basename (convention: {_DEFAULT_CATALOG_PATH})"
                ),
            })

    parsed = _parse_toml_catalog(catalog_toml or "")
    versions = parsed.get("versions") or {}
    libraries = parsed.get("libraries") or {}
    plugins = parsed.get("plugins") or {}

    for alias in libraries:
        violations.extend(_validate_alias_name(alias, "libraries"))
    for alias in plugins:
        violations.extend(_validate_alias_name(alias, "plugins"))
    for alias in versions:
        # Version aliases share the same naming rules / reserved words.
        violations.extend(_validate_alias_name(alias, "versions"))

    # Accessor clashes: someAlias vs some-alias share one clash key.
    for section_name, table in (("libraries", libraries), ("plugins", plugins), ("versions", versions)):
        by_key: Dict[str, List[str]] = {}
        for alias in table:
            by_key.setdefault(_catalog_clash_key(alias), []).append(alias)
        for key, aliases in by_key.items():
            if len(aliases) > 1:
                violations.append({
                    "rule": "accessor_clash",
                    "detail": (
                        f"{section_name} aliases {aliases!r} normalize to the same "
                        f"accessor clash key {key!r}"
                    ),
                })

    for ref in _extract_version_refs(catalog_toml or ""):
        if ref["versionRef"] not in versions:
            violations.append({
                "rule": "undefined_version_ref",
                "detail": (
                    f"{ref['section']} alias {ref['alias']!r} references missing "
                    f"version {ref['versionRef']!r}"
                ),
            })

    if build_content:
        # id(libs.plugins.x) is invalid — must use alias(libs.plugins.x).
        for m in re.finditer(
            r"\bid\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\.plugins\.([a-zA-Z0-9.]+)\s*\)",
            build_content,
        ):
            catalog = m.group(1)
            plugin_acc = m.group(2)
            violations.append({
                "rule": "plugin_id_accessor_misuse",
                "detail": (
                    f"found id({catalog}.plugins.{plugin_acc}) — use "
                    f"alias({catalog}.plugins.{plugin_acc}) instead"
                ),
            })
        # Catalog accessors are not available in subprojects { } / buildscript { }.
        for block_name in ("subprojects", "buildscript"):
            pos = 0
            while True:
                found = _find_block(build_content, block_name, pos)
                if not found:
                    break
                body, _start, end = found
                if re.search(r"\blibs\.[a-zA-Z_]", body) or re.search(
                    r"\balias\s*\(\s*libs\.", body
                ):
                    violations.append({
                        "rule": "libs_accessor_unavailable_in_block",
                        "detail": (
                            f"type-safe libs accessors are not available inside "
                            f"{block_name} {{ }}; move catalog usage to the root "
                            f"project or a regular subproject build script"
                        ),
                    })
                    break
                pos = end

    return {
        "violations": violations,
        "aliasCount": {
            "versions": len(versions),
            "libraries": len(libraries),
            "plugins": len(plugins),
        },
        "catalogPath": catalog_path or _DEFAULT_CATALOG_PATH,
    }


def handle_catalog_entry(args: Dict) -> Any:
    """MCP handler for catalog_entry (#288) — generate or validate catalog edits."""
    mode = args.get("mode") or "generate"
    if mode not in ("generate", "validate"):
        return {
            "error": f"mode must be 'generate' or 'validate', got {mode!r}",
            "violations": [{"rule": "invalid_mode", "detail": f"unsupported mode {mode!r}"}],
        }

    catalog_toml = args.get("catalogToml")
    if catalog_toml is not None and not isinstance(catalog_toml, str):
        catalog_toml = str(catalog_toml)

    if mode == "validate":
        build_content = args.get("buildContent")
        if build_content is not None and not isinstance(build_content, str):
            build_content = str(build_content)
        catalog_path = args.get("catalogPath")
        if not catalog_toml and args.get("projectPath"):
            # Convenience: read default catalog from project when TOML omitted.
            root = args.get("projectPath") or os.getcwd()
            candidate = os.path.join(root, _DEFAULT_CATALOG_PATH)
            if os.path.isfile(candidate):
                with open(candidate, encoding="utf-8") as fh:
                    catalog_toml = fh.read()
                catalog_path = catalog_path or _DEFAULT_CATALOG_PATH
        if catalog_toml is None:
            return {
                "error": "validate mode requires catalogToml (or a projectPath with gradle/libs.versions.toml)",
                "violations": [{
                    "rule": "missing_catalog",
                    "detail": "catalogToml is required for validate when the default catalog file is absent",
                }],
            }
        return validate_catalog(catalog_toml, build_content=build_content, catalog_path=catalog_path)

    # generate
    coord = args.get("coordinate") or {}
    if not isinstance(coord, dict):
        return {
            "error": "coordinate must be an object with groupId and artifactId",
            "violations": [{"rule": "missing_coordinate", "detail": "coordinate is required for generate"}],
        }
    group_id = coord.get("groupId")
    artifact_id = coord.get("artifactId")
    version = coord.get("version")
    if not group_id or not artifact_id:
        return {
            "error": "coordinate.groupId and coordinate.artifactId are required for generate",
            "violations": [{"rule": "missing_coordinate", "detail": "groupId and artifactId are required"}],
        }
    kind = args.get("kind") or "library"
    return generate_catalog_entry(
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
        kind=kind if isinstance(kind, str) else "library",
        catalog_toml=catalog_toml,
        catalog_name=args.get("catalogName") or "libs",
        alias=args.get("alias"),
    )


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


# Env var prefixes/names that must never reach a scanned project's OWN
# subprocess (Gradle build scripts run arbitrary code that can read
# System.getenv() — GHSA-4778-r7hp-92v7). Denylist, not an allowlist, so
# JAVA_HOME/GRADLE_USER_HOME/ANDROID_HOME/PATH/locale and everything else
# Gradle needs stays intact.
_SECRET_ENV_EXACT = frozenset({"GITHUB_TOKEN"})
_SECRET_ENV_PREFIXES = (_CRED_ENV_PREFIX,)  # "MAVEN_REPO_" (#291 creds + host pins)


def _is_secret_env_key(key: str) -> bool:
    if key in _SECRET_ENV_EXACT:
        return True
    return any(key.startswith(prefix) for prefix in _SECRET_ENV_PREFIXES)


# HTTP(S)_PROXY / ALL_PROXY routinely embed `user:pass@host` (#298). Unlike
# MAVEN_REPO_*/GITHUB_TOKEN these are NOT dropped wholesale — Gradle's own
# network access legitimately needs the proxy host:port — only the userinfo
# is redacted (R2a, same leak class as GHSA-4778-r7hp-92v7: a scanned
# project's build script reading System.getenv("HTTPS_PROXY") would
# otherwise exfiltrate the proxy password).
_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)


def _redact_env_userinfo(env: Dict[str, str]) -> Dict[str, str]:
    """Return a COPY of ``env`` with userinfo stripped from proxy vars and any
    ``MAVEN_MCP_*`` var that carries a URL (e.g. ``MAVEN_MCP_REPOSITORY_BASE``),
    via the existing ``_strip_userinfo`` (redacts to ``***@host``, keeping
    host:port intact — never drops the var, since Gradle needs the address
    even without the credential)."""
    out = dict(env)
    for key in _PROXY_ENV_KEYS:
        val = out.get(key)
        if val and "@" in val:
            out[key] = _strip_userinfo(val)
    for key in out:
        if key.startswith("MAVEN_MCP_") and out[key] and "@" in out[key]:
            out[key] = _strip_userinfo(out[key])
    return out


def _scrubbed_subprocess_env() -> Dict[str, str]:
    """``os.environ`` with credential-bearing vars removed, for spawning the
    scanned project's own Gradle wrapper (GHSA-4778-r7hp-92v7): the wrapper
    executes the project's OWN build scripts (including buildSrc/convention
    plugins), which could otherwise read MAVEN_REPO_*_TOKEN / GITHUB_TOKEN via
    System.getenv() and exfiltrate them (e.g. through a plugin/dependency
    fetch to an attacker URL). Proxy/MAVEN_MCP_* userinfo is additionally
    redacted (R2a) rather than dropped — see ``_redact_env_userinfo``."""
    scrubbed = {k: v for k, v in os.environ.items() if not _is_secret_env_key(k)}
    return _redact_env_userinfo(scrubbed)


_gradle_run = subprocess.run


def _find_gradle_wrapper(project_root: str) -> Optional[str]:
    for name in ("gradlew", "gradlew.bat"):
        path = os.path.join(project_root, name)
        if os.path.isfile(path):
            return path
    return None


def _gradle_cli_prefix_args() -> List[str]:
    """CLI flags prepended to every Gradle wrapper invocation."""
    if _offline_enabled():
        return ["--offline"]
    return []


def _run_gradle_command(
    project_root: str,
    gradlew: str,
    args: List[str],
    timeout: int = GRADLE_RESOLVE_TIMEOUT,
) -> Tuple[int, str, str]:
    try:
        result = _gradle_run(
            [gradlew] + _gradle_cli_prefix_args() + args,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_scrubbed_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"Gradle command timed out after {timeout}s"
    return result.returncode, result.stdout or "", result.stderr or ""


def _parse_gav_from_dependency_line(token: str) -> Optional[Tuple[str, str, str]]:
    token = token.strip()
    token = re.sub(r"\s*\([cn*]\)\s*$", "", token).strip()
    if not token or token.startswith("project "):
        return None
    if " -> " in token:
        left, right = token.split(" -> ", 1)
        right = re.sub(r"\s*\([cn*]\)\s*$", "", right).strip()
        left_parts = left.strip().split(":")
        if len(left_parts) < 2:
            return None
        group_id, artifact_id = left_parts[0], left_parts[1]
        if ":" in right:
            right_parts = right.split(":")
            if len(right_parts) >= 3:
                return right_parts[0], right_parts[1], ":".join(right_parts[2:])
        if len(left_parts) >= 3:
            return group_id, artifact_id, right
        return None
    parts = token.split(":")
    if len(parts) >= 3:
        return parts[0], parts[1], ":".join(parts[2:])
    return None


def _parse_gradle_dependencies_stdout(
    stdout: str,
    module_label: Optional[str],
    configuration: str,
) -> List[Dict]:
    deps: List[Dict] = []
    for line in stdout.splitlines():
        m = re.match(r"^(?:\+---|\\---)\s+(.+)$", line)
        if not m:
            continue
        token = m.group(1).strip()
        if re.search(r"\(n\)\s*$", token):
            continue
        gav = _parse_gav_from_dependency_line(token)
        if not gav:
            continue
        group_id, artifact_id, version = gav
        deps.append({
            "groupId": group_id,
            "artifactId": artifact_id,
            "version": version,
            "configuration": configuration,
            "module": module_label,
            "resolvedBy": "gradle",
            "usages": [{"module": module_label, "configuration": configuration}],
        })
    return deps


def _parse_build_environment_classpath(stdout: str) -> List[Dict]:
    deps: List[Dict] = []
    in_classpath = False
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped == "classpath" or stripped.startswith("classpath -"):
            in_classpath = True
            continue
        if not in_classpath:
            continue
        if stripped == "" and deps:
            break
        m = re.match(r"^(?:\+---|\\---)\s+(.+)$", line)
        if not m:
            if deps and not line.startswith("|") and not stripped.startswith("+"):
                break
            continue
        gav = _parse_gav_from_dependency_line(m.group(1))
        if not gav:
            continue
        group_id, artifact_id, version = gav
        deps.append({
            "groupId": group_id,
            "artifactId": artifact_id,
            "version": version,
            "configuration": "classpath",
            "module": None,
            "resolvedBy": "gradle",
            "usages": [{"module": None, "configuration": "classpath"}],
        })
    return deps


def _is_production_runtime_configuration(config: str) -> bool:
    """True for production runtime classpaths; excludes test/compile/classpath."""
    if not config:
        return False
    if _is_test_configuration(config):
        return False
    if config in ("classpath", "compileOnly"):
        return False
    if config == "compileClasspath" or config.endswith("CompileClasspath"):
        return False
    return config.endswith("RuntimeClasspath")


def _parse_gradle_configuration_headers(stdout: str) -> List[str]:
    """Extract configuration names from ``gradlew … dependencies`` probe output."""
    configs: List[str] = []
    seen: set = set()
    for line in stdout.splitlines():
        m = re.match(r"^([A-Za-z][\w\d]*) - ", line)
        if not m:
            continue
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            configs.append(name)
    return configs


def _select_configurations_to_resolve(available: List[str]) -> List[str]:
    """Pick production runtime configurations from a probed Gradle config list."""
    selected = [c for c in available if _is_production_runtime_configuration(c)]
    if not selected:
        return []

    def _sort_key(name: str) -> Tuple[int, str]:
        if name.startswith("release") and name.endswith("RuntimeClasspath"):
            return (0, name)
        if name.endswith("RuntimeClasspath"):
            return (1, name)
        return (2, name)

    selected.sort(key=_sort_key)
    if any(
        c.startswith("release") and c.endswith("RuntimeClasspath")
        for c in selected
    ):
        selected = [c for c in selected if c != "runtimeClasspath"]
    return selected


def _probe_gradle_configurations(
    project_root: str,
    gradlew: str,
    module: str,
) -> Tuple[List[str], Optional[str]]:
    if module == ":":
        args = ["-q", "dependencies"]
        task_label = ":dependencies"
    else:
        args = ["-q", f"{module}:dependencies"]
        task_label = f"{module}:dependencies"
    code, stdout, stderr = _run_gradle_command(project_root, gradlew, args)
    if code != 0:
        msg = f"{task_label} probe exited with code {code}"
        if stderr.strip():
            msg += f": {stderr.strip()}"
        return [], msg
    return _parse_gradle_configuration_headers(stdout), None


def _count_production_runtime_deps(deps: List[Dict]) -> int:
    count = 0
    for dep in deps:
        for usage in dep.get("usages") or []:
            if _is_production_runtime_configuration(usage.get("configuration", "")):
                count += 1
                break
    return count


def _discover_gradle_modules(project_root: str, gradlew: Optional[str] = None) -> List[str]:
    modules = [":"]
    settings_content = None
    for fname in GRADLE_SETTINGS_FILES:
        path = os.path.join(project_root, fname)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                settings_content = fh.read()
            break
    if settings_content:
        for module_path in _parse_settings_modules(settings_content):
            if not module_path.startswith(":"):
                module_path = ":" + module_path
            if module_path not in modules:
                modules.append(module_path)
    if gradlew:
        code, stdout, _stderr = _run_gradle_command(project_root, gradlew, ["-q", "projects"])
        if code == 0:
            for line in stdout.splitlines():
                m = re.search(r"Project '([^']+)'", line)
                if not m:
                    continue
                module_path = m.group(1)
                if not module_path.startswith(":"):
                    module_path = ":" + module_path
                if module_path not in modules:
                    modules.append(module_path)
    return modules


def _dedupe_gradle_resolved_deps(deps: List[Dict]) -> List[Dict]:
    merged: Dict[Tuple[str, str, str], Dict] = {}
    for dep in deps:
        key = (dep["groupId"], dep["artifactId"], dep["version"])
        usage = {
            "module": dep.get("module"),
            "configuration": dep.get("configuration", ""),
        }
        if key in merged:
            usages = merged[key].setdefault("usages", [])
            if usage not in usages:
                usages.append(usage)
        else:
            entry = {
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "version": dep["version"],
                "resolvedBy": "gradle",
                "usages": [usage],
            }
            merged[key] = entry
    return list(merged.values())


def _gradle_resolve_dependencies(project_root: str) -> Dict:
    gradlew = _find_gradle_wrapper(project_root)
    if not gradlew:
        return {
            "dependencies": [],
            "notes": [],
            "errors": ["Gradle wrapper (gradlew) not found"],
        }

    collected: List[Dict] = []
    errors: List[str] = []
    notes: List[str] = []
    attempts = 0
    failures = 0

    for module in _discover_gradle_modules(project_root, gradlew):
        probed, probe_err = _probe_gradle_configurations(project_root, gradlew, module)
        if probe_err:
            errors.append(probe_err)
        configurations = _select_configurations_to_resolve(probed)
        if not configurations:
            configurations = [
                c for c in _GRADLE_RESOLVE_CONFIGURATIONS
                if _is_production_runtime_configuration(c)
            ]

        skip_bare_runtime = False
        module_label = None if module == ":" else module
        for configuration in configurations:
            if configuration == "runtimeClasspath" and skip_bare_runtime:
                continue
            if module == ":":
                args = ["-q", "dependencies", "--configuration", configuration]
                task_label = f":{configuration}"
            else:
                args = ["-q", f"{module}:dependencies", "--configuration", configuration]
                task_label = f"{module}:{configuration}"
            attempts += 1
            code, stdout, stderr = _run_gradle_command(project_root, gradlew, args)
            if code != 0:
                failures += 1
                msg = f"{task_label} exited with code {code}"
                if stderr.strip():
                    msg += f": {stderr.strip()}"
                errors.append(msg)
                continue
            parsed = _parse_gradle_dependencies_stdout(stdout, module_label, configuration)
            collected.extend(parsed)
            if (
                parsed
                and configuration.startswith("release")
                and configuration.endswith("RuntimeClasspath")
            ):
                skip_bare_runtime = True

    attempts += 1
    code, stdout, stderr = _run_gradle_command(project_root, gradlew, ["-q", "buildEnvironment"])
    if code == 0:
        collected.extend(_parse_build_environment_classpath(stdout))
    else:
        failures += 1
        msg = "buildEnvironment exited with code {}".format(code)
        if stderr.strip():
            msg += f": {stderr.strip()}"
        errors.append(msg)

    deduped = _dedupe_gradle_resolved_deps(collected)
    production_count = _count_production_runtime_deps(deduped)
    if production_count == 0:
        if deduped:
            errors.append(
                "No production runtime dependencies resolved; only build classpath/"
                + "plugin dependencies were found"
            )
        elif failures == attempts and attempts > 0:
            notes.append("All Gradle dependency tasks failed.")
        elif not errors:
            notes.append("No production configurations resolved; project may lack applicable variants.")

    return {
        "dependencies": deduped,
        "notes": notes,
        "errors": errors,
        "productionCount": production_count,
    }


def _collect_gradle_provenance(project_root: str) -> Dict:
    """Collect catalog/source provenance from Gradle build files (no resolution)."""
    dependencies: List[Dict] = []
    dead_repo_hints: List[Dict] = []

    settings_result = None
    for f in GRADLE_SETTINGS_FILES:
        p = os.path.join(project_root, f)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                settings_result = {"content": fh.read(), "file": f}
            dead_repo_hints.extend(_detect_dead_repo_hints(settings_result["content"], f, None))
            break

    if settings_result:
        descriptors = _parse_settings_catalogs(settings_result["content"])
        if not descriptors:
            default_toml = os.path.join(project_root, "gradle", "libs.versions.toml")
            if os.path.exists(default_toml):
                descriptors = [{"name": "libs", "tomlPath": "gradle/libs.versions.toml"}]
    else:
        default_toml = os.path.join(project_root, "gradle", "libs.versions.toml")
        descriptors = (
            [{"name": "libs", "tomlPath": "gradle/libs.versions.toml"}]
            if os.path.exists(default_toml)
            else []
        )

    catalogs: Dict[str, Dict] = {}
    for desc in descriptors:
        toml_path = os.path.join(project_root, desc["tomlPath"])
        if not os.path.exists(toml_path):
            continue
        with open(toml_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        catalogs[desc["name"]] = {"tomlPath": desc["tomlPath"], "parsed": _parse_toml_catalog(content)}

    catalog_entry_map: Dict[str, Dict] = {}
    for catalog_name, catalog_data in catalogs.items():
        toml_path = catalog_data["tomlPath"]
        parsed = catalog_data["parsed"]
        for alias, entry in parsed["libraries"].items():
            dep = {
                "groupId": entry["groupId"],
                "artifactId": entry["artifactId"],
                "version": entry["version"],
                "source": {
                    "kind": "catalog-library",
                    "catalogName": catalog_name,
                    "tomlPath": toml_path,
                    "alias": alias,
                },
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
                "source": {
                    "kind": "catalog-plugin",
                    "catalogName": catalog_name,
                    "tomlPath": toml_path,
                    "alias": alias,
                },
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
        return ref[:dot_idx], ref[dot_idx + 1 :]

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
                plugin_alias = alias_path[len(plugins_prefix) :]
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

    modules = _parse_settings_modules(settings_result["content"]) if settings_result else []
    for module_path in modules:
        dir_path = _module_path_to_dir(project_root, module_path)
        for build_file in GRADLE_BUILD_FILES:
            path = os.path.join(dir_path, build_file)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            process_build_file_deps(content, build_file, module_path)
            process_plugins_block(content, build_file, module_path, False)
            dead_repo_hints.extend(_detect_dead_repo_hints(content, build_file, module_path))
            break

    for build_file in GRADLE_BUILD_FILES:
        path = os.path.join(project_root, build_file)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        process_build_file_deps(content, build_file, None)
        process_plugins_block(content, build_file, None, False)
        process_buildscript_classpath(content, build_file)
        dead_repo_hints.extend(_detect_dead_repo_hints(content, build_file, None))
        break

    if settings_result:
        process_plugins_block(settings_result["content"], settings_result["file"], None, True)

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

    return {"dependencies": dependencies, "deadRepositoryHints": dead_repo_hints}


_PROVENANCE_SOURCE_PRIORITY = {
    "catalog-library": 0,
    "catalog-plugin": 1,
    "plugins-dsl": 2,
    "buildscript-classpath": 3,
    "module-direct": 4,
    "buildsrc": 5,
    "convention-plugin": 6,
}


def _pick_best_provenance(candidates: List[Dict]) -> Optional[Dict]:
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda d: _PROVENANCE_SOURCE_PRIORITY.get(
            (d.get("source") or {}).get("kind", ""), 99
        ),
    )


def _merge_gradle_with_provenance(resolved: List[Dict], provenance: List[Dict]) -> List[Dict]:
    prov_by_ga: Dict[Tuple[str, str], List[Dict]] = {}
    for dep in provenance:
        gid, aid = dep.get("groupId"), dep.get("artifactId")
        if gid and aid:
            prov_by_ga.setdefault((gid, aid), []).append(dep)

    merged: List[Dict] = []
    in_output_ga: set = set()
    in_output_catalog: set = set()

    for dep in resolved:
        key = (dep["groupId"], dep["artifactId"])
        entry = {
            "groupId": dep["groupId"],
            "artifactId": dep["artifactId"],
            "version": dep["version"],
            "resolvedBy": "gradle",
            "usages": list(dep.get("usages") or []),
        }
        prov = _pick_best_provenance(prov_by_ga.get(key, []))
        if prov and prov.get("source"):
            source_kind = prov["source"].get("kind", "")
            alias = prov["source"].get("alias")
            prov_usages = prov.get("usages") or []
            attach_catalog = (
                source_kind not in ("catalog-library", "catalog-plugin")
                or bool(prov_usages)
            )
            if attach_catalog:
                entry["source"] = prov["source"]
                if prov.get("isPlatform"):
                    entry["isPlatform"] = True
                    entry["platformKind"] = prov.get("platformKind")
                if source_kind in ("catalog-library", "catalog-plugin") and alias:
                    in_output_catalog.add((source_kind, alias))
            else:
                entry["source"] = {"kind": "gradle-resolved"}
        else:
            entry["source"] = {"kind": "gradle-resolved"}
        merged.append(entry)
        in_output_ga.add(key)

    for prov in provenance:
        gid, aid = prov.get("groupId"), prov.get("artifactId")
        if not gid or not aid:
            continue
        source = prov.get("source") or {}
        kind = source.get("kind", "")
        alias = source.get("alias")
        key = (gid, aid)
        if kind in ("catalog-library", "catalog-plugin"):
            catalog_key = (kind, alias) if alias else (kind, gid, aid)
            if catalog_key in in_output_catalog:
                continue
            entry = {
                "groupId": gid,
                "artifactId": aid,
                "version": prov.get("version"),
                "resolvedBy": "provenance",
                "source": source or {"kind": "unknown"},
                "usages": list(prov.get("usages") or []),
            }
            if prov.get("isPlatform"):
                entry["isPlatform"] = True
                entry["platformKind"] = prov.get("platformKind")
            merged.append(entry)
            in_output_catalog.add(catalog_key)
            continue
        if key in in_output_ga:
            continue
        entry = {
            "groupId": gid,
            "artifactId": aid,
            "version": prov.get("version"),
            "resolvedBy": "provenance",
            "source": source or {"kind": "unknown"},
            "usages": list(prov.get("usages") or []),
        }
        if prov.get("isPlatform"):
            entry["isPlatform"] = True
            entry["platformKind"] = prov.get("platformKind")
        merged.append(entry)
        in_output_ga.add(key)

    return merged


def scan_project(project_root: str) -> Dict:
    """Returns {buildSystem, dependencies: [...ScannedDependency],
    deadRepositoryHints: [...], managedPins: [...]}."""
    build_system = _detect_build_system(project_root)
    dependencies: List[Dict] = []
    dead_repo_hints: List[Dict] = []
    managed_pins: List[Dict] = []

    if build_system == "gradle":
        gradlew = _find_gradle_wrapper(project_root)
        if not gradlew:
            raise ValueError(
                "Gradle project requires a Gradle wrapper (gradlew). "
                "Add the wrapper with `gradle wrapper` or copy gradlew from a template project."
            )
        resolved = _gradle_resolve_dependencies(project_root)
        production_count = resolved.get("productionCount", 0)
        if production_count == 0:
            detail = resolved.get("errors") or resolved.get("notes") or ["no production runtime dependencies resolved"]
            raise ValueError(
                "Gradle dependency resolution failed: " + "; ".join(detail)
            )
        provenance = _collect_gradle_provenance(project_root)
        dependencies = _merge_gradle_with_provenance(
            resolved["dependencies"], provenance["dependencies"]
        )
        for dep in provenance["dependencies"]:
            if dep.get("isPlatform") and dep.get("version"):
                managed_pins.append({
                    "groupId": dep["groupId"],
                    "artifactId": dep["artifactId"],
                    "version": dep["version"],
                    "module": (dep.get("usages") or [{}])[0].get("module"),
                })
        result: Dict[str, Any] = {
            "buildSystem": "gradle",
            "dependencies": dependencies,
            "deadRepositoryHints": provenance.get("deadRepositoryHints", []),
            "managedPins": managed_pins,
            "resolvedBy": "gradle",
            "notes": resolved.get("notes", []),
        }
        if resolved.get("errors"):
            result["gradleErrors"] = resolved["errors"]
        return result

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
            if dep.get("resolvedBy") is not None:
                entry["resolvedBy"] = dep["resolvedBy"]
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
    result = {
        "buildSystem": scan["buildSystem"],
        "dependencies": deps,
        "deadRepositoryHints": scan.get("deadRepositoryHints", []),
    }
    if scan.get("resolvedBy"):
        result["resolvedBy"] = scan["resolvedBy"]
    if scan.get("notes"):
        result["notes"] = scan["notes"]
    if scan.get("gradleErrors"):
        result["gradleErrors"] = scan["gradleErrors"]
    return result


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

    def _check_one(dep: Dict) -> Dict[str, Any]:
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
            return {
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "latestVersion": latest,
                "stability": classify_version(latest),
                "resolvedFrom": resolved_from,
            }
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
            return error_entry

    # #400: bounded parallel fan-out. _map_parallel is index-mapped, so
    # `results` stays in the SAME order as args["dependencies"] regardless of
    # which worker thread finishes first; per-item isolation is unchanged —
    # _check_one still catches its own exceptions exactly as the sequential
    # loop did.
    results, _partial = _map_parallel(args["dependencies"], _check_one)
    return {"results": results}


def handle_compare_dependency_versions(args: Dict) -> Any:
    ctx = build_resolution_context(args)

    def _compare_one(dep: Dict) -> Dict[str, Any]:
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
            return {
                "groupId": dep["groupId"],
                "artifactId": dep["artifactId"],
                "currentVersion": dep["currentVersion"],
                "latestVersion": latest,
                "latestStability": classify_version(latest),
                "upgradeType": upgrade_type,
                "upgradeAvailable": upgrade_type != "none",
                "resolvedFrom": resolved_from,
            }
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
            return error_entry

    # #400: bounded parallel fan-out, order preserved (see
    # handle_check_multiple_dependencies for the same pattern/rationale).
    results, _partial = _map_parallel(args["dependencies"], _compare_one)
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
    if scan.get("resolvedBy") != "gradle":
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

    # #400: marker resolution is a per-dependency POM fetch — parallelize it
    # the same way as the other batch fan-outs. No new try/except is added
    # here: resolve_plugin_marker_implementation is documented as never
    # raising (degrades to None on any failure), matching the original
    # sequential loop, which had none either.
    def _resolve_one(dep: Dict) -> Optional[Dict]:
        return (
            resolve_plugin_marker_implementation(
                dep["groupId"], dep["artifactId"], dep.get("version"), ctx
            )
            if ctx is not None
            else None
        )

    resolutions, _partial = _map_parallel(original_deps, _resolve_one)
    query_deps = [
        resolved if resolved else dep
        for dep, resolved in zip(original_deps, resolutions)
    ]

    # NOTE: unlike handle_audit_project_dependencies, this does not dedupe
    # identical (groupId, artifactId, version) requests before querying OSV —
    # known minor inefficiency, left as a follow-up rather than risking a
    # larger restructure here.
    raw = query_osv_batch(query_deps)
    results = []
    capability: Optional[str] = None
    for i, r in enumerate(raw):
        entry = dict(r)
        if resolutions[i]:
            entry["groupId"] = original_deps[i]["groupId"]
            entry["artifactId"] = original_deps[i]["artifactId"]
            entry["version"] = original_deps[i]["version"]
            entry["resolvedImplementation"] = resolutions[i]
        entry["vulnerabilityCount"] = len(entry["vulnerabilities"])
        safe_upgrade = _compute_safe_upgrade(entry["vulnerabilities"])
        if safe_upgrade is not None:
            entry["safeUpgrade"] = safe_upgrade
        if entry.get("capabilityUnavailable") and capability is None:
            capability = entry["capabilityUnavailable"]
        results.append(entry)
    out: Dict[str, Any] = {"results": results}
    return _with_capability(out, capability)


def handle_get_dependency_health(args: Dict) -> Any:
    ctx = build_resolution_context(args)

    # #400: parallelize the per-dependency fan-out (metadata + POM + GitHub
    # API calls, several per dep). Per-item error handling is preserved
    # EXACTLY as it was in the sequential loop: only the initial
    # fetch_metadata call is guarded by a try/except (as before) — anything
    # raised further down still propagates and fails the whole call, matching
    # the original code, which had no try/except around the rest of the body
    # either. #400 changes performance, not error-handling semantics.
    def _check_one(dep: Dict) -> Dict[str, Any]:
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
            return result
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
        pom_licenses: List[Dict[str, Optional[str]]] = []
        if target_version:
            pom = fetch_pom(group_id, artifact_id, target_version, ctx)
            if pom:
                gh_repo = extract_github_repo_from_pom(pom)
                pom_licenses = extract_licenses_from_pom(pom)
                scm_url = extract_scm_url_from_pom(pom)
                if scm_url:
                    result["scm"] = {"url": scm_url, "host": scm_host(scm_url)}

        cached_repo_meta = None
        github_cap = _external_capability("github")
        if not gh_repo and not github_cap:
            guess = guess_github_repo(group_id, artifact_id)
            if guess:
                cached_repo_meta = gh_fetch_repo(guess["owner"], guess["repo"])
                if cached_repo_meta:
                    gh_repo = guess

        if not gh_repo:
            if not pom_licenses:
                result["signals"].append("no license declared")
            scm = result.get("scm")
            if github_cap:
                result["signals"].append("GitHub metrics unavailable (offline/closed mode)")
                result["healthError"] = "GitHub unavailable (offline/closed mode)"
                result["capabilityUnavailable"] = github_cap
            elif scm and scm["host"] != "github":
                result["signals"].append(f"SCM hosted on {scm['host']}; GitHub metrics unavailable")
            else:
                result["signals"].append("no public GitHub repository found")
                result["healthError"] = "GitHub repository not found; activity metrics unavailable"
            return result

        owner = gh_repo["owner"]
        repo = gh_repo["repo"]
        result["repository"] = {"owner": owner, "repo": repo, "url": f"https://github.com/{owner}/{repo}"}
        if not result.get("scm"):
            result["scm"] = {"url": result["repository"]["url"], "host": "github"}

        # OpenSSF Scorecard (#411): a SEPARATE deps.dev capability from the
        # GitHub API used below, so this runs regardless of github_cap — an
        # offline/rate-limited GitHub API does not automatically also skip
        # this enrichment (and vice versa). Only real scorecard data or a
        # genuine capability failure is surfaced; deps.dev simply having no
        # scorecard on file for this repo (common — not every repo is scored)
        # degrades to silent omission, never a flagged failure.
        scorecard_result = fetch_depsdev_scorecard(owner, repo)
        if scorecard_result.get("scorecard"):
            result["scorecard"] = scorecard_result["scorecard"]
        elif scorecard_result.get("capabilityUnavailable"):
            result["scorecard"] = {"capabilityUnavailable": scorecard_result["capabilityUnavailable"]}

        if github_cap:
            # gh_repo came from POM SCM while GitHub API is offline — keep
            # repository identity but skip live metrics.
            if not pom_licenses:
                result["signals"].append("no license declared")
            result["signals"].append("GitHub metrics unavailable (offline/closed mode)")
            result["healthError"] = "GitHub unavailable (offline/closed mode)"
            result["capabilityUnavailable"] = github_cap
            return result

        repo_meta = cached_repo_meta or gh_fetch_repo(owner, repo)
        if not repo_meta:
            if not pom_licenses:
                result["signals"].append("no license declared")
            result["healthError"] = "GitHub repository metadata unavailable (rate limit or network)"
            result["capabilityUnavailable"] = "unreachable"
            return result

        releases = gh_fetch_releases(owner, repo)
        issue_stats = gh_fetch_issue_stats(owner, repo)
        release_summary = _summarize_releases(releases)

        owner_login = (repo_meta.get("owner") or {}).get("login") or owner
        owner_info = gh_fetch_user(owner_login)

        spdx = (repo_meta.get("license") or {}).get("spdx_id")
        pom_license_name = pom_licenses[0]["name"] if pom_licenses else None
        license_val = spdx if (spdx and spdx != "NOASSERTION") else pom_license_name

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

        return result

    # R2c: a smaller dedicated bound than the default MAX_PARALLEL_FETCHES —
    # see MAX_GITHUB_PARALLEL_FETCHES for why (GitHub's secondary rate
    # limiter penalizes concurrent requests, and this fan-out makes several
    # api.github.com calls per dependency).
    results, _partial = _map_parallel(
        args["dependencies"], _check_one, max_workers=MAX_GITHUB_PARALLEL_FETCHES,
    )
    return {"results": results}


def handle_search_artifacts(args: Dict) -> Any:
    query = args["query"]
    # Coerce + clamp before any search URL is built — schema bounds are advisory
    # only (same reasoning as verify_coordinates' suggestLimit clamp).
    try:
        limit = int(args.get("limit", SEARCH_LIMIT_DEFAULT))
    except (TypeError, ValueError):
        limit = SEARCH_LIMIT_DEFAULT
    limit = max(1, min(limit, SEARCH_LIMIT_MAX))
    rtype = _normalize_search_backend(
        args.get("repositoryType") or _repository_type_env()
    )
    # ResolutionContext carries offline / repository_base / mirrors for routing.
    ctx = build_resolution_context(args)
    return search_artifacts_with_backend(query, limit, ctx, rtype)


def handle_get_dependency_license(args: Dict) -> Any:
    """Batch license intelligence for Maven dependencies (#300)."""
    deps = list(args.get("dependencies") or [])
    # Cap enforced in-handler before any network I/O (schema maxItems is advisory).
    if len(deps) > MAX_LICENSE_DEPENDENCIES:
        deps = deps[:MAX_LICENSE_DEPENDENCIES]
    ctx = build_resolution_context(args)

    def _license_one(dep: Dict) -> Dict[str, Any]:
        group_id = dep["groupId"]
        artifact_id = dep["artifactId"]
        version = dep.get("version")
        try:
            return resolve_dependency_license(group_id, artifact_id, version, ctx)
        except Exception as e:
            return _license_result(
                group_id, artifact_id, version, None, None, None, "unknown", None,
                error=str(e),
            )

    # #400: bounded parallel fan-out, order preserved.
    results, _partial = _map_parallel(deps, _license_one)
    return {"results": results}


def handle_check_license_compliance(args: Dict) -> Any:
    """Aggregate transitive licenses and flag policy violations (#289)."""
    deps = list(args.get("dependencies") or [])
    if len(deps) > MAX_LICENSE_COMPLIANCE_ROOTS:
        deps = deps[:MAX_LICENSE_COMPLIANCE_ROOTS]
    project_license = args.get("projectLicense")
    disallow = args.get("disallow")
    if disallow is not None and not isinstance(disallow, list):
        disallow = [str(disallow)]
    return check_license_compliance(
        deps,
        project_license=project_license,
        disallow=disallow,
    )


def _build_license_audit(
    license_entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the ``licenses`` section for audit_project_dependencies (#300)."""
    by_category: Dict[str, int] = {}
    unique_spdx: List[str] = []
    seen_spdx = set()
    deps_out: List[Dict[str, Any]] = []
    for entry in license_entries:
        cat = entry.get("category") or "unknown"
        by_category[cat] = by_category.get(cat, 0) + 1
        spdx = entry.get("spdxId")
        if spdx and spdx not in seen_spdx:
            seen_spdx.add(spdx)
            unique_spdx.append(spdx)
        deps_out.append({
            "groupId": entry["groupId"],
            "artifactId": entry["artifactId"],
            "version": entry.get("version"),
            "spdxId": entry.get("spdxId"),
            "category": cat,
            "notes": entry.get("notes"),
            "name": entry.get("name"),
            "url": entry.get("url"),
            "source": entry.get("source"),
        })
    has_unknown = by_category.get("unknown", 0) > 0
    has_proprietary_or_copyleft = any(
        by_category.get(c, 0) > 0
        for c in ("proprietary", "weak-copyleft", "strong-copyleft", "network-copyleft")
    )
    return {
        "summary": {
            "byCategory": by_category,
            "uniqueSpdxIds": unique_spdx,
            "hasUnknown": has_unknown,
            "hasProprietaryOrCopyleft": has_proprietary_or_copyleft,
        },
        "dependencies": deps_out,
    }


def _detect_new_license_categories(
    license_entries: List[Dict[str, Any]],
) -> List[str]:
    """Categories that appear only once in the scanned set (#300).

    Comparison is per SPDX *category*, not exact SPDX id: a project already
    using MIT should not warn about every new MIT dependency. A category that
    appears exactly once is treated as new relative to the rest of the set
    (useful when adding one AGPL library into an otherwise Apache/MIT tree).
    With fewer than two licensed dependencies there is no baseline to compare,
    so the result is empty.
    """
    if len(license_entries) < 2:
        return []
    counts: Dict[str, int] = {}
    for entry in license_entries:
        cat = entry.get("category") or "unknown"
        counts[cat] = counts.get(cat, 0) + 1
    return sorted(cat for cat, n in counts.items() if n == 1)


def _dedup_resolved_from(audit_deps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Hoist the most-common ``resolvedFrom`` value to a top-level default and
    strip it from every entry that matches it exactly (#405).

    A large audit routinely resolves 200-300 dependencies from the SAME one
    or two declared repositories, repeating an identical ``resolvedFrom``
    object on nearly every entry — pure token bloat. No provenance is lost:
    an entry with no ``resolvedFrom`` of its own falls back to the top-level
    ``defaultResolvedFrom``; an entry whose provenance genuinely DIFFERS (a
    different repo answered, or public-fallback was used only for that one)
    keeps its own ``resolvedFrom`` untouched. Returns ``None`` (no top-level
    field added, no entries touched) when no value is shared by >=2 entries —
    hoisting a value used by exactly one entry would save nothing.
    """
    counts: Dict[str, int] = {}
    by_key: Dict[str, Dict[str, Any]] = {}
    for entry in audit_deps:
        rf = entry.get("resolvedFrom")
        if not rf:
            continue
        key = json.dumps(rf, sort_keys=True)
        counts[key] = counts.get(key, 0) + 1
        by_key[key] = rf
    if not counts:
        return None
    best_key = max(counts, key=lambda k: counts[k])
    if counts[best_key] < 2:
        return None
    default_rf = by_key[best_key]
    for entry in audit_deps:
        if entry.get("resolvedFrom") == default_rf:
            del entry["resolvedFrom"]
    return default_rf


def _has_audit_issue(entry: Dict[str, Any]) -> bool:
    """True when an audit_deps entry carries a signal worth surfacing under
    ``onlyIssues`` (#405): a fetch error, an available upgrade, a known
    vulnerability, or a license-category signal. audit_project_dependencies
    does not itself compute dependency conflicts or dead-repository hints
    (those live in detect_dependency_conflicts / scan_project's
    deadRepositoryHints) so they are not part of this predicate."""
    if entry.get("error"):
        return True
    upgrade_type = entry.get("upgradeType")
    if upgrade_type and upgrade_type != "none":
        return True
    if entry.get("vulnerabilities"):
        return True
    if entry.get("signals"):
        return True
    return False


def handle_audit_project_dependencies(args: Dict) -> Any:
    project_path = args.get("projectPath") or os.getcwd()
    include_vulns = args.get("includeVulnerabilities", True)
    if include_vulns is None:
        include_vulns = True
    production_only = args.get("productionOnly", True)
    if production_only is None:
        production_only = True
    include_licenses = args.get("includeLicenses", False)
    if include_licenses is None:
        include_licenses = False
    only_issues = bool(args.get("onlyIssues", False))

    ctx = build_resolution_context(args)
    # #402: one wall-clock budget for the WHOLE tool invocation, shared across
    # every fan-out phase below (metadata, vulnerabilities, licenses) — not a
    # separate budget per phase, since a project large enough to blow through
    # TOOL_DEADLINE in one phase would otherwise just move the same risk to
    # the next. `partial`/`notes` are only added to the output when the
    # deadline actually fires (see below) — the common, fast case is
    # byte-for-byte unchanged.
    deadline = _now() + TOOL_DEADLINE
    deadline_hit = False
    scan = scan_project(project_path)
    if scan.get("resolvedBy") != "gradle":
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

    def _audit_error_entry(
        dep: Dict, current_version: Optional[str], error_msg: str,
        resolved_from: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        error_entry: Dict[str, Any] = {
            "groupId": dep["groupId"],
            "artifactId": dep["artifactId"],
            "currentVersion": current_version,
            "source": dep["source"],
            "usages": dep.get("usages", []),
            "module": (dep.get("usages") or [{}])[0].get("module"),
            "configuration": (dep.get("usages") or [{}])[0].get("configuration"),
            "error": error_msg,
        }
        if resolved_from is not None:
            error_entry["resolvedFrom"] = resolved_from
        if dep.get("effectiveVersion") is not None:
            error_entry["effectiveVersion"] = dep["effectiveVersion"]
        if dep.get("managedBy") is not None:
            error_entry["managedBy"] = dep["managedBy"]
        return error_entry

    # Memoize metadata fetches per GA. #400: shared across worker threads, so
    # every read-then-maybe-write against it goes through metadata_cache_lock
    # (double-checked: the network fetch itself runs OUTSIDE the lock). A
    # check-then-fetch race between two threads for the SAME ga_key can still
    # cause a redundant duplicate fetch (perf, not correctness) — the lock's
    # job is solely to make the dict read/write atomic and to guarantee every
    # dep sharing a ga_key ends up with the SAME metadata object (setdefault,
    # first-writer-wins), never a corrupted or inconsistent cache entry.
    metadata_cache: Dict[str, Any] = {}
    metadata_cache_lock = threading.Lock()

    def _fetch_one_audit_dep(dep: Dict) -> Dict[str, Any]:
        current_version = _effective_version(dep)
        ga_key = f"{dep['groupId']}:{dep['artifactId']}"
        # resolved_from is captured as soon as fetch_metadata succeeds, so an
        # unexpected downstream failure still carries provenance — mirrors the
        # #317 finding 1 fix applied to handle_check_multiple_dependencies /
        # handle_compare_dependency_versions.
        resolved_from = None
        try:
            with metadata_cache_lock:
                metadata = metadata_cache.get(ga_key)
            if metadata is None:
                fetched = fetch_metadata(dep["groupId"], dep["artifactId"], ctx)
                with metadata_cache_lock:
                    metadata = metadata_cache.setdefault(ga_key, fetched)
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
            return entry
        except Exception as e:
            # str(e) is safe here: fetch_metadata's own messages are redacted
            # at the source (see fetch_metadata), and find_latest_version_for_
            # current/get_upgrade_type are pure version-string functions that
            # never embed a repo URL.
            return _audit_error_entry(dep, current_version, str(e), resolved_from)

    # #400/#402: bounded parallel fan-out, order preserved, bounded by the
    # shared tool-wide deadline. A dep left unprocessed when the deadline
    # fires gets a placeholder error entry below — every scanned dependency
    # still gets exactly one row in `dependencies`, never silently dropped.
    metadata_results, metadata_partial = _map_parallel(
        deps_with_version, _fetch_one_audit_dep,
        max_workers=MAX_PARALLEL_FETCHES, deadline=deadline,
    )
    if metadata_partial:
        deadline_hit = True
    for dep, entry in zip(deps_with_version, metadata_results):
        if entry is None:
            entry = _audit_error_entry(
                dep, _effective_version(dep),
                f"skipped: exceeded the {TOOL_DEADLINE}s tool deadline",
            )
        audit_deps.append(entry)

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
    osv_capability: Optional[str] = None
    if include_vulns and deps_with_version:
        gav_map: Dict[str, List[Dict]] = {}
        for a in audit_deps:
            if not a.get("currentVersion"):
                continue
            key = f"{a['groupId']}:{a['artifactId']}:{a['currentVersion']}"
            gav_map.setdefault(key, []).append(a)

        # #400/#402: parallelize the per-unique-GAV marker-resolution fan-out
        # (each is its OWN POM fetch). unique_keys fixes gav_map's insertion
        # order up front so results stay index-mapped to it. No try/except is
        # added here: resolve_plugin_marker_implementation never raises
        # (degrades to None), matching the original loop. A deadline cutoff
        # ALSO surfaces as None here — indistinguishable from (and handled
        # identically to) a coordinate that genuinely resolved to "not a
        # marker": both fall back to querying OSV with the ORIGINAL GAV below,
        # which was already this loop's existing behavior for a falsy result.
        unique_keys = list(gav_map.keys())
        firsts = [gav_map[key][0] for key in unique_keys]

        def _resolve_marker_one(first: Dict) -> Optional[Dict]:
            return resolve_plugin_marker_implementation(
                first["groupId"], first["artifactId"], first["currentVersion"], ctx
            )

        resolved_list, marker_partial = _map_parallel(
            firsts, _resolve_marker_one,
            max_workers=MAX_PARALLEL_FETCHES, deadline=deadline,
        )
        if marker_partial:
            deadline_hit = True
        resolved_impls: Dict[str, Optional[Dict]] = dict(zip(unique_keys, resolved_list))
        unique_gavs = [
            resolved if resolved else {
                "groupId": first["groupId"],
                "artifactId": first["artifactId"],
                "version": first["currentVersion"],
            }
            for first, resolved in zip(firsts, resolved_list)
        ]

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
            entry_cap = vuln_results[i].get("capabilityUnavailable")
            if entry_cap and osv_capability is None:
                osv_capability = entry_cap
            for target in targets:
                target["vulnerabilities"] = mapped_vulns
                if entry_cap:
                    target["capabilityUnavailable"] = entry_cap
                if resolved:
                    target["resolvedImplementation"] = resolved

    licenses_section: Optional[Dict[str, Any]] = None
    new_license_categories: Optional[List[str]] = None
    if include_licenses:
        # Resolve licenses for versioned deps only (POM fetch needs a version).
        # #400: split into a cheap sequential PLANNING pass (collect the
        # unique GAVs needing a fetch, first-seen order — identical dedup
        # criterion to the original inline `if gav_key not in license_cache`
        # check) and a PARALLEL fetch pass, then a final sequential ASSEMBLE
        # pass that mutates `a["signals"]` in the SAME order as before. This
        # keeps the deterministic dedup/signal bookkeeping single-threaded
        # while parallelizing the actual network fetch.
        unique_license_keys: List[str] = []
        unique_license_items: List[Tuple[str, str, str]] = []
        seen_license_keys: set = set()
        for a in audit_deps:
            ver = a.get("currentVersion")
            if not ver:
                continue
            gav_key = f"{a['groupId']}:{a['artifactId']}:{ver}"
            if gav_key not in seen_license_keys:
                seen_license_keys.add(gav_key)
                unique_license_keys.append(gav_key)
                unique_license_items.append((a["groupId"], a["artifactId"], ver))

        def _fetch_one_license(item: Tuple[str, str, str]) -> Dict[str, Any]:
            gid, aid, ver = item
            try:
                return resolve_dependency_license(gid, aid, ver, ctx)
            except Exception as e:
                return _license_result(
                    gid, aid, ver, None, None, None, "unknown", None, error=str(e),
                )

        fetched_licenses, license_partial = _map_parallel(
            unique_license_items, _fetch_one_license,
            max_workers=MAX_PARALLEL_FETCHES, deadline=deadline,
        )
        if license_partial:
            deadline_hit = True
        license_cache: Dict[str, Dict[str, Any]] = {}
        for key, (gid, aid, ver), result in zip(
            unique_license_keys, unique_license_items, fetched_licenses
        ):
            if result is None:
                result = _license_result(
                    gid, aid, ver, None, None, None, "unknown", None,
                    error=f"skipped: exceeded the {TOOL_DEADLINE}s tool deadline",
                )
            license_cache[key] = result

        license_entries: List[Dict[str, Any]] = []
        for a in audit_deps:
            ver = a.get("currentVersion")
            if not ver:
                continue
            gav_key = f"{a['groupId']}:{a['artifactId']}:{ver}"
            lic = license_cache[gav_key]
            license_entries.append(lic)
            signals = a.setdefault("signals", [])
            cat = lic.get("category") or "unknown"
            if cat == "unknown":
                if "unknown license" not in signals:
                    signals.append("unknown license")
            elif cat == "proprietary":
                if "proprietary license" not in signals:
                    signals.append("proprietary license")
        licenses_section = _build_license_audit(license_entries)
        new_license_categories = _detect_new_license_categories(license_entries)

    # #405: hoist a repeated resolvedFrom to one top-level default BEFORE
    # summary/onlyIssues filtering — the dedup ratio and the "default repo"
    # itself are more representative computed over the FULL scanned set than
    # over whatever onlyIssues later narrows `dependencies` down to.
    default_resolved_from = _dedup_resolved_from(audit_deps)

    summary = {
        "total": len(audit_deps),
        "upgradeable": sum(1 for d in audit_deps if d.get("upgradeType") and d["upgradeType"] != "none"),
        "vulnerable": sum(1 for d in audit_deps if d.get("vulnerabilities")),
        "major": sum(1 for d in audit_deps if d.get("upgradeType") == "major"),
        "minor": sum(1 for d in audit_deps if d.get("upgradeType") == "minor"),
        "patch": sum(1 for d in audit_deps if d.get("upgradeType") == "patch"),
    }

    # #405: onlyIssues (default false, unchanged output) filters `dependencies`
    # down to entries carrying a signal, while `summary` still describes the
    # WHOLE scanned set — the counts above are computed before filtering.
    output_deps = audit_deps
    if only_issues:
        output_deps = [d for d in audit_deps if _has_audit_issue(d)]
        summary["withIssues"] = len(output_deps)
        summary["clean"] = summary["total"] - summary["withIssues"]

    out: Dict[str, Any] = {
        "buildSystem": scan["buildSystem"],
        "dependencies": output_deps,
        "summary": summary,
    }
    if only_issues:
        out["onlyIssues"] = True
    if default_resolved_from is not None:
        out["defaultResolvedFrom"] = default_resolved_from
    if licenses_section is not None:
        out["licenses"] = licenses_section
    if new_license_categories is not None:
        out["newLicenseCategories"] = new_license_categories
    if deadline_hit:
        # #402: at least one fan-out phase above hit the shared tool-wide
        # deadline and stopped early — surfaced only in this (rare,
        # degenerate-batch) case so the common fast path's output shape is
        # completely unchanged.
        out["partial"] = True
        out["notes"] = [
            f"Stopped early after exceeding the {TOOL_DEADLINE}s tool "
            f"deadline; some dependencies were not fully processed and are "
            f"marked with an error noting the skip."
        ]
    return _with_capability(out, osv_capability)


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
    gated_calls_lock: Optional["threading.Lock"] = None,
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

    ``gated_calls_lock`` (#400): the per-coordinate fan-out in
    ``handle_verify_coordinates`` now runs on a ThreadPoolExecutor, so this
    function can be entered concurrently by multiple worker threads sharing
    the SAME ``gated_calls`` cell -- an unguarded check-then-increment would
    let the total exceed ``MAX_GATED_SOLR_CALLS_PER_BATCH`` (a real, documented
    load-safety cap, not just a perf nicety). Optional and defaults to
    ``None`` so direct single-threaded callers (tests exercising this counter
    in isolation) are unaffected; ``handle_verify_coordinates`` always passes
    a real lock created fresh alongside ``gated_calls``.

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
    def _reserve_gated_call() -> bool:
        """Atomically check-and-increment ``gated_calls[0]`` against the cap.

        The check and the increment MUST happen as one atomic step under
        ``gated_calls_lock`` — otherwise two concurrent callers could both
        observe room under the cap and both increment, exceeding it by up to
        (worker count - 1). Falls back to an unguarded (but still correct
        for a single-threaded caller) check when no lock is supplied.
        """
        if gated_calls_lock is not None:
            with gated_calls_lock:
                if gated_calls[0] < MAX_GATED_SOLR_CALLS_PER_BATCH:
                    gated_calls[0] += 1
                    return True
                return False
        if gated_calls[0] < MAX_GATED_SOLR_CALLS_PER_BATCH:
            gated_calls[0] += 1
            return True
        return False

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
        if _reserve_gated_call():
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
        if versions and _reserve_gated_call():
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
    gated_calls_lock: Optional["threading.Lock"] = None,
) -> Dict[str, Any]:
    """Verify a single coordinate. Runs its OWN per-repo existence probe (not
    fetch_metadata's raise, which conflates absent vs unreachable and drops the
    answering repo). Classifies existence as a tri-state and, only when ABSENT,
    queries Maven Central for popularity-aware did-you-mean candidates. When
    EXISTS, additionally computes `typosquatRisk` (#322 Layer 2) -- see
    `_compute_typosquat_risk`. ``gated_calls`` is the per-batch Solr-call
    counter shared across the whole `handle_verify_coordinates` invocation;
    callers must pass a list created fresh at the top of that call.
    ``gated_calls_lock`` (#400) guards it under the parallel per-coordinate
    fan-out -- see `_compute_typosquat_risk`."""
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
            group_id, artifact_id, len(union_versions), versions, gated_calls,
            gated_calls_lock,
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
    # #400: the per-coordinate fan-out below now runs on a bounded
    # ThreadPoolExecutor (via _map_parallel), so gated_calls needs a real lock
    # -- also created fresh per call, same "local, never module-level" reasoning.
    gated_calls_lock = threading.Lock()

    def _verify_dep(dep: Dict) -> Dict[str, Any]:
        group_id = dep.get("groupId", "")
        artifact_id = dep.get("artifactId", "")
        version = dep.get("version")
        try:
            return _verify_one(
                group_id, artifact_id, version, suggest_limit, ctx,
                gated_calls, gated_calls_lock,
            )
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
            return item

    results, _partial = _map_parallel(dependencies, _verify_dep)
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
            "additionalProperties": False,
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
        "description": "Check if a specific version of a Maven artifact exists in any repository resolved for the project: declared repositories first, then the public Maven Central / Google Maven / Gradle Plugin Portal fallback when the project declares none (see projectPath).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "groupId": {"type": "string", "description": "Maven group ID"},
                "artifactId": {"type": "string", "description": "Maven artifact ID"},
                "version": {"type": "string", "description": "Version to check for existence"},
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
            "additionalProperties": False,
            "properties": {
                "dependencies": {
                    "type": "array",
                    "description": "Dependencies to look up — no version needed; this tool reports the latest available version for each.",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "groupId": {"type": "string", "description": "Maven group ID"},
                            "artifactId": {"type": "string", "description": "Maven artifact ID"},
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
            "additionalProperties": False,
            "properties": {
                "dependencies": {
                    "type": "array",
                    "description": "Dependencies with their currently pinned version, compared against the latest available.",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "groupId": {"type": "string", "description": "Maven group ID"},
                            "artifactId": {"type": "string", "description": "Maven artifact ID"},
                            "currentVersion": {"type": "string", "description": "Currently pinned version to compare against the latest available"},
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
        "description": "Get changelog/release notes between two versions (AndroidX/AGP developer docs when applicable, else GitHub releases).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "groupId": {"type": "string", "description": "Maven group ID"},
                "artifactId": {"type": "string", "description": "Maven artifact ID"},
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
            "additionalProperties": False,
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
            "additionalProperties": False,
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
            "additionalProperties": False,
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
            "additionalProperties": False,
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
        "description": "Check whether a set of versions is mutually compatible. Validates (1) dependency versions against the Spring Boot BOM (spring-boot-dependencies) when springBoot is set, (2) AGP↔Gradle↔JDK and Kotlin Gradle plugin↔Gradle/AGP ranges from a shipped matrix file, and (3) javax→jakarta EE coordinate migration when Spring Boot ≥ 3. Returns conflicts with suggested compatible versions and reference URLs. v1 coverage is intentionally bounded — see notes[] in the response; matrices are not scraped at runtime and must be refreshed via the documented procedure in compat-matrices.json.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "springBoot": {
                    "type": "string",
                    "description": "Spring Boot version. When set, expands org.springframework.boot:spring-boot-dependencies and checks dependencies[] against managed versions; also enables javax→jakarta checks when ≥ 3.0.0.",
                },
                "android": {
                    "type": "object",
                    "additionalProperties": False,
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
                        "additionalProperties": False,
                        "properties": {
                            "groupId": {"type": "string", "description": "Maven group ID"},
                            "artifactId": {"type": "string", "description": "Maven artifact ID"},
                            "version": {"type": "string", "description": "Version to compare against the Spring Boot BOM / javax→jakarta map. A dependency without a version is skipped by those checks."},
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
        "description": "Check dependencies for known vulnerabilities using the OSV.dev database. Each dependency requires a pinned version — OSV lookups are version-specific and version-less coordinates are not queried. An empty vulnerabilities list means no known CVE/GHSA advisory was found for that coordinate+version in OSV.dev; it is NOT a safety guarantee (OSV coverage is incomplete and reporting lags real-world disclosure). When ≥1 vulnerability is found, a per-dependency safeUpgrade candidate is synthesized from the already-fetched fixed-version data (the highest fixed version across all known CVEs) — ADVISORY ONLY, a candidate to verify, never a guaranteed-safe pin; fixesAllKnown is false when at least one CVE has no known fix.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dependencies": {
                    "type": "array",
                    "maxItems": 100,
                    "description": "Dependencies to check, each with a pinned version (required).",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "groupId": {"type": "string", "description": "Maven group ID"},
                            "artifactId": {"type": "string", "description": "Maven artifact ID"},
                            "version": {"type": "string", "description": "Pinned version to check — required; OSV lookups are version-specific"},
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
        "description": "Get health signals for Maven dependencies: version info, GitHub activity, issue stats, license, and maintenance signals. When the GitHub repository is known, also surfaces the OpenSSF Scorecard (overallScore + per-check name/score/reason) from deps.dev when one is on file — omitted (or flagged with capabilityUnavailable) when deps.dev has no scorecard for that repo, is offline, or is unreachable.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dependencies": {
                    "type": "array",
                    "description": "Dependencies to evaluate for maintenance/health signals.",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "groupId": {"type": "string", "description": "Maven group ID"},
                            "artifactId": {"type": "string", "description": "Maven artifact ID"},
                            "version": {"type": "string", "description": "Optional. When omitted, the latest preferred-stable version is evaluated."},
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
        "name": "get_dependency_license",
        "description": "Resolve license intelligence for Maven dependencies: SPDX id, category (permissive / weak-copyleft / strong-copyleft / network-copyleft / proprietary / unknown), plain-English notes, and source (pom / github / spdx-normalized). Uses POM <licenses> plus optional GitHub license metadata; category mapping is a static lookup (no external license API).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dependencies": {
                    "type": "array",
                    "maxItems": 100,
                    "description": "Dependencies to resolve license info for.",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "groupId": {"type": "string", "description": "Maven group ID"},
                            "artifactId": {"type": "string", "description": "Maven artifact ID"},
                            "version": {"type": "string", "description": "Optional. When omitted, the latest preferred-stable version is used."},
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
        "name": "check_license_compliance",
        "description": "Aggregate SPDX licenses across the transitive closure of one or more Maven GAVs (deps.dev GetDependencies + GetVersion) and flag risky/incompatible licenses against a projectLicense posture or an explicit disallow list (SPDX ids and/or categories). Verdicts: ok / review / violation. Missing license metadata degrades to review, never a false ok. Heuristic policy signal — not legal advice; see notes[].",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dependencies": {
                    "type": "array",
                    "maxItems": 20,
                    "description": "Root GAVs whose transitive graphs are scanned. Version is required. Capped at MAX_LICENSE_COMPLIANCE_ROOTS.",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "groupId": {"type": "string", "description": "Maven group ID"},
                            "artifactId": {"type": "string", "description": "Maven artifact ID"},
                            "version": {"type": "string", "description": "Required — used to resolve the transitive graph for license aggregation."},
                        },
                        "required": ["groupId", "artifactId", "version"],
                    },
                },
                "projectLicense": {
                    "type": "string",
                    "description": "Optional project SPDX id or license name. A permissive posture (or omitted projectLicense) defaults to disallowing strong-copyleft, network-copyleft, and proprietary.",
                },
                "disallow": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional override: SPDX ids and/or category names to flag as violation. When set, replaces the default disallow set entirely.",
                },
            },
            "required": ["dependencies"],
        },
    },
    {
        "name": "search_artifacts",
        "description": "Search Maven artifacts by keyword. Uses Maven Central Solr by default; in closed/offline mode (or with repositoryType) routes to Nexus 3 REST or Artifactory AQL/GAVC against MAVEN_MCP_REPOSITORY_BASE / mirrors.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "Search query (keyword, or groupId:artifactId for coordinate search)"},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100, "description": "Maximum number of results. Default 10, clamped to [1, 100]."},
                "repositoryType": {
                    "type": "string",
                    "enum": ["auto", "nexus", "artifactory", "central"],
                    "description": "Search backend. auto (default) uses Solr in public mode and detects Nexus/Artifactory in closed mode. Override with nexus, artifactory, or central. Also settable via MAVEN_MCP_REPOSITORY_TYPE.",
                },
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories / mirrors. Defaults to the current working directory."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "audit_project_dependencies",
        "description": "Orchestrates a full dependency audit: scans project build files, checks for available updates, and optionally queries OSV.dev for vulnerabilities. Optional includeLicenses adds license categorization, summary, and newLicenseCategories (categories unique in the scanned set). Optional onlyIssues narrows the returned dependencies to only those with a signal (error, available upgrade, vulnerability, or license flag); summary always covers the full scanned set.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "projectPath": {"type": "string", "description": "Project root used to resolve declared repositories. Defaults to the current working directory."},
                "includeVulnerabilities": {"type": "boolean", "description": "Include OSV vulnerability check (default true)"},
                "productionOnly": {"type": "boolean", "description": "Exclude test-scope dependencies (default true)"},
                "includeLicenses": {"type": "boolean", "description": "Include license intelligence (POM/GitHub resolve + category summary). Default false to avoid extra POM fetches."},
                "onlyIssues": {"type": "boolean", "description": "Return only dependencies with a signal (error, upgrade available, vulnerability, or license flag) plus a compact summary. Default false (unchanged full output). Reduces response size on large projects."},
            },
        },
    },
    {
        "name": "catalog_entry",
        "description": "Generate or validate Gradle version-catalog (libs.versions.toml) entries. mode=generate builds a rule-correct [versions]/[libraries]/[plugins] snippet with kebab alias + libs/alias(libs.plugins.*) accessor; mode=validate flags reserved aliases, invalid first subgroups, undefined version.ref, accessor clashes, id(libs.plugins.*) misuse, and libs usage inside subprojects/buildscript. Returns a minimal diff suggestion, not a full file rewrite.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["generate", "validate"],
                    "description": "generate a catalog entry from a coordinate, or validate catalog TOML (+ optional build script text).",
                },
                "coordinate": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "Required for generate. Maven GAV or plugin marker coordinate.",
                    "properties": {
                        "groupId": {"type": "string", "description": "Maven group ID"},
                        "artifactId": {"type": "string", "description": "Maven artifact ID"},
                        "version": {"type": "string", "description": "Optional; when omitted, generates a version-less accessor (no [versions] pin)."},
                    },
                    "required": ["groupId", "artifactId"],
                },
                "kind": {
                    "type": "string",
                    "enum": ["library", "plugin"],
                    "description": "Entry kind for generate. Default: library.",
                },
                "alias": {
                    "type": "string",
                    "description": "Optional preferred alias for generate; sanitized if it violates catalog rules.",
                },
                "catalogToml": {
                    "type": "string",
                    "description": "Existing libs.versions.toml content. Used by validate; for generate, avoids alias clashes and enables version-only bump suggestions.",
                },
                "buildContent": {
                    "type": "string",
                    "description": "Optional build script text for validate — detects id(libs.plugins.*) misuse and libs accessors inside subprojects/buildscript.",
                },
                "catalogPath": {
                    "type": "string",
                    "description": "Optional path of the catalog file for validate path-convention checks (default gradle/libs.versions.toml).",
                },
                "catalogName": {
                    "type": "string",
                    "description": "Catalog accessor prefix for generate (default libs).",
                },
                "projectPath": {
                    "type": "string",
                    "description": "Optional project root. In validate mode, reads gradle/libs.versions.toml when catalogToml is omitted.",
                },
            },
            "required": ["mode"],
        },
    },
    {
        "name": "verify_coordinates",
        "description": "Verify whether Maven coordinates exist (tri-state: exists / absent / unknown) and, for absent ones, suggest the closest real coordinates. Detects hallucinated / slopsquat-shaped names an LLM may invent. Existence is NOT a safety guarantee: a published typosquat reports exists and is not flagged. Suggestions are candidates to verify, not endorsements.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dependencies": {
                    "type": "array",
                    "maxItems": 100,
                    "description": "Coordinates to verify for existence; version is optional per item (see items.version).",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "groupId": {"type": "string", "description": "Maven group ID"},
                            "artifactId": {"type": "string", "description": "Maven artifact ID"},
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
    "get_dependency_license": handle_get_dependency_license,
    "check_license_compliance": handle_check_license_compliance,
    "search_artifacts": handle_search_artifacts,
    "audit_project_dependencies": handle_audit_project_dependencies,
    "catalog_entry": handle_catalog_entry,
    "verify_coordinates": handle_verify_coordinates,
}

# Name -> inputSchema, for the dispatcher's own required-argument pre-check
# (see _handle_tools_call) — built once from TOOLS rather than re-scanning
# the list per call.
TOOL_SCHEMAS = {t["name"]: t["inputSchema"] for t in TOOLS}


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
    # Validate required top-level arguments BEFORE calling the handler, using
    # the tool's OWN inputSchema.required — a missing/malformed client argument
    # (Invalid params, #397) must be detected here, not inferred from catching
    # KeyError around the handler call: a handler can just as well raise a
    # KeyError from an INTERNAL lookup with nothing to do with `arguments`
    # (e.g. handle_get_dependency_health's metadata["versions"],
    # check_android_kotlin_compatibility's agp_entry["minGradle"]) — catching
    # KeyError there mislabels an internal bug as a client mistake and hides
    # it from the isError:true self-correction path below (code review
    # follow-up on #397).
    required = (TOOL_SCHEMAS.get(tool_name) or {}).get("required") or []
    if isinstance(arguments, dict):
        missing = [name for name in required if name not in arguments]
    else:
        missing = list(required)
    if missing:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32602,
                "message": f"Invalid params: missing required field {missing[0]!r}",
            },
        }
    try:
        result = handler(arguments)
    except Exception as e:
        # MCP spec (2024-11-05): a TOOL execution failure (handler raised while
        # doing its job — resolution failure, ValueError, network error, an
        # internal KeyError unrelated to the arguments the client sent, etc.)
        # is reported as a successful response with isError:true, not a
        # JSON-RPC protocol error, so the model can see it and self-correct (#397).
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            },
        }
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "content": [{"type": "text", "text": json.dumps(result)}],
        },
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

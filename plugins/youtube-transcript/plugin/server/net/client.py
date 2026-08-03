"""Outbound-fetch constants, the closed `net/` exception set, the opener
construction + scheme/host/port allowlist + redirect-rejection policy layer of
`fetch()` (T-6a), and (T-6b, this revision) `fetch()`'s remaining resource
controls -- header merge, retry/backoff, byte cap, gzip-bomb cap, the
streaming network-budget deadline check -- plus `parse_xml_guarded()`.

`net/` may import only `domain/` (`ALLOWED_EDGES`). This module re-exports
`HTTP_TIMEOUT` from `domain/` (moved there in cycle 8 specifically so `domain/`
itself can derive `ENCODE_RESERVE` from it, since `domain/`'s own row is "nothing"
and could not import it back from here).

`net/client.py` is the **one** module in this project permitted to import
`urllib.request`/`urllib.error`/`http.client`/`socket`/`ssl`/`ftplib`/`asyncio`/
`ctypes`/`xmlrpc.client`/`smtplib`/`webbrowser`/`http.server`, and the **one** module
permitted to touch `xml.*` (via `parse_xml_guarded`, T-6b) -- both enforced by
`tests/test_import_boundaries.py`. `importlib` remains banned here too (cycle 3 had
granted it to this module specifically; cycle 4 revoked that -- nothing in this plan
ever needs dynamic import, least of all in the one module where a dynamic-import
egress bypass would be most dangerous).

**This module is the plan's own repeatedly-named highest-density area for security
findings (nine `multiexpert-review` cycles found bypasses here).** The AST/text-ban
mechanism in `test_import_boundaries.py`/`test_source_policy.py` is a regression
guard, not a closed security boundary (plan.md) -- the load-bearing guarantee that
egress stays inside this one file is code review of this file, same as it always
was. Per tasks.md's T-6b acceptance, this module also receives one dedicated human
or `security-expert` review pass before that task is considered closed -- not
something the implementer can self-certify (see progress.md's Learnings).
"""

import logging
import random
import ssl
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, NoReturn, Optional
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.parsers import expat

from domain import (  # HTTP_TIMEOUT re-exported (cycle 8) and used directly below
    ENCODE_RESERVE,
    HTTP_TIMEOUT,
    TOOL_CALL_DEADLINE,
    Deadline,
    redact_url,
)

_LOGGER = logging.getLogger(__name__)

# --- Resource-control constants (T-6b) -------------------------------------------

HTTP_MAX_ATTEMPTS = 2
MIN_ATTEMPT_TIMEOUT = 5
HTTP_MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# Streaming chunk size for the capped body read below -- arbitrary but small
# relative to `HTTP_MAX_RESPONSE_BYTES`, chosen only so the read loop actually
# loops (letting the per-chunk deadline check fire more than once on a real
# multi-chunk body) rather than for any throughput reason.
_READ_CHUNK_SIZE = 64 * 1024


# --- Cross-border value types (`net/` -> `providers/`) --------------------------
#
# `Transport` bundles only the injectable `sleep`/`jitter` used by the retry
# backoff -- **never** the opener itself, which stays private to `net/client.py`
# (T-6a/T-6b). This replaces the two bare callables previously threaded separately
# through `InnertubeProvider.__init__`/`InnertubeSession` (plan.md cycle 8,
# `frozen=True` narrow-check fix cycle 9).
@dataclass(frozen=True)
class Transport:
    sleep: Callable[[float], None]
    # `Callable[[float, float], float]`, matching `random.uniform(a, b)`'s own
    # signature -- T-6b's retry backoff calls this as `jitter(0, 0.25)` (fixed
    # here; T-6a's committed annotation said `Callable[[], float]`, a no-args
    # shape that predates T-6b's actual call site and would mismatch it under
    # mypy). Every timing test pins this to a fake always returning its upper
    # bound (`0.25`) so an exact-backoff assertion is never flaky against real
    # randomness.
    jitter: Callable[[float, float], float]


# The one and only entry `fetch()`'s header merge owns unconditionally (AC-20) --
# narrow-check fix (Y-6): kept to exactly this single entry, asserted exactly by
# `test_base_headers_are_exactly_accept_encoding`, so a reintroduced identity
# header can't hide inside a growing base set. Deliberately does NOT include a
# default value for the caller-supplied identity header T-10 sets explicitly on
# every leg's `headers` argument (AC-12) -- `net/client.py` owns none of that
# decision; see `_merge_headers`'s docstring for the merge-direction rationale and
# `test_source_policy.py`'s literal-string ban guarding against its return here.
BASE_HEADERS: Mapping[str, str] = {"Accept-Encoding": "gzip"}


def _merge_headers(caller_headers: Optional[Mapping[str, str]]) -> Dict[str, str]:
    """`{**(headers or {}), **BASE_HEADERS}`, both sides' keys normalized via
    `.title()` first (Y-7): `urllib.request.Request.add_header` itself
    re-normalizes header names via `str.capitalize()` before storing them, so an
    un-normalized dict-level merge could pick the wrong "winner" between two
    differently-cased spellings of the same header purely by dict insertion
    order -- normalizing here first makes the merge's stated precedence (`BASE_HEADERS`
    wins any collision, Y-5) the actual precedence, not an accident of casing.
    `BASE_HEADERS` merges in **last** specifically so it cannot be overridden --
    the base set exists to be unconditional (AC-20), and a caller sending e.g.
    `Accept-Encoding: identity` must not be able to defeat that."""
    normalized_caller = {key.title(): value for key, value in (caller_headers or {}).items()}
    normalized_base = {key.title(): value for key, value in BASE_HEADERS.items()}
    return {**normalized_caller, **normalized_base}


# Production default when a caller doesn't need to inject a fake `Transport` --
# real `time.sleep`/`random.uniform`. `fetch()` falls back to this when its own
# `transport` parameter is left `None` (see `fetch()`'s docstring for why that
# parameter has a default at all, unlike the plan's bare interface signature).
_DEFAULT_TRANSPORT = Transport(sleep=time.sleep, jitter=random.uniform)


# `fetch()`'s return type across the `net/` -> `providers/` border (plan.md
# narrow-check fix Y-3). Exactly three fields -- a naive `fetch()` returning the raw
# `http.client.HTTPResponse`/urllib response object would hand `providers/innertube.py`
# a live `.read()`/`.fp` handle, the same class of risk `Transport`'s opener capture
# was, just previously unnoticed because it wasn't named.
@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


# --- Closed exception set -------------------------------------------------------
#
# Not `DomainFailure` subclasses -- these are internal to the `net/` <-> `providers/`
# boundary; `providers/innertube.py` (T-10) is the single place translating each of
# these into a `ProviderError` subclass (which *is* a `DomainFailure`) before
# anything crosses further out to `tools/`/`protocol/`.
#
# A `BlockedUpstream` member previously lived here but was removed
# (acceptance-fix pass, coverage-audit gap-1): `net/client.py` never detects a
# consent-wall/bot-check response itself -- it returns a plain `Response` for
# any non-redirect/429/5xx status (including 403), by design (plan.md line 141:
# "`blocked_by_provider`'s discriminator ... is the same class of gap[, implemented
# as an isolated function]" scoped to `providers/innertube.py`, not this module).
# `providers/innertube.py::_looks_blocked_by_body`/`_enforce_playability_gate`'s
# bot-check `reason` string are the actual, sole discriminators, both raising
# `BlockedByProvider` directly -- never routing through this module's exception
# set at all. Keeping an unraised `BlockedUpstream` here was dead code with no
# real network-layer signal behind it, not a missing test.


class NetError(Exception):
    """Common base for this module's own closed exception set."""


class ResponseTooLarge(NetError):  # noqa: N818 -- name pinned literally by tasks.md's T-3 block
    """Raised when a response body would exceed `HTTP_MAX_RESPONSE_BYTES`."""


class TransportFailed(NetError):  # noqa: N818
    """DNS, timeout, connection reset, or HTTP 5xx after the retry budget (T-6b)."""


class Throttled(NetError):  # noqa: N818
    """HTTP 429. Carries the upstream `Retry-After` value, if any."""

    def __init__(self, message: str = "", *, retry_after: int = 0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PolicyRejected(NetError):  # noqa: N818
    """Scheme/host allowlist rejection, or a redirect (AC-19's boundary)."""


class MalformedUpstream(NetError):  # noqa: N818
    """Raised by `parse_xml_guarded()` (T-6b) on its own DOCTYPE/entity rejection,
    or on genuinely malformed XML (truncated body, mismatched tags)."""


# --- Scheme/host/port allowlist (T-6a) -------------------------------------------
#
# T-P3 (`swarm-report/research/youtube-transcript-size-measurements.md`) confirmed
# the exact host set actually used for every leg this plugin reaches (video-ref
# resolution, InnerTube player POST, timedtext caption GET): `www.youtube.com` and
# `youtubei.googleapis.com`. **Exact match only, no suffix branch** -- a prior plan
# draft's `*.googlevideo.com` suffix logic is dropped entirely (unused: that host is
# where `streamingData`'s audio/video segment URLs point, a section this
# captions-only plugin never reads), rather than kept as dead, unexercised code that
# would also widen the allowlist to `evilgooglevideo.com`-shaped attacker hosts if a
# suffix check were ever written carelessly.
ALLOWED_HOSTS: frozenset = frozenset({"www.youtube.com", "youtubei.googleapis.com"})

ALLOWED_SCHEME = "https"
ALLOWED_PORT = 443


def _check_policy(url: str) -> None:
    """Scheme, then host, then port -- in this exact order, and entirely before the
    opener is ever touched (`fetch()` calls this first). Each check raises
    `PolicyRejected` on its own rejection reason.

    - Scheme: anything but `https` is rejected (`file:`/`data:`/`ftp:`/`http:` all
      included) -- checked first, so a non-`https` URL never even reaches the host
      string comparison below, let alone the opener.
    - Host: `urlsplit(url).hostname` -- `None`/empty (the `https:///x` case) is
      rejected before any string comparison against the allowlist, not merely
      falling through to a `not in` check that would also (harmlessly, but
      accidentally) accept `None` as "not in" a frozenset.
    - Port: `None` (no explicit port in the URL) or exactly `443` -- anything else
      (`https://www.youtube.com:8080/...`) is rejected. This guards the
      upstream-supplied `baseUrl` for the timedtext leg (T-10/AC-18), which is not
      caller-controlled but still needs this check.

    Security-review fix pass (T-6-secfix), two findings:

    - `urlsplit(url)` and the `.port` property access below both raise a bare
      `ValueError` on malformed input (out-of-range port, non-numeric port,
      malformed IPv6 bracket syntax -- confirmed empirically for all three), which
      would otherwise escape `fetch()` outside its closed `NetError` set entirely.
      Both are wrapped here and translated to `PolicyRejected`, same as any other
      rejection reason this function raises.
    - Every raise below routes through `_log_and_raise` rather than raising
      directly, so a policy-layer rejection is logged (redacted) exactly like every
      other exception `fetch()` raises -- previously these three bypassed
      `_log_and_raise` entirely, since this function runs before `fetch()`'s own
      `try` block.
    """
    try:
        parts = urlsplit(url)
    except ValueError as error:
        _log_and_raise(PolicyRejected(f"malformed URL: {error}"), url, cause=error)

    if parts.scheme != ALLOWED_SCHEME:
        _log_and_raise(PolicyRejected(f"scheme {parts.scheme!r} is not {ALLOWED_SCHEME!r}"), url)

    host = parts.hostname
    if not host or host not in ALLOWED_HOSTS:
        _log_and_raise(PolicyRejected(f"host {host!r} is not in the allowlist"), url)

    try:
        port = parts.port
    except ValueError as error:
        _log_and_raise(PolicyRejected(f"malformed URL: {error}"), url, cause=error)

    if port is not None and port != ALLOWED_PORT:
        _log_and_raise(PolicyRejected(f"port {port} is not {ALLOWED_PORT}"), url)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Returning `None` from `redirect_request()` is urllib's own contract for "do
    not follow this redirect" (`cpython/Lib/urllib/request.py`). Empirically
    confirmed (prior review cycle) that this alone does not surface as a clean
    `PolicyRejected` to `fetch()`'s caller -- it only prevents the follow, so it is
    defense in depth here, never the primary redirect-rejection mechanism.
    `fetch()` additionally inspects `HTTPError.code` explicitly (see below)."""

    def redirect_request(  # type: ignore[override]
        self, req, fp, code, msg, headers, newurl
    ) -> Optional[urllib.request.Request]:
        return None


def _build_opener() -> urllib.request.OpenerDirector:
    """Explicit handler list, never `urllib.request.build_opener()`'s default set
    (which would add `FileHandler`/`FTPHandler`/`HTTPHandler`/`UnknownHandler`,
    none of which this policy permits): `HTTPSHandler` bound to
    `ssl.create_default_context()` (full certificate + hostname verification, the
    stdlib default, never a bypass token), the no-redirect handler above,
    `HTTPErrorProcessor` + `HTTPDefaultErrorHandler` (so a non-2xx status surfaces
    as `HTTPError`, letting `fetch()` inspect `.code`), and `ProxyHandler({})` (an
    explicit empty mapping, so no `HTTP_PROXY`/`HTTPS_PROXY` environment variable
    can redirect egress through a proxy this policy never reviewed). No
    `HTTPHandler` is added at all, so even a request that somehow reached this
    opener with a plain `http://` URL would fail with `URLError: unknown url type`
    rather than actually connecting -- defense in depth behind `_check_policy`'s
    scheme check, not a substitute for it.

    Empirically confirmed: `OpenerDirector.add_handler` (`cpython/Lib/urllib/
    request.py`) only appends a handler to `self.handlers` if it finds at least one
    `<protocol>_open`/`_request`/`_response`/`_error` method on it via `dir()`;
    `ProxyHandler({})` dynamically registers zero such methods when its `proxies`
    mapping is empty (it iterates that mapping at `__init__` to decide which
    per-protocol methods to set), so it is added here for the same reason
    `build_opener()`'s default set includes one -- explicit statement that no
    per-environment-variable proxy routing is active -- but never actually appears
    in `_OPENER.handlers` afterward. `test_opener_has_no_default_handlers` asserts
    the real, empirically-observed handler-type set, not the aspirational
    call-site list."""
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.ProxyHandler({}),
    ):
        opener.add_handler(handler)
    return opener


# Constructed exactly once per process, at import time -- **never** rebuilt per
# `fetch()` call (cycle 3 finding: `ssl.create_default_context()` loads the system CA
# bundle, costing ~10-30ms per call for nothing if rebuilt on every invocation).
# **Never exposed outside this module**: no getter, no `Transport`/`Response` field,
# nothing importable that exposes `open()` (cycle 9 -- see `Transport`'s own
# docstring above for why this matters: some *other* object exposing this same
# director as an attribute could reach the network bypassing every check
# `_check_policy`/`_build_opener` enforce, with zero `ALLOWED_EDGES` violation).
# `test_source_policy.py`'s `test_opener_reference_banned_outside_net_client` bans
# that attribute-access pattern anywhere under `plugin/server/**` as a regression
# guard for exactly this (the pattern itself isn't spelled out in this comment, to
# avoid this very file tripping its own ban).
_OPENER = _build_opener()


def _retry_after(error: urllib.error.HTTPError) -> int:
    """Best-effort `Retry-After` header parse for `Throttled`'s `retry_after` --
    absent or non-numeric (a HTTP-date form is legal per RFC 9110 but unused by
    YouTube in practice) both fall back to `0`, same as `Throttled`'s own default."""
    raw = error.headers.get("Retry-After") if error.headers is not None else None
    if raw is None:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def _log_and_raise(error: NetError, url: str, *, cause: Optional[BaseException] = None) -> NoReturn:
    """Every raised `NetError` is logged at DEBUG first -- always through
    `domain.redact_url(url)`, never the raw `url` (T-10's timedtext leg URL carries
    a signed `?...&sig=...`-shaped query string upstream; the exception messages
    raised in this module never interpolate the raw URL either, only fixed text and
    status codes, so this call site is the one place that could otherwise leak it).
    Raises `error` (chained onto `cause` when given) -- called at every terminal
    raise point below so no exception exits this function unlogged.

    Typed `NoReturn` (security-review fix pass, T-6-secfix) rather than the
    previously-committed `-> None`: this function has always unconditionally raised
    on every path, `-> None` was simply an inaccurate annotation. `NoReturn` is what
    lets mypy treat `_check_policy`'s own call sites (below) as truly terminal, so
    the variable reads immediately after each of them are recognized as
    unreachable-if-raised rather than possibly-unbound."""
    _LOGGER.debug("net.fetch failed for %s: %s", redact_url(url), error)
    if cause is not None:
        raise error from cause
    raise error


def _read_capped_body(response_like: Any, deadline: Deadline) -> bytes:
    """Reads a response object's body via repeated `.read(n)` calls -- streaming,
    never a single unbounded `.read()` -- enforcing two independent bounds on every
    iteration, per T-6b:

    1. **Byte cap**: `to_read` shrinks as the running total approaches
       `HTTP_MAX_RESPONSE_BYTES + 1`, so this never allocates past that many bytes
       total; `ResponseTooLarge` is raised the moment the cumulative total would
       exceed the cap, before any further read is attempted (streaming, not
       read-then-check).
    2. **Network-budget deadline**: `deadline.remaining() - ENCODE_RESERVE` is
       checked before every chunk, independent of the per-attempt socket timeout
       already passed to `_OPENER.open()` -- this is what actually bounds the
       "slow drip" scenario plan.md's Technical Approach describes: a connection
       that never times out at the socket level because it keeps sending *some*
       bytes, just very slowly, is still wall-clock bounded here.
    """
    chunks = []
    total = 0
    while True:
        if deadline.remaining() - ENCODE_RESERVE <= 0:
            raise TransportFailed("network budget exhausted during body read")
        to_read = min(_READ_CHUNK_SIZE, HTTP_MAX_RESPONSE_BYTES + 1 - total)
        chunk = response_like.read(to_read)
        if not chunk:
            break
        total += len(chunk)
        if total > HTTP_MAX_RESPONSE_BYTES:
            raise ResponseTooLarge(
                f"response body exceeds {HTTP_MAX_RESPONSE_BYTES} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _inflate_gzip_capped(data: bytes, cap: int) -> bytes:
    """Ported from `plugins/maven-mcp/plugin/server/server.py`'s
    `_inflate_gzip_capped` (lines 387-403 at the time of porting) -- ``data`` here
    is the already byte-capped (by `_read_capped_body` above) wire-size body, so
    this is the SECOND, independent cap, against the DECOMPRESSED size: a small
    compressed body can still expand far past `cap` (a gzip bomb), and
    `Content-Length`/the wire-size cap only ever describe the size on the wire.

    The running total is tracked **cumulatively across every
    `decompressobj().decompress(chunk, max_length=...)` call, including any
    `unconsumed_tail`** -- not a per-call peak -- exactly as the ported function
    does: `zlib.decompressobj.decompress`'s `max_length` bounds only what one call
    produces, so a bomb spread across several `unconsumed_tail` continuations
    would slip past a peak-only check while still exceeding `cap` in aggregate.
    """
    decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)  # 16+wbits = gzip header/trailer
    try:
        out = decompressor.decompress(data, cap + 1)
        while decompressor.unconsumed_tail and len(out) <= cap:
            out += decompressor.decompress(decompressor.unconsumed_tail, cap + 1 - len(out))
        if len(out) <= cap:
            out += decompressor.flush()
    except zlib.error as error:
        # Malformed/corrupt gzip body -- a transport-level anomaly, not a
        # gzip-bomb-cap violation; mapped to this module's own transport-failure
        # exception rather than left as a bare zlib.error a caller doesn't expect.
        raise TransportFailed(f"invalid gzip response body: {error}") from error
    if len(out) > cap:
        raise ResponseTooLarge(f"decompressed gzip body exceeds {cap} bytes")
    return out


def fetch(
    url: str,
    *,
    method: str = "GET",
    body: Optional[bytes] = None,
    headers: Optional[Mapping[str, str]] = None,
    deadline: Optional[Deadline] = None,
    transport: Optional[Transport] = None,
) -> Response:
    """`_check_policy` (scheme, then host, then port) runs first, before the
    module-private opener is ever touched or either resource-control parameter
    below is even consulted -- unchanged from T-6a, so a rejection here never
    reaches the opener, the retry loop, or the byte/deadline caps (T-6a's
    policy-layer tests call `fetch(url)` with neither `deadline` nor `transport`
    and still observe this).

    `deadline`/`transport` default to `None` rather than being required, even
    though plan.md's interface line lists them without a default: a production
    call site (T-10) always threads an explicit, invocation-scoped `Deadline` and
    its own `Transport`, per plan.md's "constructed once per invocation... never
    read from global state" rule -- but T-6a's already-committed policy-layer
    tests predate both parameters and call `fetch(url)` alone, exercising only the
    rejection-before-opener paths (which run before `deadline`/`transport` are
    ever touched). `None` resolves to a freshly started full-budget `Deadline`
    and this module's real-clock `_DEFAULT_TRANSPORT`, so those tests keep passing
    unchanged instead of needing every pre-existing call site rewritten for a
    contract only T-6b introduces.

    Retry loop (T-6b, `HTTP_MAX_ATTEMPTS = 2`, i.e. at most one retry per leg):
    before **every** attempt (including the first, where `backoff_delay` is `0`),
    `remaining_after_backoff = network_budget_remaining - (backoff_delay if retry
    else 0)`, `network_budget_remaining = deadline.remaining() - ENCODE_RESERVE`;
    below `MIN_ATTEMPT_TIMEOUT` (`5s`), no attempt is made and `TransportFailed`
    raises immediately -- the floor and the clamp below are both computed from
    this same backoff-inclusive `remaining_after_backoff`, per plan.md's cycle 4
    fix (both were three cycles' worth of finding the same class of arithmetic
    bug: computing either one from the bare, non-backoff-inclusive budget).
    Backoff for the one retry this design allows is `0.5*(2**1) + jitter(0, 0.25)`,
    up to `1.25s`, via `transport.jitter`/`transport.sleep` (never a bare
    `random.uniform`/`time.sleep` call in this loop) -- every timing test pins
    `jitter` to its upper bound so an exact-backoff assertion is never flaky.
    The clamp, `min(HTTP_TIMEOUT, remaining_after_backoff)`, is the timeout passed
    to `_OPENER.open()` for that attempt.

    A `5xx`/transport-level failure (`urllib.error.URLError`/`OSError`, or this
    function's own `TransportFailed` from the streaming read below) is retried if
    an attempt remains and the floor above allows it; a `3xx` (`PolicyRejected`)
    or `429` (`Throttled`) is never retried -- raised immediately, consuming no
    retry attempt, exactly as T-6a's redirect/429 branches already did (kept
    verbatim, in the same source order, just now nested one level deeper inside
    the retry loop -- `inspect.getsource(fetch)`'s substring-order assertion in
    `test_net_client_policy.py` depends on this).
    """
    _check_policy(url)

    if deadline is None:
        deadline = Deadline.start(TOOL_CALL_DEADLINE)
    if transport is None:
        transport = _DEFAULT_TRANSPORT

    merged_headers = _merge_headers(headers)
    request = urllib.request.Request(url, data=body, headers=merged_headers, method=method)

    last_error: Optional[TransportFailed] = None
    for attempt_index in range(HTTP_MAX_ATTEMPTS):
        is_retry = attempt_index > 0
        network_budget_remaining = deadline.remaining() - ENCODE_RESERVE
        backoff_delay = 0.5 * (2**1) + transport.jitter(0, 0.25) if is_retry else 0.0
        remaining_after_backoff = network_budget_remaining - backoff_delay

        if remaining_after_backoff < MIN_ATTEMPT_TIMEOUT:
            _log_and_raise(
                TransportFailed(
                    "insufficient network budget remaining for another attempt"
                ),
                url,
                cause=last_error,
            )

        if is_retry:
            transport.sleep(backoff_delay)

        attempt_timeout = min(HTTP_TIMEOUT, remaining_after_backoff)

        try:
            with _OPENER.open(request, timeout=attempt_timeout) as raw_response:
                status: int = raw_response.status
                resp_headers: Mapping[str, str] = dict(raw_response.headers.items())
                raw_body: bytes = _read_capped_body(raw_response, deadline)
        except urllib.error.HTTPError as error:
            # Redirect check ordered first, before the 429/5xx branches below --
            # `test_redirect_302_and_305_map_to_policy_rejected_before_status_branches`.
            if 300 <= error.code < 400:
                _log_and_raise(
                    PolicyRejected(
                        f"redirect response ({error.code}) rejected -- "
                        "redirects are never followed"
                    ),
                    url,
                    cause=error,
                )
            if error.code == 429:
                _log_and_raise(
                    Throttled(
                        f"rate limited ({error.code})", retry_after=_retry_after(error)
                    ),
                    url,
                    cause=error,
                )
            if 500 <= error.code < 600:
                last_error = TransportFailed(f"upstream server error ({error.code})")
                if attempt_index == HTTP_MAX_ATTEMPTS - 1:
                    _log_and_raise(last_error, url, cause=error)
                continue
            status = error.code
            resp_headers = dict(error.headers.items()) if error.headers is not None else {}
            # A non-redirect, non-429, non-5xx status (e.g. 404) is a received
            # response, not a transport failure -- read its body the same
            # capped/streaming way; a cap/deadline violation reading THIS body
            # ends the call directly (the status was already determined, so
            # retrying would not change it).
            #
            # Security-review fix pass (T-6-secfix): this call is inside the
            # `except urllib.error.HTTPError` clause of the outer `try` above, so a
            # `ResponseTooLarge`/`TransportFailed` raised here would otherwise
            # propagate straight out of `fetch()` unlogged -- Python does not
            # re-dispatch an exception raised inside one except-block to a sibling
            # except-clause of the same `try` (those sibling clauses, further down,
            # are what catch these same two exception types on the success-read
            # path above). Caught and routed through `_log_and_raise` here instead.
            try:
                raw_body = _read_capped_body(error, deadline)
            except (ResponseTooLarge, TransportFailed) as read_error:
                _log_and_raise(read_error, url)
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            last_error = TransportFailed(f"transport error: {error}")
            if attempt_index == HTTP_MAX_ATTEMPTS - 1:
                _log_and_raise(last_error, url, cause=error)
            continue
        except TransportFailed as error:
            # From `_read_capped_body`'s own network-budget deadline check on the
            # success path above -- retried like any other transport failure if
            # budget allows; if it doesn't, the floor check at the top of the next
            # iteration is what actually raises, so this branch's own raise here
            # only fires when this was already the last attempt.
            last_error = error
            if attempt_index == HTTP_MAX_ATTEMPTS - 1:
                _log_and_raise(last_error, url)
            continue
        except ResponseTooLarge as error:
            # Never retried -- a byte-cap violation is a property of this
            # response, not a transient condition another attempt would fix.
            _log_and_raise(error, url)

        response_body = raw_body
        if resp_headers.get("Content-Encoding", "").lower() == "gzip":
            response_body = _inflate_gzip_capped(raw_body, HTTP_MAX_RESPONSE_BYTES)
        return Response(status=status, headers=resp_headers, body=response_body)

    # Unreachable: every branch above either `return`s or raises on the last
    # attempt. Kept only so this function has no implicit `-> None` fallthrough.
    raise AssertionError("fetch: retry loop exhausted without returning or raising")


# --- The XML guard (T-6b) --------------------------------------------------------
#
# The only function in this project permitted to touch `xml.*` (AST-enforced,
# `test_import_boundaries.py`) -- raw `xml.parsers.expat.ParserCreate()`, never
# `xml.etree.ElementTree.XMLParser()` (which itself wraps expat but does not expose
# a way to reject a DOCTYPE/entity declaration before it's resolved). The requested
# timedtext payload is non-namespaced XML (`<timedtext format="3"><p t=".."
# d="..">text</p></timedtext>`, confirmed by the research spike) -- `ParserCreate()`'s
# default (non-namespace-aware) handling is correct as-is.


class _XMLEntityRejectedError(Exception):
    """Local sentinel, never escapes `parse_xml_guarded` -- raised by the
    DOCTYPE/entity handlers below when expat invokes them, and caught at the
    function boundary alongside `expat.ExpatError` (genuinely malformed XML:
    truncated body, mismatched tags), both re-raised as `MalformedUpstream`."""


def _reject_xml_entity(*_args: object, **_kwargs: object) -> NoReturn:
    """Bound to `StartDoctypeDeclHandler`/`EntityDeclHandler`/
    `ExternalEntityRefHandler` -- accepts and ignores whatever positional
    arguments expat calls it with (the three handlers have different
    signatures), and unconditionally raises the local sentinel above. A
    same-process XXE/billion-laughs payload never reaches expat's own entity
    resolution -- the declaration is rejected the moment expat reports it."""
    raise _XMLEntityRejectedError("DOCTYPE/entity declaration rejected")


def parse_xml_guarded(data: bytes) -> ElementTree.Element:
    parser = expat.ParserCreate()
    builder = ElementTree.TreeBuilder()
    parser.StartDoctypeDeclHandler = _reject_xml_entity
    parser.EntityDeclHandler = _reject_xml_entity
    parser.ExternalEntityRefHandler = _reject_xml_entity
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(data, True)
    except (_XMLEntityRejectedError, expat.ExpatError) as error:
        raise MalformedUpstream(f"malformed timedtext XML: {error}") from error
    return builder.close()

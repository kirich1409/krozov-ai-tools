"""Outbound-fetch constants, the closed `net/` exception set, and (T-6a, this
revision) the opener construction + scheme/host/port allowlist + redirect-rejection
policy layer of `fetch()`. T-6b layers the remaining resource controls (byte caps,
deadline checks, retry loop, gzip inflate, the XML guard) on top of this same
function -- not built here, see `fetch()`'s own docstring.

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
was.
"""

import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping, Optional
from urllib.parse import urlsplit

from domain import HTTP_TIMEOUT  # noqa: F401 -- re-exported, not redefined (cycle 8)

# --- Resource-control constants (T-6b consumes these) ---------------------------

HTTP_MAX_ATTEMPTS = 2
MIN_ATTEMPT_TIMEOUT = 5
HTTP_MAX_RESPONSE_BYTES = 10 * 1024 * 1024


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
    jitter: Callable[[], float]


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


class BlockedUpstream(NetError):  # noqa: N818
    """A consent-wall/bot-check response shape (T-10's discriminator)."""


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
    """
    parts = urlsplit(url)
    if parts.scheme != ALLOWED_SCHEME:
        raise PolicyRejected(f"scheme {parts.scheme!r} is not {ALLOWED_SCHEME!r}")

    host = parts.hostname
    if not host or host not in ALLOWED_HOSTS:
        raise PolicyRejected(f"host {host!r} is not in the allowlist")

    if parts.port is not None and parts.port != ALLOWED_PORT:
        raise PolicyRejected(f"port {parts.port} is not {ALLOWED_PORT}")


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


def fetch(url: str) -> Response:
    """The policy half of `fetch()` (T-6a): `_check_policy` (scheme, then host, then
    port) before the module-private opener is ever touched, then a plain,
    uncapped request through it, with `HTTPError` responses mapped to this module's
    exception set -- **3xx checked before 429/5xx, explicitly, via `HTTPError.code`
    inspection** (`_NoRedirectHandler` returning `None` alone does not surface as a
    clean `PolicyRejected`, see its docstring).

    T-6b adds this function's remaining resource controls on top of what's here --
    byte-cap + gzip-bomb-capped reads, the network-budget deadline check on the
    streaming read loop, the retry loop and its backoff (`transport`), and
    `method`/`body`/`headers`/`deadline`/`transport` parameters -- none of that is
    built in this task; do not add it here.
    """
    _check_policy(url)

    request = urllib.request.Request(url)
    try:
        with _OPENER.open(request) as raw_response:
            status: int = raw_response.status
            headers: Mapping[str, str] = dict(raw_response.headers.items())
            body: bytes = raw_response.read()
    except urllib.error.HTTPError as error:
        # Redirect check ordered first, before the 429/5xx branches below --
        # `test_redirect_302_and_305_map_to_policy_rejected_before_status_branches`.
        if 300 <= error.code < 400:
            raise PolicyRejected(
                f"redirect response ({error.code}) rejected -- redirects are never followed"
            ) from error
        if error.code == 429:
            raise Throttled(
                f"rate limited ({error.code})", retry_after=_retry_after(error)
            ) from error
        if 500 <= error.code < 600:
            raise TransportFailed(f"upstream server error ({error.code})") from error
        status = error.code
        headers = dict(error.headers.items()) if error.headers is not None else {}
        body = error.read()

    return Response(status=status, headers=headers, body=body)

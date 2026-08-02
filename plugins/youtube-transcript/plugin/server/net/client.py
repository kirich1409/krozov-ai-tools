"""Outbound-fetch constants and the closed `net/` exception set -- **contracts and
constants only at this stage**. The actual `fetch()` implementation (opener
construction, scheme/host allowlist, redirect handling, retry loop, deadline/size
caps, the XML guard) is T-6a/T-6b, not this task.

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
egress bypass would be most dangerous). None of those modules are imported yet,
since this task implements no fetch logic.
"""

from dataclasses import dataclass
from typing import Callable, Mapping

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

"""Shared test harness for the youtube-transcript Python server.

T-1 scope: the sys.path shim that lets test modules import the packages under
``plugin/server/`` as top-level modules (``domain``, ``net``, ``providers``,
``formats``, ``protocol``, ``tools``), plus a hermetic env-var reset so the suite's
behavior does not depend on the developer's shell environment.

T-3 scope (this revision): ``FakeProvider``/``FakeSession`` test doubles for the
provider port, plus ``mock_urlopen``/``http_error``/``_FakeHTTPResponse`` transport
doubles for T-6a/T-6b's (not yet implemented) ``net/client.py::fetch()`` tests --
added now, ahead of ``fetch()`` itself, since T-3's own ``ProviderSession.fetch()``
signature and ``net.Response``/``net.Transport`` shapes are what these doubles must
match, and every later task's tests build on this same file rather than
reintroducing their own copies. Stdlib only (zero third-party dependencies),
matching the server's zero-pip-dependency ethos.

Test modules should do ``import _helpers`` (or ``from _helpers import ...``) before
importing anything from the packages under ``plugin/server/``, so the sys.path shim
below is installed first.
"""

import email.message
import io
import os
import sys
import urllib.error
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple, Union

# --- sys.path shim ----------------------------------------------------------
# Resolve plugin/server/ relative to THIS file, never the process cwd, so the
# suite imports the same packages whether run from the repo root, /tmp, or
# anywhere else (mirrors plugins/maven-mcp/tests/_helpers.py).
_SERVER_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin", "server")
)
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

# --- hermetic env-var reset --------------------------------------------------
# The live-canary gate (AC-13): default to off so an ambient
# YOUTUBE_TRANSCRIPT_LIVE_CANARY=1 in the developer's shell can't silently make an
# otherwise-mocked test suite reach out to the real network.
os.environ.pop("YOUTUBE_TRANSCRIPT_LIVE_CANARY", None)
# Hermetic proxy defaults: this server talks to the network via stdlib urllib
# (net/client.py, T-3+), so an inherited proxy env var must not change request
# routing under test, mirroring plugins/maven-mcp/tests/_helpers.py's identical
# reset for the same reason.
for _proxy_key in (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
):
    os.environ.pop(_proxy_key, None)

# The two packages below are only importable once the sys.path shim above has run
# -- which is why this file, not the individual test modules, owns both the shim
# and these doubles (T-2's `domain/` and T-3's `providers/base.py` both already
# exist by the time this module is imported).
import domain  # noqa: E402
import providers.base as providers_base  # noqa: E402


# --- Segment/Transcript builder (T-5) ----------------------------------------------


def make_segments(
    count: int, *, text: Callable[[int], str] = lambda i: f"segment {i}"
) -> Tuple["domain.Segment", ...]:
    """Builds `count` evenly-spaced 900ms-long segments (100ms gaps between them,
    1000ms apart start-to-start) with per-index text from `text(i)` -- for T-5+'s
    `formats/` tests, which routinely need many segments of varying length without
    writing each one out by hand."""
    return tuple(domain.Segment(start_ms=i * 1000, duration_ms=900, text=text(i)) for i in range(count))


# --- Provider port test doubles --------------------------------------------------


class FakeSession(providers_base.ProviderSession):
    """A `ProviderSession` double. `fetch_calls` records every `(track, deadline)`
    pair passed to `fetch()`, in order, for call-counting assertions (AC-23)."""

    def __init__(
        self,
        listing: "domain.TrackListing",
        transcripts: Optional[Mapping[str, "domain.Transcript"]] = None,
        *,
        fetch_error: Optional[BaseException] = None,
    ) -> None:
        self.listing = listing
        self._transcripts: Mapping[str, "domain.Transcript"] = transcripts or {}
        self._fetch_error = fetch_error
        self.fetch_calls: List[Tuple["domain.TrackDescriptor", "domain.Deadline"]] = []

    def fetch(
        self, track: "domain.TrackDescriptor", deadline: "domain.Deadline"
    ) -> "domain.Transcript":
        self.fetch_calls.append((track, deadline))
        if track not in self.listing.tracks:
            raise providers_base.UpstreamChanged(
                "fetch() called with a track not in this session's listing"
            )
        if self._fetch_error is not None:
            raise self._fetch_error
        return self._transcripts[track.track_id]


class FakeProvider(providers_base.TranscriptProvider):
    """A `TranscriptProvider` double. `open_calls` records every `(video_id,
    deadline)` pair passed to `open()`, in order."""

    def __init__(
        self,
        *,
        normalize_result: Optional["domain.VideoId"] = None,
        session: Optional[FakeSession] = None,
        open_error: Optional[BaseException] = None,
    ) -> None:
        self._normalize_result = normalize_result
        self._session = session
        self._open_error = open_error
        self.open_calls: List[Tuple["domain.VideoId", "domain.Deadline"]] = []

    def normalize_video_ref(self, value: str) -> Optional["domain.VideoId"]:
        return self._normalize_result

    def open(
        self, video_id: "domain.VideoId", deadline: "domain.Deadline"
    ) -> providers_base.ProviderSession:
        self.open_calls.append((video_id, deadline))
        if self._open_error is not None:
            raise self._open_error
        if self._session is None:
            raise AssertionError("FakeProvider.open() called with no session configured")
        return self._session


# --- Transport doubles (T-6a/T-6b's net/client.py::fetch(), not yet implemented) -


class _FakeHTTPResponse:
    """Minimal stand-in for the object `urllib.request.urlopen()` returns on
    success (`http.client.HTTPResponse`) -- just enough surface (`.status`,
    `.headers`, `.read()`, context-manager protocol) for `fetch()` to consume,
    without a real socket."""

    def __init__(
        self, body: bytes, *, status: int = 200, headers: Optional[Mapping[str, str]] = None
    ) -> None:
        self._body = body
        self.status = status
        self.code = status
        message = email.message.Message()
        for key, value in (headers or {}).items():
            message[key] = value
        self.headers = message

    def read(self, amt: Optional[int] = None) -> bytes:
        if amt is None:
            data, self._body = self._body, b""
            return data
        data, self._body = self._body[:amt], self._body[amt:]
        return data

    def close(self) -> None:
        pass

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def http_error(
    url: str,
    code: int,
    *,
    msg: str = "",
    headers: Optional[Mapping[str, str]] = None,
    body: bytes = b"",
) -> urllib.error.HTTPError:
    """Builds a real `urllib.error.HTTPError` -- itself `HTTPResponse`-like, and what
    `urlopen()` actually raises on a non-2xx status -- with a `.read()`-able `fp`,
    for T-6a/T-6b's redirect/429/5xx-mapping tests."""
    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(url, code, msg, message, io.BytesIO(body))


def mock_urlopen(
    responses: Sequence[Union[_FakeHTTPResponse, BaseException]],
) -> Tuple[Callable[..., _FakeHTTPResponse], List[Any]]:
    """Returns `(fake_urlopen, calls)`. `fake_urlopen(request, *a, **kw)` pops the
    next entry from `responses` (an `_FakeHTTPResponse`, or an exception instance to
    raise) in call order; `calls` records every request object it was invoked with,
    in order -- for T-6a/T-6b's call-counting (AC-23) and retry-path (AC-22)
    assertions."""
    queue: List[Union[_FakeHTTPResponse, BaseException]] = list(responses)
    calls: List[Any] = []

    def fake_urlopen(request: Any, *args: Any, **kwargs: Any) -> _FakeHTTPResponse:
        calls.append(request)
        if not queue:
            raise AssertionError("mock_urlopen: no more responses queued")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return fake_urlopen, calls


__all__: List[str] = [
    "FakeProvider",
    "FakeSession",
    "http_error",
    "make_segments",
    "mock_urlopen",
]

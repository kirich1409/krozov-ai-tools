"""T-14 request-budget/timing tests: the request-COUNT half of AC-23, dispatched
through the real, fully-wired stack (`composition.build_provider()` -> `server.
build_registry()` -> `protocol.dispatch.handle_message()`), never a bare `net.
client.fetch()` call in isolation (that's `tests/test_net_client_resources.py`'s
job, T-6b) and never global `time`/`random` monkeypatching -- every timing/retry
knob here is injected through `build_provider(sleep=, jitter=)`, the concrete seam
T-13b's `composition.py` exists to provide.

Every assertion below is **exact** (`assertEqual`, never `assertLessEqual`) --
tasks.md's T-14 acceptance is explicit that a weaker "at most N requests" bound
would be silently satisfied by an implementation that never retries at all, which
is exactly the kind of regression this file exists to catch. Both timing
assertions use `math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)`, with
both tolerance arguments always named explicitly -- `math.isclose`'s non-zero
default `rel_tol` would otherwise dominate the comparison at this magnitude,
silently widening the tolerance past what "exact" is supposed to mean (the same
cycle-7 fix `test_net_client_resources.py` already applies).
"""

import json
import math
import unittest
from typing import Any, Dict, List, Sequence, Tuple, Union
from unittest.mock import patch

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim -- see _helpers.py's module docstring.

import composition
import net.client as net_client
import protocol.dispatch as dispatch
import server
from _helpers import _FakeHTTPResponse, http_error
from protocol.registry import Registry

_VIDEO_ID_STR = "dQw4w9WgXcQ"

# The one place this file hardcodes a magnitude rather than deriving it from a
# constant -- plan.md's own worked example pins this exact value for the
# "response arrives just under the attempt's own timeout" scenario (identical to
# `test_net_client_resources.py`'s own `_EPSILON`).
_EPSILON = 0.01

# Matches `net/client.py::fetch`'s own `transport.jitter(0, 0.25)` call -- every
# timing test here pins `jitter` to this exact upper bound so the backoff
# component of every exact-timing assertion is deterministic, never flaky against
# real randomness (T-6b's own convention, `test_net_client_resources.py`).
_JITTER_UPPER_BOUND = 0.25


# --- _FakeClock / injected Transport ----------------------------------------------


class _FakeClock:
    """An injectable clock: `now()` returns the current fake time, `advance()`
    moves it forward -- never real wall-clock time. The same instance drives both
    `server.build_registry(..., clock=clock.now)`'s whole-invocation `Deadline`
    and the `Transport.sleep` backoff below, so every phase of one dispatched call
    shares one consistent fake timeline."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _fake_sleep_jitter(clock: _FakeClock) -> Tuple[Any, Any]:
    """Returns `(sleep, jitter)` -- `sleep` advances the same fake clock the
    `Deadline` reads from (backoff modeled as elapsed time, never a real wait),
    `jitter` is pinned to `_JITTER_UPPER_BOUND`. Passed straight into
    `composition.build_provider(sleep=, jitter=)` -- T-13b's own concrete
    injection seam, never global `time.sleep`/`random.uniform` monkeypatching."""

    def fake_sleep(seconds: float) -> None:
        clock.advance(seconds)

    def fake_jitter(low: float, high: float) -> float:
        del low, high
        return _JITTER_UPPER_BOUND

    return fake_sleep, fake_jitter


def _build_registry_with_injected_clock(clock: _FakeClock) -> Registry:
    sleep, jitter = _fake_sleep_jitter(clock)
    provider = composition.build_provider(sleep=sleep, jitter=jitter)
    return server.build_registry(provider, clock=clock.now)


# --- Fixture bodies (verbatim shape from test_composition.py's own end-to-end
# request-count tests, T-13b) ------------------------------------------------------


def _watch_page_html(api_key: str = "TEST_INNERTUBE_API_KEY") -> str:
    return (
        "<html><head></head><body><script>"
        'var ytInitialPlayerResponse = {"videoDetails": {"videoId": "stub"}};'
        "</script>"
        "<script>"
        f'ytcfg.set({{"INNERTUBE_API_KEY":"{api_key}","INNERTUBE_CONTEXT":{{}}}});'
        "</script></body></html>"
    )


def _player_response_with_one_caption_track() -> Dict[str, Any]:
    return {
        "playabilityStatus": {"status": "OK"},
        "videoDetails": {"lengthSeconds": "600"},
        "captions": {
            "playerCaptionsTracklistRenderer": {
                "captionTracks": [
                    {
                        "baseUrl": "https://www.youtube.com/api/timedtext?v=x&lang=en",
                        "languageCode": "en",
                        "name": {"simpleText": "English"},
                    }
                ]
            }
        },
    }


def _timedtext_xml() -> bytes:
    return b'<timedtext format="3"><body><p t="0" d="900">hello world</p></body></timedtext>'


def _watch_response() -> _FakeHTTPResponse:
    return _FakeHTTPResponse(_watch_page_html().encode("utf-8"))


def _player_response() -> _FakeHTTPResponse:
    return _FakeHTTPResponse(json.dumps(_player_response_with_one_caption_track()).encode("utf-8"))


def _timedtext_response() -> _FakeHTTPResponse:
    return _FakeHTTPResponse(_timedtext_xml())


def _leg_fail_then_succeed(success: _FakeHTTPResponse) -> List[Tuple[float, Union[_FakeHTTPResponse, BaseException]]]:
    """One leg's plan for the "fails once (5xx, first attempt), succeeds on retry,
    fast -- not a timeout" scenario: no clock advance on either attempt (a 5xx
    response and its retry both arrive quickly), so this contributes ~0s to the
    total elapsed time -- only the backoff sleep between them costs real (fake)
    time."""
    return [
        (0.0, http_error("https://www.youtube.com/x", 500)),
        (0.0, success),
    ]


def _leg_timeout_then_succeed_with_margin(
    success: _FakeHTTPResponse,
) -> List[Tuple[float, Union[_FakeHTTPResponse, BaseException]]]:
    """One leg's plan for the "worst-case-still-succeeds" scenario: the first
    attempt times out (consumes a full `HTTP_TIMEOUT`), the retry succeeds just
    under its own timeout (`HTTP_TIMEOUT - _EPSILON`)."""
    return [
        (net_client.HTTP_TIMEOUT, TimeoutError("simulated attempt timeout")),
        (net_client.HTTP_TIMEOUT - _EPSILON, success),
    ]


# --- _ScriptedOpener: stands in for `net.client._OPENER` --------------------------
#
# Identical mechanism to `test_net_client_resources.py`'s own `_ScriptedOpener` --
# duplicated here rather than imported (this test suite's established convention:
# every test module is self-contained, sharing only `_helpers.py`; see this
# repo's other test files, none of which import from a sibling test module).


class _ScriptedOpener:
    def __init__(
        self,
        clock: _FakeClock,
        plan: Sequence[Tuple[float, Union[_FakeHTTPResponse, BaseException]]],
    ) -> None:
        self._clock = clock
        self._plan: List[Tuple[float, Union[_FakeHTTPResponse, BaseException]]] = list(plan)
        self.calls: List[Any] = []

    def open(self, request: Any, *, timeout: Any = None) -> _FakeHTTPResponse:
        del timeout
        self.calls.append(request)
        if not self._plan:
            raise AssertionError("_ScriptedOpener: no more planned outcomes queued")
        advance, outcome = self._plan.pop(0)
        self._clock.advance(advance)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _tools_call_message(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }


def _dispatch(registry: Any, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    response = dispatch.handle_message(registry, _tools_call_message(tool_name, arguments))
    assert response is not None
    return json.loads(response["result"]["content"][0]["text"])


# --- test_exact_six_on_fast_failure_retry -----------------------------------------


class TestExactSixOnFastFailureRetry(unittest.TestCase):
    def test_exact_six_on_fast_failure_retry(self) -> None:
        """Every one of `get_transcript`'s 3 legs (watch page, player, timedtext)
        fails once (5xx, first attempt) and succeeds on retry (fast, not a
        timeout) -- a non-paginated `get_transcript` run issues EXACTLY 6
        requests, never "at most 6"."""
        clock = _FakeClock()
        registry = _build_registry_with_injected_clock(clock)
        plan: List[Tuple[float, Union[_FakeHTTPResponse, BaseException]]] = []
        plan += _leg_fail_then_succeed(_watch_response())
        plan += _leg_fail_then_succeed(_player_response())
        plan += _leg_fail_then_succeed(_timedtext_response())
        opener = _ScriptedOpener(clock, plan)

        with patch.object(net_client, "_OPENER", new=opener):
            payload = _dispatch(registry, "get_transcript", {"video": _VIDEO_ID_STR})

        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(len(opener.calls), 6)


# --- test_exact_four_list_tracks_fast_failure -------------------------------------


class TestExactFourListTracksFastFailure(unittest.TestCase):
    def test_exact_four_list_tracks_fast_failure(self) -> None:
        """The equivalent scenario for `list_transcript_tracks`'s 2 legs (watch
        page, player -- it never fetches the timedtext leg, T-11): EXACTLY 4
        requests, never "at most 4"."""
        clock = _FakeClock()
        registry = _build_registry_with_injected_clock(clock)
        plan: List[Tuple[float, Union[_FakeHTTPResponse, BaseException]]] = []
        plan += _leg_fail_then_succeed(_watch_response())
        plan += _leg_fail_then_succeed(_player_response())
        opener = _ScriptedOpener(clock, plan)

        with patch.object(net_client, "_OPENER", new=opener):
            payload = _dispatch(registry, "list_transcript_tracks", {"video": _VIDEO_ID_STR})

        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(len(opener.calls), 4)


# --- test_early_exit_leg1_timeout_two_requests ------------------------------------


class TestEarlyExitLeg1TimeoutTwoRequests(unittest.TestCase):
    def test_early_exit_leg1_timeout_two_requests(self) -> None:
        """Leg 1 (watch page) fails all `HTTP_MAX_ATTEMPTS` attempts by timeout
        -> `get_transcript` fails at EXACTLY `HTTP_TIMEOUT + backoff_delay +
        HTTP_TIMEOUT` (computed from the actual imported constants, never a
        hardcoded decimal) with EXACTLY 2 requests issued, never reaching legs
        2/3 -- an unplanned third `.open()` call would raise `AssertionError`
        from `_ScriptedOpener` itself, not just fail a count assertion."""
        clock = _FakeClock()
        registry = _build_registry_with_injected_clock(clock)
        opener = _ScriptedOpener(
            clock,
            [
                (net_client.HTTP_TIMEOUT, TimeoutError("simulated attempt timeout")),
                (net_client.HTTP_TIMEOUT, TimeoutError("simulated attempt timeout")),
            ],
        )

        with patch.object(net_client, "_OPENER", new=opener):
            payload = _dispatch(registry, "get_transcript", {"video": _VIDEO_ID_STR})

        self.assertEqual(payload["status"], "transport_error", payload)
        self.assertEqual(len(opener.calls), 2)

        backoff_delay = 0.5 * (2**1) + _JITTER_UPPER_BOUND  # net/client.py's own retry formula
        expected_total = net_client.HTTP_TIMEOUT + backoff_delay + net_client.HTTP_TIMEOUT
        self.assertTrue(
            math.isclose(clock.now(), expected_total, rel_tol=0.0, abs_tol=1e-9),
            (clock.now(), expected_total),
        )


# --- test_worst_case_all_legs_retry_succeeds_with_margin --------------------------


class TestWorstCaseAllLegsRetrySucceedsWithMargin(unittest.TestCase):
    def test_worst_case_all_legs_retry_succeeds_with_margin(self) -> None:
        """All 3 legs fail their first attempt by timeout; each retry responds at
        `t = HTTP_TIMEOUT - EPSILON` into the retry -> the whole call succeeds at
        EXACTLY `3 * (HTTP_TIMEOUT + backoff_delay + (HTTP_TIMEOUT - EPSILON))`
        with EXACTLY 6 requests."""
        clock = _FakeClock()
        registry = _build_registry_with_injected_clock(clock)
        plan: List[Tuple[float, Union[_FakeHTTPResponse, BaseException]]] = []
        plan += _leg_timeout_then_succeed_with_margin(_watch_response())
        plan += _leg_timeout_then_succeed_with_margin(_player_response())
        plan += _leg_timeout_then_succeed_with_margin(_timedtext_response())
        opener = _ScriptedOpener(clock, plan)

        with patch.object(net_client, "_OPENER", new=opener):
            payload = _dispatch(registry, "get_transcript", {"video": _VIDEO_ID_STR})

        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(len(opener.calls), 6)

        backoff_delay = 0.5 * (2**1) + _JITTER_UPPER_BOUND
        per_leg = net_client.HTTP_TIMEOUT + backoff_delay + (net_client.HTTP_TIMEOUT - _EPSILON)
        expected_total = 3 * per_leg
        self.assertTrue(
            math.isclose(clock.now(), expected_total, rel_tol=0.0, abs_tol=1e-9),
            (clock.now(), expected_total),
        )


if __name__ == "__main__":
    unittest.main()

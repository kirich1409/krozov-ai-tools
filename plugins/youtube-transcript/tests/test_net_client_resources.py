"""Tests for `net/client.py`'s T-6b resource controls: header merge, retry/backoff
(floor + clamp, both backoff-inclusive), the byte cap, the cumulative gzip-bomb
cap, the streaming network-budget deadline check, and the XML guard
(`parse_xml_guarded`).

Every timing test here uses an injected `Deadline` clock (`_FakeClock`, a plain
advance-then-return counter) and a pinned `jitter` (always returns its upper
bound, `0.25`) -- never real `time.sleep`/unpinned `random`, per the brief's hard
CI-cost + flakiness constraint. `_ScriptedOpener` stands in for `client._OPENER`
the same way `test_net_client_policy.py`'s `_FakeOpener` does, except each queued
outcome also carries how much fake-clock time that attempt "consumed" -- the
plan's own "nominal k=1" mock-transport model (plan.md's honest scope note: this
suite only ever exercises one clock-advance per attempt, not several blocking
operations within one attempt).
"""

import math
import os
import unittest
from typing import Any, List, Optional, Sequence, Tuple, Union
from unittest.mock import patch

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim -- see _helpers.py's module docstring.

import net.client as client
from _helpers import _FakeHTTPResponse, http_error

# The one place this file hardcodes a magnitude rather than deriving it from a
# constant: plan.md's own worked example pins this exact value for the
# "response arrives just under the attempt's own timeout" scenario.
_EPSILON = 0.01

_FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fixture_path(name: str) -> str:
    return os.path.join(_FIXTURES_DIR, name)


class _FakeClock:
    """An injectable `Deadline` clock: `now()` returns the current fake time,
    `advance(seconds)` moves it forward -- never real wall-clock time."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _fake_transport(clock: _FakeClock, *, jitter_value: float = 0.25) -> Tuple[client.Transport, List[float]]:
    """A `Transport` whose `sleep` advances the SAME fake clock the test's
    `Deadline` reads from (modeling backoff as elapsed time, never a real
    wait), and whose `jitter` is pinned to `jitter_value` -- every timing test
    below pins this to `0.25`, `jitter(0, 0.25)`'s upper bound, so an
    exact-backoff assertion is never flaky against real randomness."""
    sleeps: List[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    def fake_jitter(low: float, high: float) -> float:
        del low, high
        return jitter_value

    return client.Transport(sleep=fake_sleep, jitter=fake_jitter), sleeps


_Outcome = Union[_FakeHTTPResponse, BaseException]


class _ScriptedOpener:
    """Stands in for `client._OPENER`. `plan` is consumed in call order, one
    `(clock_advance_seconds, outcome)` pair per `.open()` call: `outcome` is
    either an `_FakeHTTPResponse` (or a real `HTTPError` built by
    `_helpers.http_error`) to return, or any other exception instance to raise.
    Advancing the clock BEFORE returning/raising models the wall-clock time one
    whole blocking attempt would have consumed."""

    def __init__(self, clock: _FakeClock, plan: Sequence[Tuple[float, _Outcome]]) -> None:
        self._clock = clock
        self._plan: List[Tuple[float, _Outcome]] = list(plan)
        self.calls: List[Tuple[Any, Optional[float]]] = []

    def open(self, request: Any, *, timeout: Optional[float] = None) -> _FakeHTTPResponse:
        self.calls.append((request, timeout))
        if not self._plan:
            raise AssertionError("_ScriptedOpener: no more planned outcomes queued")
        advance, outcome = self._plan.pop(0)
        self._clock.advance(advance)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _request_header(request: Any, name: str) -> Optional[str]:
    """Case-insensitive header lookup against an actual `urllib.request.Request`
    -- `Request.get_header()` itself is case-SENSITIVE against whatever
    `add_header()`'s own `str.capitalize()` normalized the key to (empirically:
    `"Accept-Encoding".capitalize()` is `"Accept-encoding"`, not `.title()`'s
    `"Accept-Encoding"`), so asserting on the wire-real request object needs its
    own case-insensitive lookup rather than relying on that quirk."""
    for key, value in request.header_items():
        if key.lower() == name.lower():
            return value
    return None


def _generous_deadline(clock: _FakeClock) -> "client.Deadline":
    """A `Deadline` with far more budget than any single test below could
    plausibly exhaust -- for tests that aren't themselves about the floor/clamp
    arithmetic."""
    return client.Deadline.start(client.ENCODE_RESERVE + 1000.0, clock=clock.now)


class TestRawReadCap(unittest.TestCase):
    def test_raw_read_cap(self) -> None:
        clock = _FakeClock()
        deadline = _generous_deadline(clock)
        with patch.object(client, "HTTP_MAX_RESPONSE_BYTES", 10):
            response = _FakeHTTPResponse(b"x" * 20)
            with self.assertRaises(client.ResponseTooLarge):
                client._read_capped_body(response, deadline)
            # Streaming, not read-then-check: the loop never requests more than
            # cap + 1 bytes cumulative across every `.read(n)` call -- proven by
            # replaying the same sequence of `read` calls against a second fake
            # and summing exactly what was requested each time.
            requested_total = 0
            probe = _FakeHTTPResponse(b"x" * 20)
            real_read = probe.read

            def counting_read(amt: "Optional[int]" = None) -> bytes:
                nonlocal requested_total
                assert amt is not None
                requested_total += amt
                return real_read(amt)

            probe.read = counting_read  # type: ignore[method-assign]
            with self.assertRaises(client.ResponseTooLarge):
                client._read_capped_body(probe, _generous_deadline(_FakeClock()))
            self.assertLessEqual(requested_total, 11)  # cap(10) + 1


class TestGzipBombCumulativeCap(unittest.TestCase):
    def test_gzip_bomb_cumulative_cap(self) -> None:
        # Black-box: the committed fixture is ~2KB compressed, ~2MB decompressed
        # -- a small cap set well under the inflated size must engage.
        fixture_path = _fixture_path("gzip_bomb.bin")
        with open(fixture_path, "rb") as f:
            bomb = f.read()
        with self.assertRaises(client.ResponseTooLarge):
            client._inflate_gzip_capped(bomb, cap=1000)

        # White-box: the cap is tracked CUMULATIVELY across every
        # `decompressobj().decompress()` call (including `unconsumed_tail`
        # continuations), not as a per-call peak. Scripted so that NEITHER
        # individual call's own output (6 bytes each) exceeds `cap=10` alone --
        # a per-call-peak check would wrongly let this pass -- but the running
        # total across both calls (12 bytes) does, which is exactly the defect
        # class this cumulative tracking exists to catch.
        class _ScriptedDecompressor:
            def __init__(self) -> None:
                self._script = [(b"A" * 6, b"more-input-pending"), (b"B" * 6, b"")]
                self.unconsumed_tail = b""

            def decompress(self, data: bytes, max_length: int) -> bytes:
                del data, max_length
                output, tail = self._script.pop(0)
                self.unconsumed_tail = tail
                return output

            def flush(self) -> bytes:
                return b""

        fake = _ScriptedDecompressor()
        with patch.object(client.zlib, "decompressobj", return_value=fake), self.assertRaises(
            client.ResponseTooLarge
        ):
            client._inflate_gzip_capped(b"irrelevant-compressed-bytes", cap=10)


class _DrippingResponse:
    """`.read()` never returns EOF -- only the per-chunk deadline check inside
    `_read_capped_body` ends this -- and advances `clock` by `interval` on every
    call, simulating one blocking recv per chunk. `clock`/`interval` are taken
    as constructor arguments (not closed over from an enclosing loop) so this
    class is safe to instantiate fresh on each iteration of a parametrized loop."""

    def __init__(self, clock: _FakeClock, interval: float) -> None:
        self._clock = clock
        self._interval = interval
        self.status = 200
        self.headers: dict = {}

    def read(self, amt: Optional[int] = None) -> bytes:
        del amt
        self._clock.advance(self._interval)
        return b"x"

    def __enter__(self) -> "_DrippingResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass


class TestSlowDripBodyPhaseAbortsWithinBudgetPlusHttpTimeout(unittest.TestCase):
    def test_slow_drip_body_phase_aborts_within_budget_plus_http_timeout(self) -> None:
        for interval in (0.5, 4, 7.5, 14.99):
            with self.subTest(interval=interval):
                clock = _FakeClock()
                network_budget_remaining_initial = 10.0
                deadline = client.Deadline.start(
                    client.ENCODE_RESERVE + network_budget_remaining_initial, clock=clock.now
                )

                with self.assertRaises(client.TransportFailed):
                    client._read_capped_body(_DrippingResponse(clock, interval), deadline)

                # Bound from plan.md's Technical Approach: abort no later than
                # `network_budget_remaining + HTTP_TIMEOUT` (the one extra
                # `HTTP_TIMEOUT` covers the single in-flight read that could
                # still be "blocking" when the budget ran out -- every tested
                # interval is itself < HTTP_TIMEOUT, matching a real per-recv
                # socket operation that could never legitimately run longer
                # without its own socket timeout firing first).
                self.assertLessEqual(
                    clock.now(),
                    network_budget_remaining_initial + client.HTTP_TIMEOUT,
                )


_TIMEDTEXT_SAMPLE = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<timedtext format="3">'
    b'<body>'
    b'<p t="0" d="900">Hello</p>'
    b'<p t="1000" d="900">World</p>'
    b"</body>"
    b"</timedtext>"
)


class TestDoctypeAscii(unittest.TestCase):
    def test_doctype_ascii(self) -> None:
        with open(_fixture_path("doctype_ascii.xml"), "rb") as f:
            data = f.read()
        with self.assertRaises(client.MalformedUpstream):
            client.parse_xml_guarded(data)


class TestDoctypeUtf16(unittest.TestCase):
    def test_doctype_utf16(self) -> None:
        with open(_fixture_path("doctype_utf16.xml"), "rb") as f:
            data = f.read()
        with self.assertRaises(client.MalformedUpstream):
            client.parse_xml_guarded(data)


def _read_fixture(name: str) -> bytes:
    with open(_fixture_path(name), "rb") as f:
        return f.read()


class TestDoctypeMapsToMalformedUpstream(unittest.TestCase):
    def test_doctype_maps_to_malformed_upstream(self) -> None:
        # Both the sentinel path (a DOCTYPE/entity declaration, either fixture
        # above) and genuinely malformed XML (expat's own ExpatError -- a
        # mismatched/truncated tag, no DOCTYPE involved at all) map to the
        # SAME exception type -- proving the type mapping itself, not just
        # that "some exception" is raised on the doctype fixtures specifically.
        for data in (
            _read_fixture("doctype_ascii.xml"),
            _read_fixture("doctype_utf16.xml"),
            b"<timedtext><body><p>unterminated",  # expat.ExpatError, no DOCTYPE
        ):
            with self.subTest(data=data[:40]), self.assertRaises(client.MalformedUpstream):
                client.parse_xml_guarded(data)


class TestXmlTagNamesNonNamespaced(unittest.TestCase):
    def test_xml_tag_names_non_namespaced(self) -> None:
        root = client.parse_xml_guarded(_TIMEDTEXT_SAMPLE)
        self.assertEqual(root.tag, "timedtext")
        self.assertEqual(root.attrib.get("format"), "3")
        body = list(root)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0].tag, "body")
        cues = list(body[0])
        self.assertEqual([cue.tag for cue in cues], ["p", "p"])
        self.assertEqual([cue.text for cue in cues], ["Hello", "World"])
        self.assertEqual(cues[0].attrib, {"t": "0", "d": "900"})


class TestSingleLegRetrySuccessTotalComputedFromConstants(unittest.TestCase):
    def test_single_leg_retry_success_total_computed_from_constants(self) -> None:
        clock = _FakeClock()
        transport, sleeps = _fake_transport(clock)
        deadline = client.Deadline.start(client.ENCODE_RESERVE + 100.0, clock=clock.now)
        opener = _ScriptedOpener(
            clock,
            [
                (client.HTTP_TIMEOUT, TimeoutError("simulated attempt timeout")),
                (client.HTTP_TIMEOUT - _EPSILON, _FakeHTTPResponse(b"ok", status=200)),
            ],
        )
        with patch.object(client, "_OPENER", new=opener):
            response = client.fetch(
                "https://www.youtube.com/x", deadline=deadline, transport=transport
            )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b"ok")
        self.assertEqual(len(opener.calls), 2)

        backoff_delay = 0.5 * (2**1) + 0.25
        expected_total = client.HTTP_TIMEOUT + backoff_delay + (client.HTTP_TIMEOUT - _EPSILON)
        self.assertTrue(
            math.isclose(clock.now(), expected_total, rel_tol=0.0, abs_tol=1e-9),
            (clock.now(), expected_total),
        )
        self.assertEqual(sleeps, [backoff_delay])
        # No leg's clamp truncates below HTTP_TIMEOUT in this scenario --
        # remaining_after_backoff stays comfortably above HTTP_TIMEOUT for both
        # attempts at this budget.
        for _request, timeout in opener.calls:
            assert timeout is not None
            self.assertTrue(math.isclose(timeout, client.HTTP_TIMEOUT, rel_tol=0.0, abs_tol=1e-9))


class TestClampTruncatesBelowHttpTimeout(unittest.TestCase):
    def test_clamp_truncates_below_http_timeout(self) -> None:
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        # First attempt (no backoff): remaining_after_backoff == 5.5s < HTTP_TIMEOUT.
        deadline = client.Deadline.start(client.ENCODE_RESERVE + 5.5, clock=clock.now)
        opener = _ScriptedOpener(clock, [(0.0, _FakeHTTPResponse(b"ok"))])
        with patch.object(client, "_OPENER", new=opener):
            client.fetch("https://www.youtube.com/x", deadline=deadline, transport=transport)
        self.assertEqual(len(opener.calls), 1)
        _request, timeout = opener.calls[0]
        assert timeout is not None
        self.assertTrue(math.isclose(timeout, 5.5, rel_tol=0.0, abs_tol=1e-9))
        self.assertLess(timeout, client.HTTP_TIMEOUT)


class TestFloorFormulaBoundaryCase(unittest.TestCase):
    def test_floor_formula_boundary_case(self) -> None:
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)

        # remaining_after_backoff = MIN_ATTEMPT_TIMEOUT - 0.5s -- fails fast,
        # opener never reached (an unplanned `.open()` call raises
        # AssertionError from `_ScriptedOpener`, not `TransportFailed`, so this
        # also proves the opener is never touched, not just that some
        # exception fired).
        below_deadline = client.Deadline.start(
            client.ENCODE_RESERVE + (client.MIN_ATTEMPT_TIMEOUT - 0.5), clock=clock.now
        )
        below_opener = _ScriptedOpener(clock, [])
        with patch.object(client, "_OPENER", new=below_opener), self.assertRaises(
            client.TransportFailed
        ):
            client.fetch("https://www.youtube.com/x", deadline=below_deadline, transport=transport)
        self.assertEqual(len(below_opener.calls), 0)

        # remaining_after_backoff = MIN_ATTEMPT_TIMEOUT + 0.5s -- proceeds.
        clock2 = _FakeClock()
        transport2, _sleeps2 = _fake_transport(clock2)
        above_deadline = client.Deadline.start(
            client.ENCODE_RESERVE + (client.MIN_ATTEMPT_TIMEOUT + 0.5), clock=clock2.now
        )
        above_opener = _ScriptedOpener(clock2, [(0.0, _FakeHTTPResponse(b"ok"))])
        with patch.object(client, "_OPENER", new=above_opener):
            response = client.fetch(
                "https://www.youtube.com/x", deadline=above_deadline, transport=transport2
            )
        self.assertEqual(response.status, 200)
        self.assertEqual(len(above_opener.calls), 1)


class TestRetryBudgetAndBackoffWithPinnedMaxJitter(unittest.TestCase):
    def test_retry_budget_and_backoff_with_pinned_max_jitter(self) -> None:
        clock = _FakeClock()
        transport, sleeps = _fake_transport(clock, jitter_value=0.25)
        deadline = client.Deadline.start(client.ENCODE_RESERVE + 100.0, clock=clock.now)
        opener = _ScriptedOpener(
            clock,
            [
                (0.0, TimeoutError("simulated attempt timeout")),
                (0.0, _FakeHTTPResponse(b"ok")),
            ],
        )
        with patch.object(client, "_OPENER", new=opener):
            client.fetch("https://www.youtube.com/x", deadline=deadline, transport=transport)

        expected_backoff = 0.5 * (2**1) + 0.25  # 1.25s, jitter pinned to its upper bound
        self.assertEqual(len(sleeps), 1)
        self.assertTrue(math.isclose(sleeps[0], expected_backoff, rel_tol=0.0, abs_tol=1e-9))
        self.assertTrue(math.isclose(expected_backoff, 1.25, rel_tol=0.0, abs_tol=1e-9))


class Test429NoRetryConsumed(unittest.TestCase):
    def test_429_no_retry_consumed(self) -> None:
        clock = _FakeClock()
        transport, sleeps = _fake_transport(clock)
        deadline = _generous_deadline(clock)
        opener = _ScriptedOpener(
            clock,
            [(0.0, http_error("https://www.youtube.com/x", 429, headers={"Retry-After": "30"}))],
        )
        with patch.object(client, "_OPENER", new=opener), self.assertRaises(client.Throttled) as cm:
            client.fetch("https://www.youtube.com/x", deadline=deadline, transport=transport)
        self.assertEqual(cm.exception.retry_after, 30)
        # No retry attempt consumed -- exactly one opener call, no backoff sleep.
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(sleeps, [])


class TestLogRedactsQueryString(unittest.TestCase):
    def test_log_redacts_query_string(self) -> None:
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = client.Deadline.start(client.ENCODE_RESERVE + 100.0, clock=clock.now)
        url = "https://www.youtube.com/api/timedtext?pot=ABC123&sig=DEF456"
        opener = _ScriptedOpener(
            clock,
            [
                (0.0, http_error(url, 500)),
                (0.0, http_error(url, 500)),
            ],
        )
        with patch.object(client, "_OPENER", new=opener), self.assertLogs(
            "net.client", level="DEBUG"
        ) as cm, self.assertRaises(client.TransportFailed):
            client.fetch(url, deadline=deadline, transport=transport)

        full_log = "\n".join(cm.output)
        self.assertNotIn("pot=", full_log)
        self.assertNotIn("sig=", full_log)
        self.assertNotIn("ABC123", full_log)
        self.assertNotIn("DEF456", full_log)
        self.assertIn("https://www.youtube.com/api/timedtext", full_log)


class TestPolicyRejectionIsLoggedAndRedacted(unittest.TestCase):
    """Security-review fix pass (T-6-secfix), finding 2: `_check_policy`'s three
    `PolicyRejected` raises used to bypass `_log_and_raise` entirely, since
    `_check_policy` runs before `fetch()`'s own `try` block -- a DEBUG-level log
    handler captured nothing on a scheme rejection (confirmed empirically, brief's
    finding 2). Uses a `?pot=...&sig=...`-shaped query string (same shape as
    `TestLogRedactsQueryString` above) to also cover the brief's redaction
    constraint for this newly-routed log entry specifically."""

    def test_policy_rejection_logs_redacted_entry(self) -> None:
        url = "http://www.youtube.com/api/timedtext?pot=ABC123&sig=DEF456"
        with self.assertLogs("net.client", level="DEBUG") as cm, self.assertRaises(
            client.PolicyRejected
        ):
            client.fetch(url)

        full_log = "\n".join(cm.output)
        self.assertNotIn("pot=", full_log)
        self.assertNotIn("sig=", full_log)
        self.assertNotIn("ABC123", full_log)
        self.assertNotIn("DEF456", full_log)
        self.assertIn("http://www.youtube.com/api/timedtext", full_log)


class TestAcceptEncodingPresentOnEveryRequest(unittest.TestCase):
    def test_accept_encoding_present_on_every_request(self) -> None:
        self.assertEqual(client._merge_headers(None), {"Accept-Encoding": "gzip"})
        self.assertEqual(client._merge_headers({}), {"Accept-Encoding": "gzip"})

        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = _generous_deadline(clock)
        opener = _ScriptedOpener(clock, [(0.0, _FakeHTTPResponse(b"ok"))])
        with patch.object(client, "_OPENER", new=opener):
            client.fetch("https://www.youtube.com/x", deadline=deadline, transport=transport)
        request, _timeout = opener.calls[0]
        self.assertEqual(_request_header(request, "Accept-Encoding"), "gzip")


class TestBaseAcceptEncodingSurvivesCallerOverride(unittest.TestCase):
    def test_base_accept_encoding_survives_caller_override(self) -> None:
        merged = client._merge_headers({"Accept-Encoding": "identity"})
        self.assertEqual(merged["Accept-Encoding"], "gzip")
        # Case-variant spelling of the same header must not create a second
        # entry that survives the merge either (Y-7's `.title()` normalization).
        merged_lower = client._merge_headers({"accept-encoding": "identity"})
        self.assertEqual(merged_lower, {"Accept-Encoding": "gzip"})

        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = _generous_deadline(clock)
        opener = _ScriptedOpener(clock, [(0.0, _FakeHTTPResponse(b"ok"))])
        with patch.object(client, "_OPENER", new=opener):
            client.fetch(
                "https://www.youtube.com/x",
                headers={"Accept-Encoding": "identity"},
                deadline=deadline,
                transport=transport,
            )
        request, _timeout = opener.calls[0]
        self.assertEqual(_request_header(request, "Accept-Encoding"), "gzip")


class TestBaseHeadersAreExactlyAcceptEncoding(unittest.TestCase):
    def test_base_headers_are_exactly_accept_encoding(self) -> None:
        self.assertEqual(dict(client.BASE_HEADERS), {"Accept-Encoding": "gzip"})


# --- Additional coverage: paths not named in T-6b's `check` line but exercised
# for completeness (fallback non-3xx/429/5xx status, transport-error retry
# exhaustion, gzip end-to-end decode through `fetch()`, corrupt gzip body). ---


class TestNonRedirectStatusReadThroughRetryLoop(unittest.TestCase):
    def test_404_status_body_read_through_retry_loop(self) -> None:
        # A non-redirect, non-429, non-5xx status is a received response, not a
        # transport failure -- `fetch()` returns it (status + body) rather than
        # raising, exactly as T-6a's original fallback branch already did.
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = _generous_deadline(clock)
        opener = _ScriptedOpener(
            clock, [(0.0, http_error("https://www.youtube.com/x", 404, body=b"not found"))]
        )
        with patch.object(client, "_OPENER", new=opener):
            response = client.fetch(
                "https://www.youtube.com/x", deadline=deadline, transport=transport
            )
        self.assertEqual(response.status, 404)
        self.assertEqual(response.body, b"not found")


class TestNonRetryableStatusBodyReadFailureIsLogged(unittest.TestCase):
    """Security-review fix pass (T-6-secfix), finding 3: `_read_capped_body(error,
    deadline)`'s call inside the non-redirect/429/5xx fallback branch above (e.g.
    404) is nested inside `fetch()`'s own `except urllib.error.HTTPError` clause --
    a `ResponseTooLarge`/`TransportFailed` raised there used to propagate straight
    out of `fetch()` unlogged, since Python does not re-dispatch an exception
    raised inside one except-block to a sibling except-clause of the same `try`
    (confirmed empirically, brief's finding 3). Both bodies below are logged
    (asserted via `assertLogs`) as well as correctly raised/typed."""

    def test_error_status_body_read_too_large_is_logged(self) -> None:
        # Oversized: same byte-cap mechanism as `TestResponseTooLargeDuringAttempt
        # IsNeverRetried`, just triggered from inside the 404 fallback branch
        # instead of the success-read path.
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = _generous_deadline(clock)
        opener = _ScriptedOpener(
            clock, [(0.0, http_error("https://www.youtube.com/x", 404, body=b"x" * 20))]
        )
        with patch.object(client, "HTTP_MAX_RESPONSE_BYTES", 10), patch.object(
            client, "_OPENER", new=opener
        ), self.assertLogs("net.client", level="DEBUG") as cm, self.assertRaises(
            client.ResponseTooLarge
        ):
            client.fetch("https://www.youtube.com/x", deadline=deadline, transport=transport)
        self.assertEqual(len(opener.calls), 1)
        self.assertTrue(any("net.fetch failed" in line for line in cm.output))

    def test_error_status_body_read_deadline_exhausted_is_logged(self) -> None:
        # Deadline-exhausted: the network budget is used up by the (fake-clock)
        # time the 404 response itself took to arrive, so `_read_capped_body`'s
        # own first-iteration deadline check fires before it ever calls
        # `.read()` on the error body -- same mechanism as
        # `TestDeadlineExhaustedDuringBodyReadThenFloorBlocksRetry` above, just
        # reached via the non-retryable-status branch instead of the
        # success-read path.
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = client.Deadline.start(client.ENCODE_RESERVE + 20.0, clock=clock.now)
        opener = _ScriptedOpener(
            clock,
            [(25.0, http_error("https://www.youtube.com/x", 404, body=b"not found"))],
        )
        with patch.object(client, "_OPENER", new=opener), self.assertLogs(
            "net.client", level="DEBUG"
        ) as cm, self.assertRaises(client.TransportFailed):
            client.fetch("https://www.youtube.com/x", deadline=deadline, transport=transport)
        self.assertEqual(len(opener.calls), 1)
        self.assertTrue(any("net.fetch failed" in line for line in cm.output))


class TestTransportErrorExhaustsRetryThenRaises(unittest.TestCase):
    def test_transport_error_on_every_attempt_raises_after_retry_exhausted(self) -> None:
        clock = _FakeClock()
        transport, sleeps = _fake_transport(clock)
        deadline = client.Deadline.start(client.ENCODE_RESERVE + 100.0, clock=clock.now)
        opener = _ScriptedOpener(
            clock,
            [
                (0.0, ConnectionResetError("connection reset")),
                (0.0, ConnectionResetError("connection reset")),
            ],
        )
        with patch.object(client, "_OPENER", new=opener), self.assertRaises(
            client.TransportFailed
        ):
            client.fetch("https://www.youtube.com/x", deadline=deadline, transport=transport)
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(len(sleeps), 1)  # backoff before the one retry, none after


class TestDeadlineExhaustedOnLastAttemptBodyReadRaisesDirectly(unittest.TestCase):
    def test_deadline_exhausted_on_last_attempt_body_read_raises_directly(self) -> None:
        # Distinct from the previous test: here the network-budget deadline is
        # exhausted DURING the body read of the already-last attempt (retry
        # already consumed) -- covers `fetch()`'s `except TransportFailed`
        # branch's own terminal `_log_and_raise` call specifically, as opposed
        # to that branch's `continue` path (attempt not yet last) or the
        # separate floor-check raise (a different call site entirely).
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = client.Deadline.start(client.ENCODE_RESERVE + 100.0, clock=clock.now)
        opener = _ScriptedOpener(
            clock,
            [
                (0.0, TimeoutError("simulated attempt timeout")),
                (0.0, _DrippingResponse(clock, 200.0)),
            ],
        )
        with patch.object(client, "_OPENER", new=opener), self.assertRaises(
            client.TransportFailed
        ):
            client.fetch("https://www.youtube.com/x", deadline=deadline, transport=transport)
        self.assertEqual(len(opener.calls), 2)


class TestResponseTooLargeDuringAttemptIsNeverRetried(unittest.TestCase):
    def test_response_too_large_during_attempt_is_never_retried(self) -> None:
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = _generous_deadline(clock)
        opener = _ScriptedOpener(clock, [(0.0, _FakeHTTPResponse(b"x" * 20))])
        with patch.object(client, "HTTP_MAX_RESPONSE_BYTES", 10), patch.object(
            client, "_OPENER", new=opener
        ), self.assertRaises(client.ResponseTooLarge):
            client.fetch("https://www.youtube.com/x", deadline=deadline, transport=transport)
        self.assertEqual(len(opener.calls), 1)


class TestDeadlineExhaustedDuringBodyReadThenFloorBlocksRetry(unittest.TestCase):
    def test_deadline_exhausted_during_body_read_then_floor_blocks_retry(self) -> None:
        # `_read_capped_body`'s own `TransportFailed` (network-budget deadline,
        # not the byte cap) raised on the SUCCESS path inside `fetch()`'s retry
        # loop is caught by `fetch()`'s own `except TransportFailed` branch, not
        # propagated straight through -- covers that branch specifically
        # (distinct from `test_slow_drip_...`'s direct, unit-level exercise of
        # `_read_capped_body` in isolation). Exhausting the network-budget
        # deadline this way necessarily exhausts the SAME budget the floor
        # check reads on the next attempt (same `Deadline`, same clock) -- so
        # the realistic outcome is not "retried and succeeds" but "the retry's
        # own floor check fails immediately, without a second network call",
        # asserted here via `opener.calls == 1`.
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = client.Deadline.start(client.ENCODE_RESERVE + 20.0, clock=clock.now)
        opener = _ScriptedOpener(clock, [(0.0, _DrippingResponse(clock, 25.0))])
        with patch.object(client, "_OPENER", new=opener), self.assertRaises(
            client.TransportFailed
        ):
            client.fetch("https://www.youtube.com/x", deadline=deadline, transport=transport)
        self.assertEqual(len(opener.calls), 1)


class TestGzipResponseDecodedEndToEnd(unittest.TestCase):
    def test_gzip_content_encoding_response_transparently_decompressed(self) -> None:
        import gzip

        original = b"hello transcript body" * 5
        opener_response = _FakeHTTPResponse(
            gzip.compress(original), status=200, headers={"Content-Encoding": "gzip"}
        )
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = _generous_deadline(clock)
        opener = _ScriptedOpener(clock, [(0.0, opener_response)])
        with patch.object(client, "_OPENER", new=opener):
            response = client.fetch(
                "https://www.youtube.com/x", deadline=deadline, transport=transport
            )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, original)

    def test_gzip_content_encoding_matched_case_insensitively(self) -> None:
        import gzip

        original = b"hello again"
        opener_response = _FakeHTTPResponse(
            gzip.compress(original), status=200, headers={"Content-Encoding": "GZIP"}
        )
        clock = _FakeClock()
        transport, _sleeps = _fake_transport(clock)
        deadline = _generous_deadline(clock)
        opener = _ScriptedOpener(clock, [(0.0, opener_response)])
        with patch.object(client, "_OPENER", new=opener):
            response = client.fetch(
                "https://www.youtube.com/x", deadline=deadline, transport=transport
            )
        self.assertEqual(response.body, original)


class TestInflateGzipCappedSuccessAndCorruptBody(unittest.TestCase):
    def test_inflate_gzip_capped_success_under_cap(self) -> None:
        import gzip

        original = b"small payload" * 3
        compressed = gzip.compress(original)
        self.assertEqual(client._inflate_gzip_capped(compressed, cap=len(original) + 10), original)

    def test_inflate_gzip_capped_corrupt_body_maps_to_transport_failed(self) -> None:
        with self.assertRaises(client.TransportFailed):
            client._inflate_gzip_capped(b"not a real gzip stream", cap=1000)


if __name__ == "__main__":
    unittest.main()

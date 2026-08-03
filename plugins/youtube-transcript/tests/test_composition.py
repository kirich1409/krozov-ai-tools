"""Tests for `composition.py` + `server.py` (T-13b) -- the wiring layer that turns
every previously-built piece (T-1 through T-13a) into a runnable MCP server.

See `docs/plans/youtube-transcript/tasks.md`'s T-13b block for the full acceptance
list this file's `check` is drawn from.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from typing import Any, Dict, List, Sequence, Union
from unittest import mock

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim -- see _helpers.py's module docstring.

import composition
import domain
import net.client as net_client
import protocol.dispatch as dispatch
import providers.base as providers_base
import server
from _helpers import FakeSession, _FakeHTTPResponse
from protocol.registry import Registry

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SERVER_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "plugin", "server"))

_VIDEO_ID_STR = "dQw4w9WgXcQ"


# --- Shared filesystem/AST helpers ------------------------------------------------


def _iter_server_py_files() -> List[str]:
    found: List[str] = []
    for root, dirs, files in os.walk(_SERVER_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


def _top_level_def_names(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


# --- 1: exactly one build_provider( call site outside composition.py/tests/ ------


def _count_build_provider_calls(path: str) -> int:
    """AST-based, not a literal substring `grep` -- deliberately so a docstring or
    comment mentioning ``build_provider(`` in prose (e.g. this file's own, and
    server.py's own module docstring) is never miscounted as a real call site.
    Counts `ast.Call` nodes whose callee is named `build_provider`, either as a bare
    `Name` (`build_provider(...)`) or an `Attribute` (`composition.build_provider(...)`)."""
    with open(path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=path)
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "build_provider":
            count += 1
    return count


class TestSingleBuildProviderCallSite(unittest.TestCase):
    def test_single_build_provider_call_site(self) -> None:
        offenders = []
        total = 0
        for path in _iter_server_py_files():
            if os.path.basename(path) == "composition.py":
                continue  # build_provider's own definition site, not a call site.
            count = _count_build_provider_calls(path)
            if count:
                offenders.append((path, count))
            total += count
        self.assertEqual(
            total,
            1,
            f"expected exactly one build_provider( call site under plugin/server/ "
            f"outside composition.py -- found: {offenders}",
        )


# --- 2: build_registry()/main() live only in server.py, never composition.py -----


class TestBuildRegistryAndMainOnlyInServerPy(unittest.TestCase):
    def test_build_registry_and_main_only_in_server_py(self) -> None:
        composition_path = os.path.join(_SERVER_DIR, "composition.py")
        server_path = os.path.join(_SERVER_DIR, "server.py")

        composition_defs = _top_level_def_names(composition_path)
        server_defs = _top_level_def_names(server_path)

        self.assertNotIn("build_registry", composition_defs)
        self.assertNotIn("main", composition_defs)
        self.assertIn("build_registry", server_defs)
        self.assertIn("main", server_defs)

        self.assertFalse(hasattr(composition, "build_registry"))
        self.assertFalse(hasattr(composition, "main"))
        self.assertTrue(callable(server.build_registry))
        self.assertTrue(callable(server.main))


# --- 3: subprocess smoke test -- empty stdin, no ModuleNotFoundError -------------


class TestStdlibShadowingSmokeImport(unittest.TestCase):
    def test_stdlib_shadowing_smoke_import(self) -> None:
        server_path = os.path.join(_SERVER_DIR, "server.py")
        # Run from a cwd well outside the repo -- proves server.py's imports resolve
        # purely from the script's own directory (Python's automatic sys.path[0]
        # behavior), never from an inherited/ambient CWD-relative path, so nothing
        # under plugin/server/ can be silently shadowed by an unrelated same-named
        # module reachable only from some other working directory.
        with tempfile.TemporaryDirectory() as tmp_cwd:
            result = subprocess.run(
                [sys.executable, server_path],
                input="",
                capture_output=True,
                text=True,
                cwd=tmp_cwd,
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertNotIn("ModuleNotFoundError", result.stderr)


# --- 4: build_registry(provider, clock=...)'s per-call deadline seam -------------


class _DeadlineCheckingProvider(providers_base.TranscriptProvider):
    """A `TranscriptProvider` double whose `open()` explicitly checks
    `deadline.expired()` and raises `DeadlineExpired` if so -- mirroring
    `InnertubeProvider.open()`'s own real deadline checks (T-10). Used instead of
    `_helpers.FakeProvider` (which never inspects `deadline` at all) specifically so
    THIS test's clock-advancement scenario has an observable effect: whether the
    `Deadline` `build_registry`'s closure hands to `handle()` was built fresh for
    THIS call, or is a stale one bound once at registration time."""

    def __init__(self, video_id: "domain.VideoId", session: FakeSession) -> None:
        self._video_id = video_id
        self._session = session

    def normalize_video_ref(self, value: str) -> "domain.VideoId":
        del value
        return self._video_id

    def open(self, video_id: "domain.VideoId", deadline: "domain.Deadline") -> providers_base.ProviderSession:
        del video_id
        if deadline.expired():
            raise domain.DeadlineExpired("test double: deadline expired at open()")
        return self._session


def _queue_clock(values: Sequence[float]):
    remaining = list(values)

    def clock() -> float:
        if not remaining:
            raise AssertionError("_queue_clock: exhausted")
        return remaining.pop(0)

    return clock


class TestSecondCallGetsFreshDeadlineViaBuildRegistryClock(unittest.TestCase):
    def test_second_call_gets_fresh_deadline_via_build_registry_clock(self) -> None:
        video_id = domain.VideoId(value=_VIDEO_ID_STR)
        track = domain.TrackDescriptor(
            track_id="manual:en",
            language_code="en",
            language_name="English",
            kind="manual",
            estimated_characters=None,
            is_default=True,
        )
        listing = domain.TrackListing(tracks=(track,), duration_seconds=100, default_audio_language=None)
        session = FakeSession(listing)
        provider = _DeadlineCheckingProvider(video_id, session)

        # Call 1 starts at t=1000 (deadline_at = 1000 + TOOL_CALL_DEADLINE(180) =
        # 1180); its own open()-time expired() check reads t=1050 -- well inside
        # budget. Call 2 starts at t=1300 -- already PAST call 1's deadline_at
        # (1180), i.e. TOOL_CALL_DEADLINE has elapsed on the absolute clock BETWEEN
        # the two calls -- but build_registry's closure calls
        # build_deadline(clock=clock) fresh each time, so call 2 gets its OWN
        # deadline_at = 1300 + 180 = 1480, and its own open()-time check at t=1350 is
        # still comfortably inside ITS OWN budget. A registration-time-bound Deadline
        # (the bug this test guards against) would instead still be checking against
        # call 1's stale deadline_at=1180 at t=1350 -- long since expired -- which
        # would make call 2 raise DeadlineExpired instead of succeeding.
        self.assertGreater(1300.0 - 1000.0, domain.TOOL_CALL_DEADLINE)
        clock = _queue_clock([1000.0, 1050.0, 1300.0, 1350.0])

        registry = server.build_registry(provider, clock=clock)
        message: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_transcript_tracks", "arguments": {"video": _VIDEO_ID_STR}},
        }

        response1 = dispatch.handle_message(registry, message)
        assert response1 is not None
        payload1 = json.loads(response1["result"]["content"][0]["text"])
        self.assertEqual(payload1["status"], "ok", payload1)

        response2 = dispatch.handle_message(registry, {**message, "id": 2})
        assert response2 is not None
        payload2 = json.loads(response2["result"]["content"][0]["text"])
        self.assertEqual(payload2["status"], "ok", payload2)


# --- 5/6: end-to-end (mocked transport) request counts ---------------------------


def _watch_page_html(api_key: str = "TEST_INNERTUBE_API_KEY") -> str:
    return (
        "<html><head></head><body><script>"
        'var ytInitialPlayerResponse = {"videoDetails": {"videoId": "stub"}};'
        "</script>"
        "<script>"
        f'ytcfg.set({{"INNERTUBE_API_KEY":"{api_key}","INNERTUBE_CONTEXT":{{}},'
        '"INNERTUBE_CONTEXT_CLIENT_VERSION":"2.20240101.00.00","STS":12345}});'
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


class _CountingOpener:
    """Stands in for `net.client._OPENER` -- pops the next queued
    `_FakeHTTPResponse` (or raises the next queued exception) per `.open()` call, in
    order, recording every call for a request-count assertion. This is the real
    transport boundary `net/client.py::fetch()` itself talks to (see
    `tests/test_net_client_resources.py`'s identical pattern) -- mocking here, rather
    than one layer up at `providers.innertube.fetch`, is what makes this an actual
    end-to-end test of the full dispatch stack: JSON-RPC message in, through
    `Registry`/`tools/`/`InnertubeProvider`/`net/client.py`'s real retry+policy
    machinery, out to this one mocked boundary."""

    def __init__(self, responses: Sequence[Union[_FakeHTTPResponse, BaseException]]) -> None:
        self._queue: List[Union[_FakeHTTPResponse, BaseException]] = list(responses)
        self.calls: List[Any] = []

    def open(self, request: Any, *, timeout: Any = None) -> _FakeHTTPResponse:
        del timeout
        self.calls.append(request)
        if not self._queue:
            raise AssertionError("_CountingOpener: no more responses queued")
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _build_registry_with_real_provider() -> Registry:
    provider = composition.build_provider(sleep=lambda seconds: None, jitter=lambda low, high: 0.0)
    return server.build_registry(provider)


class TestEndToEndRequestCountGetTranscript(unittest.TestCase):
    def test_end_to_end_request_count_get_transcript(self) -> None:
        registry = _build_registry_with_real_provider()
        opener = _CountingOpener(
            [
                _FakeHTTPResponse(_watch_page_html().encode("utf-8")),
                _FakeHTTPResponse(json.dumps(_player_response_with_one_caption_track()).encode("utf-8")),
                _FakeHTTPResponse(_timedtext_xml()),
            ]
        )
        message: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_transcript", "arguments": {"video": _VIDEO_ID_STR}},
        }

        with mock.patch.object(net_client, "_OPENER", new=opener):
            response = dispatch.handle_message(registry, message)

        assert response is not None
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(len(opener.calls), 3)


class TestEndToEndRequestCountListTracks(unittest.TestCase):
    def test_end_to_end_request_count_list_tracks(self) -> None:
        registry = _build_registry_with_real_provider()
        opener = _CountingOpener(
            [
                _FakeHTTPResponse(_watch_page_html().encode("utf-8")),
                _FakeHTTPResponse(json.dumps(_player_response_with_one_caption_track()).encode("utf-8")),
            ]
        )
        message: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_transcript_tracks", "arguments": {"video": _VIDEO_ID_STR}},
        }

        with mock.patch.object(net_client, "_OPENER", new=opener):
            response = dispatch.handle_message(registry, message)

        assert response is not None
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(len(opener.calls), 2)


if __name__ == "__main__":
    unittest.main()

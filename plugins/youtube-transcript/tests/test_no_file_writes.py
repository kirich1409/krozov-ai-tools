"""T-14: zero filesystem writes running both tools against fixtures in an empty
temp dir.

`test_source_policy.py`'s bans (this same task) are a static, text-pattern
regression guard; this file is the dynamic complement -- actually running both
tools end-to-end (through the real `Registry`/dispatch stack, T-13a/T-13b) with
the process's own current working directory pointed at a fresh, empty
`tempfile.TemporaryDirectory()`, then asserting that directory is still empty
afterward. A stub `TranscriptProvider` (never the real network-touching
`InnertubeProvider`) supplies fixture data -- this file is about filesystem
writes, not network egress (`net/client.py`'s own egress policy is covered
elsewhere, T-6a/T-6b).
"""

import json
import os
import tempfile
import unittest
from typing import Any, Dict

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim -- see _helpers.py's module docstring.

from _helpers import FakeProvider, FakeSession, make_segments

import domain
import protocol.dispatch as dispatch
import server

_VIDEO_ID_STR = "dQw4w9WgXcQ"
_VIDEO_ID = domain.VideoId(_VIDEO_ID_STR)


def _track(language_code: str = "en") -> domain.TrackDescriptor:
    return domain.TrackDescriptor(
        track_id=f"manual:{language_code}",
        language_code=language_code,
        language_name=language_code,
        kind="manual",
        estimated_characters=None,
        is_default=True,
    )


def _tools_call_message(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }


class TestNoFileWritesRunningBothToolsAgainstFixtures(unittest.TestCase):
    def test_no_file_writes_running_both_tools_against_fixtures(self) -> None:
        track = _track("en")
        # A many-segment transcript, not just one -- exercises formats.encode's
        # real chunking/counting pass (T-5/T-9), not just the trivial single-
        # segment path, while still staying well under MAX_PAGE_CHARS so this
        # is a single-page, non-paginated response.
        transcript = domain.Transcript(segments=make_segments(200))
        session = FakeSession(_listing_with(track), transcripts={track.track_id: transcript})
        provider = FakeProvider(normalize_result=_VIDEO_ID, session=session)
        registry = server.build_registry(provider)

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as empty_tmp_dir:
            self.assertEqual(os.listdir(empty_tmp_dir), [])
            os.chdir(empty_tmp_dir)
            try:
                get_transcript_response = dispatch.handle_message(
                    registry,
                    _tools_call_message("get_transcript", {"video": _VIDEO_ID_STR}),
                )
                list_tracks_response = dispatch.handle_message(
                    registry,
                    _tools_call_message("list_transcript_tracks", {"video": _VIDEO_ID_STR}),
                )
            finally:
                os.chdir(original_cwd)

            assert get_transcript_response is not None
            assert list_tracks_response is not None
            get_transcript_payload = json.loads(
                get_transcript_response["result"]["content"][0]["text"]
            )
            list_tracks_payload = json.loads(
                list_tracks_response["result"]["content"][0]["text"]
            )
            self.assertEqual(get_transcript_payload["status"], "ok", get_transcript_payload)
            self.assertEqual(list_tracks_payload["status"], "ok", list_tracks_payload)

            # The load-bearing assertion: running both tools left this directory
            # exactly as empty as it started -- zero files, zero subdirectories,
            # not even a temp/lock file created and cleaned up mid-call.
            self.assertEqual(os.listdir(empty_tmp_dir), [])


def _listing_with(track: domain.TrackDescriptor) -> domain.TrackListing:
    return domain.TrackListing(tracks=(track,), duration_seconds=200, default_audio_language=None)


if __name__ == "__main__":
    unittest.main()

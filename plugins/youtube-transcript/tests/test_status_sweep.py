"""T-14: every one of the 13 `domain.Status` enum members is reached by at least
one test.

This file proves reachability directly, by construction, rather than grepping the
rest of the suite for status-string literals (which would be fragile against a
future rename/refactor of an unrelated test file and wouldn't prove the status is
reachable through real production code, only that some string appears somewhere).
Each of the 13 members below is driven through the real `get_transcript`/
`list_transcript_tracks` handlers (T-11/T-12) against a `_helpers.FakeProvider`/
`FakeSession` double -- the same test doubles T-12's own unit suite uses -- so this
is a genuine, independently-runnable proof that every status this server can name
is actually producible by the code that claims to produce it, not just a coverage
tautology.

See `docs/plans/youtube-transcript/tasks.md`'s T-14 block (AC-17's "full
reachability sweep") for the acceptance this file closes.
"""

import unittest
from typing import Optional

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim -- see _helpers.py's module docstring.

from _helpers import FakeProvider, FakeSession, make_segments

import domain
import providers.base as providers_base
import tools.get_transcript as get_transcript
import tools.list_transcript_tracks as list_transcript_tracks

_VIDEO_ID = domain.VideoId("dQw4w9WgXcQ")


def _track(
    language_code: str, kind: str = "manual", *, is_default: bool = False
) -> domain.TrackDescriptor:
    return domain.TrackDescriptor(
        track_id=f"{kind}:{language_code}",
        language_code=language_code,
        language_name=language_code,
        kind=kind,
        estimated_characters=None,
        is_default=is_default,
    )


def _listing(tracks, *, duration_seconds: int = 100) -> domain.TrackListing:
    return domain.TrackListing(
        tracks=tuple(tracks), duration_seconds=duration_seconds, default_audio_language=None
    )


def _deadline() -> domain.Deadline:
    return domain.Deadline.start(180.0, clock=lambda: 0.0)


def _status_via_get_transcript(
    args: dict, *, session: Optional[FakeSession] = None, open_error: Optional[BaseException] = None
) -> domain.Status:
    provider = FakeProvider(normalize_result=_VIDEO_ID, session=session, open_error=open_error)
    outcome = get_transcript.handle(provider, _deadline(), {"video": "x", **args})
    return outcome.status


def _status_via_list_tracks(
    *, session: Optional[FakeSession] = None, open_error: Optional[BaseException] = None
) -> domain.Status:
    provider = FakeProvider(normalize_result=_VIDEO_ID, session=session, open_error=open_error)
    outcome = list_transcript_tracks.handle(provider, _deadline(), {"video": "x"})
    return outcome.status


class TestAllThirteenStatusMembersAreReachable(unittest.TestCase):
    def test_all_thirteen_status_members_are_reachable(self) -> None:
        reached: set = set()

        # --- OK: a normal successful get_transcript call. ---------------------
        track = _track("en")
        transcript = domain.Transcript(segments=make_segments(1))
        session = FakeSession(_listing([track]), transcripts={track.track_id: transcript})
        reached.add(_status_via_get_transcript({}, session=session))

        # --- NO_TRANSCRIPT: no captions at all. --------------------------------
        reached.add(_status_via_get_transcript({}, session=FakeSession(_listing([]))))

        # --- LANGUAGE_UNAVAILABLE: trackId supplied, matches nothing. ----------
        session_unmatched = FakeSession(_listing([_track("en")]))
        reached.add(
            _status_via_get_transcript({"trackId": "manual:zz"}, session=session_unmatched)
        )

        # --- The 10 ProviderError leaves: provider.open() raises each, one at a
        # time, driven through list_transcript_tracks.handle() (never fetches a
        # track, so this exercises exactly the open()-raises path for each). ----
        provider_error_leaves = (
            providers_base.VideoNotFound,
            providers_base.VideoUnavailable,
            providers_base.AgeRestricted,
            providers_base.RegionBlocked,
            providers_base.LiveNotReady,
            providers_base.RateLimited,
            providers_base.BlockedByProvider,
            providers_base.UpstreamChanged,
            providers_base.TranscriptTooLarge,
            providers_base.TransportError,
        )
        for error_cls in provider_error_leaves:
            with self.subTest(error_cls=error_cls.__name__):
                reached.add(_status_via_list_tracks(open_error=error_cls("simulated")))

        self.assertEqual(
            reached,
            set(domain.Status),
            f"unreached Status members: {set(domain.Status) - reached}",
        )
        self.assertEqual(len(reached), 13)


if __name__ == "__main__":
    unittest.main()

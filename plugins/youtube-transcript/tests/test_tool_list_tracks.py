"""Tests for `tools/list_transcript_tracks.py` (T-11): normalize-before-open,
call-count assertions on `provider.open`/`session.fetch`, the `no_transcript` /
envelope-duration interaction, the 50-track cap + sort, the once-per-call
`estimate_characters` invariant, non-mutation of the original provider-returned
`TrackDescriptor`s, and the `DomainFailure` -> `transport_error` mapping for both
`provider.open(...)` and `formats.estimate_characters(...)` raising
`DeadlineExpired`. See `docs/plans/youtube-transcript/tasks.md`'s T-11 block and
`docs/specs/2026-08-01-youtube-transcript.md`'s AC-1/AC-6/AC-7/AC-8 for the full
acceptance list this file's `check` list is drawn from.
"""

import unittest
from typing import Optional
from unittest import mock

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim before the imports below -- see _helpers.py's module
# docstring and test_domain.py's identical comment for the mypy-vs-runtime reason
# this bare top-level import needs the suppression.

from _helpers import FakeProvider, FakeSession

import domain
import formats
import tools.list_transcript_tracks as list_tracks


def _track(
    language_code: str,
    kind: str = "manual",
    *,
    is_default: bool = False,
    track_id: Optional[str] = None,
) -> domain.TrackDescriptor:
    return domain.TrackDescriptor(
        track_id=track_id or f"{kind}:{language_code}",
        language_code=language_code,
        language_name=language_code,
        kind=kind,
        estimated_characters=None,
        is_default=is_default,
    )


def _listing(
    tracks, *, duration_seconds: int = 100, default_audio_language: Optional[str] = None
) -> domain.TrackListing:
    return domain.TrackListing(
        tracks=tuple(tracks),
        duration_seconds=duration_seconds,
        default_audio_language=default_audio_language,
    )


def _deadline() -> domain.Deadline:
    return domain.Deadline.start(180.0, clock=lambda: 0.0)


class TestVideoNotFound(unittest.TestCase):
    def test_invalid_video_ref_returns_not_found_without_opening(self) -> None:
        """AC-6/AC-8: normalize_video_ref failing (returns None) maps to
        video_not_found, and open() must not be called at all -- asserted on the
        call counter, not just the returned status (cycle 8 fix)."""
        provider = FakeProvider(normalize_result=None)
        outcome = list_tracks.handle(provider, _deadline(), {"video": "not a video ref"})
        self.assertEqual(outcome.status, domain.Status.VIDEO_NOT_FOUND)
        self.assertEqual(provider.open_calls, [])

    def test_video_not_found(self) -> None:
        """Same outcome, checked independently of the call-counter assertion
        above -- covers the plain status-mapping half of AC-6/AC-8."""
        provider = FakeProvider(normalize_result=None)
        outcome = list_tracks.handle(provider, _deadline(), {"video": "garbage"})
        self.assertEqual(outcome.status, domain.Status.VIDEO_NOT_FOUND)

    def test_non_string_video_returns_not_found_without_opening(self) -> None:
        """`video` is untrusted JSON input (schema declares it a string, but
        `protocol/dispatch.py` never checks argument type, only presence) -- a
        non-string value must resolve to `video_not_found` via the same
        `isinstance(video_arg, str)` guard `get_transcript._normalize_video` uses,
        not reach `provider.normalize_video_ref` at all. `normalize_result` is
        configured to a real `VideoId` here (not `None`, unlike the two tests
        above) specifically so this fails loudly if the guard were ever removed:
        `FakeProvider.normalize_video_ref` ignores its argument's type and always
        returns whatever `normalize_result` was configured to, so without the
        guard this would resolve successfully instead of `video_not_found`."""
        video_id = domain.VideoId("dQw4w9WgXcQ")
        provider = FakeProvider(normalize_result=video_id)
        outcome = list_tracks.handle(provider, _deadline(), {"video": [1, 2, 3]})
        self.assertEqual(outcome.status, domain.Status.VIDEO_NOT_FOUND)
        self.assertEqual(provider.open_calls, [])


class TestOpenAndFetchCallCounts(unittest.TestCase):
    def test_open_called_once(self) -> None:
        video_id = domain.VideoId("dQw4w9WgXcQ")
        session = FakeSession(_listing([_track("en")]))
        provider = FakeProvider(normalize_result=video_id, session=session)
        list_tracks.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})
        self.assertEqual(len(provider.open_calls), 1)
        self.assertEqual(provider.open_calls[0][0], video_id)

    def test_never_calls_fetch(self) -> None:
        video_id = domain.VideoId("dQw4w9WgXcQ")
        session = FakeSession(_listing([_track("en"), _track("fr", "auto")]))
        provider = FakeProvider(normalize_result=video_id, session=session)
        list_tracks.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})
        self.assertEqual(session.fetch_calls, [])


class TestNoTranscript(unittest.TestCase):
    def test_empty_tracks_maps_to_no_transcript_with_duration(self) -> None:
        """AC-7: no captions at all -> no_transcript, with videoDurationSeconds
        still present in the ToolOutcome's own payload."""
        video_id = domain.VideoId("dQw4w9WgXcQ")
        session = FakeSession(_listing([], duration_seconds=321))
        provider = FakeProvider(normalize_result=video_id, session=session)
        outcome = list_tracks.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})
        self.assertEqual(outcome.status, domain.Status.NO_TRANSCRIPT)
        self.assertEqual(outcome.payload, {"tracks": [], "videoDurationSeconds": 321})

    def test_envelope_retains_duration_on_no_transcript(self) -> None:
        """The *built envelope* (not just the ToolOutcome) still carries
        videoDurationSeconds on no_transcript -- reachable only because T-7's
        FIELDS_BY_STATUS[no_transcript] allowlists it."""
        import protocol.envelope as envelope

        video_id = domain.VideoId("dQw4w9WgXcQ")
        session = FakeSession(_listing([], duration_seconds=555))
        provider = FakeProvider(normalize_result=video_id, session=session)
        outcome = list_tracks.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})
        wire = envelope.build(outcome, video=video_id)
        self.assertEqual(wire["videoDurationSeconds"], 555)
        self.assertEqual(wire["tracks"], [])


class TestCapAndSort(unittest.TestCase):
    def test_track_count_cap_and_sort(self) -> None:
        """55 tracks (mixed manual/auto, unsorted input order) -> 50 kept,
        truncated=true, sorted manual-before-auto then alphabetically."""
        manual_tracks = [_track(f"m{i:02d}", "manual") for i in range(30)]
        auto_tracks = [_track(f"a{i:02d}", "auto") for i in range(25)]
        # Interleave to prove input order doesn't matter.
        all_tracks = []
        for m, a in zip(manual_tracks, auto_tracks):
            all_tracks.append(a)
            all_tracks.append(m)
        all_tracks.extend(manual_tracks[len(auto_tracks) :])
        self.assertEqual(len(all_tracks), 55)

        video_id = domain.VideoId("dQw4w9WgXcQ")
        session = FakeSession(_listing(all_tracks, duration_seconds=100))
        provider = FakeProvider(normalize_result=video_id, session=session)
        outcome = list_tracks.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})

        self.assertEqual(outcome.status, domain.Status.OK)
        self.assertEqual(outcome.payload["truncated"], True)
        kept = outcome.payload["tracks"]
        self.assertEqual(len(kept), 50)
        # All 30 manual tracks (sorted) come first, then the first 20 auto tracks
        # (sorted) -- manual-before-auto tiering, per sort_tracks().
        expected_order = [t.track_id for t in sorted(manual_tracks, key=lambda t: t.language_code)]
        expected_order += [
            t.track_id for t in sorted(auto_tracks, key=lambda t: t.language_code)[:20]
        ]
        self.assertEqual([t.track_id for t in kept], expected_order)


class TestEstimatedCharacters(unittest.TestCase):
    def test_estimated_characters_computed_once_not_per_track(self) -> None:
        video_id = domain.VideoId("dQw4w9WgXcQ")
        tracks = [_track("en"), _track("fr", "auto"), _track("de", "manual")]
        session = FakeSession(_listing(tracks, duration_seconds=200))
        provider = FakeProvider(normalize_result=video_id, session=session)

        with mock.patch.object(
            list_tracks, "estimate_characters", wraps=formats.estimate_characters
        ) as spy:
            outcome = list_tracks.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})

        spy.assert_called_once_with(200)
        expected = formats.estimate_characters(200)
        for track in outcome.payload["tracks"]:
            self.assertEqual(track.estimated_characters, expected)
            # Every kept track's mapping is the exact same reused object, not a
            # per-track recomputation that merely happens to be equal.
            self.assertIs(track.estimated_characters, outcome.payload["tracks"][0].estimated_characters)


class TestOriginalTracksNeverMutated(unittest.TestCase):
    def test_original_listing_tracks_never_mutated(self) -> None:
        video_id = domain.VideoId("dQw4w9WgXcQ")
        original = _track("en")
        session = FakeSession(_listing([original], duration_seconds=100))
        provider = FakeProvider(normalize_result=video_id, session=session)

        outcome = list_tracks.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})

        self.assertIsNone(original.estimated_characters)
        self.assertIs(session.listing.tracks[0], original)
        returned = outcome.payload["tracks"][0]
        self.assertIsNot(returned, original)
        self.assertIsNotNone(returned.estimated_characters)
        self.assertEqual(returned.track_id, original.track_id)


class TestDeadlineExpiredMapping(unittest.TestCase):
    def test_open_raises_deadline_expired_maps_to_transport_error(self) -> None:
        video_id = domain.VideoId("dQw4w9WgXcQ")
        provider = FakeProvider(normalize_result=video_id, open_error=domain.DeadlineExpired("expired"))
        outcome = list_tracks.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})
        self.assertEqual(outcome.status, domain.Status.TRANSPORT_ERROR)

    def test_estimate_characters_raises_deadline_expired_mid_pass_maps_to_transport_error(
        self,
    ) -> None:
        video_id = domain.VideoId("dQw4w9WgXcQ")
        session = FakeSession(_listing([_track("en")], duration_seconds=100))
        provider = FakeProvider(normalize_result=video_id, session=session)

        with mock.patch.object(
            list_tracks, "estimate_characters", side_effect=domain.DeadlineExpired("expired mid-pass")
        ):
            outcome = list_tracks.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})

        self.assertEqual(outcome.status, domain.Status.TRANSPORT_ERROR)


if __name__ == "__main__":
    unittest.main()

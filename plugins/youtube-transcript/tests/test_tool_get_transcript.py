"""Tests for `tools/get_transcript.py` (T-12): normalize-before-open,
call-count assertions on `provider.open`/`session.fetch`, the `no_transcript`/
`language_unavailable` payload contracts, the domain-object `resolved_track`
payload key, cursor precedence over other arguments, the cursor's two-phase
`upstream_changed` validation (decode failure, videoId mismatch, and the
post-fetch segmentIndex-vs-real-count check), the `MAX_PAGES` derived-counting
ceiling, and the `DomainFailure` -> `transport_error`/`upstream_changed` mapping
for `provider.open`/`session.fetch`/`formats.encode` raising `DeadlineExpired`
and `tools.cursor.decode` raising `CursorInvalid`. See
`docs/plans/youtube-transcript/tasks.md`'s T-12 block and
`docs/specs/2026-08-01-youtube-transcript.md`'s AC-3/AC-4/AC-5/AC-7/AC-8/AC-11
for the full acceptance list this file's `check` list is drawn from.
"""

import unittest
from typing import Optional
from unittest import mock

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim before the imports below -- see _helpers.py's module
# docstring and test_domain.py's identical comment for the mypy-vs-runtime reason
# this bare top-level import needs the suppression.

from _helpers import FakeProvider, FakeSession, make_segments

import domain
import formats
import tools.cursor as cursor
import tools.get_transcript as get_transcript


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
        call counter, not just the returned status."""
        provider = FakeProvider(normalize_result=None)
        outcome = get_transcript.handle(provider, _deadline(), {"video": "not a video ref"})
        self.assertEqual(outcome.status, domain.Status.VIDEO_NOT_FOUND)
        self.assertEqual(provider.open_calls, [])


class TestOpenAndFetchCallCounts(unittest.TestCase):
    def test_no_cursor_exactly_once_open_and_fetch(self) -> None:
        video_id = domain.VideoId("dQw4w9WgXcQ")
        track = _track("en")
        transcript = domain.Transcript(segments=make_segments(3))
        session = FakeSession(_listing([track]), transcripts={track.track_id: transcript})
        provider = FakeProvider(normalize_result=video_id, session=session)

        outcome = get_transcript.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})

        self.assertEqual(outcome.status, domain.Status.OK)
        self.assertEqual(len(provider.open_calls), 1)
        self.assertEqual(provider.open_calls[0][0], video_id)
        self.assertEqual(len(session.fetch_calls), 1)
        self.assertEqual(session.fetch_calls[0][0], track)


class TestNoTranscript(unittest.TestCase):
    def test_empty_tracks_no_transcript_exactly_two_requests_never_fetches(self) -> None:
        """AC-7: no captions at all -> no_transcript. `provider.open()` itself
        is the only outbound cost here (its own 2 logical requests, watch page +
        player) -- `session.fetch()` must never be called (the empty-tracks path
        costs 2 requests total, not 3)."""
        video_id = domain.VideoId("dQw4w9WgXcQ")
        session = FakeSession(_listing([]))
        provider = FakeProvider(normalize_result=video_id, session=session)

        outcome = get_transcript.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})

        self.assertEqual(outcome.status, domain.Status.NO_TRANSCRIPT)
        self.assertEqual(len(provider.open_calls), 1)
        self.assertEqual(session.fetch_calls, [])


class TestLanguageUnavailable(unittest.TestCase):
    def test_language_unavailable_includes_available_languages(self) -> None:
        """AC-3/AC-5: an unmatched `trackId` (T-9's `select_track` treats a
        supplied `trackId` as the *only* tier consulted, never falling back --
        see resolution.py) maps to language_unavailable, with a sorted, deduped
        `languageCode` list from the freshly resolved tracks."""
        video_id = domain.VideoId("dQw4w9WgXcQ")
        tracks = [_track("en"), _track("en", "auto"), _track("fr", "auto"), _track("de")]
        session = FakeSession(_listing(tracks))
        provider = FakeProvider(normalize_result=video_id, session=session)

        outcome = get_transcript.handle(
            provider, _deadline(), {"video": "dQw4w9WgXcQ", "trackId": "manual:xx"}
        )

        self.assertEqual(outcome.status, domain.Status.LANGUAGE_UNAVAILABLE)
        # "en" appears twice (manual + auto) in the source tracks -- deduped to
        # one entry, sorted alphabetically.
        self.assertEqual(outcome.payload["availableLanguages"], ["de", "en", "fr"])

    def test_explicit_language_mismatch_does_not_fall_back_to_default_track(self) -> None:
        """AC-3 regression: an explicit, non-matching `languages` request must
        return `language_unavailable`, never silently falling back to a track
        resolved via `default_audio_language`/`is_default` (AC-3: "does NOT
        silently fall back to another language"). Fixture deliberately has
        both a `default_audio_language` match and an `is_default=True` track
        so that, before this fix, `select_track` would have resolved one of
        those instead of returning `None`."""
        video_id = domain.VideoId("dQw4w9WgXcQ")
        default_track = _track("de", "manual", is_default=True)
        other_track = _track("en", "manual")
        session = FakeSession(_listing([default_track, other_track], default_audio_language="de"))
        provider = FakeProvider(normalize_result=video_id, session=session)

        outcome = get_transcript.handle(
            provider, _deadline(), {"video": "dQw4w9WgXcQ", "languages": ["xx"]}
        )

        self.assertEqual(outcome.status, domain.Status.LANGUAGE_UNAVAILABLE)
        self.assertEqual(outcome.payload["availableLanguages"], ["de", "en"])

    def test_capped_languages_without_track_id_returns_language_unavailable(self) -> None:
        """AC-3 residual gap (fix2): `validate_languages()` collapses "no
        `languages` supplied" and "cap violated" (>10 entries) into the same `[]`
        -- `get_transcript.py` must recover the distinction from the raw
        argument and reject a cap-violating request the same way as a
        non-matching one, instead of silently falling through to the AC-2
        default-invocation tiers (which would otherwise resolve `default_track`
        here and return `status: ok`)."""
        video_id = domain.VideoId("dQw4w9WgXcQ")
        default_track = _track("de", "manual", is_default=True)
        session = FakeSession(_listing([default_track], default_audio_language="de"))
        provider = FakeProvider(normalize_result=video_id, session=session)

        outcome = get_transcript.handle(
            provider,
            _deadline(),
            {"video": "dQw4w9WgXcQ", "languages": [f"l{i}" for i in range(11)]},
        )

        self.assertEqual(outcome.status, domain.Status.LANGUAGE_UNAVAILABLE)
        self.assertEqual(outcome.payload["availableLanguages"], ["de"])

    def test_capped_languages_with_track_id_still_resolves_via_track_id(self) -> None:
        """AC-5: `trackId` takes precedence over a capped `languages` list when
        both are supplied -- the cap violation must not block a valid
        `trackId`-only resolution."""
        video_id = domain.VideoId("dQw4w9WgXcQ")
        track = _track("en")
        transcript = domain.Transcript(segments=make_segments(2))
        session = FakeSession(_listing([track]), transcripts={track.track_id: transcript})
        provider = FakeProvider(normalize_result=video_id, session=session)

        outcome = get_transcript.handle(
            provider,
            _deadline(),
            {
                "video": "dQw4w9WgXcQ",
                "languages": [f"l{i}" for i in range(11)],
                "trackId": track.track_id,
            },
        )

        self.assertEqual(outcome.status, domain.Status.OK)
        self.assertIs(outcome.payload["resolved_track"], track)

    def test_available_languages_capped_at_fifty(self) -> None:
        video_id = domain.VideoId("dQw4w9WgXcQ")
        tracks = [_track(f"l{i:03d}") for i in range(60)]
        session = FakeSession(_listing(tracks))
        provider = FakeProvider(normalize_result=video_id, session=session)

        outcome = get_transcript.handle(
            provider, _deadline(), {"video": "dQw4w9WgXcQ", "trackId": "manual:xx"}
        )

        self.assertEqual(outcome.status, domain.Status.LANGUAGE_UNAVAILABLE)
        self.assertEqual(len(outcome.payload["availableLanguages"]), 50)


class TestResolvedTrackPayload(unittest.TestCase):
    def test_resolved_track_in_payload_on_success(self) -> None:
        """AC-5: the outcome's payload carries the domain `TrackDescriptor`
        object itself -- envelope.build() (T-7) is what constructs the wire
        `resolvedTrack` shape, not this handler."""
        video_id = domain.VideoId("dQw4w9WgXcQ")
        track = _track("en")
        transcript = domain.Transcript(segments=make_segments(2))
        session = FakeSession(_listing([track]), transcripts={track.track_id: transcript})
        provider = FakeProvider(normalize_result=video_id, session=session)

        outcome = get_transcript.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})

        self.assertEqual(outcome.status, domain.Status.OK)
        self.assertIs(outcome.payload["resolved_track"], track)


class TestCursorPrecedence(unittest.TestCase):
    def test_cursor_overrides_other_args(self) -> None:
        """AC-11: when a `cursor` is supplied alongside other arguments that
        disagree with what it encodes, the cursor's values win entirely --
        `trackId`/`languages`/`format`/`includeTimestamps` in `args` here would
        each resolve differently if honored."""
        video_id_str = "dQw4w9WgXcQ"
        track_en = _track("en")
        track_fr = _track("fr", "auto")
        transcript = domain.Transcript(segments=make_segments(2))
        session = FakeSession(
            _listing([track_en, track_fr]),
            transcripts={track_en.track_id: transcript, track_fr.track_id: transcript},
        )
        provider = FakeProvider(normalize_result=domain.VideoId(video_id_str), session=session)

        raw_cursor = cursor.encode(
            cursor.CursorFields(
                video_id=video_id_str,
                track_id=track_en.track_id,
                format="text",
                include_timestamps=True,
                segment_index=0,
            )
        )

        outcome = get_transcript.handle(
            provider,
            _deadline(),
            {
                "video": "https://youtu.be/dQw4w9WgXcQ",
                "cursor": raw_cursor,
                "trackId": track_fr.track_id,
                "languages": ["fr"],
                "format": "srt",
                "includeTimestamps": False,
            },
        )

        self.assertEqual(outcome.status, domain.Status.OK)
        self.assertIs(outcome.payload["resolved_track"], track_en)
        # includeTimestamps=True (the cursor's value) renders a timestamp
        # prefix; format "text" (the cursor's value), not "srt"'s numbered cue
        # blocks (the ignored arg's value).
        self.assertIn("[00:00:00.000]", outcome.payload["transcript"])


class TestCursorValidation(unittest.TestCase):
    def test_malformed_cursor_maps_to_upstream_changed(self) -> None:
        """`tools.cursor.decode` raising `CursorInvalid` is covered by the
        single blanket `except DomainFailure`, since `CursorInvalid` already is
        one -- decode fails before any outbound request."""
        provider = FakeProvider(normalize_result=domain.VideoId("dQw4w9WgXcQ"))

        outcome = get_transcript.handle(
            provider, _deadline(), {"video": "dQw4w9WgXcQ", "cursor": "not-a-valid-cursor!!"}
        )

        self.assertEqual(outcome.status, domain.Status.UPSTREAM_CHANGED)
        self.assertEqual(provider.open_calls, [])

    def test_cursor_video_id_mismatch_upstream_changed(self) -> None:
        track = _track("en")
        transcript = domain.Transcript(segments=make_segments(2))
        session = FakeSession(_listing([track]), transcripts={track.track_id: transcript})
        # FakeProvider.normalize_video_ref ignores its argument and always
        # returns this fixed value -- deliberately different from the cursor's
        # own embedded videoId below, so normalization itself succeeds but the
        # AC-11 cross-check still must fail.
        provider = FakeProvider(normalize_result=domain.VideoId("BBBBBBBBBBB"), session=session)

        raw_cursor = cursor.encode(
            cursor.CursorFields(
                video_id="AAAAAAAAAAA",
                track_id=track.track_id,
                format="text",
                include_timestamps=False,
                segment_index=0,
            )
        )

        outcome = get_transcript.handle(
            provider, _deadline(), {"video": "irrelevant", "cursor": raw_cursor}
        )

        self.assertEqual(outcome.status, domain.Status.UPSTREAM_CHANGED)
        self.assertEqual(provider.open_calls, [])

    def test_cursor_segment_index_exceeds_real_count_upstream_changed(self) -> None:
        """Phase-2 check: only knowable once the track is actually fetched and
        decoded -- `tools/cursor.py::decode()` cannot see this at first-phase
        validation time, so `fetch()` must have already run."""
        video_id_str = "dQw4w9WgXcQ"
        track = _track("en")
        transcript = domain.Transcript(segments=make_segments(3))
        session = FakeSession(_listing([track]), transcripts={track.track_id: transcript})
        provider = FakeProvider(normalize_result=domain.VideoId(video_id_str), session=session)

        raw_cursor = cursor.encode(
            cursor.CursorFields(
                video_id=video_id_str,
                track_id=track.track_id,
                format="text",
                include_timestamps=False,
                segment_index=999,
            )
        )

        outcome = get_transcript.handle(
            provider, _deadline(), {"video": video_id_str, "cursor": raw_cursor}
        )

        self.assertEqual(outcome.status, domain.Status.UPSTREAM_CHANGED)
        self.assertEqual(len(session.fetch_calls), 1)


class TestMaxPagesTruncation(unittest.TestCase):
    def test_max_pages_truncation_after_full_fetch(self) -> None:
        """AC-11's derived page-counting: a cursor whose segmentIndex sits past
        the MAX_PAGES-th page's boundary gets truncated=true/nextCursor=null --
        only after the full fetch+decode this task's acceptance names as an
        accepted, disclosed v1 cost."""
        video_id_str = "dQw4w9WgXcQ"
        track = _track("en")
        # Every segment's rendered text alone exceeds MAX_PAGE_CHARS, so each
        # page holds exactly one segment (fit_page's "always at least one
        # segment" rule) -- 25 such segments guarantee more than MAX_PAGES (20)
        # pages exist.
        long_text = "x" * (formats.MAX_PAGE_CHARS + 1)
        transcript = domain.Transcript(segments=make_segments(25, text=lambda i: long_text))
        session = FakeSession(_listing([track]), transcripts={track.track_id: transcript})
        provider = FakeProvider(normalize_result=domain.VideoId(video_id_str), session=session)

        # segment_index=20: pages 1..20 (one segment each) already consumed
        # segments 0..19 -- this call is for page 21, past the MAX_PAGES ceiling.
        raw_cursor = cursor.encode(
            cursor.CursorFields(
                video_id=video_id_str,
                track_id=track.track_id,
                format="text",
                include_timestamps=False,
                segment_index=20,
            )
        )

        outcome = get_transcript.handle(
            provider, _deadline(), {"video": video_id_str, "cursor": raw_cursor}
        )

        self.assertEqual(outcome.status, domain.Status.OK)
        self.assertEqual(outcome.payload["truncated"], True)
        self.assertIsNone(outcome.payload["nextCursor"])
        # The ceiling response is reached only after a full fetch+decode.
        self.assertEqual(len(session.fetch_calls), 1)


class TestDeadlineExpiredMapping(unittest.TestCase):
    def test_open_raises_deadline_expired_maps_to_transport_error(self) -> None:
        provider = FakeProvider(
            normalize_result=domain.VideoId("dQw4w9WgXcQ"),
            open_error=domain.DeadlineExpired("expired"),
        )

        outcome = get_transcript.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})

        self.assertEqual(outcome.status, domain.Status.TRANSPORT_ERROR)

    def test_fetch_raises_deadline_expired_maps_to_transport_error(self) -> None:
        video_id = domain.VideoId("dQw4w9WgXcQ")
        track = _track("en")
        session = FakeSession(_listing([track]), fetch_error=domain.DeadlineExpired("expired"))
        provider = FakeProvider(normalize_result=video_id, session=session)

        outcome = get_transcript.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})

        self.assertEqual(outcome.status, domain.Status.TRANSPORT_ERROR)

    def test_encode_raises_deadline_expired_mid_pass_maps_to_transport_error(self) -> None:
        video_id = domain.VideoId("dQw4w9WgXcQ")
        track = _track("en")
        transcript = domain.Transcript(segments=make_segments(3))
        session = FakeSession(_listing([track]), transcripts={track.track_id: transcript})
        provider = FakeProvider(normalize_result=video_id, session=session)

        with mock.patch.object(
            formats, "encode", side_effect=domain.DeadlineExpired("expired mid-pass")
        ):
            outcome = get_transcript.handle(provider, _deadline(), {"video": "dQw4w9WgXcQ"})

        self.assertEqual(outcome.status, domain.Status.TRANSPORT_ERROR)


if __name__ == "__main__":
    unittest.main()

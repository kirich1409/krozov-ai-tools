"""Tests for `tools/resolution.py` (T-9): AC-2's five-tier `select_track()`
resolution order, AC-3's BCP-47 `languages` matching, AC-5's `trackId`
precedence, `sort_tracks()`'s manual-before-auto sort, and `validate_languages()`'s
cap enforcement. One test per tier (cycle 8 finding: a single aggregate test
previously hid which tier's logic was actually broken) -- see
`docs/plans/youtube-transcript/tasks.md`'s T-9 block for the full acceptance list.
"""

import unittest
from typing import Optional

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim before the imports below -- see _helpers.py's module
# docstring and test_domain.py's identical comment for the mypy-vs-runtime reason
# this bare top-level import needs the suppression.

from domain import TrackDescriptor, TrackListing
from tools.resolution import select_track, sort_tracks, validate_languages


def _track(
    language_code: str,
    kind: str = "manual",
    *,
    is_default: bool = False,
    track_id: Optional[str] = None,
) -> TrackDescriptor:
    return TrackDescriptor(
        track_id=track_id or f"{kind}:{language_code}",
        language_code=language_code,
        language_name=language_code,
        kind=kind,
        estimated_characters=None,
        is_default=is_default,
    )


def _listing(
    tracks, *, duration_seconds: int = 100, default_audio_language: Optional[str] = None
) -> TrackListing:
    return TrackListing(
        tracks=tuple(tracks),
        duration_seconds=duration_seconds,
        default_audio_language=default_audio_language,
    )


class TestSelectTrackTiers(unittest.TestCase):
    def test_tier1_exact_track_id(self) -> None:
        """`track_id` matches a track and wins even though `languages` and the
        default-audio/`is_default` signals would all point elsewhere -- AC-5's
        precedence rule."""
        wanted = _track("fr", "auto", track_id="auto:fr")
        listing = _listing(
            [
                _track("en", "manual", is_default=True, track_id="manual:en"),
                wanted,
            ],
            default_audio_language="en",
        )
        result = select_track(listing, languages=["de"], track_id="auto:fr")
        self.assertIs(result, wanted)

    def test_tier1_invalid_track_id_does_not_fall_through(self) -> None:
        """An unmatched/invalid `track_id` returns `None` rather than silently
        resolving a different track via `languages` or the default-audio-language
        signal -- the caller (AC-5) maps `None` here to `language_unavailable`."""
        listing = _listing(
            [_track("en", "manual", is_default=True)],
            default_audio_language="en",
        )
        self.assertIsNone(
            select_track(listing, languages=["en"], track_id="manual:zz-does-not-exist")
        )
        self.assertIsNone(select_track(listing, track_id="not-a-valid-shape"))

    def test_tier2_default_audio_language_match(self) -> None:
        """A track's `language_code` matching `listing.default_audio_language`
        wins over the `is_default` marker on another track, when no `languages`
        entry matches any track (isolating this tier from tier 2's `languages`
        precedence -- see `test_language_preference_beats_default_signal_tracks`
        for that interaction)."""
        wanted = _track("de", "manual")
        listing = _listing(
            [
                _track("en", "auto", is_default=True),
                wanted,
            ],
            default_audio_language="de",
        )
        result = select_track(listing)
        self.assertIs(result, wanted)

    def test_tier3_upstream_default_track(self) -> None:
        """With no `default_audio_language` signal and no `languages` entry
        matching any track, the `is_default=True` track wins over the
        alphabetically-first fallback (isolating this tier from tier 2's
        `languages` precedence -- see
        `test_language_preference_beats_default_signal_tracks` for that
        interaction)."""
        wanted = _track("ja", "manual", is_default=True)
        listing = _listing(
            [
                _track("fr", "auto"),
                wanted,
            ],
            default_audio_language=None,
        )
        result = select_track(listing, languages=["zz"])
        self.assertIs(result, wanted)

    def test_language_preference_beats_default_signal_tracks(self) -> None:
        """Regression guard for the tier-order fix: `languages` (tier 2) must
        win over a *different* track that matches `default_audio_language`
        and/or carries `is_default=True`. Without this, the original tier bug
        (tier 2/3 counted before `languages`, contradicting AC-2's literal
        order) could silently reintroduce itself."""
        wanted = _track("en", "manual")
        default_and_is_default_track = _track("de", "manual", is_default=True)
        listing = _listing(
            [default_and_is_default_track, wanted],
            default_audio_language="de",
        )
        result = select_track(listing, languages=["en"])
        self.assertIs(result, wanted)

    def test_tier4_language_preference_match(self) -> None:
        """With both default-signal tiers absent, the first `languages` entry
        that matches (exact match preferred) wins over an earlier, non-matching
        preference entry and over the alphabetically-first fallback track."""
        wanted = _track("de", "manual")
        listing = _listing(
            [
                _track("aa", "manual"),  # would win tier 5's fallback if reached
                wanted,
                _track("fr", "manual"),
            ],
            default_audio_language=None,
        )
        result = select_track(listing, languages=["zz", "de"])
        self.assertIs(result, wanted)

    def test_tier4_primary_subtag_match(self) -> None:
        """AC-3: `"en"` matches an available `en-US` track when no exact match
        exists."""
        wanted = _track("en-US", "manual")
        listing = _listing([wanted, _track("fr", "manual")], default_audio_language=None)
        result = select_track(listing, languages=["en"])
        self.assertIs(result, wanted)

    def test_tier4_manual_preferred_over_auto(self) -> None:
        """AC-3: manual is preferred over auto-generated within the same matched
        language."""
        wanted = _track("en", "manual")
        auto_same_language = _track("en", "auto", track_id="auto:en")
        listing = _listing([auto_same_language, wanted], default_audio_language=None)
        result = select_track(listing, languages=["en"])
        self.assertIs(result, wanted)

    def test_tier5_fallback(self) -> None:
        """With every earlier tier's signal absent (no `track_id`, no
        `default_audio_language`, no `is_default` track, no matching
        `languages`), the fallback is the first manual track sorted by
        `language_code`, else the first auto-generated track sorted by
        `language_code` -- exactly `sort_tracks()`'s own ordering."""
        listing = _listing(
            [
                _track("zz", "auto"),
                _track("bb", "manual"),
                _track("aa", "manual"),
            ],
            default_audio_language=None,
        )
        result = select_track(listing, languages=["not-present"])
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual((result.kind, result.language_code), ("manual", "aa"))

    def test_tier5_fallback_auto_only(self) -> None:
        """The fallback still resolves to an auto-generated track when no manual
        track exists at all."""
        listing = _listing(
            [_track("zz", "auto"), _track("aa", "auto")], default_audio_language=None
        )
        result = select_track(listing)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual((result.kind, result.language_code), ("auto", "aa"))

    def test_select_track_empty_listing_returns_none(self) -> None:
        listing = _listing([], default_audio_language=None)
        self.assertIsNone(select_track(listing))

    def test_both_default_signals_absent_tier_skipped(self) -> None:
        """`default_audio_language is None` and no track has `is_default=True` is
        an explicit non-error case (AC-2): tiers 2/3 are silently skipped, not
        raised as a failure, falling through to tier 4/5 -- this resolves cleanly
        rather than raising."""
        listing = _listing(
            [_track("fr", "manual"), _track("en", "manual")],
            default_audio_language=None,
        )
        result = select_track(listing, languages=["en"])
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.language_code, "en")

        # And with no `languages` either, tier 5's fallback still resolves --
        # neither missing signal is treated as an error.
        fallback = select_track(listing)
        self.assertIsNotNone(fallback)
        assert fallback is not None
        self.assertEqual(fallback.language_code, "en")


class TestSortTracks(unittest.TestCase):
    def test_manual_before_auto_regardless_of_language_code(self) -> None:
        """Not a literal `(kind, languageCode)` string tuple-sort: `"auto"` sorts
        before `"manual"` alphabetically, but the corrected rank map must still
        put every manual track ahead of every auto track."""
        auto_a = _track("aa", "auto")
        manual_z = _track("zz", "manual")
        result = sort_tracks([auto_a, manual_z])
        self.assertEqual(result, (manual_z, auto_a))

    def test_alphabetical_within_tier(self) -> None:
        manual_b = _track("bb", "manual")
        manual_a = _track("aa", "manual")
        auto_b = _track("bb", "auto")
        auto_a = _track("aa", "auto")
        result = sort_tracks([manual_b, auto_b, manual_a, auto_a])
        self.assertEqual(result, (manual_a, manual_b, auto_a, auto_b))

    def test_empty(self) -> None:
        self.assertEqual(sort_tracks([]), ())


class TestValidateLanguages(unittest.TestCase):
    def test_none_returns_empty_list(self) -> None:
        self.assertEqual(validate_languages(None), [])

    def test_within_caps_returned_unchanged(self) -> None:
        languages = ["en", "fr-CA", "de"]
        self.assertEqual(validate_languages(languages), languages)

    def test_too_many_entries_rejected(self) -> None:
        self.assertEqual(validate_languages(["a"] * 11), [])

    def test_entry_too_long_rejected(self) -> None:
        self.assertEqual(validate_languages(["a" * 21]), [])

    def test_boundary_values_accepted(self) -> None:
        languages = ["a" * 20] * 10
        self.assertEqual(validate_languages(languages), languages)


if __name__ == "__main__":
    unittest.main()

"""Track-resolution algorithm for `get_transcript`: AC-2's five-tier resolution
order, AC-3's BCP-47 `languages` matching table, and AC-5's `trackId`-takes-
precedence-over-`languages` rule -- plus the manual-before-auto sort order both
`list_transcript_tracks` (AC-1) and this module's own tier 4/5 tie-breaking share,
and `languages` input-cap validation (AC-3, a domain outcome, never a schema
error).

`tools/` (`ALLOWED_EDGES`) may import `domain/`, `formats/`, and `providers/base.py`
-- never `providers/innertube.py` directly. This module only needs `domain/` (for
the `TrackDescriptor`/`TrackListing` types) and `providers.base.parse_track_id`
(the same `trackId` codec `providers/base.py::encode_track_id` produces, T-3).

Stdlib only.
"""

from typing import List, Optional, Sequence, Tuple

from domain import TrackDescriptor, TrackListing
from providers.base import parse_track_id

# AC-3: at most 10 entries, each at most 20 characters.
_MAX_LANGUAGES = 10
_MAX_LANGUAGE_LENGTH = 20


def sort_tracks(tracks: Sequence[TrackDescriptor]) -> Tuple[TrackDescriptor, ...]:
    """AC-1's corrected sort order: manual rank 0, auto rank 1, alphabetical by
    `language_code` within each tier. Deliberately not a literal
    `(kind, languageCode)` tuple-sort on the raw string values -- that would sort
    `"auto"` before `"manual"` alphabetically, which is the exact bug this
    explicit rank map exists to avoid (plan.md cycle 9 hostile-implementer-
    walkthrough finding)."""

    def _rank(track: TrackDescriptor) -> Tuple[int, str]:
        kind_rank = 0 if track.kind == "manual" else 1
        return kind_rank, track.language_code

    return tuple(sorted(tracks, key=_rank))


def _primary_subtag(language_code: str) -> str:
    return language_code.split("-", 1)[0].lower()


def _match_languages(
    sorted_tracks: Sequence[TrackDescriptor], languages: Sequence[str]
) -> Optional[TrackDescriptor]:
    """AC-3's BCP-47 matching table: for each requested language, in the caller's
    preference order, an exact `languageCode` match (case-insensitive) is
    preferred; failing that, a primary-subtag match (`"en"` matches an available
    `en-US` track) is used. Manual is preferred over auto-generated within each
    tier -- already guaranteed here by `sorted_tracks` having gone through
    `sort_tracks()` first, so the first hit encountered in iteration order is
    already the correct manual-over-auto pick."""
    for requested in languages:
        requested_lower = requested.lower()
        for track in sorted_tracks:
            if track.language_code.lower() == requested_lower:
                return track
        requested_subtag = _primary_subtag(requested)
        for track in sorted_tracks:
            if _primary_subtag(track.language_code) == requested_subtag:
                return track
    return None


def select_track(
    listing: TrackListing,
    *,
    languages: Optional[Sequence[str]] = None,
    track_id: Optional[str] = None,
) -> Optional[TrackDescriptor]:
    """AC-2's five-tier deterministic resolution order, with `track_id` (AC-5)
    taking precedence over `languages`:

    1. Exact `track_id` match. If `track_id` is supplied it is the *only* tier
       consulted: an invalid `track_id` (fails `parse_track_id`'s shape check) or
       one that matches no track in `listing` returns `None` immediately rather
       than falling through to tiers 2-5 -- so the caller (AC-5) can map that
       directly to `language_unavailable` instead of silently resolving a
       different track than the one explicitly requested.
    2. The caller's `languages` preference list (AC-3). If `languages` was
       supplied (non-empty) and matches no track, this is likewise a hard stop:
       `None` is returned immediately, the same as tier 1's no-match case --
       tiers 3-5 are **not** consulted in this case (AC-3: "It does NOT silently
       fall back to another language."). Tiers 3-5 below only ever run when
       `languages` was NOT supplied at all (empty/`None`) -- AC-2's own
       "called with no languages/trackId/format params" default-invocation case.
    3. A track whose `language_code` matches `listing.default_audio_language`.
    4. A track upstream marks as the default caption track (`is_default=True`),
       independent of tier 3's signal.
    5. Fallback: the first manual track, else the first auto-generated track,
       sorted by `language_code` -- exactly `sort_tracks()`'s own ordering, so
       tier 5 is just that tuple's first element.

    A `default_audio_language` of `None` and the absence of any `is_default=True`
    track are both valid, non-error states: tiers 3/4 are silently skipped, not
    raised as an error, falling through to tier 5 (AC-2) -- but only on the
    no-`languages`-supplied path; see tier 2 above for the `languages`-supplied
    hard-stop case.
    """
    if track_id is not None:
        parsed = parse_track_id(track_id)
        if parsed is None:
            return None
        kind, language_code = parsed
        for track in listing.tracks:
            if track.kind == kind and track.language_code == language_code:
                return track
        return None

    sorted_tracks = sort_tracks(listing.tracks)

    if languages:
        # AC-3: `languages` was explicitly supplied and non-empty -- this tier
        # is a hard stop. A match returns immediately; a non-match returns
        # `None` immediately, without falling through to tiers 3-5 below.
        return _match_languages(sorted_tracks, languages)

    if listing.default_audio_language is not None:
        for track in sorted_tracks:
            if track.language_code == listing.default_audio_language:
                return track

    for track in sorted_tracks:
        if track.is_default:
            return track

    if sorted_tracks:
        return sorted_tracks[0]
    return None


def validate_languages(languages: Optional[Sequence[str]]) -> List[str]:
    """AC-3's `languages` cap: at most 10 entries, each at most 20 characters.
    A violation is "rejected the same way as a non-matching language" (AC-3's own
    wording) -- a domain outcome for the caller to turn into
    `status: "language_unavailable"`, never a schema-level error raised here. So
    this never raises: an out-of-cap input simply comes back as an empty list,
    which `select_track()`'s tier 4 then treats identically to "no `languages`
    supplied at all" (falling through to tier 5), leaving the "the caller asked
    for languages that didn't resolve" distinction to the tool layer that also
    sees the original, unvalidated input.
    """
    if languages is None:
        return []
    # `languages` is untrusted, JSON-decoded `tools/call` input (schema declares
    # it a string array, but `protocol/dispatch.py` never checks argument type,
    # only presence) -- a non-list/tuple value, or a list containing a non-str
    # entry, must be rejected the same way as any other cap violation (this
    # docstring's own framing) rather than crashing `len()`/`len(language)` with
    # a raw `TypeError`.
    if not isinstance(languages, (list, tuple)):
        return []
    if len(languages) > _MAX_LANGUAGES:
        return []
    for language in languages:
        if not isinstance(language, str) or len(language) > _MAX_LANGUAGE_LENGTH:
            return []
    return list(languages)

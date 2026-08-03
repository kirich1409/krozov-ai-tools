"""`get_transcript` tool handler (T-12): track resolution, cursor-driven
pagination, and content encoding -- the most complex tools-layer handler in this
server, where AC-3/AC-4/AC-5/AC-7/AC-8/AC-11 all meet. See
`docs/plans/youtube-transcript/tasks.md`'s T-12 block for the full acceptance
list this module implements against.

`tools/` (`ALLOWED_EDGES`) may import `domain/`, `formats/`, and
`providers/base.py` -- plus same-package `tools/cursor.py`/`tools/resolution.py`
(the general same-package-imports-always-allowed rule), never
`providers/innertube.py` directly. This module uses all of the above, plus
`tools/__init__.py::outcome_from_error`.

**Pagination (AC-11) in one pass**: a `cursor` argument, once decoded, replaces
`video`/`languages`/`trackId`/`format`/`includeTimestamps` entirely rather than
merging with them -- the cursor's own five encoded fields are the *only* values a
continuation call resolves against (`_handle_with_cursor` never reads any of
those five keys out of `args`). A fresh call (no `cursor`) starts pagination at
`segment_index=0`, which makes the `formats.count_pages_to` replay below a
zero-iteration no-op on that path -- the extra cost only shows up on a deep
continuation call, exactly as AC-11 describes.

**The entire body is wrapped in one `except DomainFailure -> outcome_from_error`**
(`handle()` below), not just the encode/count_pages_to call site -- covers
`provider.open(...)`/`session.fetch(...)` raising `DeadlineExpired`,
`formats.encode`/`formats.count_pages_to` raising it mid-pass, and
`tools.cursor.decode` raising `CursorInvalid`, uniformly.

Stdlib only.
"""

from typing import Any, Dict, List, Optional

import formats
from domain import Deadline, DomainFailure, FORMATS, Status, ToolOutcome, TrackListing, VideoId
from formats import FormatOptions, MAX_PAGE_CHARS, MAX_PAGES
from providers.base import TranscriptProvider, UpstreamChanged
from tools import cursor as tools_cursor
from tools import outcome_from_error
from tools.resolution import select_track, validate_languages

# AC-3's cap, shared with AC-1: at most 50 entries in `availableLanguages`.
_MAX_AVAILABLE_LANGUAGES = 50

# AC-4: `format` defaults to "text" when omitted -- and, since this server's own
# `protocol/dispatch.py` only validates the `tools/call` request's *required*
# fields (never the full `inputSchema`, including its `enum` constraints), an
# out-of-enum value reaching here falls back to the same default rather than
# raising, on the theory that a well-behaved MCP host already enforces the
# schema's `enum` before a call is ever made.
_DEFAULT_FORMAT = "text"


def handle(provider: TranscriptProvider, deadline: Deadline, args: Dict[str, Any]) -> ToolOutcome:
    try:
        cursor_raw = args.get("cursor")
        if cursor_raw:
            return _handle_with_cursor(provider, deadline, args, cursor_raw)
        return _handle_fresh(provider, deadline, args)
    except DomainFailure as exc:
        return outcome_from_error(exc)


def _normalize_video(provider: TranscriptProvider, video_arg: Any) -> Optional[VideoId]:
    # A non-string `video_arg` (schema declares it a string, but nothing upstream
    # of this handler enforces that -- see `_DEFAULT_FORMAT`'s comment above)
    # is treated as an unrecognizable reference, never passed into a provider
    # method typed to expect `str`.
    if not isinstance(video_arg, str):
        return None
    return provider.normalize_video_ref(video_arg)


def _handle_fresh(provider: TranscriptProvider, deadline: Deadline, args: Dict[str, Any]) -> ToolOutcome:
    video_id = _normalize_video(provider, args.get("video"))
    if video_id is None:
        # AC-6/AC-8: normalization runs, and fails, before any outbound request
        # -- `provider.open` must not be called at all here.
        return ToolOutcome(status=Status.VIDEO_NOT_FOUND)

    raw_languages = args.get("languages")
    languages = validate_languages(raw_languages)
    # AC-3: a genuinely cap-violated `languages` list (>10 entries, or an entry
    # >20 chars) validates down to `[]`, identically to "no `languages` supplied
    # at all" -- `validate_languages()` itself doesn't distinguish the two (see
    # its own docstring). This flag recovers the distinction here, from the raw,
    # unvalidated argument, so a cap violation can be rejected the same way as a
    # non-matching language (AC-3) instead of silently falling through to the
    # AC-2 default-invocation tiers. A `None` or already-empty `raw_languages` is
    # legitimately "no languages requested" and leaves this `False`.
    languages_capped = isinstance(raw_languages, (list, tuple)) and len(raw_languages) > 0 and not languages
    track_id = args.get("trackId")
    fmt = args.get("format")
    # `fmt not in FORMATS` alone would raise `TypeError: unhashable type` for a
    # non-str, unhashable `format` (e.g. a JSON array/object) -- `args` is
    # untrusted JSON that `protocol/dispatch.py` never type-checks beyond
    # presence, so the `isinstance` guard must run (and short-circuit) first.
    if not isinstance(fmt, str) or fmt not in FORMATS:
        fmt = _DEFAULT_FORMAT
    # `includeTimestamps` is untrusted JSON input (schema declares it a boolean,
    # but `protocol/dispatch.py` never checks argument type, only presence) --
    # `bool(...)` alone would truthiness-coerce a non-bool value (e.g. the string
    # "false", or `1`) to `True` instead of treating it as the AC-4 default, so
    # the type must be checked explicitly before use.
    raw_include_timestamps = args.get("includeTimestamps", False)
    include_timestamps = isinstance(raw_include_timestamps, bool) and raw_include_timestamps

    return _resolve_and_paginate(
        provider,
        deadline,
        video_id,
        languages=languages,
        languages_capped=languages_capped,
        track_id=track_id,
        fmt=fmt,
        include_timestamps=include_timestamps,
        segment_index=0,
    )


def _handle_with_cursor(
    provider: TranscriptProvider, deadline: Deadline, args: Dict[str, Any], cursor_raw: str
) -> ToolOutcome:
    # First-phase validation (shape, enum membership, MAX_SEGMENTS ceiling) --
    # raises CursorInvalid on any failure, caught by handle()'s blanket
    # `except DomainFailure` and mapped to upstream_changed.
    fields = tools_cursor.decode(cursor_raw)

    video_id = _normalize_video(provider, args.get("video"))
    if video_id is None:
        return ToolOutcome(status=Status.VIDEO_NOT_FOUND)
    if video_id.value != fields.video_id:
        # AC-11: a continuation call's `video` argument MUST match the cursor's
        # embedded videoId -- a mismatch is upstream_changed, not video_not_found
        # (the video itself resolves fine; it just isn't the one this cursor was
        # issued for).
        raise UpstreamChanged("get_transcript: cursor videoId does not match the video argument")

    # AC-11: every other supplied argument (languages/trackId/format/
    # includeTimestamps) is ignored in favor of the cursor's own encoded values
    # -- so none of them is read here at all.
    return _resolve_and_paginate(
        provider,
        deadline,
        VideoId(fields.video_id),
        languages=None,
        languages_capped=False,
        track_id=fields.track_id,
        fmt=fields.format,
        include_timestamps=fields.include_timestamps,
        segment_index=fields.segment_index,
    )


def _resolve_and_paginate(
    provider: TranscriptProvider,
    deadline: Deadline,
    video_id: VideoId,
    *,
    languages: Optional[List[str]],
    languages_capped: bool,
    track_id: Optional[str],
    fmt: str,
    include_timestamps: bool,
    segment_index: int,
) -> ToolOutcome:
    session = provider.open(video_id, deadline)
    listing: TrackListing = session.listing

    if not listing.tracks:
        # AC-7: no captions at all. This path costs exactly the 2 requests
        # `provider.open` itself issues (watch page + player) -- `session.fetch`
        # is never called.
        return ToolOutcome(status=Status.NO_TRANSCRIPT)

    if languages_capped and track_id is None:
        # AC-3/AC-5: a cap-violated `languages` list is rejected the same way as
        # a non-matching one -- but only when there's no `trackId` to fall back
        # to (AC-5: `trackId` still takes precedence over a capped `languages`
        # list when both are supplied). Short-circuit `select_track` entirely by
        # forcing the same "no track resolved" branch below, rather than
        # duplicating its `availableLanguages` construction.
        resolved = None
    else:
        resolved = select_track(listing, languages=languages, track_id=track_id)
    if resolved is None:
        # AC-3/AC-5: sorted, deduped languageCode list from the freshly resolved
        # tracks, capped at AC-1's shared 50-entry limit.
        available = sorted({track.language_code for track in listing.tracks})
        return ToolOutcome(
            status=Status.LANGUAGE_UNAVAILABLE,
            payload={"availableLanguages": available[:_MAX_AVAILABLE_LANGUAGES]},
        )

    transcript = session.fetch(resolved, deadline)

    if segment_index > len(transcript.segments):
        # AC-11's second-phase check: only knowable once the track is actually
        # fetched and decoded, since that's what produces the real segment
        # count -- tools/cursor.py::decode() cannot see this at first-phase
        # validation time.
        raise UpstreamChanged(
            "get_transcript: cursor segmentIndex exceeds the fetched track's real segment count"
        )

    options = FormatOptions(include_timestamps=include_timestamps)

    # AC-11's derived page-counting: replay the same segment-aligned chunking
    # from segmentIndex=0 up to this call's own start index, deriving how many
    # MAX_PAGE_CHARS-sized pages precede it -- no stored counter, no forgeable
    # cursor field. A fresh call (segment_index=0) makes this a 0-iteration
    # no-op; the cost only shows up on a deep continuation call.
    pages_before_this_one = formats.count_pages_to(
        transcript,
        fmt,
        target_index=segment_index,
        max_chars=MAX_PAGE_CHARS,
        options=options,
        deadline=deadline,
    )
    if pages_before_this_one >= MAX_PAGES:
        # The ceiling was already reached by the page this call would have
        # produced -- refuse rather than continuing (AC-11). This is a full
        # fetch+decode before this response, an accepted v1 cost (no
        # cross-invocation caching, plan.md Decisions Made) -- not fast-pathed.
        return ToolOutcome(
            status=Status.OK,
            payload={
                "resolved_track": resolved,
                "transcript": "",
                "truncated": True,
                "nextCursor": None,
            },
        )

    page = formats.encode(
        transcript,
        fmt,
        start_index=segment_index,
        max_chars=MAX_PAGE_CHARS,
        options=options,
        deadline=deadline,
    )

    has_more = page.next_index < len(transcript.segments)
    next_cursor = (
        tools_cursor.encode(
            tools_cursor.CursorFields(
                video_id=video_id.value,
                track_id=resolved.track_id,
                format=fmt,
                include_timestamps=include_timestamps,
                segment_index=page.next_index,
            )
        )
        if has_more
        else None
    )

    return ToolOutcome(
        status=Status.OK,
        payload={
            "resolved_track": resolved,
            "transcript": page.text,
            "truncated": has_more,
            "nextCursor": next_cursor,
        },
    )


__all__ = ["handle"]

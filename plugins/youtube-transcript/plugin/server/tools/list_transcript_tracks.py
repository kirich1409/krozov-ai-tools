"""`list_transcript_tracks` tool handler (T-11): lists a video's caption tracks
with derived `estimatedCharacters`, never fetching any track's actual content.

`tools/` (`ALLOWED_EDGES`) may import `domain/`, `formats/`, and
`providers/base.py` -- never `providers/innertube.py` directly. This module uses
`domain/` (`ToolOutcome`, `Status`, `TrackDescriptor`, `DomainFailure`), `formats/`
(`estimate_characters`), and `providers/base.py` only via the `TranscriptProvider`
type already threaded in through `handle()`'s parameter -- no new edge needed.

Stdlib only.
"""

from typing import Any, Dict

from domain import Deadline, DomainFailure, Status, ToolOutcome, TrackDescriptor
from formats import estimate_characters
from providers.base import TranscriptProvider
from tools import outcome_from_error
from tools.resolution import sort_tracks

# AC-1: at most 50 tracks returned, sorted manual-before-auto then alphabetically
# by languageCode (sort_tracks, T-9), before truncation.
MAX_TRACKS = 50


def handle(provider: TranscriptProvider, deadline: Deadline, args: Dict[str, Any]) -> ToolOutcome:
    # Entire body wrapped in one `except DomainFailure` (tasks.md T-11 cycle-8 fix)
    # -- both `provider.open(...)` and `formats.estimate_characters(...)` can raise
    # `DeadlineExpired`, and both must map to `status: transport_error` the same way.
    try:
        video_id = provider.normalize_video_ref(args["video"])
        if video_id is None:
            # AC-6/AC-8: normalization runs, and fails, before any outbound
            # request -- `provider.open` must not be called at all here.
            return ToolOutcome(status=Status.VIDEO_NOT_FOUND)

        session = provider.open(video_id, deadline)
        # `session.fetch(...)` is never called by this tool -- it only lists
        # tracks, it doesn't fetch content.

        listing = session.listing
        if not listing.tracks:
            # AC-7: no captions at all -> no_transcript, but the envelope must
            # still carry videoDurationSeconds (FIELDS_BY_STATUS[no_transcript]).
            return ToolOutcome(
                status=Status.NO_TRANSCRIPT,
                payload={"tracks": [], "videoDurationSeconds": listing.duration_seconds},
            )

        sorted_tracks = sort_tracks(listing.tracks)
        truncated = len(sorted_tracks) > MAX_TRACKS
        kept = sorted_tracks[:MAX_TRACKS]

        # Computed exactly once per handle() invocation -- depends only on
        # duration_seconds, identical for every track of this video (tasks.md
        # T-11 cycle-8 fix) -- and reused across all kept tracks below, never
        # recomputed per track.
        estimated_characters = estimate_characters(listing.duration_seconds)

        response_tracks = tuple(
            TrackDescriptor(
                track_id=track.track_id,
                language_code=track.language_code,
                language_name=track.language_name,
                kind=track.kind,
                estimated_characters=estimated_characters,
                is_default=track.is_default,
            )
            for track in kept
        )

        return ToolOutcome(
            status=Status.OK,
            payload={
                "tracks": response_tracks,
                "videoDurationSeconds": listing.duration_seconds,
                "truncated": truncated,
            },
        )
    except DomainFailure as exc:
        return outcome_from_error(exc)


__all__ = ["MAX_TRACKS", "handle"]

"""The provider port -- `TranscriptProvider`/`ProviderSession` ABCs, the closed
`ProviderError(DomainFailure)` hierarchy, and the opaque `trackId` codec.

`providers/base.py` may import only `domain/` (own-package imports of
`providers/video_ref.py` are also fine, per the general same-package rule) --
**never `providers/innertube.py`** (plan.md cycle 4 finding: the general
same-package rule would otherwise accidentally legalize the abstraction importing
its own concrete implementation, the one dependency direction `composition.py`
exists as a separate wiring layer specifically to avoid, AC-23/AC-24). Enforced by
`tests/test_import_boundaries.py::test_providers_base_cannot_import_innertube`.

Stdlib only.
"""

import re
from abc import ABC, abstractmethod
from typing import ClassVar, Optional, Tuple

from domain import DomainFailure, Deadline, Status, TrackDescriptor, TrackListing, Transcript, VideoId

# --- Provider port -------------------------------------------------------------


class TranscriptProvider(ABC):
    """Stateless port: `open()` never stores per-video state on `self` (T-10's
    `test_provider_holds_no_per_video_state` makes this a falsifiable property)."""

    @abstractmethod
    def normalize_video_ref(self, value: str) -> Optional[VideoId]:
        """Parse/normalize a caller-supplied `video` string into a `VideoId`, or
        `None` if `value` is not a recognizable reference (AC-6)."""

    @abstractmethod
    def open(self, video_id: VideoId, deadline: Deadline) -> "ProviderSession":
        """Resolve the video and return a session holding the parsed player-response
        context as its own attribute. Always succeeds for a playable video
        regardless of whether it has captions -- `NoTranscript` is not raised here
        (plan.md cycle 2); raises a `ProviderError` subclass otherwise."""


class ProviderSession(ABC):
    """Holds one video's already-resolved listing. `listing.tracks` may be an empty
    tuple (no captions) -- this is `no_transcript`, resolved by `tools/`, not here."""

    listing: TrackListing

    @abstractmethod
    def fetch(self, track: TrackDescriptor, deadline: Deadline) -> Transcript:
        """Fetch and decode one track's captions. `deadline` is this call's own
        explicit parameter (plan.md cycle 3 -- never silently inherited from
        `open()`'s deadline). Raises `UpstreamChanged` if `track` is not, by
        identity/equality, a member of `self.listing.tracks` (precondition stated
        here, tested at T-10)."""


# --- ProviderError hierarchy ---------------------------------------------------
#
# `ProviderError(DomainFailure)` -- was `ProviderError(Exception)` before plan.md
# cycle 4 introduced `DomainFailure` as the common base so `protocol/`'s dispatch
# layer can do `isinstance(exc, DomainFailure)` via its already-permitted `domain/`
# edge, without needing a forbidden edge to `providers/base.py` itself.
#
# Each subclass pins its own `status: ClassVar[Status]` (never dynamically computed)
# so `tools/__init__.py::outcome_from_error` (below this file, in `tools/`) can map
# any `ProviderError` instance to a `ToolOutcome` with zero per-subclass special
# casing. `NoTranscript` is deliberately absent -- removed from the hierarchy
# entirely by plan.md's cycle-2 redesign (see `ProviderSession.open`'s docstring).


class ProviderError(DomainFailure):
    """Common base for the ten closed subclasses below. Never raised directly."""

    status: ClassVar[Status]

    def __init__(self, message: str = "", *, retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class VideoNotFound(ProviderError):  # noqa: N818 -- name pinned literally by tasks.md's T-3 block
    status = Status.VIDEO_NOT_FOUND


class VideoUnavailable(ProviderError):  # noqa: N818
    status = Status.VIDEO_UNAVAILABLE


class AgeRestricted(ProviderError):  # noqa: N818
    status = Status.AGE_RESTRICTED


class RegionBlocked(ProviderError):  # noqa: N818
    status = Status.REGION_BLOCKED


class LiveNotReady(ProviderError):  # noqa: N818
    status = Status.LIVE_NOT_READY


class RateLimited(ProviderError):  # noqa: N818
    status = Status.RATE_LIMITED


class BlockedByProvider(ProviderError):  # noqa: N818
    status = Status.BLOCKED_BY_PROVIDER


class UpstreamChanged(ProviderError):  # noqa: N818
    status = Status.UPSTREAM_CHANGED


class TranscriptTooLarge(ProviderError):  # noqa: N818
    status = Status.TRANSCRIPT_TOO_LARGE


class TransportError(ProviderError):
    status = Status.TRANSPORT_ERROR


# --- Opaque trackId codec -------------------------------------------------------
#
# AC-18: `trackId` is composed only of `{languageCode, kind}` -- never a URL, host,
# or path fragment. `_TRACK_ID_PATTERN` is the exact validation shape AC-18 and
# `domain.TrackDescriptor.__post_init__` both apply, restated here since this is the
# single place a caller-supplied (or cursor-decoded) `trackId` string is parsed back
# into its two constituent fields.
_TRACK_ID_PATTERN = re.compile(r"^(manual|auto):([A-Za-z0-9-]{1,20})\Z")


def encode_track_id(kind: str, language_code: str) -> str:
    return f"{kind}:{language_code}"


def parse_track_id(value: str) -> Optional[Tuple[str, str]]:
    """Returns `(kind, language_code)`, or `None` if `value` does not match
    `^(manual|auto):[A-Za-z0-9-]{1,20}$` (AC-18) -- never raises on malformed input,
    since a caller-supplied `trackId` (AC-5) or a cursor-decoded one (AC-11) is
    exactly the kind of untrusted input this function exists to reject cleanly.
    A non-`str` `value` (e.g. `tools/get_transcript.py`'s `args.get("trackId")`,
    read from untrusted JSON without a type check upstream) is likewise treated
    as "does not match" rather than raising -- `re.Pattern.match` on a non-
    string/bytes object raises a raw `TypeError`, which is exactly the kind of
    escape this function's own docstring promises never happens."""
    if not isinstance(value, str):
        return None
    match = _TRACK_ID_PATTERN.match(value)
    if match is None:
        return None
    return match.group(1), match.group(2)

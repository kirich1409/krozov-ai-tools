"""AC-11's pagination cursor codec: `encode()`/`decode()` for the opaque
`nextCursor` string a continuation `get_transcript` call carries.

`CursorFields` binds all five values AC-11 requires the wire encoding to carry
-- `video_id` and `track_id` (so a continuation call is bound to the same video
and track, not just a raw pagination position), `format`, `include_timestamps`,
and `segment_index`. There is deliberately no sixth `pageOrdinal`/page-number
field (plan.md cycle 2 finding): page counting is derived by replaying the
segment-aligned chunking from `segmentIndex = 0` (see `formats.count_pages_to`,
T-5), not carried as its own cursor value, so a field for it would be both
unreachable by any server-emitted cursor and would contradict this module's own
five-key `decode()` check below.

`decode()` raises `domain.CursorInvalid` (declared in `domain/`, T-2 -- not
redefined here, see that module's symbol-placement-rule docstring) on any
validation failure, first-phase only (AC-11's second-phase `segmentIndex`-vs-
real-segment-count check needs the fetched track and so belongs to T-12's
`get_transcript`, not here).

`tools/` may import `domain/`, `formats/`, and `providers/base.py`
(`ALLOWED_EDGES`, plan.md) -- this module uses the first and third, no new edge
needed. Stdlib only (`base64`, `json`).
"""

import base64
import json
import re
from dataclasses import dataclass

from domain import FORMATS, MAX_SEGMENTS, CursorInvalid
from providers.base import parse_track_id

# Cursor string longer than this is rejected before any decode work at all --
# not even the ascii-encode/base64-decode step runs (AC-11).
MAX_CURSOR_CHARS = 512

# The cursor's wire-level dict must have exactly these five keys -- nothing
# more, nothing fewer (AC-11).
_VIDEO_ID_KEY = "videoId"
_TRACK_ID_KEY = "trackId"
_FORMAT_KEY = "format"
_INCLUDE_TIMESTAMPS_KEY = "includeTimestamps"
_SEGMENT_INDEX_KEY = "segmentIndex"
_EXPECTED_KEYS = frozenset(
    {_VIDEO_ID_KEY, _TRACK_ID_KEY, _FORMAT_KEY, _INCLUDE_TIMESTAMPS_KEY, _SEGMENT_INDEX_KEY}
)

# AC-6's video ID pattern, restated here rather than imported: `providers/video_ref.py`'s
# copy is a private module attribute (`_VIDEO_ID_PATTERN`), and `tools/` has no
# permitted edge to `providers.video_ref` in the first place (only
# `providers.base`, ALLOWED_EDGES) -- so this module owns its own compiled
# pattern rather than reaching for either.
_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class CursorFields:
    """The five values a pagination cursor binds together -- see this module's
    docstring for why there is no sixth `page_ordinal` field."""

    video_id: str
    track_id: str
    format: str
    include_timestamps: bool
    segment_index: int


def encode(fields: CursorFields) -> str:
    payload = {
        _VIDEO_ID_KEY: fields.video_id,
        _TRACK_ID_KEY: fields.track_id,
        _FORMAT_KEY: fields.format,
        _INCLUDE_TIMESTAMPS_KEY: fields.include_timestamps,
        _SEGMENT_INDEX_KEY: fields.segment_index,
    }
    raw_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw_json, altchars=b"-_").decode("ascii")


def decode(raw: str) -> CursorFields:
    # 1. Size cap, before any decode work at all (AC-11).
    if len(raw) > MAX_CURSOR_CHARS:
        raise CursorInvalid(f"cursor exceeds {MAX_CURSOR_CHARS} characters")

    # 2. `b64decode(altchars=b"-_", validate=True)`, never `urlsafe_b64decode`
    # (which silently strips invalid characters instead of raising). Every
    # failure mode reachable here -- a non-ascii `raw`, invalid base64
    # alphabet/padding, or malformed JSON -- subclasses `ValueError` in CPython
    # (`UnicodeEncodeError`/`binascii.Error`/`json.JSONDecodeError` all do),
    # so one `except ValueError` covers all three decode phases.
    try:
        decoded_bytes = base64.b64decode(raw.encode("ascii"), altchars=b"-_", validate=True)
        parsed = json.loads(decoded_bytes)
    except ValueError as exc:
        raise CursorInvalid("cursor failed to decode as base64url JSON") from exc

    # 3. Decoded JSON must be a dict with exactly these five keys.
    if not isinstance(parsed, dict):
        raise CursorInvalid("decoded cursor is not a JSON object")
    if set(parsed.keys()) != _EXPECTED_KEYS:
        raise CursorInvalid(
            f"decoded cursor has keys {sorted(parsed.keys())}, expected {sorted(_EXPECTED_KEYS)}"
        )

    video_id = parsed[_VIDEO_ID_KEY]
    track_id = parsed[_TRACK_ID_KEY]
    fmt = parsed[_FORMAT_KEY]
    include_timestamps = parsed[_INCLUDE_TIMESTAMPS_KEY]
    segment_index = parsed[_SEGMENT_INDEX_KEY]

    # 4. `videoId` against the AC-6 regex.
    if not isinstance(video_id, str) or not _VIDEO_ID_PATTERN.match(video_id):
        raise CursorInvalid("cursor videoId failed the AC-6 pattern")

    # 5. `segmentIndex` non-negative and below MAX_SEGMENTS. `bool` is a
    # subclass of `int` in Python, so it is excluded explicitly -- `true`/`false`
    # are not valid segment indices even though `isinstance(True, int)` holds.
    if (
        isinstance(segment_index, bool)
        or not isinstance(segment_index, int)
        or segment_index < 0
        or segment_index >= MAX_SEGMENTS
    ):
        raise CursorInvalid("cursor segmentIndex out of bounds")

    # 6. `format` against the AC-4 enum (`FORMATS`, from `domain/`).
    if not isinstance(fmt, str) or fmt not in FORMATS:
        raise CursorInvalid("cursor format not in the AC-4 enum")

    # 7. `includeTimestamps` must be an actual bool, not a truthy/falsy non-bool
    # value (e.g. `1`/`0`/`"true"`).
    if not isinstance(include_timestamps, bool):
        raise CursorInvalid("cursor includeTimestamps is not a bool")

    # 8. `trackId` against AC-18's shape, via `parse_track_id` (reused from
    # `providers/base.py`, a permitted `tools/ -> providers/base.py` edge).
    if not isinstance(track_id, str) or parse_track_id(track_id) is None:
        raise CursorInvalid("cursor trackId failed parse_track_id")

    return CursorFields(
        video_id=video_id,
        track_id=track_id,
        format=fmt,
        include_timestamps=include_timestamps,
        segment_index=segment_index,
    )


__all__ = ["MAX_CURSOR_CHARS", "CursorFields", "decode", "encode"]

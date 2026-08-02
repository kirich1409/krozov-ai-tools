"""Plain-text encoder (T-5).

One line per segment: `"{text}\\n"`, or `"[{timestamp}] {text}\\n"` when
`options.include_timestamps` is set (AC-4's `format: "text"` + `includeTimestamps`).
`timestamp` is `HH:MM:SS.mmm` of the segment's `start_ms` -- this server's own choice
of representation (the spec does not pin an exact string), documented here rather than
left implicit.

No fixed per-page overhead (no header, unlike `vtt.py`) and no cue-injection
neutralization (that only applies to `srt`/`vtt` cue text, AC-21) -- plain text has no
cue-boundary syntax for caption text to forge in the first place.

Because every segment renders to a self-contained `"...\\n"` chunk with no separator
that depends on page position, concatenating pages produced by repeated `encode()`
calls reproduces byte-for-byte what a single whole-document `encode()` call would
produce (the byte-exact-concat property).
"""

from domain import Deadline, Segment, Transcript

from formats import FormatOptions, MAX_PAGE_CHARS, Page
from formats._paging import DeadlineStride, fit_page, format_timecode


def _render_segment(segment: Segment, options: FormatOptions) -> str:
    if options.include_timestamps:
        return f"[{format_timecode(segment.start_ms, '.')}] {segment.text}\n"
    return f"{segment.text}\n"


def encode(
    transcript: Transcript,
    fmt: str,
    *,
    start_index: int = 0,
    max_chars: int = MAX_PAGE_CHARS,
    options: FormatOptions,
    deadline: Deadline,
) -> Page:
    segments = transcript.segments
    stride = DeadlineStride()
    count = fit_page(
        segments,
        start_index,
        max_chars,
        0,
        lambda i: len(_render_segment(segments[i], options)),
        deadline,
        stride,
    )
    rendered = "".join(_render_segment(segments[i], options) for i in range(start_index, start_index + count))
    return Page(text=rendered, next_index=start_index + count)


def count_pages_to(
    transcript: Transcript,
    fmt: str,
    *,
    target_index: int,
    max_chars: int,
    options: FormatOptions,
    deadline: Deadline,
) -> int:
    segments = transcript.segments
    stride = DeadlineStride()
    index = 0
    pages = 0
    while index < target_index:
        count = fit_page(
            segments,
            index,
            max_chars,
            0,
            lambda i: len(_render_segment(segments[i], options)),
            deadline,
            stride,
        )
        if count == 0:
            break
        index += count
        pages += 1
    return pages

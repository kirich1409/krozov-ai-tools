"""SRT encoder (T-5).

Standard SubRip cue block, one per segment:

    {cue_number}
    {start} --> {end}
    {cue_text}
    <blank line>

`cue_number` is `index + 1` -- derived directly from the segment's position, never a
separately-threaded counter, so it continues monotonically across pages for free
(AC-11: "cue numbering (srt) continues monotonically across pages"): segment `i` is
always cue `i + 1` no matter which page it lands on. `start`/`end` are `HH:MM:SS,mmm`
(comma decimal separator, the real SRT convention -- vtt.py uses a dot instead).
`cue_text` is `segment.text` run through `formats._cue.collapse_cue_text` (AC-21).

No fixed per-page overhead (no header, unlike `vtt.py`). Every cue block already ends
in its own blank line (`"\\n\\n"`), which is also the correct separator between
consecutive cues -- so pages concatenate byte-for-byte with no extra join logic, and
iterating pages via `encode()` reproduces exactly what one whole-document `encode()`
call would produce (the byte-exact-concat property).
"""

from domain import Deadline, Segment, Transcript

from formats import FormatOptions, MAX_PAGE_CHARS, Page
from formats._cue import collapse_cue_text
from formats._paging import DeadlineStride, fit_page, format_timecode


def _render_segment(segment: Segment, index: int, options: FormatOptions) -> str:
    # `options` is accepted for a uniform render-callback signature across
    # text.py/srt.py/vtt.py, but unused here -- srt always renders cue timing,
    # nothing about a cue block varies by FormatOptions (only text.py's
    # `include_timestamps` does, per AC-4).
    cue_number = index + 1
    start = format_timecode(segment.start_ms, ",")
    end = format_timecode(segment.start_ms + segment.duration_ms, ",")
    cue_text = collapse_cue_text(segment.text)
    return f"{cue_number}\n{start} --> {end}\n{cue_text}\n\n"


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
        lambda i: len(_render_segment(segments[i], i, options)),
        deadline,
        stride,
    )
    rendered = "".join(
        _render_segment(segments[i], i, options) for i in range(start_index, start_index + count)
    )
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
            lambda i: len(_render_segment(segments[i], i, options)),
            deadline,
            stride,
        )
        if count == 0:
            break
        index += count
        pages += 1
    return pages

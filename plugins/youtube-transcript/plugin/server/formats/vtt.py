"""WebVTT encoder (T-5).

Every page starts with its own `WEBVTT\\n\\n` header + blank line (plan.md's Technical
Approach table: "vtt's encoder emits its own header block per page") -- so any single
page is, on its own, a structurally valid VTT document (`test_per_page_valid`), and the
header's fixed length counts against that page's `max_chars` budget from the start
(`_HEADER_OVERHEAD` below, threaded into `fit_page`'s `fixed_overhead`).

Cue block, one per segment, no cue number (optional in VTT, omitted here -- unlike
`srt.py`, AC-11 only requires monotonic cue *numbering* for `srt`):

    {start} --> {end}
    {cue_text}
    <blank line>

`start`/`end` are `HH:MM:SS.mmm` (dot decimal separator -- the real WebVTT convention;
`srt.py` uses a comma instead). `cue_text` is `segment.text` run through
`formats._cue.collapse_cue_text` (AC-21).

Concatenating pages produced by repeated `encode()` calls does **not** reproduce a
whole-document `encode()` call byte-for-byte, because every page carries its own
header -- reproducing the whole document requires stripping the header (its first two
lines: `WEBVTT` + the blank line after it) from every page except the first before
concatenating (`test_two_line_header_strip_concat`); byte-exact concat as `text.py`/
`srt.py` have it does not apply here, per this task's own constraints.
"""

from domain import Deadline, Segment, Transcript

from formats import FormatOptions, MAX_PAGE_CHARS, Page
from formats._cue import collapse_cue_text
from formats._paging import DeadlineStride, fit_page, format_timecode

HEADER = "WEBVTT\n\n"
_HEADER_OVERHEAD = len(HEADER)


def _render_segment(segment: Segment, options: FormatOptions) -> str:
    # `options` is accepted for a uniform render-callback signature across
    # text.py/srt.py/vtt.py, but unused here -- see srt.py's identical note.
    start = format_timecode(segment.start_ms, ".")
    end = format_timecode(segment.start_ms + segment.duration_ms, ".")
    cue_text = collapse_cue_text(segment.text)
    return f"{start} --> {end}\n{cue_text}\n\n"


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
        _HEADER_OVERHEAD,
        lambda i: len(_render_segment(segments[i], options)),
        deadline,
        stride,
    )
    rendered = "".join(_render_segment(segments[i], options) for i in range(start_index, start_index + count))
    return Page(text=HEADER + rendered, next_index=start_index + count)


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
            _HEADER_OVERHEAD,
            lambda i: len(_render_segment(segments[i], options)),
            deadline,
            stride,
        )
        if count == 0:
            break
        index += count
        pages += 1
    return pages

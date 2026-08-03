"""Format-layer constants and dispatch (T-3 constants, T-5 encoders + dispatch).

`formats/` may import only `domain/` (`ALLOWED_EDGES`). `MAX_SEGMENTS`/`FORMATS` are
re-exported here from `domain/`, not redefined -- moved there by plan.md's
symbol-placement rule (cycle 3/cycle 7) since `providers/innertube.py` and
`protocol/schemas.py` also need them and neither has a permitted edge to `formats/`.

`Page`/`FormatOptions` are defined here (not `domain/`) and imported *back* by
`text.py`/`srt.py`/`vtt.py` -- deliberately, and in this file's top-to-bottom order:
this module also imports `text`/`srt`/`vtt` (for the dispatch table below), which is
a real import cycle in the trivial, standard-Python-safe sense (a submodule importing
attributes off its own still-initializing parent package). It works because `Page`,
`FormatOptions`, and the constants above are all bound as attributes of this module
*before* the `from formats import text` (etc.) lines run -- by the time those
submodules ask for `formats.Page`, it already exists in `sys.modules["formats"]`.
Reordering the sections below (constants/types before the submodule imports) would
break this; keep the order.
"""

from dataclasses import dataclass
from typing import Mapping

from domain import FORMATS, MAX_SEGMENTS, Deadline, Transcript

MAX_PAGE_CHARS = 50_000
MAX_PAGES = 20
CHARS_PER_SECOND = 15
CUE_OVERHEAD_FACTOR = 3


@dataclass(frozen=True)
class FormatOptions:
    """Per-call rendering options. `include_timestamps` only affects `text.py` (AC-4:
    `format: "text"` accepts an optional `includeTimestamps`, default `false`) --
    `srt`/`vtt` always render cue timing (it is structurally required by both formats),
    so they ignore this field rather than branching on it."""

    include_timestamps: bool = False


@dataclass(frozen=True)
class Page:
    """One page of encoded transcript text. `next_index` is the index of the first
    segment *not* included in this page -- equal to the transcript's total segment
    count once the last page has been produced. Segment-aligned: a page boundary never
    falls inside a `Segment` (AC-11)."""

    text: str
    next_index: int


# Import order matters -- see module docstring. `Page`/`FormatOptions`/the constants
# above must already be bound on this module before these run.
from formats import srt as _srt  # noqa: E402
from formats import text as _text  # noqa: E402
from formats import vtt as _vtt  # noqa: E402

_ENCODERS = {"text": _text, "srt": _srt, "vtt": _vtt}


def encode(
    transcript: Transcript,
    fmt: str,
    *,
    start_index: int = 0,
    max_chars: int = MAX_PAGE_CHARS,
    options: FormatOptions,
    deadline: Deadline,
) -> Page:
    """Routes to the named format's own `encode()`. `fmt` not in `FORMATS` is a caller
    bug (every caller validates `fmt` against `FORMATS`/the AC-4 enum before reaching
    here) -- raises `ValueError`, not a `DomainFailure`, matching this project's
    bug/domain-failure split (a plain `ValueError` reaches `Registry.call()`'s other,
    `-32603` branch instead of instructing a caller to retry a deterministic bug)."""
    if fmt not in _ENCODERS:
        raise ValueError(f"formats.encode: unknown format {fmt!r}, expected one of {sorted(FORMATS)}")
    return _ENCODERS[fmt].encode(
        transcript, fmt, start_index=start_index, max_chars=max_chars, options=options, deadline=deadline
    )


def count_pages_to(
    transcript: Transcript,
    fmt: str,
    *,
    target_index: int,
    max_chars: int,
    options: FormatOptions,
    deadline: Deadline,
) -> int:
    """Routes to the named format's own `count_pages_to()`. See `encode()`'s docstring
    for the `fmt`-not-in-`FORMATS` behavior."""
    if fmt not in _ENCODERS:
        raise ValueError(f"formats.count_pages_to: unknown format {fmt!r}, expected one of {sorted(FORMATS)}")
    return _ENCODERS[fmt].count_pages_to(
        transcript, fmt, target_index=target_index, max_chars=max_chars, options=options, deadline=deadline
    )


def estimate_characters(duration_seconds: int) -> Mapping[str, int]:
    """AC-1's derived-estimate formula, one aggregating function (not three per-format
    functions, cycle 5 finding): `text = round(duration_seconds * CHARS_PER_SECOND)`;
    `srt`/`vtt` are `text * CUE_OVERHEAD_FACTOR`. Never fetched -- always derived from
    the video's own duration."""
    text_chars = round(duration_seconds * CHARS_PER_SECOND)
    return {
        "text": text_chars,
        "srt": text_chars * CUE_OVERHEAD_FACTOR,
        "vtt": text_chars * CUE_OVERHEAD_FACTOR,
    }


__all__ = [
    "CHARS_PER_SECOND",
    "CUE_OVERHEAD_FACTOR",
    "FORMATS",
    "MAX_PAGES",
    "MAX_PAGE_CHARS",
    "MAX_SEGMENTS",
    "FormatOptions",
    "Page",
    "count_pages_to",
    "encode",
    "estimate_characters",
]

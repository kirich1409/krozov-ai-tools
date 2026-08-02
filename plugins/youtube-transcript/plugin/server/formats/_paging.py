"""Shared segment-aligned page-fitting helper for `text.py`/`srt.py`/`vtt.py` (T-5).

Not part of this package's cross-package surface -- a same-package-only helper
(`formats/` may only import `domain/` per `ALLOWED_EDGES`, and this module itself
imports only `domain/`; the per-file entry falls back to the package-level
`"formats": frozenset({"domain"})` row in `test_import_boundaries.py`'s table, same as
every other undeclared submodule).

The one property this whole task's review history keeps finding bugs in is page-boundary
drift between `encode()` and `count_pages_to()`: if each wrote its own "how many segments
fit in one page" loop, the two could silently diverge. `fit_page()` below is that loop,
written exactly once and called by both -- `encode()` calls it once for a single page,
`count_pages_to()` calls it repeatedly (passing the *same* `DeadlineStride` instance
across every call in one pass) to replay every page boundary from `segmentIndex = 0`.
Because both consumers run the identical function, they cannot disagree on where a page
ends by construction, not by convention.
"""

from typing import Callable, Sequence

from domain import DEADLINE_CHECK_STRIDE, Deadline, DeadlineExpired, Segment


class DeadlineStride:
    """Counts segments processed across however many `fit_page()` calls share this one
    instance, checking `deadline.expired()` exactly every `DEADLINE_CHECK_STRIDE`
    segments -- cumulatively, not reset at each page boundary. A single `encode()` call
    uses a fresh instance (one page); `count_pages_to()`'s multi-page replay passes one
    instance through the whole pass, so the stride bound holds over the *pass*, not just
    within whichever page happens to be current when segment 1000, 2000, ... is hit."""

    __slots__ = ("_count",)

    def __init__(self) -> None:
        self._count = 0

    def tick(self, deadline: Deadline) -> None:
        self._count += 1
        if self._count >= DEADLINE_CHECK_STRIDE:
            self._count = 0
            if deadline.expired():
                raise DeadlineExpired(
                    "deadline expired during formats paging pass "
                    f"(checked every {DEADLINE_CHECK_STRIDE} segments)"
                )


def fit_page(
    segments: Sequence[Segment],
    start_index: int,
    max_chars: int,
    fixed_overhead: int,
    segment_length: Callable[[int], int],
    deadline: Deadline,
    stride: DeadlineStride,
) -> int:
    """Returns how many segments, starting at `start_index`, fit in one page bounded by
    `max_chars` (which `fixed_overhead` -- e.g. vtt's per-page header -- counts against
    from the start). Never materializes rendered text; `segment_length(i)` is the exact
    number of characters segment `i` would contribute once rendered.

    Always includes at least one segment if any remain, even when that single segment's
    own rendered length already exceeds `max_chars` -- otherwise a page could fit zero
    segments and pagination would never make forward progress.

    Calls `stride.tick(deadline)` once per segment examined (mid-pass, not only at
    entry), which may raise `DeadlineExpired`.
    """
    total = len(segments)
    consumed = fixed_overhead
    count = 0
    index = start_index
    while index < total:
        length = segment_length(index)
        if count > 0 and consumed + length > max_chars:
            break
        consumed += length
        count += 1
        index += 1
        stride.tick(deadline)
    return count


def format_timecode(total_ms: int, decimal_separator: str) -> str:
    """`HH:MM:SS<sep>mmm`, e.g. `00:01:02,500` (srt, `sep=","`) or `00:01:02.500` (vtt/
    text, `sep="."`). No hour cap -- unrealistic for a real video, not worth a ceiling."""
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    seconds, millis = divmod(rem_ms, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{decimal_separator}{millis:03d}"

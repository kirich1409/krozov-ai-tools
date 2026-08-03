"""Cue-injection neutralization for `srt.py`/`vtt.py` cue text (T-5, spec AC-21).

**This is a display/format-correctness measure, not a security boundary** (AC-21's
redesign, `docs/specs/2026-08-01-youtube-transcript.md` and `docs/plans/youtube-transcript/plan.md`'s
"cue-injection-neutralization ... demoted from a security requirement to a
format-correctness one" section): the whole transcript is already wrapped in T-7's
per-invocation-random, unforgeable content boundary (`domain.generate_content_boundary`)
and marked untrusted, so this transform does not need to be adversarially idempotent or
forgery-proof -- a residual imperfection here would only affect how faithfully the
interior SRT/VTT cue structure round-trips, never whether untrusted content could be
mistaken for trusted content. It is implemented correctly anyway, cheaply, because that
costs nothing extra.

Two transforms, in this pinned order (blank-line-collapse, then arrow-collapse):

1. Blank-line-collapse: any run of blank lines (lines containing only spaces/tabs, or
   nothing) is removed entirely -- "to nothing", per AC-21's literal wording -- rather
   than collapsed to a single blank line. A blank line inside cue text would otherwise
   reproduce the blank-line separator real SRT/VTT uses between cue blocks, letting
   caption text visually forge a new cue boundary.
2. Arrow-collapse: `re.sub(r"-{2,}>", "->", text)` -- a longest-match regex, not
   `text.replace("-->", "->")`. The naive `.replace` form is the one real bug this
   mechanism's review history found: it reconstructs `"-->"` from `"--->"` under a
   single left-to-right pass (`"--->".replace("-->", "->")` yields `"-->"`, right back
   where it started). The regex form has no such defect: `-{2,}` greedily consumes an
   *entire* contiguous run of hyphens before requiring `>`, so the whole run is replaced
   by one `"->"` in a single pass, regardless of how many hyphens preceded it --
   verified against `"--->"`, `"---->"`, `"-------->"`, all collapsing to `"->"`.

Running blank-line-collapse first cannot hand arrow-collapse a *new* hyphen/arrow
adjacency that was not already present in the input: the blank-line regex only ever
deletes whitespace/newline characters (never `-` or `>`), and it always leaves at least
one `\n` -- the preceding non-blank line's own terminator -- at the junction it creates
(or the removal is at the very start of the string, where there is nothing to fuse
with). So the two transforms compose safely in the pinned order.
"""

import re

_BLANK_LINE = re.compile(r"^[ \t]*\n", re.MULTILINE)
_ARROW_RUN = re.compile(r"-{2,}>")


def collapse_cue_text(text: str) -> str:
    without_blank_lines = _BLANK_LINE.sub("", text)
    return _ARROW_RUN.sub("->", without_blank_lines)

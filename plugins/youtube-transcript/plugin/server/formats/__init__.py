"""Format-layer constants -- **constants only at this stage**; `formats/{text,srt,vtt}.py`
(T-5) implement the actual encoders.

`formats/` may import only `domain/` (`ALLOWED_EDGES`). `MAX_SEGMENTS`/`FORMATS` are
re-exported here from `domain/`, not redefined -- moved there by plan.md's
symbol-placement rule (cycle 3/cycle 7) since `providers/innertube.py` and
`protocol/schemas.py` also need them and neither has a permitted edge to `formats/`.
"""

from domain import FORMATS, MAX_SEGMENTS

MAX_PAGE_CHARS = 50_000
MAX_PAGES = 20
CHARS_PER_SECOND = 15
CUE_OVERHEAD_FACTOR = 3

__all__ = [
    "CHARS_PER_SECOND",
    "CUE_OVERHEAD_FACTOR",
    "FORMATS",
    "MAX_PAGES",
    "MAX_PAGE_CHARS",
    "MAX_SEGMENTS",
]

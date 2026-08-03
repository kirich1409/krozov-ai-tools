"""Startup wiring for the concrete provider and per-call deadlines -- `build_provider()`/
`build_deadline()` (T-13b).

`composition.py` (`ALLOWED_EDGES`) may import `domain/`, `providers/base.py`, and
`providers/innertube.py` -- **never `protocol/`, never `tools/`**. This is exactly why
`main()`, `build_registry()`, and the handler-registration wiring live in `server.py`
instead of here: this module is deliberately isolated from the protocol/tools layers
that *consume* the provider it builds (AC-23/AC-24, plan.md's module-layout diagram)
-- `server.py` imports both this module and those layers, never the reverse.

`build_provider()` is meant to be called exactly once, at process startup
(`server.py::main()` is that one call site -- `tests/test_composition.py::
test_single_build_provider_call_site` asserts there is exactly one `build_provider(`
call site anywhere under `plugin/server/` outside this file).

Stdlib only.
"""

import random
import time
from typing import Callable

from domain import TOOL_CALL_DEADLINE, Deadline
from providers.base import TranscriptProvider
from providers.innertube import InnertubeProvider

# Re-exported so `server.py` -- which has no permitted `ALLOWED_EDGES` route to
# `providers/base.py` itself -- can still type-annotate `build_registry(provider:
# TranscriptProvider, ...)` against this same type, via its already-permitted edge to
# this module. Not a hack: `composition.py` already imports this name for
# `build_provider`'s own return annotation below; `server.py` reusing it through the
# one edge it has is the module-layout diagram's intended shape, not a workaround.
__all__ = ["TranscriptProvider", "build_deadline", "build_provider"]


def build_provider(
    *,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[float, float], float] = random.uniform,
) -> TranscriptProvider:
    """Constructs the one `TranscriptProvider` this server process ever uses --
    called once, at startup, never re-constructed per call. `sleep`/`jitter` are
    injectable parameters, passed straight through to `InnertubeProvider.__init__`
    (T-10): this is what lets an end-to-end test actually reach the injection seam
    `net.fetch()`'s own `Transport` declares at the bottom of the stack, which
    nothing above it exposed a way to supply before this task."""
    return InnertubeProvider(sleep=sleep, jitter=jitter)


def build_deadline(clock: Callable[[], float] = time.monotonic) -> Deadline:
    """Starts a fresh whole-invocation `Deadline` against `TOOL_CALL_DEADLINE`.
    `clock` is an explicit, real parameter -- not silently defaulted away to a bare
    `time.monotonic()` read inside this function's body -- so a per-call test can
    inject a fake clock without globally monkeypatching `time.monotonic`, which
    would also perturb the retry/backoff machinery running inside the same call
    (`net/client.py::fetch`'s own `Deadline`-driven budget)."""
    return Deadline.start(TOOL_CALL_DEADLINE, clock=clock)

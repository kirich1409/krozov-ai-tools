"""Process entry point -- `SERVER_VERSION`/`USER_AGENT`, `build_registry()`, `main()`
(T-13b). This is the wiring layer that turns every previously-built piece (T-1
through T-13a) into a runnable MCP server over stdio.

`server.py` (`ALLOWED_EDGES`) may import `composition.py`, `protocol/`, `tools/`, and
`domain/` -- deliberately wider than `composition.py`'s own edge set, which excludes
`protocol/`/`tools/` entirely (see `composition.py`'s module docstring). That's why
the handler-registration wiring below -- constructing a `Registry`, registering both
tools' handlers as closures, and wiring `protocol.dispatch.serve_stdio` -- lives here,
not there.

Stdlib only.
"""

import sys
import time
from typing import Any, Callable, Dict

import tools.get_transcript as get_transcript_tool
import tools.list_transcript_tracks as list_transcript_tracks_tool
from composition import TranscriptProvider, build_deadline, build_provider
from domain import ToolOutcome
from protocol.dispatch import serve_stdio
from protocol.registry import Registry
from protocol.schemas import TOOL_SCHEMAS

# The 3-version-sync-locations Non-negotiable (root CLAUDE.md): every release bumps
# `plugin.json`, `marketplace.json`, and these two constants together, in lockstep
# (`scripts/validate.sh --check-tag` greps for them here by name). Deliberately
# decoupled from two other, unrelated version-shaped strings elsewhere in this
# server: `protocol/dispatch.py`'s `_PROTOCOL_VERSION`/`_SERVER_INFO` (the MCP wire
# protocol's own identity, not this plugin's release version -- that module's own
# docstring explains why they must never be conflated), and
# `providers/innertube.py`'s `_USER_AGENT` (the ANDROID client's outbound
# `User-Agent` header sent to YouTube's InnerTube API, T-10 -- a completely
# separate string this module has no `ALLOWED_EDGES` route to and no reason to
# reference).
SERVER_VERSION = "0.1.1"
USER_AGENT = f"youtube-transcript/{SERVER_VERSION}"

_SCHEMAS_BY_NAME: Dict[str, Dict[str, Any]] = {schema["name"]: schema for schema in TOOL_SCHEMAS}


def build_registry(provider: TranscriptProvider, *, clock: Callable[[], float] = time.monotonic) -> Registry:
    """Registers both tools' handlers as closures over `provider`/`clock`. Each
    closure calls `build_deadline(clock=clock)` **fresh on every invocation** --
    never once, at registration time -- which is the concrete seam
    `tests/test_composition.py::test_second_call_gets_fresh_deadline_via_build_
    registry_clock` proves: two sequential `tools/call` dispatches through the same
    `Registry`, with `clock` advanced past `TOOL_CALL_DEADLINE` between them, both
    still succeed, because each call gets its own deadline computed against ITS OWN
    start time, not a deadline bound once when this function ran.

    `get_transcript`'s/`list_transcript_tracks`'s `handle(provider, deadline, args)`
    signature (T-11/T-12) is a different shape than `Registry.Handler`'s
    `(args) -> ToolOutcome` (T-13a) -- these closures are exactly what bridges that
    gap, each wrapping one tool's `handle` with `provider`/a freshly-built `deadline`
    already bound, leaving only `args` as the closure's own parameter.
    """
    registry = Registry()

    def _handle_get_transcript(args: Dict[str, Any]) -> ToolOutcome:
        return get_transcript_tool.handle(provider, build_deadline(clock=clock), args)

    def _handle_list_transcript_tracks(args: Dict[str, Any]) -> ToolOutcome:
        return list_transcript_tracks_tool.handle(provider, build_deadline(clock=clock), args)

    registry.register("get_transcript", _SCHEMAS_BY_NAME["get_transcript"], _handle_get_transcript)
    registry.register(
        "list_transcript_tracks",
        _SCHEMAS_BY_NAME["list_transcript_tracks"],
        _handle_list_transcript_tracks,
    )
    return registry


def main() -> None:
    """`build_registry`'s only caller (`clock` defaulted to `time.monotonic`).
    Constructs the one `TranscriptProvider` this process ever uses -- `build_
    provider()`, called exactly once, here -- and wires `serve_stdio` over the real
    `sys.stdin`/`sys.stdout`."""
    provider = build_provider()
    registry = build_registry(provider)
    serve_stdio(registry, sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()

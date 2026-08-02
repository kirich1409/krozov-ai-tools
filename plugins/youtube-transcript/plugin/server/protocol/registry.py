"""Tool registration and invocation -- `Registry` (T-13a).

`protocol/registry.py` may import `domain/`, `protocol/envelope.py`, and
`protocol/schemas.py` (`ALLOWED_EDGES`) -- never `tools/`, never
`providers/innertube.py`. This is what makes the safety-net translation below
"coarser than the primary translation" (tasks.md T-13a): `protocol/` cannot reach
`tools.outcome_from_error`, so a `DomainFailure` that reaches this module is mapped
to one generic `Status.TRANSPORT_ERROR`, not the specific status the handler should
have produced itself.

Stdlib only.
"""

import logging
from typing import Any, Callable, Dict, List

from domain import DomainFailure, Status, ToolOutcome
from protocol import envelope

logger = logging.getLogger(__name__)

# A registered tool handler: takes the `tools/call` `arguments` dict, returns a
# domain-level `ToolOutcome` -- never the wire-shape dict itself (that's
# `envelope.build()`'s job, called once per `Registry.call()` invocation below).
Handler = Callable[[Dict[str, Any]], ToolOutcome]


class Registry:
    """Holds every registered tool's schema and handler. Constructs no per-call
    state of its own (tasks.md T-13a) -- a registered handler is invoked exactly
    once per `call()`, fresh, with nothing cached or memoized here between calls;
    a caller (T-13b) needing per-invocation state (e.g. a fresh `Deadline`) supplies
    a closure as the handler that builds that state itself on each invocation.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, Handler] = {}
        self._schemas: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, schema: Dict[str, Any], handler: Handler) -> None:
        """`schema` is one `protocol.schemas.TOOL_SCHEMAS` entry (the full
        `{name, description, inputSchema, annotations, ...}` dict), not just the
        `inputSchema` sub-object -- `tools()` below returns these verbatim for the
        `tools/list` response."""
        self._handlers[name] = handler
        self._schemas[name] = schema

    def tools(self) -> List[Dict[str, Any]]:
        """Every registered tool's schema, in registration order -- what
        `protocol/dispatch.py`'s `tools/list` handler returns verbatim, and what it
        also uses to check whether a `tools/call` request names a known tool."""
        return list(self._schemas.values())

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Invokes the tool named `name`'s registered handler fresh, then
        `envelope.build()`'s wire-shape dict.

        Catches `DomainFailure` specifically -- not a bare `except Exception` -- as
        a defense-in-depth safety net: T-11/T-12's handlers are contractually
        supposed to catch every `DomainFailure` themselves first (via
        `tools.outcome_from_error`, unreachable from here) and never let one escape
        to this layer, so this branch firing at all is always a bug in the calling
        handler, logged as such. It is translated to a generic
        `ToolOutcome(status=Status.TRANSPORT_ERROR)` built directly from `domain/`
        symbols -- never via `tools.outcome_from_error`, which `protocol/` has no
        permitted edge to.

        Any other exception is **propagated**, not caught here -- constructing the
        JSON-RPC `-32603` error response for it is `protocol/dispatch.py`'s
        `handle_message`'s job, not this method's: this method's `Dict[str, Any]`
        return type only ever describes the successful/`DomainFailure` path, never
        the `-32603` path, which is a different response shape entirely (a
        JSON-RPC error object, not a `result`).
        """
        handler = self._handlers[name]
        try:
            outcome = handler(args)
        except DomainFailure as exc:
            logger.warning(
                "protocol.registry.Registry.call: handler for tool %r let a "
                "DomainFailure (%s) escape uncaught -- this is always a bug in "
                "that handler, which is contractually supposed to catch it first "
                "via tools.outcome_from_error; translating via the generic "
                "safety net instead",
                name,
                type(exc).__name__,
            )
            outcome = ToolOutcome(status=Status.TRANSPORT_ERROR)
        return envelope.build(outcome)

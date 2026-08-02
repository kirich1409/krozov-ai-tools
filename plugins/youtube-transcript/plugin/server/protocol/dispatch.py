"""JSON-RPC 2.0 dispatch over stdio -- `serve_stdio()`/`handle_message()` (T-13a).

`protocol/dispatch.py` may import `domain/`, `protocol/envelope.py`, and
`protocol/schemas.py` (`ALLOWED_EDGES`) -- plus `protocol/registry.py`, a
same-package import, always allowed regardless of the table (`test_import_
boundaries.py`'s "Same-package imports are always allowed" rule) -- never
`tools/`, never `providers/innertube.py`.

**The `content[0].text` serialization step (tasks.md T-13a, cycle 9):**
`tools/call`'s response wraps `Registry.call()`'s full result dict in exactly one
`content` block, `{"type": "text", "text": json.dumps(result)}` -- the single wire
carrier for `protocol/envelope.build()`'s dict keys (including `contentNotice`/
`transcript`). No `structuredContent` key is ever emitted (`TOOL_SCHEMAS` declares
no `outputSchema`).

**`isError` lives at the `CallToolResult` level, alongside `content`,** sourced
from `domain.STATUS_POLICY`'s third tuple element for the outcome's `status` --
never a key inside the serialized `content[0].text` payload itself, and always
`False` for every status this server currently models (`STATUS_POLICY`'s own
invariant, AC-10).

**This module does NOT copy `maven-mcp/plugin/server/server.py`'s second branch**
(lines ~11502-11509: catching an arbitrary exception into a *successful-looking*
`{"content": [...], "isError": true}` result carrying `str(e)`). That branch is
deliberately excluded here on two independent grounds:
AC-15 forbids `str(exception)` in any caller-visible field, and `STATUS_POLICY`
never sets `isError: true` (AC-10) -- there is no status this plan models where a
genuine bug should look like a successful, retryable domain outcome. A non-
`DomainFailure` exception propagated out of `Registry.call()` instead becomes a
genuine JSON-RPC `-32603` error object here, in `handle_message` -- the **sole**
place that catches it -- with a fixed, generic message, never `str(e)`.

Stdlib only.
"""

import json
import logging
from typing import Any, Dict, Optional, TextIO

from domain import STATUS_POLICY, Status
from protocol.registry import Registry

logger = logging.getLogger(__name__)

# MCP `initialize` response fields this server negotiates. Decoupled entirely from
# `server.py`'s `SERVER_VERSION`/`USER_AGENT` (T-13b, root CLAUDE.md's version-sync
# Non-negotiable) -- `protocol/dispatch.py` has no permitted `ALLOWED_EDGES` route to
# `server.py` to read that constant, and these two things are conceptually
# different anyway: `SERVER_VERSION` is this *plugin's* release version, this is the
# MCP wire-protocol implementation's own identity, which this module owns outright
# and never needs to keep in sync with a plugin release.
_PROTOCOL_VERSION = "2025-06-18"
_SERVER_INFO: Dict[str, str] = {"name": "youtube-transcript", "version": "1"}

_GENERIC_INTERNAL_ERROR_MESSAGE = "Internal error"
_GENERIC_PARSE_ERROR_MESSAGE = "Parse error: invalid JSON"


def _error_response(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _handle_initialize(msg_id: Any) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": dict(_SERVER_INFO),
        },
    }


def _handle_tools_list(registry: Registry, msg_id: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": registry.tools()}}


def _handle_ping(msg_id: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": {}}


def _handle_tools_call(registry: Registry, msg_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _error_response(msg_id, -32602, "Invalid params: 'arguments' must be an object")

    known_schemas = {schema.get("name"): schema for schema in registry.tools()}
    schema = known_schemas.get(tool_name)
    if schema is None:
        return _error_response(msg_id, -32601, f"Unknown tool: {tool_name}")

    required = (schema.get("inputSchema") or {}).get("required") or []
    missing = [field_name for field_name in required if field_name not in arguments]
    if missing:
        return _error_response(
            msg_id, -32602, f"Invalid params: missing required field {missing[0]!r}"
        )

    try:
        result = registry.call(tool_name, arguments)
    except Exception as exc:
        # The sole place a propagated non-DomainFailure exception (Registry.call()
        # already caught and translated every DomainFailure itself) becomes a
        # JSON-RPC error -- logged with full detail to stderr for diagnosis, but
        # the response carries only a fixed, generic message, never str(exc)
        # (AC-15; see this module's docstring for why maven-mcp's isError:true/
        # str(e) branch is not copied here).
        logger.exception(
            "protocol.dispatch.handle_message: tools/call %r raised a non-"
            "DomainFailure exception (%s) -- a genuine bug, not a domain-modeled "
            "failure; responding with -32603",
            tool_name,
            type(exc).__name__,
        )
        return _error_response(msg_id, -32603, _GENERIC_INTERNAL_ERROR_MESSAGE)

    _, _, is_error = STATUS_POLICY[Status(result["status"])]
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": is_error,
        },
    }


def handle_message(registry: Registry, msg: Any) -> Optional[Dict[str, Any]]:
    """Dispatches one already-JSON-decoded message; returns the JSON-RPC response
    object, or `None` for a notification (a message with no `id`) -- `serve_stdio`
    writes nothing to stdout in that case.

    Parse errors (`-32700`) are never seen here -- they can only occur decoding the
    raw line before a `msg` object exists at all, which is `serve_stdio`'s job.
    """
    if not isinstance(msg, dict):
        return _error_response(None, -32600, "Invalid Request: expected a JSON object")

    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if msg_id is None:
        return None  # notification -- no response

    if not isinstance(params, dict):
        return _error_response(msg_id, -32602, "Invalid params: expected an object")

    if method == "initialize":
        return _handle_initialize(msg_id)
    if method == "tools/list":
        return _handle_tools_list(registry, msg_id)
    if method == "tools/call":
        return _handle_tools_call(registry, msg_id, params)
    if method == "ping":
        return _handle_ping(msg_id)
    return _error_response(msg_id, -32601, f"Method not found: {method}")


def _write_response(stream: TextIO, response: Dict[str, Any]) -> None:
    stream.write(json.dumps(response) + "\n")
    stream.flush()


def serve_stdio(registry: Registry, stdin: TextIO, stdout: TextIO) -> None:
    """Reads one JSON-RPC message per line from `stdin` until EOF, dispatching each
    through `handle_message` and writing any response (one JSON object per line) to
    `stdout`. All diagnostics go through `logging` (stderr-only by default, never
    stdout) -- `stdout` carries only valid JSON-RPC, per this task's acceptance.
    """
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("protocol.dispatch.serve_stdio: received invalid JSON on stdin")
            _write_response(stdout, _error_response(None, -32700, _GENERIC_PARSE_ERROR_MESSAGE))
            continue
        response = handle_message(registry, msg)
        if response is not None:
            _write_response(stdout, response)

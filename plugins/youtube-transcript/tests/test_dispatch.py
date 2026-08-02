"""Tests for `protocol/registry.py` + `protocol/dispatch.py` (T-13a).

See `docs/plans/youtube-transcript/tasks.md`'s T-13a block for the full acceptance
criteria this file's `check` list is drawn from. All tests here exercise a stub
`Registry` with hand-registered fake tools -- never the real `get_transcript`/
`list_transcript_tracks` handlers (T-11/T-12, implemented separately), matching
tasks.md's "tested against a stub handler" note.
"""

import io
import json
import unittest
from typing import Any, Dict

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim before the imports below -- see _helpers.py's module
# docstring.

import domain
import protocol.dispatch as dispatch
import protocol.envelope as envelope
from protocol.registry import Registry

_STUB_SCHEMA: Dict[str, Any] = {
    "name": "stub_tool",
    "description": "A stub tool for protocol-layer tests.",
    "inputSchema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    },
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
}

_OTHER_STUB_SCHEMA: Dict[str, Any] = {
    "name": "other_stub_tool",
    "description": "A second stub tool, for tools()/tools/list ordering tests.",
    "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
}


def _ok_handler(args: Dict[str, Any]) -> "domain.ToolOutcome":
    return domain.ToolOutcome(status=domain.Status.OK, payload={})


def _make_registry(handler: Any, *, schema: Dict[str, Any] = _STUB_SCHEMA) -> Registry:
    reg = Registry()
    reg.register(schema["name"], schema, handler)
    return reg


def _tools_call_message(tool_name: str, arguments: Dict[str, Any], *, msg_id: Any = 1) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }


# --- Registry: register()/tools()/call() -----------------------------------------


class TestRegistryToolsReturnsRegisteredSchemasInOrder(unittest.TestCase):
    def test_registry_tools_returns_registered_schemas_in_order(self) -> None:
        reg = Registry()
        reg.register("stub_tool", _STUB_SCHEMA, _ok_handler)
        reg.register("other_stub_tool", _OTHER_STUB_SCHEMA, _ok_handler)
        self.assertEqual(reg.tools(), [_STUB_SCHEMA, _OTHER_STUB_SCHEMA])


class TestRegistryCallInvokesHandlerAndBuildsEnvelope(unittest.TestCase):
    def test_registry_call_invokes_handler_and_builds_envelope(self) -> None:
        reg = _make_registry(_ok_handler)
        result = reg.call("stub_tool", {"x": "hello"})
        # envelope.build()'s exact shape for a bare Status.OK/{} outcome.
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["message"], envelope.MESSAGES[domain.Status.OK])
        self.assertFalse(result["retryable"])
        self.assertIsNone(result["retryAfterSeconds"])


class TestRegistryCallInvokesHandlerFreshWithArgs(unittest.TestCase):
    def test_registry_call_invokes_handler_fresh_with_args(self) -> None:
        received_args = []

        def handler(args: Dict[str, Any]) -> "domain.ToolOutcome":
            received_args.append(args)
            return domain.ToolOutcome(status=domain.Status.OK, payload={})

        reg = _make_registry(handler)
        reg.call("stub_tool", {"x": "first"})
        reg.call("stub_tool", {"x": "second"})
        self.assertEqual(received_args, [{"x": "first"}, {"x": "second"}])


# --- Named check #1: JSON-RPC 2.0 protocol shape ----------------------------------


class TestProtocolShape(unittest.TestCase):
    def test_protocol_shape(self) -> None:
        reg = _make_registry(_ok_handler)

        # initialize
        init_response = dispatch.handle_message(reg, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init_response is not None
        self.assertEqual(init_response["jsonrpc"], "2.0")
        self.assertEqual(init_response["id"], 1)
        self.assertIn("protocolVersion", init_response["result"])
        self.assertIn("serverInfo", init_response["result"])
        self.assertIn("capabilities", init_response["result"])

        # tools/list
        list_response = dispatch.handle_message(reg, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert list_response is not None
        self.assertEqual(list_response["result"]["tools"], [_STUB_SCHEMA])

        # tools/call
        call_response = dispatch.handle_message(reg, _tools_call_message("stub_tool", {"x": "y"}, msg_id=3))
        assert call_response is not None
        self.assertEqual(call_response["id"], 3)
        self.assertIn("content", call_response["result"])
        self.assertIn("isError", call_response["result"])

        # ping
        ping_response = dispatch.handle_message(reg, {"jsonrpc": "2.0", "id": 4, "method": "ping", "params": {}})
        self.assertEqual(ping_response, {"jsonrpc": "2.0", "id": 4, "result": {}})

        # Parse error (-32700) is serve_stdio's responsibility, exercised separately
        # below (TestServeStdioParseErrorReturnsMinus32700) -- handle_message only
        # ever receives an already-decoded message, so it structurally cannot
        # produce -32700 itself.

        # Invalid Request (-32600): non-dict message.
        invalid_request = dispatch.handle_message(reg, ["not", "a", "dict"])
        assert invalid_request is not None
        self.assertEqual(invalid_request["error"]["code"], -32600)

        # Method not found (-32601).
        unknown_method = dispatch.handle_message(
            reg, {"jsonrpc": "2.0", "id": 5, "method": "not/a/method", "params": {}}
        )
        assert unknown_method is not None
        self.assertEqual(unknown_method["error"]["code"], -32601)

        # Unknown tool name also surfaces as -32601 (mirrors the same-repo
        # maven-mcp reference's convention, plugins/maven-mcp/plugin/server/
        # server.py's _handle_tools_call).
        unknown_tool = dispatch.handle_message(reg, _tools_call_message("no_such_tool", {}, msg_id=6))
        assert unknown_tool is not None
        self.assertEqual(unknown_tool["error"]["code"], -32601)

        # Invalid params (-32602): missing required argument.
        missing_required = dispatch.handle_message(reg, _tools_call_message("stub_tool", {}, msg_id=7))
        assert missing_required is not None
        self.assertEqual(missing_required["error"]["code"], -32602)

        # Invalid params (-32602): params not an object.
        params_not_object = dispatch.handle_message(
            reg, {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": "nope"}
        )
        assert params_not_object is not None
        self.assertEqual(params_not_object["error"]["code"], -32602)

        # Invalid params (-32602): tools/call's params.arguments is present but
        # not an object (distinct from params itself not being an object, above).
        arguments_not_object = dispatch.handle_message(
            reg,
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "stub_tool", "arguments": "nope"}},
        )
        assert arguments_not_object is not None
        self.assertEqual(arguments_not_object["error"]["code"], -32602)

        # A notification (no "id") gets no response at all.
        notification_response = dispatch.handle_message(
            reg, {"jsonrpc": "2.0", "method": "ping", "params": {}}
        )
        self.assertIsNone(notification_response)


# --- Named check #2: DomainFailure caught as safety net, NOT -32603 --------------


class TestDomainFailureCaughtAsSafetyNetNot32603(unittest.TestCase):
    def test_domain_failure_caught_as_safety_net_not_32603(self) -> None:
        def raising_handler(args: Dict[str, Any]) -> "domain.ToolOutcome":
            raise domain.DeadlineExpired("whole-invocation deadline exhausted")

        reg = _make_registry(raising_handler)
        response = dispatch.handle_message(reg, _tools_call_message("stub_tool", {"x": "y"}))
        assert response is not None

        # Not a JSON-RPC error -- a normal successful CallToolResult carrying the
        # generic transport_error status.
        self.assertNotIn("error", response)
        self.assertIn("result", response)
        self.assertFalse(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], domain.Status.TRANSPORT_ERROR.value)
        self.assertTrue(payload["retryable"])


class TestRegistryCallSafetyNetBuildsGenericTransportError(unittest.TestCase):
    def test_registry_call_safety_net_builds_generic_transport_error(self) -> None:
        # The same property, exercised directly at Registry.call()'s own level
        # (not through the full dispatch stack) -- a ProviderError subclass would
        # carry a specific status via tools.outcome_from_error, which protocol/
        # cannot import; the safety net here is deliberately coarser (always
        # Status.TRANSPORT_ERROR), regardless of which DomainFailure subclass fired.
        def raising_handler(args: Dict[str, Any]) -> "domain.ToolOutcome":
            raise domain.CursorInvalid("forged cursor")

        reg = _make_registry(raising_handler)
        result = reg.call("stub_tool", {"x": "y"})
        self.assertEqual(result["status"], domain.Status.TRANSPORT_ERROR.value)


# --- Named check #3: non-DomainFailure exception becomes -32603 ------------------


class TestNonDomainExceptionBecomes32603(unittest.TestCase):
    def test_non_domain_exception_becomes_32603(self) -> None:
        def raising_handler(args: Dict[str, Any]) -> "domain.ToolOutcome":
            raise RuntimeError("a genuine bug, not a domain-modeled failure")

        reg = _make_registry(raising_handler)
        response = dispatch.handle_message(reg, _tools_call_message("stub_tool", {"x": "y"}))
        assert response is not None

        self.assertNotIn("result", response)
        self.assertEqual(response["error"]["code"], -32603)


class TestRegistryCallPropagatesNonDomainFailure(unittest.TestCase):
    def test_registry_call_propagates_non_domain_failure(self) -> None:
        # Registry.call() itself does not catch this -- it must propagate out,
        # uncaught, for handle_message to be the one that builds the -32603
        # response (tasks.md's "two-outcome split" clarification).
        def raising_handler(args: Dict[str, Any]) -> "domain.ToolOutcome":
            raise KeyError("some_internal_lookup")

        reg = _make_registry(raising_handler)
        with self.assertRaises(KeyError):
            reg.call("stub_tool", {"x": "y"})


# --- Named check #4: exactly one content block, no structuredContent -------------


class TestToolsCallResponseIsSingleJsonDumpsTextBlockNoStructuredContent(unittest.TestCase):
    def test_tools_call_response_is_single_json_dumps_text_block_no_structured_content(
        self,
    ) -> None:
        def handler(args: Dict[str, Any]) -> "domain.ToolOutcome":
            return domain.ToolOutcome(
                status=domain.Status.NO_TRANSCRIPT,
                payload={"tracks": (), "videoDurationSeconds": 42},
            )

        reg = _make_registry(handler)
        expected_result = reg.call("stub_tool", {"x": "y"})  # Registry.call()'s own return value

        response = dispatch.handle_message(reg, _tools_call_message("stub_tool", {"x": "y"}, msg_id=9))
        assert response is not None
        call_result = response["result"]

        self.assertEqual(list(call_result.keys()), ["content", "isError"])
        self.assertEqual(len(call_result["content"]), 1)
        block = call_result["content"][0]
        self.assertEqual(set(block.keys()), {"type", "text"})
        self.assertEqual(block["type"], "text")
        # Byte-for-byte json.dumps() of Registry.call()'s own return value.
        self.assertEqual(block["text"], json.dumps(expected_result))
        # Round-trips via json.loads.
        self.assertEqual(json.loads(block["text"]), expected_result)
        self.assertNotIn("structuredContent", call_result)


# --- Named check #5: no exception string ever reaches the response ---------------


class TestExceptionStringNeverReachesResponse(unittest.TestCase):
    def test_exception_string_never_reaches_response(self) -> None:
        secret_marker = "SUPER-SECRET-INTERNAL-DETAIL-89f3c2"

        def raising_handler(args: Dict[str, Any]) -> "domain.ToolOutcome":
            raise RuntimeError(secret_marker)

        reg = _make_registry(raising_handler)
        response = dispatch.handle_message(reg, _tools_call_message("stub_tool", {"x": "y"}))
        assert response is not None
        serialized_response = json.dumps(response)

        self.assertNotIn(secret_marker, serialized_response)
        self.assertEqual(response["error"]["code"], -32603)


# --- Named check #6: isError lives at the CallToolResult level, always False -----


class TestIsErrorFieldIsCallToolResultLevelAlwaysFalse(unittest.TestCase):
    def test_is_error_field_is_call_tool_result_level_always_false(self) -> None:
        for status in domain.Status:
            with self.subTest(status=status):
                def handler(args: Dict[str, Any], _status: "domain.Status" = status) -> "domain.ToolOutcome":
                    return domain.ToolOutcome(status=_status, payload={})

                reg = _make_registry(handler)
                response = dispatch.handle_message(reg, _tools_call_message("stub_tool", {"x": "y"}))
                assert response is not None
                call_result = response["result"]

                self.assertIn("isError", call_result)
                self.assertIs(call_result["isError"], False)
                # Not a key inside the serialized content[0].text payload itself.
                payload = json.loads(call_result["content"][0]["text"])
                self.assertNotIn("isError", payload)


# --- serve_stdio: line-oriented JSON-RPC over stdio -------------------------------


class TestServeStdioRoundTripsToolsCall(unittest.TestCase):
    def test_serve_stdio_round_trips_tools_call(self) -> None:
        reg = _make_registry(_ok_handler)
        request = _tools_call_message("stub_tool", {"x": "y"}, msg_id=42)
        stdin = io.StringIO(json.dumps(request) + "\n")
        stdout = io.StringIO()

        dispatch.serve_stdio(reg, stdin, stdout)

        lines = [line for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 1)
        response = json.loads(lines[0])
        self.assertEqual(response["id"], 42)
        self.assertIn("content", response["result"])


class TestServeStdioParseErrorReturnsMinus32700(unittest.TestCase):
    def test_serve_stdio_parse_error_returns_minus_32700(self) -> None:
        reg = _make_registry(_ok_handler)
        stdin = io.StringIO("not valid json at all\n")
        stdout = io.StringIO()

        dispatch.serve_stdio(reg, stdin, stdout)

        lines = [line for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 1)
        response = json.loads(lines[0])
        self.assertEqual(response["error"]["code"], -32700)
        self.assertIsNone(response["id"])


class TestServeStdioSkipsBlankLines(unittest.TestCase):
    def test_serve_stdio_skips_blank_lines(self) -> None:
        reg = _make_registry(_ok_handler)
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
        stdin = io.StringIO("\n   \n" + json.dumps(ping) + "\n\n")
        stdout = io.StringIO()

        dispatch.serve_stdio(reg, stdin, stdout)

        lines = [line for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {"jsonrpc": "2.0", "id": 1, "result": {}})


class TestServeStdioWritesNothingForNotifications(unittest.TestCase):
    def test_serve_stdio_writes_nothing_for_notifications(self) -> None:
        reg = _make_registry(_ok_handler)
        notification = {"jsonrpc": "2.0", "method": "ping", "params": {}}
        stdin = io.StringIO(json.dumps(notification) + "\n")
        stdout = io.StringIO()

        dispatch.serve_stdio(reg, stdin, stdout)

        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()

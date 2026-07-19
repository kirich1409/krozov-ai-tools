"""Dispatcher robustness tests (#343).

The server must survive any successfully-parsed JSON line that is not an
object (bare scalar, ``null``, boolean) with a -32600 Invalid Request
response, and must handle JSON-RPC 2.0 batch requests (arrays) instead of
crashing the process.
"""

import contextlib
import io
import json
import unittest
import unittest.mock

from _helpers import server


def _run_main(lines):
    """Feed `lines` (already-serialized JSON strings) through server.main().

    Returns the parsed JSON values written to stdout, one per output line.
    """
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()
    with unittest.mock.patch.object(server.sys, "stdin", stdin):
        with contextlib.redirect_stdout(stdout):
            server.main()
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line]


def _ping(msg_id):
    return {"jsonrpc": "2.0", "id": msg_id, "method": "ping"}


class NonObjectMessageTest(unittest.TestCase):
    """A non-dict JSON value must produce -32600, never kill the loop."""

    def test_bare_scalars_get_invalid_request_and_server_survives(self):
        # The exact reproduction from issue #343: two bad lines, then a ping.
        out = _run_main(["123", '"hello"', json.dumps(_ping(9))])
        self.assertEqual(len(out), 3)
        for resp in out[:2]:
            self.assertEqual(resp["error"]["code"], -32600)
            self.assertIsNone(resp["id"])
        self.assertEqual(out[2], {"jsonrpc": "2.0", "id": 9, "result": {}})

    def test_null_and_boolean_lines(self):
        out = _run_main(["null", "true", json.dumps(_ping(1))])
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["error"]["code"], -32600)
        self.assertEqual(out[1]["error"]["code"], -32600)
        self.assertEqual(out[2]["id"], 1)

    def test_parse_error_still_reported(self):
        out = _run_main(["{not json", json.dumps(_ping(2))])
        self.assertEqual(out[0]["error"]["code"], -32700)
        self.assertEqual(out[1]["id"], 2)


class BatchRequestTest(unittest.TestCase):
    """JSON-RPC 2.0 batch (array) handling."""

    def test_batch_of_requests_returns_array_in_order(self):
        out = _run_main([json.dumps([_ping(1), _ping(2)])])
        self.assertEqual(len(out), 1)
        self.assertEqual(
            out[0],
            [
                {"jsonrpc": "2.0", "id": 1, "result": {}},
                {"jsonrpc": "2.0", "id": 2, "result": {}},
            ],
        )

    def test_batch_with_notification_omits_it_from_response(self):
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        out = _run_main([json.dumps([notification, _ping(5)])])
        self.assertEqual(out, [[{"jsonrpc": "2.0", "id": 5, "result": {}}]])

    def test_all_notifications_batch_produces_no_output(self):
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        out = _run_main([json.dumps([notification, notification])])
        self.assertEqual(out, [])

    def test_empty_batch_gets_single_error_object(self):
        out = _run_main(["[]"])
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], dict)
        self.assertEqual(out[0]["error"]["code"], -32600)

    def test_non_dict_batch_element_gets_error_entry_others_answered(self):
        out = _run_main([json.dumps([42, _ping(7)])])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0]["error"]["code"], -32600)
        self.assertEqual(out[0][1], {"jsonrpc": "2.0", "id": 7, "result": {}})

    def test_batch_element_exception_isolated(self):
        # A handler blowing up on one element must not abort the rest.
        request = {"jsonrpc": "2.0", "id": 3, "method": "ping"}
        with unittest.mock.patch.object(
            server, "_handle_ping", side_effect=[RuntimeError("boom"), {"jsonrpc": "2.0", "id": 4, "result": {}}]
        ):
            out = _run_main([json.dumps([request, _ping(4)])])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0]["error"]["code"], -32603)
        self.assertEqual(out[0][0]["id"], 3)
        self.assertEqual(out[0][1]["id"], 4)

    def test_server_survives_batch_then_answers_next_line(self):
        out = _run_main([json.dumps([_ping(1)]), json.dumps(_ping(2))])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], [{"jsonrpc": "2.0", "id": 1, "result": {}}])
        self.assertEqual(out[1], {"jsonrpc": "2.0", "id": 2, "result": {}})


class DispatchBackCompatTest(unittest.TestCase):
    """dispatch() must keep writing a single response object to stdout."""

    def test_dispatch_writes_single_response(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            server.dispatch(_ping(11))
        resp = json.loads(stdout.getvalue())
        self.assertEqual(resp, {"jsonrpc": "2.0", "id": 11, "result": {}})

    def test_dispatch_notification_writes_nothing(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            server.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(stdout.getvalue(), "")

    def test_dispatch_non_dict_scalar_writes_invalid_request(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            server.dispatch("not a request")
        resp = json.loads(stdout.getvalue())
        self.assertEqual(resp["error"]["code"], -32600)

    def test_dispatch_list_delegates_to_batch(self):
        # Batch support must not be entrypoint-dependent: dispatch() routes
        # top-level arrays through _dispatch_batch, same as main().
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            server.dispatch([_ping(1), _ping(2)])
        resp = json.loads(stdout.getvalue())
        self.assertEqual(
            resp,
            [
                {"jsonrpc": "2.0", "id": 1, "result": {}},
                {"jsonrpc": "2.0", "id": 2, "result": {}},
            ],
        )


class InvalidParamsTest(unittest.TestCase):
    """A non-object `params` is a client error: -32602, not -32603."""

    def test_list_params_get_invalid_params(self):
        out = _run_main(
            [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": [1, 2]})]
        )
        self.assertEqual(out[0]["error"]["code"], -32602)
        self.assertEqual(out[0]["id"], 1)

    def test_scalar_params_get_invalid_params(self):
        out = _run_main(
            [json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": "nope"})]
        )
        self.assertEqual(out[0]["error"]["code"], -32602)

    def test_notification_with_bad_params_gets_no_response(self):
        out = _run_main(
            [json.dumps({"jsonrpc": "2.0", "method": "ping", "params": [1]}), json.dumps(_ping(3))]
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], 3)


class McpProtocolTest(unittest.TestCase):
    """Real initialize / tools/list / tools/call path through main() (#358)."""

    def test_initialize_returns_server_info(self):
        out = _run_main(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "0"},
                        },
                    }
                )
            ]
        )
        self.assertEqual(len(out), 1)
        result = out[0]["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")
        self.assertEqual(result["serverInfo"]["name"], server.SERVER_NAME)
        self.assertEqual(result["serverInfo"]["version"], server.SERVER_VERSION)
        self.assertIn("tools", result["capabilities"])

    def test_tools_list_returns_shipped_tools(self):
        out = _run_main(
            [json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})]
        )
        self.assertEqual(len(out), 1)
        tools = out[0]["result"]["tools"]
        self.assertEqual(tools, server.TOOLS)
        names = [t["name"] for t in tools]
        self.assertEqual(names, list(server.TOOL_HANDLERS.keys()))

    def test_tools_call_wraps_handler_result_in_text_content(self):
        # Pin the MCP unwrap contract hooks rely on: .result.content[0].text
        # is JSON of the handler's return value, correlated by request id.
        def _fake_handler(arguments):
            return {"ok": True, "echo": arguments}

        with unittest.mock.patch.dict(
            server.TOOL_HANDLERS, {"scan_project_dependencies": _fake_handler}
        ):
            out = _run_main(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 42,
                            "method": "tools/call",
                            "params": {
                                "name": "scan_project_dependencies",
                                "arguments": {"projectPath": "/tmp/proj"},
                            },
                        }
                    )
                ]
            )
        self.assertEqual(out[0]["id"], 42)
        content = out[0]["result"]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(
            json.loads(content[0]["text"]),
            {"ok": True, "echo": {"projectPath": "/tmp/proj"}},
        )

    def test_tools_call_unknown_tool_is_method_not_found(self):
        out = _run_main(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "tools/call",
                        "params": {"name": "no_such_tool", "arguments": {}},
                    }
                )
            ]
        )
        self.assertEqual(out[0]["id"], 7)
        self.assertEqual(out[0]["error"]["code"], -32601)
        self.assertIn("Unknown tool", out[0]["error"]["message"])

    def test_initialize_tools_list_tools_call_session_over_stdio(self):
        # End-to-end stdio session: initialize → tools/list → tools/call.
        def _fake_handler(_arguments):
            return {"ping": "pong"}

        with unittest.mock.patch.dict(
            server.TOOL_HANDLERS, {"search_artifacts": _fake_handler}
        ):
            out = _run_main(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {"protocolVersion": "2024-11-05"},
                        }
                    ),
                    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "tools/call",
                            "params": {
                                "name": "search_artifacts",
                                "arguments": {"query": "okhttp"},
                            },
                        }
                    ),
                ]
            )
        self.assertEqual([r["id"] for r in out], [1, 2, 3])
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], server.SERVER_NAME)
        self.assertEqual(len(out[1]["result"]["tools"]), len(server.TOOLS))
        self.assertEqual(json.loads(out[2]["result"]["content"][0]["text"]), {"ping": "pong"})


class ToolExecutionErrorTest(unittest.TestCase):
    """A tool handler's own failures are MCP tool-execution errors (#397).

    Per the MCP spec (2024-11-05), a failure raised BY a tool handler while
    doing its job (resolution failure, ValueError, network error, an internal
    KeyError unrelated to the request's arguments, ...) is a "Tool Execution
    Error": a successful JSON-RPC response whose result is a CallToolResult
    with isError:true, not a JSON-RPC protocol error — the model must see
    `result.content`, not `error`, to self-correct.

    A missing/malformed required argument is a different case (client/model
    mistake, not the handler failing at its job): Invalid params (-32602).
    This is detected by a dispatcher-level PRE-CHECK against the tool's own
    `inputSchema.required`, BEFORE the handler ever runs — not by catching
    KeyError around the handler call, which would also catch (and mislabel)
    a KeyError the handler raises internally for reasons that have nothing
    to do with the arguments the client sent (code review follow-up on #397).
    """

    def test_handler_exception_is_isError_content_not_protocol_error(self):
        def _boom(_arguments):
            raise ValueError("could not resolve coordinate: no matching repo")

        with unittest.mock.patch.dict(
            server.TOOL_HANDLERS, {"scan_project_dependencies": _boom}
        ):
            out = _run_main(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 50,
                            "method": "tools/call",
                            "params": {"name": "scan_project_dependencies", "arguments": {}},
                        }
                    )
                ]
            )
        self.assertEqual(len(out), 1)
        resp = out[0]
        self.assertEqual(resp["id"], 50)
        self.assertNotIn("error", resp, "tool execution failure must not be a JSON-RPC error")
        result = resp["result"]
        self.assertIs(result["isError"], True)
        content = result["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("could not resolve coordinate", content[0]["text"])

    def test_handler_internal_keyerror_is_isError_not_invalid_params(self):
        # The exact shape the code review flagged: a KeyError raised INSIDE a
        # handler's own logic (e.g. handle_get_dependency_health's
        # metadata["versions"], check_android_kotlin_compatibility's
        # agp_entry["minGradle"]) has nothing to do with which arguments the
        # client sent. It must come back as a tool execution failure
        # (isError:true), never misdiagnosed as -32602 Invalid params just
        # because the exception type happens to be KeyError.
        def _internal_lookup_bug(_arguments):
            internal_state = {"a": 1}
            return internal_state["b"]  # KeyError unrelated to `arguments`

        with unittest.mock.patch.dict(
            server.TOOL_HANDLERS, {"scan_project_dependencies": _internal_lookup_bug}
        ):
            out = _run_main(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 53,
                            "method": "tools/call",
                            "params": {"name": "scan_project_dependencies", "arguments": {}},
                        }
                    )
                ]
            )
        self.assertEqual(len(out), 1)
        resp = out[0]
        self.assertEqual(resp["id"], 53)
        self.assertNotIn("error", resp, "internal handler KeyError must not be Invalid params")
        result = resp["result"]
        self.assertIs(result["isError"], True)
        content = result["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("'b'", content[0]["text"])

    def test_missing_required_arg_is_invalid_params_precheck(self):
        # get_latest_version requires groupId + artifactId (see TOOLS). The
        # handler is swapped for a spy that fails the test if ever called —
        # proving the -32602 comes from the dispatcher's pre-check against
        # inputSchema.required, not from the handler running and raising.
        def _must_not_be_called(_arguments):
            raise AssertionError("handler must not run when a required arg is missing")

        with unittest.mock.patch.dict(
            server.TOOL_HANDLERS, {"get_latest_version": _must_not_be_called}
        ):
            out = _run_main(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 51,
                            "method": "tools/call",
                            "params": {
                                "name": "get_latest_version",
                                "arguments": {"artifactId": "guava"},  # groupId missing
                            },
                        }
                    )
                ]
            )
        self.assertEqual(len(out), 1)
        resp = out[0]
        self.assertEqual(resp["id"], 51)
        self.assertNotIn("result", resp)
        self.assertEqual(resp["error"]["code"], -32602)
        self.assertIn("groupId", resp["error"]["message"])

    def test_unknown_tool_is_still_a_protocol_error(self):
        # Unchanged by #397: an unrecognized tool name is detected by the
        # dispatcher before any handler runs — it is not a handler exception,
        # so it stays a JSON-RPC protocol error (method not found), not
        # isError:true.
        out = _run_main(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 52,
                        "method": "tools/call",
                        "params": {"name": "no_such_tool", "arguments": {}},
                    }
                )
            ]
        )
        self.assertNotIn("result", out[0])
        self.assertEqual(out[0]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()

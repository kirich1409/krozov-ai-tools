"""Streamable HTTP transport tests.

Runs the real ``http.server.ThreadingHTTPServer`` from ``server._make_http_server``
bound to an ephemeral loopback port in setUpClass, and drives it with real
``urllib.request`` calls — loopback only, no external network. The only mocked
piece is the tools/call handler (same ``TOOL_HANDLERS`` patch as
test_dispatch.py), so no tool reaches the network either.
"""

import contextlib
import http.client
import io
import json
import os
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request

from _helpers import server


def _post(url, payload, headers=None):
    """POST ``payload`` (dict -> JSON, or raw bytes) and return (status, body).

    urllib raises HTTPError for non-2xx responses; normalize those to the same
    ``(status, body_bytes)`` tuple so error-path assertions read uniformly.
    """
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        # HTTPError is a file-like response wrapper; close it after reading to
        # avoid ResourceWarning on garbage collection.
        body = e.read()
        e.close()
        return e.code, body


class StreamableHTTPTest(unittest.TestCase):
    """POST /mcp end-to-end through the real handler and dispatcher."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = server._make_http_server("127.0.0.1", 0)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}{server.HTTP_TRANSPORT_PATH}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(2)

    def test_initialize_echoes_protocol_version(self):
        status, body = _post(
            self.url,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        self.assertEqual(status, 200)
        result = json.loads(body)["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertIn("capabilities", result)
        self.assertEqual(
            result["serverInfo"],
            {"name": server.SERVER_NAME, "version": server.SERVER_VERSION},
        )

    def test_tools_list_returns_tools(self):
        status, body = _post(self.url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(status, 200)
        tools = json.loads(body)["result"]["tools"]
        self.assertGreater(len(tools), 0)

    def test_ping_returns_empty_result(self):
        status, body = _post(self.url, {"jsonrpc": "2.0", "id": 3, "method": "ping"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"jsonrpc": "2.0", "id": 3, "result": {}})

    def test_tools_call_offline_handler(self):
        # Same TOOL_HANDLERS patch as test_dispatch.py — the real dispatcher
        # runs, but the tool itself is a stub, so nothing touches the network.
        def _fake_handler(_arguments):
            return {"results": [{"groupId": "g", "artifactId": "a"}]}

        with unittest.mock.patch.dict(server.TOOL_HANDLERS, {"search_artifacts": _fake_handler}):
            status, body = _post(
                self.url,
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "search_artifacts", "arguments": {"query": "okhttp"}},
                },
            )
        self.assertEqual(status, 200)
        result = json.loads(body)["result"]
        self.assertNotIn("isError", result)
        self.assertEqual(
            json.loads(result["content"][0]["text"]),
            {"results": [{"groupId": "g", "artifactId": "a"}]},
        )

    def test_notification_returns_202_empty_body(self):
        status, body = _post(
            self.url,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        self.assertEqual(status, 202)
        self.assertEqual(body, b"")

    def test_invalid_json_returns_400_parse_error(self):
        status, body = _post(self.url, b"{not json")
        self.assertEqual(status, 400)
        response = json.loads(body)
        self.assertEqual(response["error"]["code"], -32700)
        self.assertIsNone(response["id"])

    def test_batch_array_rejected_invalid_request(self):
        # JSON-RPC batching was removed from the target MCP protocol revision
        # (#398): a top-level array is -32600, not a batch.
        status, body = _post(self.url, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], -32600)

    def test_post_wrong_path_returns_404(self):
        status, _body = _post(
            f"http://127.0.0.1:{self.httpd.server_port}/wrong-path",
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        self.assertEqual(status, 404)

    def test_non_local_origin_rejected(self):
        status, _body = _post(
            self.url,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "http://evil.example.com"},
        )
        self.assertEqual(status, 403)

    def test_malformed_origin_rejected(self):
        # An Origin that does not even parse (unterminated IPv6 bracket) must
        # fail closed, not crash or pass.
        status, _body = _post(
            self.url,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "http://[::1"},
        )
        self.assertEqual(status, 403)

    def test_local_origin_accepted(self):
        status, _body = _post(
            self.url,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "http://localhost:3000"},
        )
        self.assertEqual(status, 200)

    def test_dispatch_exception_returns_500_internal_error(self):
        # Mirrors main()'s stdio-loop safety net: a dispatch crash must become
        # a JSON-RPC -32603 response, never a dropped connection.
        def _boom(_msg):
            raise RuntimeError("synthetic dispatch failure")

        with unittest.mock.patch.object(server, "_dispatch_message", _boom):
            status, body = _post(self.url, {"jsonrpc": "2.0", "id": 5, "method": "ping"})
        self.assertEqual(status, 500)
        response = json.loads(body)
        self.assertEqual(response["error"]["code"], -32603)
        self.assertEqual(response["id"], 5)

    def test_bad_content_length_returns_400(self):
        # urllib always sends a valid Content-Length; go one level lower to
        # exercise the defensive header parsing in do_POST.
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port)
        conn.putrequest("POST", server.HTTP_TRANSPORT_PATH)
        conn.putheader("Content-Length", "not-a-number")
        conn.endheaders()
        resp = conn.getresponse()
        resp.read()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_missing_content_length_returns_400(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port)
        conn.putrequest("POST", server.HTTP_TRANSPORT_PATH)
        conn.endheaders()
        resp = conn.getresponse()
        resp.read()
        self.assertEqual(resp.status, 400)
        conn.close()


class MethodNotAllowedTest(unittest.TestCase):
    """GET / DELETE / other verbs get 405 with Allow: POST (no SSE streams)."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = server._make_http_server("127.0.0.1", 0)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}{server.HTTP_TRANSPORT_PATH}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(2)

    def _method(self, method):
        request = urllib.request.Request(self.url, method=method)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(request)
        # Headers stay readable after close; closing avoids ResourceWarning.
        cm.exception.close()
        return cm.exception

    def test_get_returns_405_with_allow_post(self):
        error = self._method("GET")
        self.assertEqual(error.code, 405)
        self.assertEqual(error.headers.get("Allow"), "POST")

    def test_delete_returns_405(self):
        self.assertEqual(self._method("DELETE").code, 405)

    def test_head_put_patch_options_return_405(self):
        for method in ("HEAD", "PUT", "PATCH", "OPTIONS"):
            self.assertEqual(self._method(method).code, 405, method)


class TransportSelectionTest(unittest.TestCase):
    """main() picks the transport from MAVEN_MCP_TRANSPORT (env-only config)."""

    def test_http_transport_uses_env_host_and_port(self):
        env = {
            "MAVEN_MCP_TRANSPORT": "http",
            "MAVEN_MCP_HTTP_HOST": "127.0.0.1",
            "MAVEN_MCP_HTTP_PORT": "18765",
        }
        with unittest.mock.patch.dict("os.environ", env):
            with unittest.mock.patch.object(server, "run_http_server") as run:
                server.main()
        run.assert_called_once_with("127.0.0.1", 18765)

    def test_http_transport_defaults(self):
        # patch.dict restores environ on exit, so the pops inside are reverted;
        # they guarantee the defaults regardless of the developer's env.
        with unittest.mock.patch.dict("os.environ", {"MAVEN_MCP_TRANSPORT": "http"}):
            os.environ.pop("MAVEN_MCP_HTTP_HOST", None)
            os.environ.pop("MAVEN_MCP_HTTP_PORT", None)
            with unittest.mock.patch.object(server, "run_http_server") as run:
                server.main()
        run.assert_called_once_with(
            server.HTTP_TRANSPORT_DEFAULT_HOST, server.HTTP_TRANSPORT_DEFAULT_PORT
        )

    def test_invalid_port_falls_back_to_default_with_warning(self):
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_TRANSPORT": "http", "MAVEN_MCP_HTTP_PORT": "not-a-port"}
        ):
            with unittest.mock.patch.object(server, "run_http_server") as run:
                with self.assertLogs(server._logger, level="WARNING"):
                    server.main()
        run.assert_called_once_with(
            server.HTTP_TRANSPORT_DEFAULT_HOST, server.HTTP_TRANSPORT_DEFAULT_PORT
        )

    def test_stdio_transport_default_keeps_reading_stdin(self):
        # MAVEN_MCP_TRANSPORT is popped by _helpers; an unset variable must
        # select the stdio loop, which exits cleanly at stdin EOF.
        stdin = io.StringIO('{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n')
        stdout = io.StringIO()
        with unittest.mock.patch.object(server.sys, "stdin", stdin):
            with contextlib.redirect_stdout(stdout):
                with unittest.mock.patch.object(server, "run_http_server") as run:
                    server.main()
        run.assert_not_called()
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"jsonrpc": "2.0", "id": 1, "result": {}},
        )


class BindWarningTest(unittest.TestCase):
    """Non-loopback binds log the no-authentication warning; loopback does not."""

    def _run(self, host):
        """Run run_http_server with a mocked server; return the warning mock."""
        with unittest.mock.patch.object(server, "_make_http_server") as make:
            make.return_value.server_port = 8765
            with unittest.mock.patch.object(server._logger, "warning") as warn:
                server.run_http_server(host, 8765)
        make.return_value.serve_forever.assert_called_once_with()
        make.return_value.server_close.assert_called_once_with()
        return warn

    def test_non_loopback_bind_warns(self):
        warn = self._run("0.0.0.0")
        self.assertTrue(any("no authentication" in str(c) for c in warn.call_args_list))

    def test_unresolvable_hostname_bind_warns(self):
        self.assertTrue(self._run("unresolvable.invalid").called)

    def test_loopback_binds_do_not_warn(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            self.assertFalse(self._run(host).called, host)


if __name__ == "__main__":
    unittest.main()

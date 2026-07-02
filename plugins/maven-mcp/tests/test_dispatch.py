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

    def test_dispatch_non_dict_writes_invalid_request(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            server.dispatch([1, 2, 3])
        resp = json.loads(stdout.getvalue())
        self.assertEqual(resp["error"]["code"], -32600)


if __name__ == "__main__":
    unittest.main()

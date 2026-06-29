"""HTTP utility tests: ``http_get`` / ``http_post_json`` plus the header builders
``_make_headers`` / ``_github_headers`` (server.py:73-108).

Mirrors the NON-retry assertions of ``src/http/__tests__/client.test.ts``:
default User-Agent, caller-header pass-through, status pass-through, and error
mapping.

DIVERGENCE #1 (tracked as a T-10 follow-up issue): the retired TS
``fetchWithRetry`` retried once on 5xx / 429 responses and on network errors
with backoff. The Python runtime's ``http_get`` / ``http_post_json`` perform a
SINGLE request and map ``urllib.error.HTTPError`` straight to ``(code, b"")``
with no retry, backoff, or rate-limit handling. This absence is intentional for
the current runtime, so there is deliberately NO retry test here — the TS retry
cases (5xx retry, 429 retry, network-error retry, "stops after retries") have no
Python counterpart by design.
"""

import json
import unittest
from unittest import mock

from _helpers import server, mock_urlopen, http_error


def _headers_ci(req):
    """Case-insensitive {name: value} view of a urllib Request's headers.

    urllib.request.Request capitalizes header names on insertion
    (``User-Agent`` -> ``User-agent``), so assertions go through this helper
    rather than guessing the stored casing.
    """
    return {name.lower(): value for name, value in req.header_items()}


class MakeHeadersTest(unittest.TestCase):
    def test_sets_default_user_agent(self):
        headers = server._make_headers()
        self.assertEqual(headers["User-Agent"], server.USER_AGENT)
        # Mirrors client.test.ts: USER_AGENT matches maven-*-mcp/<semver>.
        self.assertRegex(server.USER_AGENT, r"^maven-.*mcp/\d+\.\d+\.\d+")

    def test_passes_through_extra_headers(self):
        headers = server._make_headers({"Accept": "application/json"})
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["User-Agent"], server.USER_AGENT)


class GithubHeadersTest(unittest.TestCase):
    def test_includes_user_agent_and_accept_without_token(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            server.os.environ.pop("GITHUB_TOKEN", None)
            headers = server._github_headers()
        self.assertEqual(headers["User-Agent"], server.USER_AGENT)
        self.assertEqual(headers["Accept"], "application/vnd.github.v3+json")
        self.assertNotIn("Authorization", headers)

    def test_injects_bearer_authorization_when_token_set(self):
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "tok123"}):
            headers = server._github_headers()
        self.assertEqual(headers["Authorization"], "Bearer tok123")
        self.assertEqual(headers["User-Agent"], server.USER_AGENT)


class HttpGetTest(unittest.TestCase):
    def test_returns_status_and_bytes(self):
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"<xml/>")]),
        ):
            status, body = server.http_get("https://example.test/x")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<xml/>")

    def test_maps_httperror_to_code_and_empty_bytes(self):
        err = http_error("https://example.test/x", 500)
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([err]),
        ):
            status, body = server.http_get("https://example.test/x")
        self.assertEqual(status, 500)
        self.assertEqual(body, b"")

    def test_attaches_default_user_agent(self):
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"ok")]),
        ) as urlopen:
            server.http_get("https://example.test/x")
        req = urlopen.call_args.args[0]
        self.assertEqual(_headers_ci(req)["user-agent"], server.USER_AGENT)

    def test_passes_through_caller_headers(self):
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"ok")]),
        ) as urlopen:
            server.http_get(
                "https://example.test/x",
                headers={"User-Agent": server.USER_AGENT, "Accept": "application/json"},
            )
        headers = _headers_ci(urlopen.call_args.args[0])
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["user-agent"], server.USER_AGENT)


class HttpPostJsonTest(unittest.TestCase):
    def test_encodes_json_body_and_sets_content_type(self):
        payload = {"queries": [{"package": {"name": "g:a"}}]}
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"{}")]),
        ) as urlopen:
            server.http_post_json("https://example.test/osv", payload)
        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(json.loads(req.data), payload)
        headers = _headers_ci(req)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["user-agent"], server.USER_AGENT)

    def test_returns_status_and_bytes(self):
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b'{"ok":true}')]),
        ):
            status, body = server.http_post_json("https://example.test/osv", {})
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"ok":true}')

    def test_maps_httperror_to_code_and_empty_bytes(self):
        err = http_error("https://example.test/osv", 500)
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([err]),
        ):
            status, body = server.http_post_json("https://example.test/osv", {})
        self.assertEqual(status, 500)
        self.assertEqual(body, b"")


if __name__ == "__main__":
    unittest.main()

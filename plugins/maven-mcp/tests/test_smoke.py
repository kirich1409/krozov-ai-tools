"""Smoke tests: the harness imports `server` and the HTTP mocking works."""

import unittest
from unittest import mock

from _helpers import server, mock_urlopen, http_error


class SmokeTest(unittest.TestCase):
    def test_import_and_pure_function(self):
        # classify_version falls through to "stable" for a plain semver (server.py:208).
        self.assertEqual(server.classify_version("1.2.3"), "stable")

    def test_http_get_returns_mocked_status_and_bytes(self):
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"hello")]),
        ):
            status, body = server.http_get("https://example.test/x")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"hello")

    def test_http_error_maps_to_code_and_empty_bytes(self):
        err = http_error("https://example.test/x", 404, "Not Found")
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([err]),
        ):
            status, body = server.http_get("https://example.test/x")
        self.assertEqual(status, 404)
        self.assertEqual(body, b"")


if __name__ == "__main__":
    unittest.main()

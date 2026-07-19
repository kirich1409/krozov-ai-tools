"""HTTP utility tests: ``http_get`` / ``http_post_json`` plus the header builders
``_make_headers`` / ``_github_headers`` and the shared ``_request_with_retry``
helper (server.py HTTP utilities section).

Mirrors the assertions of the retired ``src/http/__tests__/client.test.ts``:
default User-Agent, caller-header pass-through, status pass-through, error
mapping, AND the retry behavior (5xx / 429 / transport-error retry with
backoff). The Python port restores the retry/backoff that #302 dropped (issue
#306): the runtime retries transient failures internally while preserving the
tri-state contract callers depend on — a final 429/5xx still returns
``(code, b"")`` (never raised), a 4xx/2xx/3xx is never retried, and a transport
error is re-raised only when EVERY attempt hit one.

Retry is exercised with ``server._sleep`` patched out so the suite never sleeps.
"""

import http.server
import json
import socket
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request

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
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            server.os.environ.pop("GITHUB_TOKEN", None)
            headers = server._github_headers()
        self.assertEqual(headers["User-Agent"], server.USER_AGENT)
        self.assertEqual(headers["Accept"], "application/vnd.github.v3+json")
        self.assertNotIn("Authorization", headers)

    def test_injects_bearer_authorization_when_token_set(self):
        with unittest.mock.patch.dict("os.environ", {"GITHUB_TOKEN": "tok123"}):
            headers = server._github_headers()
        self.assertEqual(headers["Authorization"], "Bearer tok123")
        self.assertEqual(headers["User-Agent"], server.USER_AGENT)


class HttpGetTest(unittest.TestCase):
    def test_returns_status_and_bytes(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"<xml/>")]),
        ):
            status, body = server.http_get("https://example.test/x")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<xml/>")

    def test_persistent_5xx_returns_code_and_empty_bytes_after_cap(self):
        # 500 is retryable, so a persistent 500 is retried up to the cap and
        # then mapped to (500, b"") — NOT raised. (Was the no-retry mapping test
        # before #306; now folds into the persistent-5xx contract case.)
        url = "https://example.test/x"
        errs = [http_error(url, 500) for _ in range(server.HTTP_MAX_ATTEMPTS)]
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen", side_effect=mock_urlopen(errs)
                ) as urlopen:
            status, body = server.http_get(url)
        self.assertEqual(status, 500)
        self.assertEqual(body, b"")
        self.assertEqual(urlopen.call_count, server.HTTP_MAX_ATTEMPTS)
        self.assertEqual(sleep.call_count, server.HTTP_MAX_ATTEMPTS - 1)

    def test_attaches_default_user_agent(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"ok")]),
        ) as urlopen:
            server.http_get("https://example.test/x")
        req = urlopen.call_args.args[0]
        self.assertEqual(_headers_ci(req)["user-agent"], server.USER_AGENT)

    def test_passes_through_caller_headers(self):
        with unittest.mock.patch(
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

    def test_rejects_file_scheme_without_urlopen(self):
        # #348: default urllib opener honors file:// — must never reach urlopen.
        with unittest.mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(urllib.error.URLError) as cm:
                server.http_get("file:///etc/hostname")
        urlopen.assert_not_called()
        self.assertIn("file", str(cm.exception.reason).lower())

    def test_rejects_uppercase_file_scheme_without_urlopen(self):
        with unittest.mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(urllib.error.URLError) as cm:
                server.http_get("FILE:///etc/hostname")
        urlopen.assert_not_called()
        self.assertIn("file", str(cm.exception.reason).lower())

    def test_rejects_ftp_and_other_non_http_schemes(self):
        with unittest.mock.patch("urllib.request.urlopen") as urlopen:
            for url in (
                "ftp://example.test/pub/maven-metadata.xml",
                "data:text/plain,hi",
                "javascript:alert(1)",
                "/relative/path",
                "example.test/no-scheme",
            ):
                with self.subTest(url=url):
                    with self.assertRaises(urllib.error.URLError):
                        server.http_get(url)
        urlopen.assert_not_called()

    def test_rejects_link_local_metadata_url_on_initial_request(self):
        # R2c (GHSA-m84v-qqqm-6fr4 follow-up): the redirect-time link-local
        # block was previously the ONLY enforcement point — a build file
        # declaring url = "http://169.254.169.254/…" directly (no redirect
        # needed) was fetched. _assert_http_url now blocks it up front too.
        with unittest.mock.patch("urllib.request.urlopen") as urlopen:
            for url in (
                "http://169.254.169.254/latest/meta-data/",
                "http://169.254.1.1/x",
                "http://[fe80::1]/x",
            ):
                with self.subTest(url=url):
                    with self.assertRaises(urllib.error.URLError) as cm:
                        server.http_get(url)
                    self.assertIn("link-local", str(cm.exception.reason).lower())
        urlopen.assert_not_called()

    def test_allows_rfc1918_and_loopback_url_on_initial_request(self):
        # Regression guard: private-repo mode legitimately targets internal
        # hosts (#290/#298) — only link-local/metadata is blocked, never
        # RFC1918 or loopback, on the initial request either.
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen(
                [(200, b"ok"), (200, b"ok"), (200, b"ok"), (200, b"ok")]
            ),
        ) as urlopen:
            for url in (
                "http://10.0.0.5/repo",
                "http://172.16.0.5/repo",
                "http://192.168.1.1/repo",
                "http://127.0.0.1/repo",
            ):
                with self.subTest(url=url):
                    status, body = server.http_get(url)
                    self.assertEqual(status, 200)
        self.assertEqual(urlopen.call_count, 4)

    def test_allows_http_scheme(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"ok")]),
        ) as urlopen:
            status, body = server.http_get("http://example.test/x")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")
        self.assertEqual(urlopen.call_count, 1)


class HttpPostJsonTest(unittest.TestCase):
    def test_encodes_json_body_and_sets_content_type(self):
        payload = {"queries": [{"package": {"name": "g:a"}}]}
        with unittest.mock.patch(
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
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b'{"ok":true}')]),
        ):
            status, body = server.http_post_json("https://example.test/osv", {})
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"ok":true}')

    def test_rejects_file_scheme_without_urlopen(self):
        with unittest.mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(urllib.error.URLError):
                server.http_post_json("file:///tmp/x", {})
        urlopen.assert_not_called()

    def test_persistent_5xx_returns_code_and_empty_bytes_after_cap(self):
        url = "https://example.test/osv"
        errs = [http_error(url, 500) for _ in range(server.HTTP_MAX_ATTEMPTS)]
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen", side_effect=mock_urlopen(errs)
                ) as urlopen:
            status, body = server.http_post_json(url, {})
        self.assertEqual(status, 500)
        self.assertEqual(body, b"")
        self.assertEqual(urlopen.call_count, server.HTTP_MAX_ATTEMPTS)
        self.assertEqual(sleep.call_count, server.HTTP_MAX_ATTEMPTS - 1)

    def test_retries_on_5xx_then_succeeds(self):
        url = "https://example.test/osv"
        seq = [http_error(url, 503), (200, b'{"ok":true}')]
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen", side_effect=mock_urlopen(seq)
                ) as urlopen:
            status, body = server.http_post_json(url, {})
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"ok":true}')
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(sleep.call_count, 1)


class HttpRetryTest(unittest.TestCase):
    """Retry/backoff behavior ported from the retired TS ``fetchWithRetry``."""

    URL = "https://example.test/x"

    def test_503_then_200_returns_200_after_one_retry(self):
        seq = [http_error(self.URL, 503), (200, b"ok")]
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen", side_effect=mock_urlopen(seq)
                ) as urlopen:
            status, body = server.http_get(self.URL)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_429_retry_after_seconds_honored_then_success(self):
        seq = [
            http_error(self.URL, 429, hdrs={"Retry-After": "2"}),
            (200, b"ok"),
        ]
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen", side_effect=mock_urlopen(seq)
                ) as urlopen:
            status, body = server.http_get(self.URL)
        self.assertEqual(status, 200)
        self.assertEqual(urlopen.call_count, 2)
        # The Retry-After value (2s) is honored verbatim — below the cap.
        self.assertEqual(sleep.call_args.args[0], 2.0)

    def test_retry_after_absurd_value_clamped_to_max(self):
        seq = [
            http_error(self.URL, 503, hdrs={"Retry-After": "99999"}),
            (200, b"ok"),
        ]
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen", side_effect=mock_urlopen(seq)
                ):
            status, _ = server.http_get(self.URL)
        self.assertEqual(status, 200)
        # A hostile Retry-After is clamped to HTTP_RETRY_AFTER_MAX, not slept verbatim.
        self.assertEqual(sleep.call_args.args[0], server.HTTP_RETRY_AFTER_MAX)

    def test_retry_after_http_date_clamped_to_max(self):
        # HTTP-date form of Retry-After: a far-future date yields a huge delta,
        # which is clamped to HTTP_RETRY_AFTER_MAX. Deterministic (no timing
        # dependence) because the date is centuries out.
        seq = [
            http_error(self.URL, 503, hdrs={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"}),
            (200, b"ok"),
        ]
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen", side_effect=mock_urlopen(seq)
                ):
            status, _ = server.http_get(self.URL)
        self.assertEqual(status, 200)
        self.assertEqual(sleep.call_args.args[0], server.HTTP_RETRY_AFTER_MAX)

    def test_persistent_503_returns_503_not_raised(self):
        errs = [http_error(self.URL, 503) for _ in range(server.HTTP_MAX_ATTEMPTS)]
        with unittest.mock.patch.object(server, "_sleep"), \
                unittest.mock.patch(
                    "urllib.request.urlopen", side_effect=mock_urlopen(errs)
                ) as urlopen:
            status, body = server.http_get(self.URL)
        self.assertEqual(status, 503)
        self.assertEqual(body, b"")
        self.assertEqual(urlopen.call_count, server.HTTP_MAX_ATTEMPTS)

    def test_transport_error_every_attempt_raises_after_cap(self):
        errs = [urllib.error.URLError("boom") for _ in range(server.HTTP_MAX_ATTEMPTS)]
        with unittest.mock.patch.object(server, "_sleep"), \
                unittest.mock.patch(
                    "urllib.request.urlopen", side_effect=mock_urlopen(errs)
                ) as urlopen:
            with self.assertRaises(urllib.error.URLError):
                server.http_get(self.URL)
        self.assertEqual(urlopen.call_count, server.HTTP_MAX_ATTEMPTS)

    def test_transport_error_then_200_returns_200(self):
        seq = [urllib.error.URLError("boom"), (200, b"ok")]
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen", side_effect=mock_urlopen(seq)
                ) as urlopen:
            status, body = server.http_get(self.URL)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_404_returned_immediately_no_retry(self):
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen",
                    side_effect=mock_urlopen([http_error(self.URL, 404)]),
                ) as urlopen:
            status, body = server.http_get(self.URL)
        self.assertEqual(status, 404)
        self.assertEqual(body, b"")
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_200_not_retried(self):
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen",
                    side_effect=mock_urlopen([(200, b"ok")]),
                ) as urlopen:
            server.http_get(self.URL)
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_4xx_non_429_not_retried(self):
        for code in (400, 401, 403):
            with self.subTest(code=code):
                with unittest.mock.patch.object(server, "_sleep") as sleep, \
                        unittest.mock.patch(
                            "urllib.request.urlopen",
                            side_effect=mock_urlopen([http_error(self.URL, code)]),
                        ) as urlopen:
                    status, body = server.http_get(self.URL)
                self.assertEqual(status, code)
                self.assertEqual(body, b"")
                self.assertEqual(urlopen.call_count, 1)
                sleep.assert_not_called()


class HttpResponseSizeCapTest(unittest.TestCase):
    """#350: HTTP bodies must not be read unbounded into memory."""

    URL = "https://example.test/x"
    # Tiny cap so tests never allocate multi-MiB buffers.
    CAP = 64

    def setUp(self):
        self._cap_patch = unittest.mock.patch.object(
            server, "HTTP_MAX_RESPONSE_BYTES", self.CAP
        )
        self._cap_patch.start()

    def tearDown(self):
        self._cap_patch.stop()

    def test_body_at_cap_accepted(self):
        body = b"x" * self.CAP
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, body)]),
        ):
            status, got = server.http_get(self.URL)
        self.assertEqual(status, 200)
        self.assertEqual(got, body)

    def test_body_over_cap_raises_without_retry(self):
        body = b"x" * (self.CAP + 1)
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen",
                    side_effect=mock_urlopen([(200, body)]),
                ) as urlopen:
            with self.assertRaises(server.ResponseTooLargeError) as cm:
                server.http_get(self.URL)
        self.assertIn("too large", str(cm.exception.reason).lower())
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_content_length_over_cap_raises_before_full_read(self):
        # Declared Content-Length alone is enough to reject — body may be empty
        # in the mock because we never allocate the claimed size.
        oversized_cl = str(self.CAP + 1)
        with unittest.mock.patch.object(server, "_sleep") as sleep, \
                unittest.mock.patch(
                    "urllib.request.urlopen",
                    side_effect=mock_urlopen([
                        (200, b"", {"Content-Length": oversized_cl}),
                    ]),
                ) as urlopen:
            with self.assertRaises(server.ResponseTooLargeError) as cm:
                server.http_get(self.URL)
        self.assertIn("content-length", str(cm.exception.reason).lower())
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_post_json_body_over_cap_raises(self):
        body = b"y" * (self.CAP + 1)
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, body)]),
        ):
            with self.assertRaises(server.ResponseTooLargeError):
                server.http_post_json(self.URL, {})

    def test_content_length_at_cap_with_matching_body_ok(self):
        body = b"z" * self.CAP
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([
                (200, body, {"Content-Length": str(len(body))}),
            ]),
        ):
            status, got = server.http_get(self.URL)
        self.assertEqual(status, 200)
        self.assertEqual(got, body)


class SecureRedirectEndToEndTest(unittest.TestCase):
    """Real-socket, real-urlopen (NOT mocked) proof that the installed
    ``_SecureRedirectHandler`` actually intercepts redirects issued by the
    genuine urllib machinery — GHSA-xj4p-wm6r-4q3j / GHSA-m84v-qqqm-6fr4.

    Deliberately does not patch ``urllib.request.urlopen``: the vulnerability
    lived inside urlopen()'s own internally-built opener, so a mocked
    urlopen would prove nothing about whether the fix is actually wired in.
    Everything here talks to 127.0.0.1 only — no real network access.
    """

    def _start(self, handler_cls):
        httpd = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 2)
        return httpd

    def test_authorization_stripped_on_cross_host_redirect(self):
        captured: dict = {}

        class _Target(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler naming)
                captured["headers"] = dict(self.headers)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *_a, **_k):
                pass  # silence default per-request stderr access log

        target = self._start(_Target)

        class _Origin(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(302)
                # "localhost" (origin) vs "127.0.0.1" (target) are different
                # host STRINGS even though both resolve to loopback — a real
                # cross-host redirect for _repo_host()'s string comparison.
                self.send_header(
                    "Location", f"http://127.0.0.1:{target.server_port}/next"
                )
                self.end_headers()

            def log_message(self, *_a, **_k):
                pass

        origin = self._start(_Origin)

        status, body = server.http_get(
            f"http://localhost:{origin.server_port}/start",
            headers=server._make_headers({"Authorization": "Bearer secret-token"}),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")
        self.assertNotIn("Authorization", captured["headers"])

    def test_ftp_redirect_never_connects_to_target(self):
        # The base HTTPRedirectHandler allows scheme in {http, https, ftp, ''}
        # — ftp must be rejected by OUR layer. Asserting only that http_get()
        # eventually raises would be a weak/non-discriminating test: an
        # unreachable ftp target raises a URLError on stock urllib too (just
        # from a failed connection, not a deliberate scheme block). Instead
        # this listens on a REAL local port and asserts NO connection is ever
        # received — that only holds once the scheme is rejected before a
        # socket is opened, which is exactly the pre-fix vs post-fix delta.
        accepted = threading.Event()
        port_ready = threading.Event()
        ftp_port_holder = {}

        def _listener():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(("127.0.0.1", 0))
                srv.listen(1)
                srv.settimeout(3)
                ftp_port_holder["port"] = srv.getsockname()[1]
                port_ready.set()
                try:
                    conn, _addr = srv.accept()
                    accepted.set()
                    conn.close()
                except socket.timeout:
                    pass

        listener_thread = threading.Thread(target=_listener, daemon=True)
        listener_thread.start()
        self.addCleanup(listener_thread.join, 4)
        self.assertTrue(port_ready.wait(2), "listener never bound a port")
        ftp_port = ftp_port_holder["port"]

        class _Origin(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(302)
                self.send_header("Location", f"ftp://127.0.0.1:{ftp_port}/evil")
                self.end_headers()

            def log_message(self, *_a, **_k):
                pass

        origin = self._start(_Origin)
        with unittest.mock.patch.object(server, "_sleep"):
            with self.assertRaises(urllib.error.URLError):
                server.http_get(f"http://localhost:{origin.server_port}/start")
        listener_thread.join(4)
        self.assertFalse(
            accepted.is_set(),
            "ftp redirect target received a connection attempt — scheme was not blocked",
        )


class SecureRedirectHandlerUnitTest(unittest.TestCase):
    """Direct unit tests of ``_SecureRedirectHandler.redirect_request``,
    complementing the real-socket tests above. Covers the https->http
    downgrade-strip branch (a local self-signed TLS server is impractical
    with a stdlib-only harness) and the RFC1918/loopback allow-list
    requirement.
    """

    @staticmethod
    def _req(url, headers=None):
        return urllib.request.Request(url, headers=headers or {})

    def test_downgrade_same_host_strips_authorization(self):
        handler = server._SecureRedirectHandler()
        req = self._req(
            "https://nexus.example.com/repo/x", {"Authorization": "Bearer secret"}
        )
        new_req = handler.redirect_request(
            req, None, 302, "Found", {}, "http://nexus.example.com/repo/y"
        )
        self.assertNotIn("Authorization", new_req.headers)

    def test_same_host_same_scheme_keeps_authorization(self):
        handler = server._SecureRedirectHandler()
        req = self._req(
            "https://nexus.example.com/repo/x", {"Authorization": "Bearer secret"}
        )
        new_req = handler.redirect_request(
            req, None, 302, "Found", {}, "https://nexus.example.com/repo/y"
        )
        self.assertEqual(new_req.headers.get("Authorization"), "Bearer secret")

    def test_rfc1918_and_loopback_redirect_not_blocked(self):
        # Private-repo mode legitimately targets internal hosts (#290/#298) —
        # only link-local/metadata addresses are blocked, never RFC1918/loopback.
        handler = server._SecureRedirectHandler()
        req = self._req("https://example.test/x")
        for target in (
            "http://10.0.0.5/repo",
            "http://172.16.0.5/repo",
            "http://192.168.1.1/repo",
            "http://127.0.0.1/repo",
        ):
            with self.subTest(target=target):
                new_req = handler.redirect_request(req, None, 302, "Found", {}, target)
                self.assertIsNotNone(new_req)

    def test_link_local_and_ipv6_link_local_blocked(self):
        handler = server._SecureRedirectHandler()
        req = self._req("https://example.test/x")
        for target in ("http://169.254.169.254/latest/meta-data/", "http://[fe80::1]/x"):
            with self.subTest(target=target):
                with self.assertRaises(urllib.error.URLError):
                    handler.redirect_request(req, None, 302, "Found", {}, target)


if __name__ == "__main__":
    unittest.main()

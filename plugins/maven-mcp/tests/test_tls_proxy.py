"""TLS (internal CA) + HTTP(S) proxy support (#298)."""

import os
import ssl
import tempfile
import unittest
import unittest.mock
import urllib.request

from _helpers import mock_urlopen, server


# Minimal self-signed-ish PEM is not required for load_verify_locations tests
# that only check plumbing; use an empty file that fails load and a real
# create_default_context path for the happy CA case via a generated cert.


def _write_temp_pem() -> str:
    """Create a throwaway PEM file that ssl can attempt to load.

    Uses a minimal valid-enough certificate generated via ssl if available;
    otherwise writes a placeholder and asserts the warning path.
    """
    # Generate a self-signed cert with stdlib only (OpenSSL via ssl module).
    # Python 3.9+ has no high-level API for this; write a tiny valid CA from
    # cryptography is forbidden (stdlib only). Instead exercise plumbing with
    # a real system CA file when present, else a missing-path warning path.
    candidates = [
        "/etc/ssl/cert.pem",
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    # Fallback: empty temp file — load_verify_locations will warn/fail.
    fd, path = tempfile.mkstemp(suffix=".pem")
    os.close(fd)
    with open(path, "wb") as fh:
        fh.write(b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    return path


class SslContextTest(unittest.TestCase):
    def setUp(self):
        server._reset_ssl_context_cache()

    def tearDown(self):
        server._reset_ssl_context_cache()

    def test_default_verifies(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            for k in (
                "MAVEN_MCP_INSECURE_TLS",
                "MAVEN_MCP_CA_CERT",
                "SSL_CERT_FILE",
                "NODE_EXTRA_CA_CERTS",
            ):
                server.os.environ.pop(k, None)
            ctx = server._ssl_context()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

    def test_insecure_disables_verification_and_warns(self):
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_INSECURE_TLS": "1"}, clear=False
        ):
            with self.assertLogs("maven_mcp", level="WARNING") as cm:
                ctx = server._ssl_context()
                # Second call must not warn again.
                server._ssl_context()
        self.assertFalse(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertEqual(sum(1 for m in cm.output if "INSECURE_TLS" in m), 1)

    def test_ca_cert_env_loaded(self):
        ca = _write_temp_pem()
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_CA_CERT": ca}, clear=False
        ):
            server.os.environ.pop("MAVEN_MCP_INSECURE_TLS", None)
            # Spy load_verify_locations to prove plumbing without depending on
            # whether the PEM is a perfect CA.
            with unittest.mock.patch.object(
                ssl.SSLContext, "load_verify_locations", autospec=True
            ) as load:
                ctx = server._ssl_context()
        self.assertTrue(ctx.check_hostname)
        load.assert_called()
        # First positional after self is cafile=
        called_ca = load.call_args.kwargs.get("cafile") or (
            load.call_args.args[1] if len(load.call_args.args) > 1 else None
        )
        self.assertEqual(called_ca, ca)

    def test_http_get_passes_ssl_context(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            server.os.environ.pop("MAVEN_MCP_INSECURE_TLS", None)
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, b"ok")]),
            ) as urlopen:
                server.http_get("https://example.test/x")
        self.assertIn("context", urlopen.call_args.kwargs)
        self.assertIsInstance(urlopen.call_args.kwargs["context"], ssl.SSLContext)


class ProxySelectionTest(unittest.TestCase):
    def setUp(self):
        server._reset_ssl_context_cache()

    def tearDown(self):
        server._reset_ssl_context_cache()

    def test_no_proxy_env_uses_urlopen_directly(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            for k in (
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy",
            ):
                server.os.environ.pop(k, None)
            self.assertIsNone(server._explicit_env_proxies())
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, b"ok")]),
            ) as urlopen, unittest.mock.patch(
                "urllib.request.build_opener"
            ) as build:
                server.http_get("https://example.test/x")
        urlopen.assert_called_once()
        build.assert_not_called()

    def test_https_proxy_builds_opener(self):
        with unittest.mock.patch.dict(
            "os.environ",
            {"HTTPS_PROXY": "http://proxy.example:8080"},
            clear=False,
        ):
            server.os.environ.pop("NO_PROXY", None)
            server.os.environ.pop("no_proxy", None)
            fake_resp = mock_urlopen([(200, b"ok")])(None)

            class _Opener:
                def open(self, req, timeout=None):
                    return fake_resp

            with unittest.mock.patch(
                "urllib.request.build_opener", return_value=_Opener()
            ) as build, unittest.mock.patch(
                "urllib.request.urlopen"
            ) as urlopen:
                status, body = server.http_get("https://repo.example/m2/x")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")
        build.assert_called_once()
        urlopen.assert_not_called()
        handlers = build.call_args.args
        self.assertTrue(
            any(isinstance(h, urllib.request.ProxyHandler) for h in handlers)
        )
        self.assertTrue(
            any(isinstance(h, urllib.request.HTTPSHandler) for h in handlers)
        )

    def test_no_proxy_bypasses_proxy_handler(self):
        with unittest.mock.patch.dict(
            "os.environ",
            {
                "HTTPS_PROXY": "http://proxy.example:8080",
                "NO_PROXY": "repo.example,.corp.example",
            },
            clear=False,
        ):
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, b"ok")]),
            ) as urlopen, unittest.mock.patch(
                "urllib.request.build_opener"
            ) as build:
                server.http_get("https://repo.example/m2/x")
        urlopen.assert_called_once()
        build.assert_not_called()

    def test_hostname_no_proxy_matching(self):
        self.assertTrue(server._hostname_matches_no_proxy("a.corp.example", ".corp.example"))
        self.assertTrue(server._hostname_matches_no_proxy("corp.example", "corp.example"))
        self.assertFalse(server._hostname_matches_no_proxy("evil.com", "corp.example"))
        self.assertTrue(server._proxy_bypass_host("localhost"))

    def test_lowercase_proxy_env(self):
        with unittest.mock.patch.dict(
            "os.environ", {"https_proxy": "http://proxy.example:3128"}, clear=False
        ):
            server.os.environ.pop("HTTPS_PROXY", None)
            proxies = server._explicit_env_proxies()
        self.assertEqual(proxies["https"], "http://proxy.example:3128")


if __name__ == "__main__":
    unittest.main()

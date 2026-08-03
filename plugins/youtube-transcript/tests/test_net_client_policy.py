"""Tests for `net/client.py`'s policy layer (T-6a): opener construction,
scheme/host/port allowlist, and redirect handling. See
`docs/plans/youtube-transcript/tasks.md`'s T-6a block and
`docs/plans/youtube-transcript/plan.md`'s "The AST/text-ban mechanism is a
regression guard, not a closed security boundary" section for the full acceptance
criteria this file's `check` is drawn from -- this is the plan's own
repeatedly-named highest-density area for security findings (nine
`multiexpert-review` cycles found bypasses here), so several tests below assert the
*mechanism* (opener never touched, source order of the redirect check), not merely
the externally observable exception, per cycle 2's finding that a weaker
behavior-only test could pass for the wrong reason.

T-6b (a later, separate task) adds `fetch()`'s remaining resource controls (byte
caps, deadline checks, retry loop, XML guard) -- this file exercises only the
policy/opener/redirect layer T-6a builds, with a plain, single-call, uncapped fake
opener standing in for the network.
"""

import dataclasses
import inspect
import unittest
import urllib.request
from typing import Any, Callable
from unittest.mock import Mock, patch

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim before the imports below -- see _helpers.py's module
# docstring and test_domain.py's identical comment for the mypy-vs-runtime reason
# this bare top-level import needs the suppression.

import net.client as client
from _helpers import _FakeHTTPResponse, http_error, mock_urlopen


class _FakeOpener:
    """Stands in for `client._OPENER`: `.open` is whatever callable the test hands
    it (typically `_helpers.mock_urlopen`'s return), so `fetch()`'s `_OPENER.open(request)`
    call site works unchanged under test, without a real socket."""

    def __init__(self, open_fn: Callable[..., Any]) -> None:
        self.open = open_fn


def _rejected_before_opener_touched(test: unittest.TestCase, url: str) -> None:
    """Shared assertion for every "rejected before the opener is ever touched" case
    below: patches `_OPENER` with a strict `Mock`, asserts `PolicyRejected`, and
    asserts `.open` was never called -- not just that some exception was raised
    (plan.md cycle 2's finding: a weaker test could pass for the wrong reason,
    e.g. the opener being called and itself raising)."""
    fake_opener = Mock()
    with patch.object(client, "_OPENER", new=fake_opener), test.assertRaises(
        client.PolicyRejected
    ):
        client.fetch(url)
    fake_opener.open.assert_not_called()


class TestSchemeCheck(unittest.TestCase):
    def test_scheme_https_only_opener_never_called(self) -> None:
        # http: specifically -- the scheme this allowlist most plausibly could be
        # mistaken for acceptable (same host, same paths, just not https).
        _rejected_before_opener_touched(self, "http://www.youtube.com/x")


class TestFileAndDataSchemesRejected(unittest.TestCase):
    def test_file_and_data_schemes_rejected(self) -> None:
        for url in (
            "file:///etc/passwd",
            "data:text/plain,hello",
            "ftp://www.youtube.com/x",
        ):
            with self.subTest(url=url):
                _rejected_before_opener_touched(self, url)


class TestNullHostRejected(unittest.TestCase):
    def test_null_host_rejected(self) -> None:
        # urlsplit("https:///x").hostname is None -- empty netloc, no host at all.
        _rejected_before_opener_touched(self, "https:///x")


class TestMalformedUrlMapsToPolicyRejected(unittest.TestCase):
    """Security-review fix pass (T-6-secfix), finding 1: `urlsplit(url)` and the
    `.port` property access inside `_check_policy` both raise a bare `ValueError`
    on malformed input -- confirmed empirically (brief's finding 1) for all three
    URLs below -- which used to escape `fetch()` outside its closed `NetError` set
    entirely. Each must now surface as `PolicyRejected`, never a bare `ValueError`,
    with the opener never touched."""

    def test_malformed_urls_raise_policy_rejected_not_value_error(self) -> None:
        for url in (
            "https://www.youtube.com:99999/x",  # port out of range 0-65535
            "https://www.youtube.com:abc/x",  # port could not be cast to integer
            "https://[::1/x",  # malformed IPv6 bracket syntax
        ):
            with self.subTest(url=url):
                _rejected_before_opener_touched(self, url)


class TestAllowlistExactAndSuffix(unittest.TestCase):
    def test_allowlist_exact_and_suffix(self) -> None:
        # Positive: both confirmed hosts (T-P3) are accepted, and the request
        # actually reaches the (fake) opener exactly once.
        for host in ("www.youtube.com", "youtubei.googleapis.com"):
            with self.subTest(host=host):
                fake_urlopen, calls = mock_urlopen(
                    [_FakeHTTPResponse(b"ok", status=200, headers={"X-Test": "1"})]
                )
                with patch.object(client, "_OPENER", new=_FakeOpener(fake_urlopen)):
                    response = client.fetch(f"https://{host}/path")
                self.assertEqual(response.status, 200)
                self.assertEqual(response.body, b"ok")
                self.assertEqual(len(calls), 1)

        # Negative: exact-match-only means these suffix/lookalike hosts are
        # rejected -- there is no suffix-match branch to (mis)accept them.
        for host in (
            "evilgooglevideo.com",
            "googlevideo.com.evil.com",
            "www.youtube.com.evil.com",
        ):
            with self.subTest(host=host):
                _rejected_before_opener_touched(self, f"https://{host}/path")


class TestNonStandardPortRejected(unittest.TestCase):
    def test_non_standard_port_rejected(self) -> None:
        _rejected_before_opener_touched(self, "https://www.youtube.com:8080/x")

        # Positive: no explicit port, and the explicit default port, both pass --
        # the check rejects "not None and not 443", not "any explicit port".
        for url in (
            "https://www.youtube.com/x",
            "https://www.youtube.com:443/x",
        ):
            with self.subTest(url=url):
                fake_urlopen, calls = mock_urlopen([_FakeHTTPResponse(b"ok")])
                with patch.object(client, "_OPENER", new=_FakeOpener(fake_urlopen)):
                    client.fetch(url)
                self.assertEqual(len(calls), 1)


class TestOpenerHasNoDefaultHandlers(unittest.TestCase):
    def test_opener_has_no_default_handlers(self) -> None:
        banned = (
            urllib.request.FileHandler,
            urllib.request.FTPHandler,
            urllib.request.DataHandler,
        )
        # `.handlers` is a real attribute OpenerDirector.__init__ always sets
        # (verified empirically), but typeshed doesn't declare it as part of the
        # class's public stub -- hence the ignore, not a sign this is unsafe.
        opener_handlers = client._OPENER.handlers  # type: ignore[attr-defined]
        for handler in opener_handlers:
            self.assertNotIsInstance(handler, banned)

        # Structural, not just "none of the banned ones": the real opener's handler
        # set is exactly what `_build_opener()`'s explicit `add_handler` calls
        # actually register -- nothing extra (e.g. a plain `HTTPHandler`, which
        # `build_opener()`'s default set would have added) snuck in either.
        #
        # `ProxyHandler` is deliberately NOT in this expected set even though
        # `_build_opener()` calls `opener.add_handler(ProxyHandler({}))`:
        # empirically confirmed (see `_build_opener`'s docstring),
        # `OpenerDirector.add_handler` only appends a handler to `.handlers` if it
        # finds at least one dynamically-registered `<protocol>_open` method on it,
        # and `ProxyHandler({})` registers none when its `proxies` mapping is
        # empty -- so it is called for its documentation/defense-in-depth value
        # (explicitly stating "no proxy routing"), but never actually appears here.
        expected_types = {
            urllib.request.HTTPSHandler,
            client._NoRedirectHandler,
            urllib.request.HTTPErrorProcessor,
            urllib.request.HTTPDefaultErrorHandler,
        }
        actual_types = {type(handler) for handler in opener_handlers}
        self.assertEqual(actual_types, expected_types)
        self.assertNotIn(urllib.request.ProxyHandler, actual_types)


class TestRedirectMapsToPolicyRejectedBeforeStatusBranches(unittest.TestCase):
    def test_redirect_302_and_305_map_to_policy_rejected_before_status_branches(
        self,
    ) -> None:
        # Structural: the redirect (3xx) check appears in fetch()'s own source
        # before the 429 and 5xx branches -- asserting source order directly, since
        # `_NoRedirectHandler.redirect_request` returning `None` alone does not
        # surface as a clean `PolicyRejected` (empirically confirmed, plan.md), so
        # behavior alone would not prove the ordering constraint the task requires.
        source = inspect.getsource(client.fetch)
        redirect_idx = source.index("300 <= error.code < 400")
        throttled_idx = source.index("error.code == 429")
        server_error_idx = source.index("500 <= error.code < 600")
        self.assertLess(redirect_idx, throttled_idx)
        self.assertLess(redirect_idx, server_error_idx)

        # Behavioral: both 302 and 305 actually raise PolicyRejected.
        for code in (302, 305):
            with self.subTest(code=code):
                fake_urlopen, calls = mock_urlopen(
                    [http_error("https://www.youtube.com/x", code)]
                )
                with patch.object(
                    client, "_OPENER", new=_FakeOpener(fake_urlopen)
                ), self.assertRaises(client.PolicyRejected):
                    client.fetch("https://www.youtube.com/x")
                self.assertEqual(len(calls), 1)


class TestTransportFieldSetIsExactlySleepAndJitter(unittest.TestCase):
    def test_transport_field_set_is_exactly_sleep_and_jitter(self) -> None:
        # Structural, not name-specific -- asserts the *full* field set, so a
        # future, differently-named egress-capable field addition (e.g. an
        # `opener` field, cycle 8's mistake) is caught regardless of its name
        # (plan.md narrow-check fix, corrected in cycle 9).
        field_names = {f.name for f in dataclasses.fields(client.Transport)}
        self.assertEqual(field_names, {"sleep", "jitter"})
        self.assertTrue(client.Transport.__dataclass_params__.frozen)  # type: ignore[attr-defined]


class TestResponseIsPlainDataContainer(unittest.TestCase):
    def test_response_is_plain_data_container(self) -> None:
        field_names = {f.name for f in dataclasses.fields(client.Response)}
        self.assertEqual(field_names, {"status", "headers", "body"})
        self.assertTrue(client.Response.__dataclass_params__.frozen)  # type: ignore[attr-defined]

        # Never the raw http.client.HTTPResponse/urllib response object -- a plain
        # data container carries no live `.read()`/`.fp` handle across the
        # `net/` -> `providers/` border.
        response = client.Response(status=200, headers={}, body=b"x")
        self.assertFalse(hasattr(response, "read"))
        self.assertFalse(hasattr(response, "fp"))


class TestFetchOnlyEverRaisesClosedNetErrorSetForMalformedUrls(unittest.TestCase):
    """The reviewer's own optional recommendation (T-6-secfix brief): a small
    fuzz-style corpus of malformed URL strings, asserting `fetch()` only ever
    raises members of the closed `NetError` set -- would have caught finding 1
    directly (a bare `ValueError` escaping `_check_policy`), rather than relying
    on each malformed shape being separately anticipated by name."""

    def test_malformed_url_corpus_never_escapes_net_error(self) -> None:
        corpus = (
            "http://www.youtube.com/x",
            "https:///x",
            "https://www.youtube.com:99999/x",
            "https://www.youtube.com:abc/x",
            "https://[::1/x",
            "not-a-url-at-all",
            "https://www.youtube.com:8080/x",
            "",
            "https://evil.com/x",
        )
        for url in corpus:
            with self.subTest(url=url):
                fake_opener = Mock()
                with patch.object(client, "_OPENER", new=fake_opener):
                    try:
                        client.fetch(url)
                    except client.NetError:
                        pass
                    except Exception as error:
                        # Deliberately broad: this test's entire point is to catch
                        # anything that ISN'T a NetError, which a narrower except
                        # clause would defeat.
                        self.fail(
                            f"fetch({url!r}) raised {type(error).__name__}, "
                            "not a member of the closed NetError set"
                        )
                fake_opener.open.assert_not_called()


if __name__ == "__main__":
    unittest.main()

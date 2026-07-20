"""Tests for get_eol_status (#415): JDK / Kotlin / Gradle / Spring Boot
end-of-life and support status via the endoflife.date v1 API.

Cycle-matching is tested as pure logic (no network) since it is the part most
sensitive to the empirically-confirmed quirk that cycle granularity varies per
product (major.minor for Kotlin/Spring Boot, major-only for Gradle/JDK
vendors — verified live against endoflife.date for kotlin/gradle/spring-boot/
eclipse-temurin). ``_fetch_endoflife_product`` gets its own raw-HTTP tests
(same boundary as test_depsdev.py's TestFetchDepsdevDependencies); the
orchestration tests mock that function directly. Airgap tests go through the
real #296 capability short-circuit end-to-end, mirroring test_airgap.py.
"""

import json
import unittest
import unittest.mock
import urllib.error

from _helpers import mock_urlopen, server


def _cycle(
    name: str,
    *,
    is_eol: bool = False,
    eol_from=None,
    is_maintained: bool = True,
    is_lts: bool = False,
    latest_name=None,
) -> dict:
    return {
        "name": name,
        "codename": None,
        "label": name,
        "releaseDate": "2020-01-01",
        "isLts": is_lts,
        "ltsFrom": None,
        "isEol": is_eol,
        "eolFrom": eol_from,
        "isMaintained": is_maintained,
        "latest": {"name": latest_name or f"{name}.0", "date": "2024-01-01", "link": "https://example.invalid"},
        "custom": None,
    }


def _product_body(cycles) -> bytes:
    return json.dumps({
        "schema_version": "1.2.1",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "last_modified": "2026-01-01T00:00:00+00:00",
        "result": {"name": "x", "label": "X", "releases": cycles},
    }).encode()


class MatchEolCycleTest(unittest.TestCase):
    """Pure matching logic. Covers the varying cycle granularity confirmed
    live: major.minor for kotlin/spring-boot, major-only for gradle/JDK
    vendors (see server.py's module note above _fetch_endoflife_product)."""

    def test_major_minor_cycle_matches_patch_version(self):
        cycles = [_cycle("2.4"), _cycle("2.3")]
        match = server._match_eol_cycle(cycles, "2.4.10")
        self.assertEqual(match["name"], "2.4")

    def test_major_only_cycle_matches_full_version(self):
        cycles = [_cycle("9"), _cycle("8"), _cycle("7")]
        match = server._match_eol_cycle(cycles, "8.14.5")
        self.assertEqual(match["name"], "8")

    def test_exact_cycle_name_match(self):
        cycles = [_cycle("9")]
        self.assertEqual(server._match_eol_cycle(cycles, "9")["name"], "9")

    def test_dot_boundary_prevents_false_prefix_match(self):
        # cycle "1" must NOT match version "10.5" — no dot right after "1".
        # Only cycle "1" is present (no competing "10") so the "prefer longest
        # match" tie-break cannot mask a dot-boundary regression here — a
        # missing dot-boundary check would make this assert a bogus match
        # instead of None.
        cycles = [_cycle("1")]
        self.assertIsNone(server._match_eol_cycle(cycles, "10.5"))

    def test_dot_boundary_with_a_competing_longer_cycle(self):
        # Same false-prefix risk as above, but with "10" also present — the
        # correct cycle "10" must win over the falsely-matching "1" here too.
        cycles = [_cycle("1"), _cycle("10")]
        match = server._match_eol_cycle(cycles, "10.5")
        self.assertEqual(match["name"], "10")

    def test_no_match_returns_none(self):
        cycles = [_cycle("2.4")]
        self.assertIsNone(server._match_eol_cycle(cycles, "99.0.0"))

    def test_prefers_longest_matching_cycle_name(self):
        # Pathological overlap: both "1" and "1.2" prefix-match "1.2.3".
        cycles = [_cycle("1"), _cycle("1.2")]
        match = server._match_eol_cycle(cycles, "1.2.3")
        self.assertEqual(match["name"], "1.2")


class FetchEndoflifeProductTest(unittest.TestCase):
    def test_happy_path(self):
        body = _product_body([_cycle("2.4", latest_name="2.4.10")])
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)]),
        ):
            out = server._fetch_endoflife_product("kotlin")
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["cycles"]), 1)
        self.assertEqual(out["cycles"][0]["name"], "2.4")

    def test_404_is_unknown_product_not_a_crash(self):
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(404, b"")]),
        ):
            out = server._fetch_endoflife_product("java")
        self.assertFalse(out["ok"])
        self.assertIn("unknown product", out["error"])
        self.assertNotIn("capabilityUnavailable", out)

    def test_transport_error_degrades(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([urllib.error.URLError("offline")]),
        ):
            out = server._fetch_endoflife_product("kotlin")
        self.assertFalse(out["ok"])
        self.assertEqual(out["capabilityUnavailable"], "unreachable")

    def test_uses_http_get_cached_with_long_ttl(self):
        body = _product_body([_cycle("2.4")])
        with unittest.mock.patch.object(
            server, "http_get_cached", return_value=(200, body)
        ) as cached:
            out = server._fetch_endoflife_product("kotlin")
        self.assertTrue(out["ok"])
        cached.assert_called_once()
        args, _kwargs = cached.call_args
        self.assertEqual(args[1], server.TTL_ENDOFLIFE)
        self.assertIn("endoflife.date", args[0])
        self.assertIn("/products/kotlin", args[0])


class GetEolStatusOrchestrationTest(unittest.TestCase):
    """Mocks _fetch_endoflife_product directly — isolates get_eol_status's own
    per-product dispatch/aggregation/validation logic from the HTTP/cache
    layer already covered above."""

    @staticmethod
    def _fake_fetch(cycles_by_product):
        def _fetch(product):
            cycles = cycles_by_product.get(product)
            if cycles is None:
                return {
                    "ok": False, "status": 404, "cycles": [],
                    "error": f"unknown product on endoflife.date: {product!r}",
                }
            return {"ok": True, "status": 200, "cycles": cycles, "error": None}
        return _fetch

    def test_multiple_products_in_one_call(self):
        fetch = self._fake_fetch({
            "kotlin": [_cycle("2.4", latest_name="2.4.10")],
            "gradle": [_cycle("9", latest_name="9.6.1")],
        })
        with unittest.mock.patch.object(server, "_fetch_endoflife_product", side_effect=fetch):
            out = server.get_eol_status(kotlin="2.4.10", gradle="9.6.1")
        self.assertEqual(len(out["results"]), 2)
        by_product = {r["product"]: r for r in out["results"]}
        self.assertEqual(by_product["kotlin"]["cycle"], "2.4")
        self.assertEqual(by_product["gradle"]["cycle"], "9")

    def test_jdk_requires_vendor(self):
        with self.assertRaises(ValueError):
            server.get_eol_status(jdk={"version": "21"})

    def test_jdk_requires_version(self):
        with self.assertRaises(ValueError):
            server.get_eol_status(jdk={"vendor": "eclipse-temurin"})

    def test_no_products_requested_raises(self):
        with self.assertRaises(ValueError):
            server.get_eol_status()

    def test_jdk_vendor_is_used_as_the_product_slug(self):
        fetch = self._fake_fetch({
            "eclipse-temurin": [_cycle("21", is_lts=True, latest_name="21.0.11")],
        })
        with unittest.mock.patch.object(server, "_fetch_endoflife_product", side_effect=fetch):
            out = server.get_eol_status(jdk={"vendor": "eclipse-temurin", "version": "21.0.11"})
        self.assertEqual(out["results"][0]["product"], "eclipse-temurin")
        self.assertTrue(out["results"][0]["isLts"])

    def test_unknown_vendor_is_a_clear_per_item_error_not_a_crash(self):
        fetch = self._fake_fetch({})  # nothing known -> every product 404s
        with unittest.mock.patch.object(server, "_fetch_endoflife_product", side_effect=fetch):
            out = server.get_eol_status(jdk={"vendor": "not-a-real-vendor", "version": "1.0"})
        self.assertEqual(len(out["results"]), 1)
        self.assertIn("error", out["results"][0])
        self.assertNotIn("cycle", out["results"][0])

    def test_version_with_no_matching_cycle_is_a_clear_per_item_error(self):
        fetch = self._fake_fetch({"kotlin": [_cycle("2.4")]})
        with unittest.mock.patch.object(server, "_fetch_endoflife_product", side_effect=fetch):
            out = server.get_eol_status(kotlin="0.1.0")
        self.assertIn("error", out["results"][0])
        self.assertNotIn("cycle", out["results"][0])

    def test_output_field_mapping(self):
        fetch = self._fake_fetch({
            "spring-boot": [_cycle(
                "3.5", is_eol=True, eol_from="2026-06-30",
                is_maintained=True, latest_name="3.5.16",
            )],
        })
        with unittest.mock.patch.object(server, "_fetch_endoflife_product", side_effect=fetch):
            out = server.get_eol_status(spring_boot="3.5.16")
        item = out["results"][0]
        self.assertEqual(item["product"], "spring-boot")
        self.assertEqual(item["requestedVersion"], "3.5.16")
        self.assertEqual(item["cycle"], "3.5")
        self.assertTrue(item["isEol"])
        self.assertEqual(item["eolDate"], "2026-06-30")
        self.assertTrue(item["isMaintained"])
        self.assertFalse(item["isLts"])
        self.assertEqual(item["latestInCycle"], "3.5.16")

    def test_per_item_capability_propagates_to_top_level(self):
        def _fetch(product):
            return {"ok": False, "status": None, "cycles": [], "error": "x", "capabilityUnavailable": "offline"}
        with unittest.mock.patch.object(server, "_fetch_endoflife_product", side_effect=_fetch):
            out = server.get_eol_status(kotlin="2.4.10")
        self.assertEqual(out["capabilityUnavailable"], "offline")
        self.assertEqual(out["results"][0]["capabilityUnavailable"], "offline")


class EndoflifeAirgapTest(unittest.TestCase):
    """End-to-end offline/unreachable propagation through the REAL #296
    capability short-circuit (raw urlopen mock, not a function-level mock) —
    mirrors test_airgap.py's OsvAirgapTest / DepsdevAirgapTest."""

    def test_offline_short_circuits_without_network(self):
        with unittest.mock.patch.dict("os.environ", {"MAVEN_MCP_OFFLINE": "1"}, clear=False):
            server.os.environ.pop("MAVEN_MCP_ENDOFLIFE_BASE", None)
            with unittest.mock.patch("urllib.request.urlopen") as urlopen:
                out = server.get_eol_status(kotlin="2.4.10")
        urlopen.assert_not_called()
        self.assertEqual(out["capabilityUnavailable"], "offline")
        self.assertEqual(out["results"][0]["capabilityUnavailable"], "offline")

    def test_transport_failure_marks_unreachable(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            server.os.environ.pop("MAVEN_MCP_OFFLINE", None)
            server.os.environ.pop("MAVEN_MCP_ENDOFLIFE_BASE", None)
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([urllib.error.URLError("dns")]),
            ):
                out = server.get_eol_status(kotlin="2.4.10")
        self.assertEqual(out["results"][0]["capabilityUnavailable"], "unreachable")

    def test_override_routes_to_custom_base(self):
        body = _product_body([_cycle("2.4", latest_name="2.4.10")])
        with unittest.mock.patch.dict(
            "os.environ",
            {"MAVEN_MCP_ENDOFLIFE_BASE": "https://eol.corp.example/api/v1"},
            clear=False,
        ):
            server.os.environ.pop("MAVEN_MCP_OFFLINE", None)
            with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)]),
            ) as urlopen:
                server.get_eol_status(kotlin="2.4.10")
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://eol.corp.example/api/v1/products/kotlin",
        )


class HandlerDispatchTest(unittest.TestCase):
    def test_handler_calls_through(self):
        body = _product_body([_cycle("2.4", latest_name="2.4.10")])
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)]),
        ):
            out = server.handle_get_eol_status({"kotlin": "2.4.10"})
        self.assertEqual(out["results"][0]["product"], "kotlin")


if __name__ == "__main__":
    unittest.main()

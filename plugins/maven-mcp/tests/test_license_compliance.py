"""Transitive license compliance tests (#289).

Covers policy resolution, verdicts, deps.dev GetVersion license fetch,
and aggregation across a mocked GetDependencies graph.
"""

import json
import time
import unittest
import unittest.mock
import urllib.error

from _helpers import mock_urlopen, server


def _vk(name: str, version: str, system: str = "MAVEN") -> dict:
    return {"system": system, "name": name, "version": version}


def _node(name: str, version: str, relation: str = "DIRECT", errors=None) -> dict:
    return {
        "versionKey": _vk(name, version),
        "bundled": False,
        "relation": relation,
        "errors": errors or [],
    }


def _graph(nodes, edges, error: str = "") -> bytes:
    return json.dumps({"nodes": nodes, "edges": edges, "error": error}).encode()


def _version_payload(licenses) -> bytes:
    return json.dumps({
        "versionKey": _vk("ignored:ignored", "0"),
        "licenses": licenses,
    }).encode()


def _is_deps_url(url: str) -> bool:
    return ":dependencies" in url


def _is_version_url(url: str) -> bool:
    return "api.deps.dev" in url and ":dependencies" not in url


class TestLicensePolicy(unittest.TestCase):
    def test_default_permissive_disallow(self):
        policy = server.resolve_license_policy("Apache-2.0")
        self.assertEqual(policy["projectCategory"], "permissive")
        self.assertEqual(policy["policySource"], "default-permissive")
        self.assertIn("strong-copyleft", policy["disallow"])
        self.assertIn("network-copyleft", policy["disallow"])
        self.assertIn("proprietary", policy["disallow"])
        self.assertNotIn("weak-copyleft", policy["disallow"])

    def test_omitted_project_license_uses_permissive_default(self):
        policy = server.resolve_license_policy(None)
        self.assertEqual(policy["policySource"], "default-permissive")
        self.assertIn("strong-copyleft", policy["disallow"])

    def test_custom_disallow_replaces_default(self):
        policy = server.resolve_license_policy(
            "MIT",
            disallow=["LGPL-2.1-only", "weak-copyleft"],
        )
        self.assertEqual(policy["policySource"], "custom")
        self.assertEqual(
            set(policy["disallow"]),
            {"LGPL-2.1-only", "weak-copyleft"},
        )
        self.assertNotIn("strong-copyleft", policy["disallow"])

    def test_non_permissive_project_without_disallow(self):
        policy = server.resolve_license_policy("GPL-3.0-only")
        self.assertEqual(policy["projectCategory"], "strong-copyleft")
        self.assertEqual(policy["policySource"], "none")
        self.assertEqual(policy["disallow"], [])


class TestLicenseComplianceVerdict(unittest.TestCase):
    def setUp(self):
        self.policy = server.resolve_license_policy("Apache-2.0")

    def test_ok_for_permissive(self):
        out = server.license_compliance_verdict(
            spdx_id="MIT",
            category="permissive",
            policy=self.policy,
        )
        self.assertEqual(out["verdict"], "ok")

    def test_violation_for_gpl(self):
        out = server.license_compliance_verdict(
            spdx_id="GPL-3.0-only",
            category="strong-copyleft",
            policy=self.policy,
        )
        self.assertEqual(out["verdict"], "violation")
        self.assertIn("strong-copyleft", out["reason"])

    def test_missing_license_is_review_not_ok(self):
        out = server.license_compliance_verdict(
            spdx_id=None,
            category="unknown",
            policy=self.policy,
            missing_license=True,
        )
        self.assertEqual(out["verdict"], "review")
        self.assertNotEqual(out["verdict"], "ok")

    def test_fetch_error_is_review(self):
        out = server.license_compliance_verdict(
            spdx_id=None,
            category="unknown",
            policy=self.policy,
            fetch_error="deps.dev returned HTTP 503",
        )
        self.assertEqual(out["verdict"], "review")

    def test_custom_spdx_disallow(self):
        policy = server.resolve_license_policy("MIT", disallow=["MIT"])
        out = server.license_compliance_verdict(
            spdx_id="MIT",
            category="permissive",
            policy=policy,
        )
        self.assertEqual(out["verdict"], "violation")


class TestPrimaryLicenseFromDepsdev(unittest.TestCase):
    def test_single_known_spdx(self):
        out = server._primary_license_from_depsdev(["Apache-2.0"])
        self.assertEqual(out["spdxId"], "Apache-2.0")
        self.assertEqual(out["category"], "permissive")

    def test_non_standard(self):
        out = server._primary_license_from_depsdev(["non-standard"])
        self.assertIsNone(out["spdxId"])
        self.assertEqual(out["category"], "proprietary")

    def test_expression_degrades_to_unknown(self):
        out = server._primary_license_from_depsdev(["Apache-2.0 OR MIT"])
        self.assertEqual(out["category"], "unknown")
        self.assertIsNone(out["spdxId"])

    def test_empty(self):
        out = server._primary_license_from_depsdev([])
        self.assertEqual(out["category"], "unknown")


class TestFetchDepsdevLicenses(unittest.TestCase):
    def test_happy_path(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _version_payload(["MIT"]))]),
        ):
            out = server.fetch_depsdev_licenses("com.example", "lib", "1.0")
        self.assertTrue(out["ok"])
        self.assertEqual(out["licenses"], ["MIT"])

    def test_http_error_degrades(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(404, b"")]),
        ):
            out = server.fetch_depsdev_licenses("com.missing", "x", "1.0")
        self.assertFalse(out["ok"])
        self.assertEqual(out["licenses"], [])
        self.assertIn("404", out["error"] or "")

    def test_version_url_encoding(self):
        url = server._depsdev_version_url("com.google.guava", "guava", "32.1.2-jre")
        self.assertTrue(url.startswith(server.DEPSDEV_API + "/systems/MAVEN/packages/"))
        self.assertIn("com.google.guava%3Aguava", url)
        self.assertTrue(url.endswith("/32.1.2-jre"))
        self.assertNotIn(":dependencies", url)


class TestCheckLicenseCompliance(unittest.TestCase):
    def _router(self, graph_body, version_map):
        """Route deps.dev URLs to graph or GetVersion fixtures."""

        def side_effect(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if _is_deps_url(url):
                return mock_urlopen([(200, graph_body)])(req, *args, **kwargs)
            if _is_version_url(url):
                # Match by package name fragment in URL.
                for key, licenses in version_map.items():
                    enc = key.replace(":", "%3A")
                    if enc in url or key in url:
                        return mock_urlopen(
                            [(200, _version_payload(licenses))]
                        )(req, *args, **kwargs)
                return mock_urlopen([(200, _version_payload([]))])(
                    req, *args, **kwargs
                )
            raise AssertionError(f"unexpected URL: {url}")

        return side_effect

    def test_flags_transitive_gpl_in_permissive_project(self):
        graph = _graph(
            [
                _node("com.example:root", "1.0", "SELF"),
                _node("com.example:direct", "1.0", "DIRECT"),
                _node("com.example:gpl-lib", "2.0", "INDIRECT"),
            ],
            [
                {"fromNode": 0, "toNode": 1, "requirement": "1.0"},
                {"fromNode": 1, "toNode": 2, "requirement": "2.0"},
            ],
        )
        version_map = {
            "com.example:root": ["Apache-2.0"],
            "com.example:direct": ["MIT"],
            "com.example:gpl-lib": ["GPL-3.0-only"],
        }
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=self._router(graph, version_map),
        ):
            out = server.check_license_compliance(
                [{"groupId": "com.example", "artifactId": "root", "version": "1.0"}],
                project_license="Apache-2.0",
            )

        self.assertEqual(out["summary"]["total"], 3)
        self.assertGreaterEqual(out["summary"]["violationCount"], 1)
        by_ga = {
            f"{r['groupId']}:{r['artifactId']}": r for r in out["results"]
        }
        gpl = by_ga["com.example:gpl-lib"]
        self.assertTrue(gpl["viaTransitive"])
        self.assertEqual(gpl["verdict"], "violation")
        self.assertEqual(gpl["category"], "strong-copyleft")
        self.assertEqual(by_ga["com.example:root"]["viaTransitive"], False)
        self.assertEqual(by_ga["com.example:direct"]["verdict"], "ok")
        self.assertIn("notes", out)
        self.assertTrue(any("not legal advice" in n.lower() for n in out["notes"]))

    def test_missing_license_is_review(self):
        graph = _graph(
            [
                _node("com.example:root", "1.0", "SELF"),
                _node("com.example:mystery", "1.0", "DIRECT"),
            ],
            [{"fromNode": 0, "toNode": 1, "requirement": "1.0"}],
        )
        version_map = {
            "com.example:root": ["MIT"],
            "com.example:mystery": [],
        }
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=self._router(graph, version_map),
        ):
            out = server.check_license_compliance(
                [{"groupId": "com.example", "artifactId": "root", "version": "1.0"}],
                project_license="MIT",
            )
        mystery = next(
            r for r in out["results"] if r["artifactId"] == "mystery"
        )
        self.assertEqual(mystery["verdict"], "review")
        self.assertNotEqual(mystery["verdict"], "ok")

    def test_custom_disallow_overrides_default(self):
        graph = _graph(
            [
                _node("com.example:root", "1.0", "SELF"),
                _node("com.example:lgpl", "1.0", "DIRECT"),
            ],
            [{"fromNode": 0, "toNode": 1, "requirement": "1.0"}],
        )
        version_map = {
            "com.example:root": ["MIT"],
            "com.example:lgpl": ["LGPL-2.1-only"],
        }
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=self._router(graph, version_map),
        ):
            # Default permissive policy does NOT disallow weak-copyleft.
            out_default = server.check_license_compliance(
                [{"groupId": "com.example", "artifactId": "root", "version": "1.0"}],
                project_license="MIT",
            )
            out_custom = server.check_license_compliance(
                [{"groupId": "com.example", "artifactId": "root", "version": "1.0"}],
                project_license="MIT",
                disallow=["weak-copyleft"],
            )
        lgpl_default = next(
            r for r in out_default["results"] if r["artifactId"] == "lgpl"
        )
        lgpl_custom = next(
            r for r in out_custom["results"] if r["artifactId"] == "lgpl"
        )
        self.assertEqual(lgpl_default["verdict"], "ok")
        self.assertEqual(lgpl_custom["verdict"], "violation")

    def test_graph_fetch_failure_degrades(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([urllib.error.URLError("offline")]),
        ):
            out = server.check_license_compliance(
                [{"groupId": "com.example", "artifactId": "root", "version": "1.0"}],
                project_license="MIT",
            )
        self.assertTrue(out["partial"])
        self.assertTrue(out.get("errors"))
        # Root still present with review (never false ok for missing data).
        self.assertEqual(len(out["results"]), 1)
        self.assertEqual(out["results"][0]["verdict"], "review")

    def test_deadline_marks_partial_without_hanging(self):
        # #402: force the deadline path deterministically by making
        # fetch_depsdev_dependencies artificially slow relative to a tiny
        # TOOL_DEADLINE -- avoids any race on exact submit/check timing (the
        # margin between the sleep and the deadline absorbs scheduling
        # jitter). Two roots so the #400 parallel root-fetch phase actually
        # has more than one item to bound. The call must return promptly
        # (not block for the full artificial delay) with partial: true and
        # an explanatory note.
        def _slow_graph(group_id, artifact_id, version):
            time.sleep(0.2)
            return {"ok": True, "nodes": [], "edges": []}

        with unittest.mock.patch.object(server, "TOOL_DEADLINE", 0.02), \
                unittest.mock.patch.object(
                    server, "fetch_depsdev_dependencies", side_effect=_slow_graph,
                ):
            start = time.monotonic()
            out = server.check_license_compliance(
                [
                    {"groupId": "com.example", "artifactId": "root1", "version": "1.0"},
                    {"groupId": "com.example", "artifactId": "root2", "version": "1.0"},
                ],
                project_license="MIT",
            )
            elapsed = time.monotonic() - start
        self.assertTrue(out["partial"])
        self.assertTrue(any("deadline" in n.lower() for n in out["notes"]))
        # Returned well before the 0.2s the slow mock would need per root --
        # proves the call did not block waiting for the cut-off fetches.
        self.assertLess(elapsed, 0.2)

    def test_handler_wires_args(self):
        graph = _graph(
            [_node("com.example:root", "1.0", "SELF")],
            [],
        )
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=self._router(graph, {"com.example:root": ["Apache-2.0"]}),
        ):
            out = server.handle_check_license_compliance({
                "dependencies": [
                    {
                        "groupId": "com.example",
                        "artifactId": "root",
                        "version": "1.0",
                    }
                ],
                "projectLicense": "Apache-2.0",
            })
        self.assertEqual(out["results"][0]["verdict"], "ok")
        self.assertEqual(out["policy"]["policySource"], "default-permissive")

    def test_skips_versionless_roots(self):
        out = server.check_license_compliance(
            [{"groupId": "com.example", "artifactId": "root"}],
            project_license="MIT",
        )
        self.assertEqual(out["results"], [])
        self.assertEqual(out["summary"]["total"], 0)

    def test_tool_registered(self):
        names = [t["name"] for t in server.TOOLS]
        self.assertIn("check_license_compliance", names)
        self.assertIn(
            "check_license_compliance",
            server.TOOL_HANDLERS,
        )


if __name__ == "__main__":
    unittest.main()

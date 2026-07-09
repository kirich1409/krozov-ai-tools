"""Air-gapped degradation for external enrichment services (#296).

Covers offline short-circuit, short external timeouts, endpoint overrides, and
``capabilityUnavailable`` markers so empty CVE/health/changelog/transitive
results are never mistaken for verified-clean.
"""

import json
import unittest
import unittest.mock
import urllib.error

from _helpers import mock_urlopen, server


class ExternalEndpointResolutionTest(unittest.TestCase):
    def test_defaults_match_public_hosts(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            for key in (
                "MAVEN_MCP_OSV_BASE",
                "MAVEN_MCP_GITHUB_BASE",
                "MAVEN_MCP_DEPSDEV_BASE",
                "MAVEN_MCP_ANDROID_DOCS_BASE",
            ):
                server.os.environ.pop(key, None)
            self.assertEqual(server._osv_querybatch_url(), server.OSV_API_DEFAULT)
            self.assertEqual(
                server._osv_vuln_url("GHSA-1"),
                server.OSV_VULN_API_DEFAULT + "/GHSA-1",
            )
            self.assertEqual(server._github_api_base(), server.GITHUB_API_DEFAULT)
            self.assertEqual(server._depsdev_api_base(), server.DEPSDEV_API_DEFAULT)
            self.assertTrue(
                server.get_agp_releases_url("8.7.0").startswith(
                    "https://developer.android.com/build/releases/"
                )
            )

    def test_overrides_rewrite_bases(self):
        env = {
            "MAVEN_MCP_OSV_BASE": "https://osv.corp.example/v1",
            "MAVEN_MCP_GITHUB_BASE": "https://ghe.example.com/api/v3",
            "MAVEN_MCP_DEPSDEV_BASE": "https://depsdev.corp.example/v3",
            "MAVEN_MCP_ANDROID_DOCS_BASE": "https://android-docs.corp.example",
        }
        with unittest.mock.patch.dict("os.environ", env, clear=False):
            self.assertEqual(
                server._osv_querybatch_url(),
                "https://osv.corp.example/v1/querybatch",
            )
            self.assertEqual(
                server._osv_vuln_url("CVE-1"),
                "https://osv.corp.example/v1/vulns/CVE-1",
            )
            self.assertEqual(
                server._github_api_base(), "https://ghe.example.com/api/v3"
            )
            self.assertEqual(
                server._depsdev_api_base(), "https://depsdev.corp.example/v3"
            )
            self.assertEqual(
                server.get_androidx_releases_url("androidx.core"),
                "https://android-docs.corp.example/jetpack/androidx/releases/core",
            )


class OfflineCapabilityGuardTest(unittest.TestCase):
    def test_offline_without_override_is_offline(self):
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_OFFLINE": "1"}, clear=False
        ):
            for key in (
                "MAVEN_MCP_OSV_BASE",
                "MAVEN_MCP_GITHUB_BASE",
                "MAVEN_MCP_DEPSDEV_BASE",
                "MAVEN_MCP_ANDROID_DOCS_BASE",
            ):
                server.os.environ.pop(key, None)
            for svc in ("osv", "github", "depsdev", "android_docs"):
                self.assertEqual(server._external_capability(svc), "offline")

    def test_offline_with_override_allows_mirror(self):
        with unittest.mock.patch.dict(
            "os.environ",
            {
                "MAVEN_MCP_OFFLINE": "1",
                "MAVEN_MCP_OSV_BASE": "https://osv.internal/v1",
                "MAVEN_MCP_GITHUB_BASE": "https://ghe.internal/api/v3",
            },
            clear=False,
        ):
            self.assertIsNone(server._external_capability("osv"))
            self.assertIsNone(server._external_capability("github"))
            self.assertEqual(server._external_capability("depsdev"), "offline")


class OsvAirgapTest(unittest.TestCase):
    def test_offline_short_circuits_without_network(self):
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_OFFLINE": "1"}, clear=False
        ):
            server.os.environ.pop("MAVEN_MCP_OSV_BASE", None)
            with unittest.mock.patch("urllib.request.urlopen") as urlopen:
                out = server.query_osv_batch(
                    [{"groupId": "com.example", "artifactId": "lib", "version": "1.0"}]
                )
        urlopen.assert_not_called()
        self.assertEqual(out[0]["vulnerabilities"], [])
        self.assertEqual(out[0]["capabilityUnavailable"], "offline")

    def test_handler_marks_offline_empty_as_not_clean(self):
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_OFFLINE": "1"}, clear=False
        ):
            server.os.environ.pop("MAVEN_MCP_OSV_BASE", None)
            with unittest.mock.patch("urllib.request.urlopen") as urlopen:
                result = server.handle_get_dependency_vulnerabilities(
                    {
                        "dependencies": [
                            {
                                "groupId": "com.example",
                                "artifactId": "lib",
                                "version": "1.0",
                            }
                        ]
                    }
                )
        urlopen.assert_not_called()
        self.assertEqual(result["capabilityUnavailable"], "offline")
        self.assertEqual(result["results"][0]["vulnerabilityCount"], 0)
        self.assertEqual(result["results"][0]["capabilityUnavailable"], "offline")

    def test_transport_failure_marks_unreachable(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            server.os.environ.pop("MAVEN_MCP_OFFLINE", None)
            server.os.environ.pop("MAVEN_MCP_OSV_BASE", None)
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([urllib.error.URLError("blocked")]),
            ) as urlopen:
                out = server.query_osv_batch(
                    [{"groupId": "com.example", "artifactId": "lib", "version": "1.0"}]
                )
        self.assertGreaterEqual(urlopen.call_count, 1)
        self.assertEqual(out[0]["capabilityUnavailable"], "unreachable")
        # Short external timeout is passed through to urlopen.
        self.assertEqual(
            urlopen.call_args.kwargs.get("timeout"), server.HTTP_TIMEOUT_EXTERNAL
        )

    def test_override_routes_querybatch(self):
        body = json.dumps({"results": [{"vulns": []}]}).encode()
        with unittest.mock.patch.dict(
            "os.environ",
            {"MAVEN_MCP_OSV_BASE": "https://osv.corp.example/v1"},
            clear=False,
        ):
            server.os.environ.pop("MAVEN_MCP_OFFLINE", None)
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, body)]),
            ) as urlopen:
                server.query_osv_batch(
                    [{"groupId": "com.example", "artifactId": "lib", "version": "1.0"}]
                )
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://osv.corp.example/v1/querybatch",
        )


class DepsdevAirgapTest(unittest.TestCase):
    def test_offline_fetch_marks_capability(self):
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_OFFLINE": "1"}, clear=False
        ):
            server.os.environ.pop("MAVEN_MCP_DEPSDEV_BASE", None)
            with unittest.mock.patch("urllib.request.urlopen") as urlopen:
                out = server.fetch_depsdev_dependencies("com.example", "lib", "1.0")
                graph = server.get_transitive_graph("com.example", "lib", "1.0")
        urlopen.assert_not_called()
        self.assertEqual(out["capabilityUnavailable"], "offline")
        self.assertEqual(graph["capabilityUnavailable"], "offline")
        self.assertTrue(graph["partial"])

    def test_unreachable_marks_capability(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            server.os.environ.pop("MAVEN_MCP_OFFLINE", None)
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([urllib.error.URLError("dns")]),
            ):
                out = server.fetch_depsdev_dependencies("com.example", "lib", "1.0")
        self.assertEqual(out["capabilityUnavailable"], "unreachable")


class GithubAndChangelogAirgapTest(unittest.TestCase):
    def test_offline_github_get_skips_network(self):
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_OFFLINE": "1"}, clear=False
        ):
            server.os.environ.pop("MAVEN_MCP_GITHUB_BASE", None)
            with unittest.mock.patch("urllib.request.urlopen") as urlopen:
                self.assertIsNone(server._gh_get("/repos/o/r"))
                self.assertFalse(server.gh_repo_exists("o", "r"))
        urlopen.assert_not_called()

    def test_health_offline_marks_capability(self):
        pom = b"<project></project>"
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_OFFLINE": "1"}, clear=False
        ):
            server.os.environ.pop("MAVEN_MCP_GITHUB_BASE", None)
            with unittest.mock.patch.object(
                server, "fetch_metadata", return_value={
                    "versions": ["1.0"],
                    "latest": "1.0",
                    "release": "1.0",
                    "lastUpdated": None,
                    "resolvedFrom": {
                        "url": "https://nexus.example/m2",
                        "scope": "dependency",
                        "viaPublicFallback": False,
                    },
                }
            ), unittest.mock.patch.object(
                server, "fetch_pom", return_value=pom.decode()
            ), unittest.mock.patch("urllib.request.urlopen") as urlopen:
                result = server.handle_get_dependency_health(
                    {
                        "dependencies": [
                            {
                                "groupId": "com.example",
                                "artifactId": "lib",
                                "version": "1.0",
                            }
                        ]
                    }
                )
        urlopen.assert_not_called()
        entry = result["results"][0]
        self.assertEqual(entry["capabilityUnavailable"], "offline")
        self.assertIn("offline", entry["healthError"])

    def test_changes_offline_marks_capability(self):
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_OFFLINE": "1"}, clear=False
        ):
            for key in (
                "MAVEN_MCP_GITHUB_BASE",
                "MAVEN_MCP_ANDROID_DOCS_BASE",
            ):
                server.os.environ.pop(key, None)
            with unittest.mock.patch.object(
                server,
                "fetch_metadata",
                return_value={
                    "versions": ["1.0", "1.1"],
                    "latest": "1.1",
                    "release": "1.1",
                    "lastUpdated": None,
                    "resolvedFrom": {
                        "url": "https://nexus.example/m2",
                        "scope": "dependency",
                        "viaPublicFallback": False,
                    },
                },
            ), unittest.mock.patch("urllib.request.urlopen") as urlopen:
                out = server.handle_get_dependency_changes(
                    {
                        "groupId": "com.example",
                        "artifactId": "lib",
                        "fromVersion": "1.0",
                        "toVersion": "1.1",
                    }
                )
        urlopen.assert_not_called()
        self.assertTrue(out.get("repositoryNotFound"))
        self.assertEqual(out.get("capabilityUnavailable"), "offline")


class LicenseComplianceAirgapTest(unittest.TestCase):
    def test_offline_compliance_marks_capability(self):
        with unittest.mock.patch.dict(
            "os.environ", {"MAVEN_MCP_OFFLINE": "1"}, clear=False
        ):
            server.os.environ.pop("MAVEN_MCP_DEPSDEV_BASE", None)
            with unittest.mock.patch("urllib.request.urlopen") as urlopen:
                out = server.check_license_compliance(
                    [
                        {
                            "groupId": "com.example",
                            "artifactId": "lib",
                            "version": "1.0",
                        }
                    ]
                )
        urlopen.assert_not_called()
        self.assertEqual(out["capabilityUnavailable"], "offline")
        self.assertTrue(out["partial"])


if __name__ == "__main__":
    unittest.main()

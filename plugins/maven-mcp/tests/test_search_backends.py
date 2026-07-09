"""Repo-manager search backends for search_artifacts (#295).

Mocks Nexus 3 REST and Artifactory GAVC/AQL responses; covers detection,
limit handling, closed-mode routing, and non-fatal unavailable results.
"""

import json
import unittest
import unittest.mock
import urllib.error

from _helpers import empty_ctx, mock_urlopen, server


NEXUS_BASE = "https://nexus.example.com/repository/maven-public"
ARTIFACTORY_BASE = "https://artifactory.example.com/artifactory/libs-release"


def _json(obj):
    return json.dumps(obj).encode()


def _closed_ctx(base=NEXUS_BASE, offline=True):
    return server.ResolutionContext(
        "/__no_project__",
        {"dependency": [], "plugin": []},
        False,
        offline=offline,
        repository_base=base,
        mirrors=[],
    )


class DetectManagerTest(unittest.TestCase):
    def test_url_detects_nexus_repository_path(self):
        self.assertEqual(server._detect_manager_from_url(NEXUS_BASE), "nexus")

    def test_url_detects_artifactory_path(self):
        self.assertEqual(
            server._detect_manager_from_url(ARTIFACTORY_BASE), "artifactory"
        )

    def test_url_detects_jfrog_host(self):
        self.assertEqual(
            server._detect_manager_from_url("https://my.jfrog.io/my-repo"),
            "artifactory",
        )

    def test_url_unknown_returns_none(self):
        self.assertIsNone(
            server._detect_manager_from_url("https://repo.corp.example/maven")
        )

    def test_headers_detect_nexus(self):
        self.assertEqual(
            server._detect_manager_from_headers({"Server": "Nexus/3.68.0"}),
            "nexus",
        )
        self.assertEqual(
            server._detect_manager_from_headers({"X-Nexus-Reason": "ok"}),
            "nexus",
        )

    def test_headers_detect_artifactory(self):
        self.assertEqual(
            server._detect_manager_from_headers({"Server": "Artifactory/7.0"}),
            "artifactory",
        )
        self.assertEqual(
            server._detect_manager_from_headers({"X-JFrog-Version": "7"}),
            "artifactory",
        )

    def test_preferred_override_wins(self):
        self.assertEqual(
            server.detect_repository_manager(
                ARTIFACTORY_BASE, preferred="nexus", probe=False
            ),
            "nexus",
        )

    def test_probe_nexus_status(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b'{"version":"3.68"}')]),
        ):
            kind = server.detect_repository_manager(
                "https://repo.corp.example/maven", probe=True
            )
        self.assertEqual(kind, "nexus")


class ApiRootTest(unittest.TestCase):
    def test_nexus_api_root_is_origin(self):
        self.assertEqual(
            server._nexus_api_root(NEXUS_BASE),
            "https://nexus.example.com",
        )

    def test_artifactory_api_root_keeps_context_path(self):
        self.assertEqual(
            server._artifactory_api_root(ARTIFACTORY_BASE),
            "https://artifactory.example.com/artifactory",
        )

    def test_artifactory_api_root_appends_when_missing(self):
        self.assertEqual(
            server._artifactory_api_root("https://af.example.com/libs"),
            "https://af.example.com/artifactory",
        )


class ParseGavQueryTest(unittest.TestCase):
    def test_coordinate_split(self):
        self.assertEqual(
            server._parse_gav_query("com.example:lib"),
            ("com.example", "lib"),
        )
        self.assertEqual(
            server._parse_gav_query("com.example:lib:1.0.0"),
            ("com.example", "lib"),
        )

    def test_keyword_and_solr_field_not_gav(self):
        self.assertEqual(server._parse_gav_query("ktor"), (None, None))
        self.assertEqual(server._parse_gav_query("g:io.ktor"), (None, None))


class NexusSearchTest(unittest.TestCase):
    def test_maps_items_and_aggregates_versions(self):
        body = {
            "items": [
                {"group": "io.ktor", "name": "ktor-client-core", "version": "2.0.0"},
                {"group": "io.ktor", "name": "ktor-client-core", "version": "3.1.1"},
                {"group": "io.ktor", "name": "ktor-server-core", "version": "3.1.1"},
            ]
        }
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _json(body))]),
        ) as m:
            results = server.search_nexus(NEXUS_BASE, "ktor", limit=10)
        url = m.call_args_list[0].args[0].full_url
        self.assertIn("/service/rest/v1/search?", url)
        self.assertIn("format=maven2", url)
        self.assertIn("q=ktor", url)
        self.assertEqual(len(results), 2)
        by_a = {r["artifactId"]: r for r in results}
        self.assertEqual(by_a["ktor-client-core"]["versionCount"], 2)
        self.assertEqual(by_a["ktor-client-core"]["latestVersion"], "3.1.1")
        self.assertEqual(by_a["ktor-client-core"]["groupId"], "io.ktor")

    def test_coordinate_query_uses_maven_filters(self):
        body = {"items": [{"group": "com.example", "name": "lib", "version": "1.0"}]}
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _json(body))]),
        ) as m:
            server.search_nexus(NEXUS_BASE, "com.example:lib", limit=5)
        url = m.call_args_list[0].args[0].full_url
        self.assertIn("maven.groupId=com.example", url)
        self.assertIn("maven.artifactId=lib", url)

    def test_respects_limit(self):
        items = [
            {"group": "g", "name": f"a{i}", "version": "1.0"} for i in range(20)
        ]
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _json({"items": items}))]),
        ):
            results = server.search_nexus(NEXUS_BASE, "a", limit=3)
        self.assertEqual(len(results), 3)

    def test_non_200_and_transport_yield_empty(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(503, b"")]),
        ):
            self.assertEqual(server.search_nexus(NEXUS_BASE, "x"), [])
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([urllib.error.URLError("down")]),
        ):
            self.assertEqual(server.search_nexus(NEXUS_BASE, "x"), [])


class ArtifactorySearchTest(unittest.TestCase):
    def test_gavc_maps_storage_uris(self):
        body = {
            "results": [
                {
                    "uri": (
                        "https://artifactory.example.com/artifactory/api/storage/"
                        "libs-release/org/acme/artifact/1.0.0/artifact-1.0.0.jar"
                    )
                },
                {
                    "uri": (
                        "https://artifactory.example.com/artifactory/api/storage/"
                        "libs-release/org/acme/artifact/2.0.0/artifact-2.0.0.jar"
                    )
                },
            ]
        }
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _json(body))]),
        ) as m:
            results = server.search_artifactory(
                ARTIFACTORY_BASE, "org.acme:artifact", limit=10
            )
        url = m.call_args_list[0].args[0].full_url
        self.assertIn("/api/search/gavc?", url)
        self.assertIn("g=org.acme", url)
        self.assertIn("a=artifact", url)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["groupId"], "org.acme")
        self.assertEqual(results[0]["artifactId"], "artifact")
        self.assertEqual(results[0]["versionCount"], 2)
        self.assertEqual(results[0]["latestVersion"], "2.0.0")

    def test_keyword_uses_aql_post(self):
        body = {
            "results": [
                {
                    "repo": "libs-release",
                    "path": "io/ktor/ktor-client-core/3.1.1",
                    "name": "ktor-client-core-3.1.1.jar",
                }
            ]
        }
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _json(body))]),
        ) as m:
            results = server.search_artifactory(ARTIFACTORY_BASE, "ktor", limit=10)
        req = m.call_args_list[0].args[0]
        self.assertIn("/api/search/aql", req.full_url)
        self.assertEqual(req.get_method(), "POST")
        self.assertIn(b"items.find", req.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["artifactId"], "ktor-client-core")
        self.assertEqual(results[0]["groupId"], "io.ktor")
        self.assertEqual(results[0]["latestVersion"], "3.1.1")

    def test_aql_limit_bounded(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _json({"results": []}))]),
        ) as m:
            server.search_artifactory(ARTIFACTORY_BASE, "lib", limit=2)
        self.assertIn(b".limit(10)", m.call_args_list[0].args[0].data)


class SearchRoutingTest(unittest.TestCase):
    def test_public_mode_uses_solr(self):
        solr = {
            "response": {
                "docs": [
                    {
                        "g": "com.example",
                        "a": "lib",
                        "latestVersion": "1.0",
                        "versionCount": 1,
                    }
                ]
            }
        }
        ctx = empty_ctx()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _json(solr))]),
        ) as m:
            out = server.search_artifacts_with_backend("lib", 10, ctx, "auto")
        self.assertEqual(out["searchBackend"], "central")
        self.assertEqual(out["results"][0]["artifactId"], "lib")
        self.assertIn("search.maven.org", m.call_args_list[0].args[0].full_url)

    def test_closed_nexus_auto(self):
        body = {
            "items": [
                {"group": "com.example", "name": "lib", "version": "1.2.3"},
            ]
        }
        ctx = _closed_ctx(NEXUS_BASE)
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _json(body))]),
        ) as m:
            out = server.search_artifacts_with_backend("lib", 10, ctx, "auto")
        self.assertEqual(out["searchBackend"], "nexus")
        self.assertEqual(out["results"][0]["latestVersion"], "1.2.3")
        self.assertIn("nexus.example.com/service/rest/v1/search", m.call_args_list[0].args[0].full_url)

    def test_closed_artifactory_auto(self):
        body = {
            "results": [
                {
                    "uri": (
                        "https://artifactory.example.com/artifactory/api/storage/"
                        "libs-release/com/example/lib/9.0/lib-9.0.jar"
                    )
                }
            ]
        }
        ctx = _closed_ctx(ARTIFACTORY_BASE)
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _json(body))]),
        ):
            out = server.search_artifacts_with_backend(
                "com.example:lib", 10, ctx, "auto"
            )
        self.assertEqual(out["searchBackend"], "artifactory")
        self.assertEqual(out["results"][0]["latestVersion"], "9.0")

    def test_explicit_override(self):
        # Force artifactory against a nexus-shaped URL — override wins.
        body = {"results": []}
        ctx = _closed_ctx(NEXUS_BASE)
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _json(body))]),
        ) as m:
            out = server.search_artifacts_with_backend(
                "com.example:lib", 5, ctx, "artifactory"
            )
        self.assertEqual(out["searchBackend"], "artifactory")
        self.assertIn("/artifactory/api/search/gavc", m.call_args_list[0].args[0].full_url)

    def test_unavailable_when_closed_without_base(self):
        ctx = server.ResolutionContext(
            "/__no_project__",
            {"dependency": [], "plugin": []},
            False,
            offline=True,
            repository_base=None,
            mirrors=[],
        )
        out = server.search_artifacts_with_backend("lib", 10, ctx, "auto")
        self.assertEqual(out["results"], [])
        self.assertIn("searchBackendUnavailable", out)
        self.assertIn("not available", out["searchBackendUnavailable"])

    def test_unavailable_unknown_manager(self):
        ctx = _closed_ctx("https://repo.corp.example/maven")
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen(
                [
                    urllib.error.URLError("no nexus"),
                    urllib.error.URLError("no artifactory"),
                ]
            ),
        ):
            out = server.search_artifacts_with_backend("lib", 10, ctx, "auto")
        self.assertEqual(out["results"], [])
        self.assertIn("could not detect", out["searchBackendUnavailable"])

    def test_central_override_offline_unavailable(self):
        ctx = _closed_ctx(NEXUS_BASE)
        out = server.search_artifacts_with_backend("lib", 10, ctx, "central")
        self.assertEqual(out["results"], [])
        self.assertIn("offline", out["searchBackendUnavailable"])


class HandleSearchArtifactsBackendTest(unittest.TestCase):
    def test_handler_routes_closed_mode(self):
        body = {
            "items": [
                {"group": "com.example", "name": "lib", "version": "1.0.0"},
            ]
        }
        env = {
            "MAVEN_MCP_OFFLINE": "1",
            "MAVEN_MCP_REPOSITORY_BASE": NEXUS_BASE,
        }
        with unittest.mock.patch.dict("os.environ", env, clear=False):
            with unittest.mock.patch.object(
                server, "discover_repositories", return_value={"dependency": [], "plugin": []}
            ):
                with unittest.mock.patch.object(server, "_load_mirrors", return_value=[]):
                    with unittest.mock.patch(
                        "urllib.request.urlopen",
                        side_effect=mock_urlopen([(200, _json(body))]),
                    ):
                        out = server.handle_search_artifacts({"query": "lib", "limit": 5})
        self.assertEqual(out["searchBackend"], "nexus")
        self.assertEqual(out["results"][0]["groupId"], "com.example")

    def test_handler_repository_type_arg(self):
        body = {"results": []}
        env = {
            "MAVEN_MCP_REPOSITORY_BASE": ARTIFACTORY_BASE,
        }
        with unittest.mock.patch.dict("os.environ", env, clear=False):
            server.os.environ.pop("MAVEN_MCP_OFFLINE", None)
            with unittest.mock.patch.object(
                server, "discover_repositories", return_value={"dependency": [], "plugin": []}
            ):
                with unittest.mock.patch.object(server, "_load_mirrors", return_value=[]):
                    with unittest.mock.patch(
                        "urllib.request.urlopen",
                        side_effect=mock_urlopen([(200, _json(body))]),
                    ) as m:
                        out = server.handle_search_artifacts(
                            {
                                "query": "com.example:lib",
                                "repositoryType": "artifactory",
                            }
                        )
        self.assertEqual(out["searchBackend"], "artifactory")
        self.assertIn("/api/search/gavc", m.call_args_list[0].args[0].full_url)


if __name__ == "__main__":
    unittest.main()

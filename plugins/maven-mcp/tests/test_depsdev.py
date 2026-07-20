"""Tests for deps.dev transitive graphs + conflict detection (#287)."""

import json
import unittest
import unittest.mock
import urllib.error

from _helpers import mock_gradle_resolve, mock_urlopen, server, temp_project, write_fake_gradlew


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


# Diamond: root → A:1.0, root → B:1.0; A → conflict:1.0 (depth 2);
# B → mid → conflict:2.0 (depth 3). Nearest-wins → 1.0; highest-wins → 2.0.
_DIAMOND = _graph(
    [
        _node("com.example:root", "1.0", "SELF"),
        _node("com.example:a", "1.0", "DIRECT"),
        _node("com.example:b", "1.0", "DIRECT"),
        _node("com.example:conflict", "1.0", "INDIRECT"),
        _node("com.example:mid", "1.0", "INDIRECT"),
        _node("com.example:conflict", "2.0", "INDIRECT"),
    ],
    [
        {"fromNode": 0, "toNode": 1, "requirement": "1.0"},
        {"fromNode": 0, "toNode": 2, "requirement": "1.0"},
        {"fromNode": 1, "toNode": 3, "requirement": "1.0"},
        {"fromNode": 2, "toNode": 4, "requirement": "1.0"},
        {"fromNode": 4, "toNode": 5, "requirement": "2.0"},
    ],
)


class TestDepsdevUrlAndParse(unittest.TestCase):
    def test_package_name_and_url_encoding(self):
        url = server._depsdev_dependencies_url(
            "com.google.guava", "guava", "32.1.2-jre"
        )
        self.assertTrue(url.startswith(server.DEPSDEV_API + "/systems/MAVEN/packages/"))
        self.assertIn("com.google.guava%3Aguava", url)
        self.assertIn("32.1.2-jre:dependencies", url)

    def test_split_maven_package_name(self):
        self.assertEqual(
            server._split_maven_package_name("com.example:lib"),
            ("com.example", "lib"),
        )
        self.assertIsNone(server._split_maven_package_name("no-colon"))
        self.assertIsNone(server._split_maven_package_name("a:b:c"))


class TestFetchDepsdevDependencies(unittest.TestCase):
    def test_happy_path_nodes_and_edges(self):
        body = _graph(
            [
                _node("com.example:root", "1.0", "SELF"),
                _node("com.example:lib", "2.0", "DIRECT"),
            ],
            [{"fromNode": 0, "toNode": 1, "requirement": "2.0"}],
        )
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, body)]),
        ):
            out = server.fetch_depsdev_dependencies("com.example", "root", "1.0")
        self.assertTrue(out["ok"])
        self.assertFalse(out["partial"])
        self.assertEqual(len(out["nodes"]), 2)
        self.assertEqual(out["nodes"][1]["groupId"], "com.example")
        self.assertEqual(out["nodes"][1]["artifactId"], "lib")
        self.assertEqual(out["nodes"][1]["version"], "2.0")
        self.assertEqual(out["edges"], [{"from": 0, "to": 1, "requirement": "2.0"}])

    def test_http_404_degrades(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(404, b"")]),
        ):
            out = server.fetch_depsdev_dependencies("com.missing", "x", "1.0")
        self.assertFalse(out["ok"])
        self.assertTrue(out["partial"])
        self.assertIn("404", out["error"] or "")
        self.assertEqual(out["nodes"], [])

    def test_transport_error_degrades(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([urllib.error.URLError("offline")]),
        ):
            out = server.fetch_depsdev_dependencies("com.example", "x", "1.0")
        self.assertFalse(out["ok"])
        self.assertTrue(out["partial"])
        self.assertIn("deps.dev unreachable", out["error"] or "")

    def test_graph_error_marks_partial(self):
        body = _graph(
            [_node("com.example:root", "1.0", "SELF")],
            [],
            error="could not resolve",
        )
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, body)]),
        ):
            out = server.fetch_depsdev_dependencies("com.example", "root", "1.0")
        self.assertTrue(out["ok"])
        self.assertTrue(out["partial"])
        self.assertEqual(out["graphError"], "could not resolve")

    def test_node_cap_truncates(self):
        nodes = [_node("com.example:root", "1.0", "SELF")]
        for i in range(5):
            nodes.append(_node(f"com.example:lib{i}", "1.0", "DIRECT"))
        edges = [
            {"fromNode": 0, "toNode": i, "requirement": "1.0"}
            for i in range(1, 6)
        ]
        body = _graph(nodes, edges)
        with unittest.mock.patch.object(server, "MAX_TRANSITIVE_GRAPH_NODES", 3):
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, body)]),
            ):
                out = server.fetch_depsdev_dependencies("com.example", "root", "1.0")
        self.assertTrue(out["ok"])
        self.assertTrue(out["truncated"])
        self.assertTrue(out["partial"])
        self.assertEqual(len(out["nodes"]), 3)

    def test_uses_http_get_cached(self):
        body = _graph([_node("com.example:root", "1.0", "SELF")], [])
        with unittest.mock.patch.object(
            server, "http_get_cached", return_value=(200, body)
        ) as cached:
            out = server.fetch_depsdev_dependencies("com.example", "root", "1.0")
        self.assertTrue(out["ok"])
        cached.assert_called_once()
        args, _kwargs = cached.call_args
        self.assertEqual(args[1], server.TTL_DEPSDEV)
        self.assertIn("api.deps.dev", args[0])


class TestFetchDepsdevScorecard(unittest.TestCase):
    """OpenSSF Scorecard enrichment for get_dependency_health (#411)."""

    def _scorecard_body(self, overall=8.5, checks=None):
        return json.dumps({
            "projectKey": {"id": "github.com/acme/widget"},
            "description": "an example project",
            "scorecard": {
                "date": "2026-07-06T00:00:00Z",
                "repository": {"name": "github.com/acme/widget", "commit": "abc123"},
                "scorecard": {"version": "v5.5.1", "commit": "def456"},
                "overallScore": overall,
                "checks": checks if checks is not None else [
                    {
                        "name": "Maintained",
                        "documentation": {"shortDescription": "x", "url": "https://x"},
                        "score": 10,
                        "reason": "19 commit(s) in the last 90 days",
                        "details": [],
                    },
                    {
                        "name": "Packaging",
                        "documentation": {"shortDescription": "y", "url": "https://y"},
                        "score": -1,
                        "reason": "packaging workflow not detected",
                        "details": ["Warn: no publishing workflow detected."],
                    },
                ],
                "metadata": [],
            },
        }).encode()

    def test_project_url_encoding_and_lowercase_host(self):
        url = server._depsdev_project_url("Acme", "Widget")
        self.assertTrue(url.startswith(server.DEPSDEV_API + "/projects/"))
        # Single percent-encoded path segment: literal "/" become %2F, and the
        # host stays lowercase "github.com" (deps.dev rejects an uppercase host
        # with HTTP 400 "invalid project key" -- verified live).
        self.assertIn("github.com%2FAcme%2FWidget", url)

    def test_happy_path_extracts_overall_score_and_trimmed_checks(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, self._scorecard_body())]),
        ):
            out = server.fetch_depsdev_scorecard("acme", "widget")
        self.assertTrue(out["ok"])
        sc = out["scorecard"]
        self.assertEqual(sc["overallScore"], 8.5)
        self.assertEqual(sc["date"], "2026-07-06T00:00:00Z")
        self.assertEqual(sc["generatedBy"], "OpenSSF")
        self.assertEqual(len(sc["checks"]), 2)
        self.assertEqual(
            sc["checks"][0],
            {"name": "Maintained", "score": 10, "reason": "19 commit(s) in the last 90 days"},
        )
        # A -1 (not-applicable/not-run) individual check score passes through
        # unfiltered -- only overall shape is trimmed, not the raw values.
        self.assertEqual(sc["checks"][1]["score"], -1)
        # Verbose per-check sub-objects (documentation/details) are dropped.
        self.assertNotIn("documentation", sc["checks"][0])
        self.assertNotIn("details", sc["checks"][0])

    def test_project_not_found_404_yields_no_scorecard(self):
        # Empirically confirmed live against api.deps.dev: an unindexed repo
        # returns a plain-text 404 "project not found" body, not JSON.
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(404, b"project not found")]),
        ):
            out = server.fetch_depsdev_scorecard("nobody", "unknown-repo")
        self.assertFalse(out["ok"])
        self.assertIsNone(out["scorecard"])
        self.assertIn("404", out["error"])

    def test_project_known_but_no_scorecard_field(self):
        # deps.dev knows the project (200) but has not scored it -- a normal
        # outcome, not a failure: ok=True, scorecard=None.
        body = json.dumps({"projectKey": {"id": "github.com/acme/widget"}}).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, body)]),
        ):
            out = server.fetch_depsdev_scorecard("acme", "widget")
        self.assertTrue(out["ok"])
        self.assertIsNone(out["scorecard"])

    def test_transport_error_marks_unreachable(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([urllib.error.URLError("dns")]),
        ):
            out = server.fetch_depsdev_scorecard("acme", "widget")
        self.assertFalse(out["ok"])
        self.assertIsNone(out["scorecard"])
        self.assertEqual(out["capabilityUnavailable"], "unreachable")

    def test_uses_http_get_cached_with_ttl_depsdev(self):
        with unittest.mock.patch.object(
            server, "http_get_cached", return_value=(200, self._scorecard_body())
        ) as cached:
            out = server.fetch_depsdev_scorecard("acme", "widget")
        self.assertTrue(out["ok"])
        cached.assert_called_once()
        args, _kwargs = cached.call_args
        self.assertEqual(args[1], server.TTL_DEPSDEV)
        self.assertIn("api.deps.dev", args[0])


class TestResolveConflictVersion(unittest.TestCase):
    def test_highest_wins(self):
        self.assertEqual(
            server.resolve_conflict_version(
                ["1.0.0", "2.0.0", "1.5.0"], "highest-wins"
            ),
            "2.0.0",
        )

    def test_nearest_wins_prefers_shallower(self):
        self.assertEqual(
            server.resolve_conflict_version(
                ["1.0.0", "2.0.0"],
                "nearest-wins",
                depths_by_version={"1.0.0": 1, "2.0.0": 3},
            ),
            "1.0.0",
        )

    def test_nearest_wins_tie_break_highest(self):
        self.assertEqual(
            server.resolve_conflict_version(
                ["1.0.0", "2.0.0"],
                "nearest-wins",
                depths_by_version={"1.0.0": 2, "2.0.0": 2},
            ),
            "2.0.0",
        )


class TestGetTransitiveGraph(unittest.TestCase):
    def test_handler_shape(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _DIAMOND)]),
        ):
            out = server.handle_get_transitive_graph({
                "groupId": "com.example",
                "artifactId": "root",
                "version": "1.0",
            })
        self.assertEqual(out["groupId"], "com.example")
        self.assertEqual(out["artifactId"], "root")
        self.assertEqual(out["version"], "1.0")
        self.assertTrue(any(
            n["groupId"] == "com.example" and n["artifactId"] == "conflict"
            for n in out["nodes"]
        ))
        self.assertTrue(all("from" in e and "to" in e for e in out["edges"]))
        self.assertNotIn("requirement", out["edges"][0])

    def test_handler_degrades_on_unreachable(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([urllib.error.URLError("down")]),
        ):
            out = server.handle_get_transitive_graph({
                "groupId": "com.example",
                "artifactId": "root",
                "version": "1.0",
            })
        self.assertTrue(out["partial"])
        self.assertIn("error", out)
        self.assertEqual(out["nodes"], [])


class TestDetectDependencyConflicts(unittest.TestCase):
    def _two_root_project(self):
        # Two direct deps whose mocked graphs disagree on com.example:conflict.
        return {
            "pom.xml": """
            <project>
              <modelVersion>4.0.0</modelVersion>
              <groupId>com.example</groupId>
              <artifactId>app</artifactId>
              <version>1.0</version>
              <dependencies>
                <dependency>
                  <groupId>com.example</groupId>
                  <artifactId>left</artifactId>
                  <version>1.0</version>
                </dependency>
                <dependency>
                  <groupId>com.example</groupId>
                  <artifactId>right</artifactId>
                  <version>1.0</version>
                </dependency>
              </dependencies>
            </project>
            """,
        }

    def _left_graph(self) -> bytes:
        return _graph(
            [
                _node("com.example:left", "1.0", "SELF"),
                _node("com.example:conflict", "1.0", "DIRECT"),
            ],
            [{"fromNode": 0, "toNode": 1, "requirement": "1.0"}],
        )

    def _right_graph(self) -> bytes:
        return _graph(
            [
                _node("com.example:right", "1.0", "SELF"),
                _node("com.example:mid", "1.0", "DIRECT"),
                _node("com.example:conflict", "2.0", "INDIRECT"),
            ],
            [
                {"fromNode": 0, "toNode": 1, "requirement": "1.0"},
                {"fromNode": 1, "toNode": 2, "requirement": "2.0"},
            ],
        )

    def test_maven_nearest_wins(self):
        files = self._two_root_project()
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([
                    (200, self._left_graph()),
                    (200, self._right_graph()),
                ]),
            ):
                out = server.handle_detect_dependency_conflicts({
                    "projectPath": root,
                    "buildSystem": "maven",
                })
        self.assertEqual(out["strategy"], "nearest-wins")
        self.assertEqual(out["buildSystem"], "maven")
        conflicts = {
            (c["groupId"], c["artifactId"]): c for c in out["conflicts"]
        }
        self.assertIn(("com.example", "conflict"), conflicts)
        c = conflicts[("com.example", "conflict")]
        self.assertEqual(sorted(c["versions"]), ["1.0", "2.0"])
        # Depth 1 via left vs depth 2 via right → nearest-wins picks 1.0.
        self.assertEqual(c["resolvedTo"], "1.0")
        self.assertEqual(c["risk"], "high")  # resolved != highest
        self.assertTrue(out["notes"])

    def test_gradle_highest_wins(self):
        files = {
            "settings.gradle.kts": 'include(":app")\ninclude(":core")\n',
            "app/build.gradle.kts": 'dependencies { implementation("com.example:conflict:1.0") }',
            "core/build.gradle.kts": 'dependencies { implementation("com.example:conflict:2.0") }',
        }
        with temp_project(files) as root:
            write_fake_gradlew(root)
            resolved = [
                {
                    "groupId": "com.example",
                    "artifactId": "conflict",
                    "version": "1.0",
                    "resolvedBy": "gradle",
                    "usages": [{"module": ":app", "configuration": "releaseRuntimeClasspath"}],
                },
                {
                    "groupId": "com.example",
                    "artifactId": "conflict",
                    "version": "2.0",
                    "resolvedBy": "gradle",
                    "usages": [{"module": ":core", "configuration": "releaseRuntimeClasspath"}],
                },
            ]
            with mock_gradle_resolve(resolved):
                out = server.handle_detect_dependency_conflicts({
                    "projectPath": root,
                    "buildSystem": "gradle",
                })
        self.assertEqual(out["strategy"], "highest-wins")
        self.assertEqual(out["graphsFetched"], 0)
        c = next(
            x for x in out["conflicts"]
            if x["groupId"] == "com.example" and x["artifactId"] == "conflict"
        )
        self.assertEqual(c["resolvedTo"], "2.0")
        self.assertTrue(any("Gradle-resolved" in n for n in out["notes"]))

    def test_partial_when_one_root_fails(self):
        files = self._two_root_project()
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([
                    (200, self._left_graph()),
                    (404, b""),
                ]),
            ):
                out = server.handle_detect_dependency_conflicts({
                    "projectPath": root,
                    "buildSystem": "maven",
                })
        self.assertTrue(out["partial"])
        self.assertEqual(out["graphsFailed"], 1)
        self.assertEqual(out["graphsFetched"], 1)
        self.assertTrue(out["errors"])


class TestEdgeDepthMap(unittest.TestCase):
    def test_bfs_depths(self):
        edges = [
            {"from": 0, "to": 1},
            {"from": 0, "to": 2},
            {"from": 2, "to": 3},
        ]
        depths = server._edge_depth_map(edges, 0)
        self.assertEqual(depths[0], 0)
        self.assertEqual(depths[1], 1)
        self.assertEqual(depths[2], 1)
        self.assertEqual(depths[3], 2)


if __name__ == "__main__":
    unittest.main()

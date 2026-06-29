"""Tool-handler integration tests for the maven-mcp Python server (T-6).

Covers all 10 ``handle_*`` entry points (server.py :1229-:1607) by patching
``urllib.request.urlopen`` with ``mock_urlopen`` and driving the local-scan
handlers through ``temp_project``. Each handler test cites the TypeScript test
it mirrors under ``src/tools/__tests__/``.

Two extra requirements live here:
  * the #263 regression for ``handle_compare_dependency_versions`` — asserts the
    EXACT observable produced by the ``if not latest`` guard (server.py :1299),
    so deleting that guard changes the output, and
  * P3 boundary tests for the dependency-health stat/date helpers
    (``median_days_to_close`` :452, ``_months_since`` :507, ``_parse_iso`` :496,
    ``_summarize_releases`` :523) exercised directly, not only via the handler.
"""

import datetime
import json
import unittest
import unittest.mock

from _helpers import server, mock_urlopen, http_error, temp_project


# --- response builders ------------------------------------------------------

def _meta(versions, last_updated="20240101000000"):
    """maven-metadata.xml bytes; the parser only reads <version>/<lastUpdated>."""
    vers = "".join(f"<version>{v}</version>" for v in versions)
    xml = (
        "<metadata><versioning>"
        f"<lastUpdated>{last_updated}</lastUpdated>"
        f"<versions>{vers}</versions>"
        "</versioning></metadata>"
    )
    return xml.encode("utf-8")


def _json(obj):
    return json.dumps(obj).encode("utf-8")


def _patch_urlopen(responses):
    return unittest.mock.patch("urllib.request.urlopen", side_effect=mock_urlopen(responses))


# --- handle_get_latest_version ----------------------------------------------

class TestGetLatestVersion(unittest.TestCase):
    """mirrors src/tools/__tests__/get-latest-version.test.ts"""

    def test_returns_latest_stable(self):
        with _patch_urlopen([(200, _meta(["1.0.0", "2.0.0"]))]):
            out = server.handle_get_latest_version(
                {"groupId": "com.example", "artifactId": "lib"}
            )
        self.assertEqual(out["latestVersion"], "2.0.0")
        self.assertEqual(out["stability"], "stable")
        self.assertEqual(out["allVersionsCount"], 2)

    def test_no_stable_version_raises(self):
        # STABLE_ONLY over a prerelease-only metadata -> find_latest_version None
        # -> handler raises ValueError (server.py :1235-:1236).
        with _patch_urlopen([(200, _meta(["1.0.0-alpha01"]))]):
            with self.assertRaises(ValueError):
                server.handle_get_latest_version({
                    "groupId": "com.example",
                    "artifactId": "lib",
                    "stabilityFilter": "STABLE_ONLY",
                })


# --- handle_check_version_exists --------------------------------------------

class TestCheckVersionExists(unittest.TestCase):
    """mirrors src/tools/__tests__/check-version-exists.test.ts"""

    def test_version_present(self):
        with _patch_urlopen([(200, _meta(["1.0.0", "1.1.0"]))]):
            out = server.handle_check_version_exists({
                "groupId": "com.example", "artifactId": "lib", "version": "1.1.0",
            })
        self.assertTrue(out["exists"])
        self.assertEqual(out["repository"], "Maven Central")

    def test_version_absent(self):
        with _patch_urlopen([(200, _meta(["1.0.0", "1.1.0"]))]):
            out = server.handle_check_version_exists({
                "groupId": "com.example", "artifactId": "lib", "version": "9.9.9",
            })
        self.assertFalse(out["exists"])
        self.assertNotIn("repository", out)


# --- handle_check_multiple_dependencies -------------------------------------

class TestCheckMultipleDependencies(unittest.TestCase):
    """mirrors src/tools/__tests__/check-multiple-dependencies.test.ts"""

    def test_resolves_latest(self):
        with _patch_urlopen([(200, _meta(["1.0.0", "1.1.0"]))]):
            out = server.handle_check_multiple_dependencies({
                "dependencies": [{"groupId": "com.example", "artifactId": "lib"}],
            })
        self.assertEqual(out["results"][0]["latestVersion"], "1.1.0")

    def test_failed_fetch_records_error(self):
        # First dep resolves, second 404s -> fetch_metadata raises -> error entry.
        responses = [
            (200, _meta(["1.0.0", "1.1.0"])),
            http_error("https://repo.example/x", 404, "Not Found"),
        ]
        with _patch_urlopen(responses):
            out = server.handle_check_multiple_dependencies({
                "dependencies": [
                    {"groupId": "com.example", "artifactId": "good"},
                    {"groupId": "com.example", "artifactId": "bad"},
                ],
            })
        self.assertEqual(out["results"][0]["latestVersion"], "1.1.0")
        self.assertEqual(out["results"][1]["latestVersion"], "")
        self.assertIn("error", out["results"][1])


# --- handle_compare_dependency_versions (+ #263 regression) -----------------

class TestCompareDependencyVersions(unittest.TestCase):
    """mirrors src/tools/__tests__/compare-dependency-versions.test.ts"""

    def test_263_no_match_guard_exact_observables(self):
        # #263 regression. dep[0] is alpha-current with only a STABLE candidate
        # newer: find_latest_version_for_current returns None (no version is as
        # unstable-or-more than alpha), so the `if not latest` guard (server.py
        # :1299) raises "No matching version found". dep[1] resolves normally.
        # Asserting the EXACT error string + upgradeAvailable/latestVersion makes
        # this fail if the guard is removed: without it, get_upgrade_type(current,
        # None) raises a TypeError whose message would replace the error text.
        responses = [
            (200, _meta(["2.0.0"])),            # dep[0] no-match metadata
            (200, _meta(["1.0.0", "1.1.0"])),   # dep[1] sibling metadata
        ]
        with _patch_urlopen(responses):
            out = server.handle_compare_dependency_versions({
                "dependencies": [
                    {"groupId": "com.example", "artifactId": "nomatch",
                     "currentVersion": "1.0.0-alpha01"},
                    {"groupId": "com.example", "artifactId": "sibling",
                     "currentVersion": "1.0.0"},
                ],
            })
        no_match, sibling = out["results"]

        # Exact observables of the guard:
        self.assertEqual(no_match["error"], "No matching version found")
        self.assertIs(no_match["upgradeAvailable"], False)
        self.assertEqual(no_match["latestVersion"], "")

        # Sibling still resolves successfully alongside the failed one:
        self.assertEqual(sibling["latestVersion"], "1.1.0")
        self.assertIs(sibling["upgradeAvailable"], True)
        self.assertEqual(sibling["upgradeType"], "minor")


# --- handle_get_dependency_changes ------------------------------------------

class TestGetDependencyChanges(unittest.TestCase):
    """mirrors src/tools/__tests__/get-dependency-changes.test.ts"""

    def test_happy_path_github_releases(self):
        # fetch_metadata(1) + fetch_pom(1, github SCM) + gh_fetch_releases(1) = 3.
        pom = (
            "<project><scm><url>https://github.com/acme/widget</url></scm>"
            "</project>"
        )
        releases = [{
            "tag_name": "v1.2.0",
            "html_url": "https://github.com/acme/widget/releases/v1.2.0",
            "body": "release notes",
        }]
        responses = [
            (200, _meta(["1.0.0", "1.1.0", "1.2.0"])),
            (200, pom.encode("utf-8")),
            (200, _json(releases)),
        ]
        with _patch_urlopen(responses):
            out = server.handle_get_dependency_changes({
                "groupId": "com.example", "artifactId": "widget",
                "fromVersion": "1.0.0", "toVersion": "1.2.0",
            })
        self.assertEqual(out["repositoryUrl"], "https://github.com/acme/widget")
        by_version = {c["version"]: c for c in out["changes"]}
        self.assertEqual(set(by_version), {"1.1.0", "1.2.0"})
        # v1.2.0 tag normalized to 1.2.0 and matched -> carries releaseUrl/body.
        self.assertEqual(
            by_version["1.2.0"]["releaseUrl"],
            "https://github.com/acme/widget/releases/v1.2.0",
        )

    def test_repository_not_found(self):
        # POM 404 -> no SCM repo; com.example is not io.github/com.github so the
        # guess path yields nothing -> repositoryNotFound (server.py :603-:604).
        responses = [
            (200, _meta(["1.0.0", "1.1.0", "1.2.0"])),
            http_error("https://repo.example/pom", 404, "Not Found"),
        ]
        with _patch_urlopen(responses):
            out = server.handle_get_dependency_changes({
                "groupId": "com.example", "artifactId": "widget",
                "fromVersion": "1.0.0", "toVersion": "1.2.0",
            })
        self.assertIs(out["repositoryNotFound"], True)


# --- handle_scan_project_dependencies ---------------------------------------

class TestScanProjectDependencies(unittest.TestCase):
    """mirrors src/tools/__tests__/scan-project-dependencies.test.ts"""

    def test_maven_pom_scan(self):
        pom = (
            "<project><dependencies><dependency>"
            "<groupId>com.example</groupId>"
            "<artifactId>lib</artifactId>"
            "<version>1.2.3</version>"
            "</dependency></dependencies></project>"
        )
        with temp_project({"pom.xml": pom}) as root:
            out = server.handle_scan_project_dependencies({"projectPath": root})
        self.assertEqual(out["buildSystem"], "maven")
        deps = {(d["groupId"], d["artifactId"]): d for d in out["dependencies"]}
        self.assertIn(("com.example", "lib"), deps)
        self.assertEqual(deps[("com.example", "lib")]["version"], "1.2.3")

    def test_unknown_build_system(self):
        with temp_project({"README.md": "no build files here"}) as root:
            out = server.handle_scan_project_dependencies({"projectPath": root})
        self.assertEqual(out["buildSystem"], "unknown")
        self.assertEqual(out["dependencies"], [])


# --- handle_get_dependency_vulnerabilities ----------------------------------

class TestGetDependencyVulnerabilities(unittest.TestCase):
    """mirrors src/tools/__tests__/get-dependency-vulnerabilities.test.ts"""

    def test_reports_vulnerability(self):
        osv = {"results": [{"vulns": [{
            "id": "GHSA-xxxx",
            "summary": "bad bug",
            "severity": [{"type": "CVSS_V3", "score": "9.8"}],
            "affected": [{"ranges": [{"type": "ECOSYSTEM", "events": [
                {"introduced": "0"}, {"fixed": "1.2.3"},
            ]}]}],
            "references": [{"type": "ADVISORY", "url": "https://advisory/x"}],
        }]}]}
        with _patch_urlopen([(200, _json(osv))]):
            out = server.handle_get_dependency_vulnerabilities({
                "dependencies": [
                    {"groupId": "com.example", "artifactId": "lib", "version": "1.0.0"},
                ],
            })
        result = out["results"][0]
        self.assertEqual(result["vulnerabilityCount"], 1)
        self.assertEqual(result["vulnerabilities"][0]["severity"], "CRITICAL")
        self.assertEqual(result["vulnerabilities"][0]["fixedVersion"], "1.2.3")

    def test_osv_non_200_yields_no_vulns(self):
        with _patch_urlopen([(500, b"")]):
            out = server.handle_get_dependency_vulnerabilities({
                "dependencies": [
                    {"groupId": "com.example", "artifactId": "lib", "version": "1.0.0"},
                ],
            })
        self.assertEqual(out["results"][0]["vulnerabilityCount"], 0)


# --- handle_get_dependency_health -------------------------------------------

class TestGetDependencyHealth(unittest.TestCase):
    """mirrors src/tools/__tests__/get-dependency-health.test.ts"""

    def test_full_github_signals(self):
        # Call sequence (all must be 200 + valid JSON or the chain short-circuits):
        # metadata(1) + pom(1) + gh_fetch_repo(1) + gh_fetch_releases(1)
        # + gh_fetch_issue_stats(3) + gh_fetch_user(1) = 8.
        pom = (
            "<project><scm><url>https://github.com/acme/widget</url></scm>"
            "<licenses><license><name>Apache-2.0</name></license></licenses>"
            "</project>"
        )
        repo = {
            "stargazers_count": 100, "forks_count": 10, "open_issues_count": 5,
            "archived": False,
            "owner": {"login": "acme", "type": "Organization"},
            "pushed_at": "2024-06-01T00:00:00Z",
            "license": {"spdx_id": "Apache-2.0"},
            "created_at": "2020-01-01T00:00:00Z",
        }
        responses = [
            (200, _meta(["1.0.0"])),
            (200, pom.encode("utf-8")),
            (200, _json(repo)),
            (200, _json([])),                       # releases
            (200, _json({"total_count": 5})),       # issues open
            (200, _json({"total_count": 20})),      # issues closed
            (200, _json({"items": []})),            # median items
            (200, _json({"public_repos": 50, "created_at": "2015-01-01T00:00:00Z"})),
        ]
        with _patch_urlopen(responses):
            out = server.handle_get_dependency_health({
                "dependencies": [{"groupId": "com.example", "artifactId": "widget"}],
            })
        result = out["results"][0]
        self.assertEqual(result["repository"]["owner"], "acme")
        self.assertIsNotNone(result["github"])
        self.assertEqual(result["github"]["stars"], 100)
        self.assertEqual(result["github"]["license"], "Apache-2.0")

    def test_no_github_repo_health_error(self):
        # metadata(1) + pom 404 -> None(1); guess fails for com.example -> no repo.
        responses = [
            (200, _meta(["1.0.0"])),
            http_error("https://repo.example/pom", 404, "Not Found"),
        ]
        with _patch_urlopen(responses):
            out = server.handle_get_dependency_health({
                "dependencies": [{"groupId": "com.example", "artifactId": "widget"}],
            })
        result = out["results"][0]
        self.assertIsNone(result["github"])
        self.assertIn("healthError", result)


# --- handle_search_artifacts ------------------------------------------------

class TestSearchArtifacts(unittest.TestCase):
    """mirrors src/tools/__tests__/search-artifacts.test.ts"""

    def test_returns_results(self):
        body = {"response": {"docs": [
            {"g": "com.example", "a": "lib", "latestVersion": "1.0.0", "versionCount": 3},
        ]}}
        with _patch_urlopen([(200, _json(body))]):
            out = server.handle_search_artifacts({"query": "lib"})
        self.assertEqual(out["results"][0]["groupId"], "com.example")
        self.assertEqual(out["results"][0]["latestVersion"], "1.0.0")

    def test_non_200_yields_empty(self):
        with _patch_urlopen([(503, b"")]):
            out = server.handle_search_artifacts({"query": "lib"})
        self.assertEqual(out["results"], [])


# --- handle_audit_project_dependencies --------------------------------------

class TestAuditProjectDependencies(unittest.TestCase):
    """mirrors src/tools/__tests__/audit-project-dependencies.test.ts"""

    def test_maven_audit_with_upgrade(self):
        pom = (
            "<project><dependencies><dependency>"
            "<groupId>com.example</groupId>"
            "<artifactId>lib</artifactId>"
            "<version>1.0.0</version>"
            "</dependency></dependencies></project>"
        )
        # scan (local) -> fetch_metadata(1) -> query_osv_batch POST(1).
        responses = [
            (200, _meta(["1.0.0", "1.1.0"])),
            (200, _json({"results": [{"vulns": []}]})),
        ]
        with temp_project({"pom.xml": pom}) as root:
            with _patch_urlopen(responses):
                out = server.handle_audit_project_dependencies({"projectPath": root})
        self.assertEqual(out["buildSystem"], "maven")
        dep = out["dependencies"][0]
        self.assertEqual(dep["latestVersion"], "1.1.0")
        self.assertEqual(dep["upgradeType"], "minor")
        self.assertGreaterEqual(out["summary"]["upgradeable"], 1)

    def test_empty_project_no_network(self):
        # Unknown build system -> no deps, no network calls (mock would assert if
        # any urlopen happened). Exercises the empty-scan edge of the orchestrator.
        with temp_project({"README.md": "nothing"}) as root:
            with _patch_urlopen([]):
                out = server.handle_audit_project_dependencies({"projectPath": root})
        self.assertEqual(out["buildSystem"], "unknown")
        self.assertEqual(out["dependencies"], [])
        self.assertEqual(out["summary"]["total"], 0)


# --- dependency-health stat/date helpers (P3 boundaries, direct) ------------

class TestDependencyHealthHelpers(unittest.TestCase):
    """P3 edges for the health stat/date helpers, exercised directly.

    ``median_days_to_close`` (server.py :452) is a closure inside
    ``gh_fetch_issue_stats``; "directly" therefore means driving that function
    one level below ``handle_get_dependency_health`` with mocked urlopen, not
    through the handler.
    """

    def test_median_days_to_close_empty_durations(self):
        # gh_fetch_issue_stats issues 3 _gh_get calls: open, closed, median items.
        # Empty items -> empty durations -> median returns None (:471-:472).
        responses = [
            (200, _json({"total_count": 3})),   # open
            (200, _json({"total_count": 2})),   # closed
            (200, _json({"items": []})),        # median items (empty)
        ]
        with _patch_urlopen(responses):
            stats = server.gh_fetch_issue_stats("acme", "widget")
        self.assertIsNone(stats["medianDaysToClose"])

    def test_median_days_to_close_single_element(self):
        # One closed issue 4 days wide -> single-element durations -> odd branch
        # returns that value, rounded to days (:475-:479).
        responses = [
            (200, _json({"total_count": 1})),
            (200, _json({"total_count": 1})),
            (200, _json({"items": [
                {"created_at": "2024-01-01T00:00:00Z",
                 "closed_at": "2024-01-05T00:00:00Z"},
            ]})),
        ]
        with _patch_urlopen(responses):
            stats = server.gh_fetch_issue_stats("acme", "widget")
        self.assertEqual(stats["medianDaysToClose"], 4)

    def test_months_since(self):
        self.assertIsNone(server._months_since(None))  # :508-:509
        # Naive UTC "now" (matches _months_since's internal utcnow baseline)
        # without the deprecated utcnow() call.
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        recent = (now - datetime.timedelta(days=15)).isoformat()
        self.assertEqual(server._months_since(recent), 0)  # int(15/30)
        old = (now - datetime.timedelta(days=400)).isoformat()
        self.assertEqual(server._months_since(old), 13)    # int(400/30)
        # Aware ISO (offset present): :515-:516 strips tzinfo before subtracting.
        aware = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(days=400)).isoformat()
        self.assertTrue(aware.endswith("+00:00"))
        self.assertEqual(server._months_since(aware), 13)

    def test_parse_iso_naive_and_aware(self):
        naive = server._parse_iso("2020-01-02T03:04:05")  # :496
        self.assertEqual((naive.year, naive.month, naive.day), (2020, 1, 2))
        self.assertIsNone(naive.utcoffset())  # naive timestamp -> no offset
        aware = server._parse_iso("2020-01-02T03:04:05Z")  # Z -> +00:00 (:499)
        self.assertEqual(aware.utcoffset(), datetime.timedelta(0))

    def test_summarize_releases(self):
        # Empty -> all-None (:539-:540).
        empty = server._summarize_releases([])
        self.assertEqual(empty, {"last": None, "cadenceDays": None, "count": 0})

        # Single -> last set, cadence None (:542-:543).
        single = server._summarize_releases([{"published_at": "2024-03-21T00:00:00Z"}])
        self.assertEqual(single["count"], 1)
        self.assertEqual(single["last"], "2024-03-21T00:00:00Z")
        self.assertIsNone(single["cadenceDays"])

        # Cadence math: gaps of 10 and 30 days -> even-length median = 20 days.
        # draft/prerelease entries are filtered out before the math (:527).
        releases = [
            {"published_at": "2024-03-21T00:00:00Z"},
            {"published_at": "2024-03-11T00:00:00Z"},   # 10 days before
            {"published_at": "2024-02-10T00:00:00Z"},   # 30 days before 03-11
            {"published_at": "2024-04-01T00:00:00Z", "prerelease": True},
            {"published_at": "2024-04-02T00:00:00Z", "draft": True},
        ]
        summary = server._summarize_releases(releases)
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["last"], "2024-03-21T00:00:00Z")
        self.assertEqual(summary["cadenceDays"], 20)


if __name__ == "__main__":
    unittest.main()

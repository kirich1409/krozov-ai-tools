"""Project-first scoped resolution + cross-repo metadata merge (T-4 / T-5).

These tests are NET-NEW (no retired TS counterpart): they exercise the
project-aware resolution layer added for #310 (custom/private repos) and #311
(cross-repo version merge).

Network is mocked by patching ``urllib.request.urlopen``; build files are written
into a real ``TemporaryDirectory`` (via ``temp_project``) and a
``ResolutionContext`` is built from that path with ``build_resolution_context``,
so the discovery + routing path is exercised end-to-end. Each test is
falsifiable: it asserts which repo URLs reach urlopen (and, for #310, that Maven
Central is ABSENT) or the exact merged version set / raised message.
"""

import os
import unittest
import unittest.mock

from _helpers import server, mock_urlopen, http_error, temp_project


CUSTOM_URL = "https://nexus.example.com/m2"
REPO_A = "https://repo-a.example/m2"
REPO_B = "https://repo-b.example/m2"
PLUGIN_URL = "https://plugins.example.com/m2"


def _meta(versions, last_updated=None):
    """maven-metadata.xml bytes with the given version list (+ optional
    lastUpdated). The parser only reads <version> / <lastUpdated>."""
    vers = "".join(f"<version>{v}</version>" for v in versions)
    lu = f"<lastUpdated>{last_updated}</lastUpdated>" if last_updated else ""
    xml = f"<metadata><versioning>{lu}<versions>{vers}</versions></versioning></metadata>"
    return xml.encode("utf-8")


def _settings(repos_body, container="dependencyResolutionManagement"):
    """A settings.gradle.kts whose <container> declares the given repositories."""
    return "%s { repositories { %s } }" % (container, repos_body)


def _urls(mock):
    return [c.args[0].full_url for c in mock.call_args_list]


# ---------------------------------------------------------------------------
# T-4 — project-first routing & fallback policy
# ---------------------------------------------------------------------------
class TestProjectFirstRouting(unittest.TestCase):
    def test_310_custom_repo_queried_and_central_absent(self):
        # #310: a project declaring a custom maven{url} repo routes there and
        # Maven Central is NEVER queried.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, _meta(["1.0.0"]))])
        ) as m:
            result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["versions"], ["1.0.0"])
        urls = _urls(m)
        self.assertTrue(any(u.startswith(CUSTOM_URL) for u in urls))
        self.assertFalse(any(u.startswith(server.MAVEN_CENTRAL_URL) for u in urls))

    def test_no_regression_mavenCentral_declared_resolves(self):
        # A project declaring mavenCentral() still resolves via Central.
        files = {"settings.gradle.kts": _settings("mavenCentral()")}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _meta(["1.0.0", "2.0.0"]))]),
        ) as m:
            result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["versions"], ["1.0.0", "2.0.0"])
        self.assertTrue(any(u.startswith(server.MAVEN_CENTRAL_URL) for u in _urls(m)))

    def test_no_build_file_falls_back_to_public(self):
        # No build file -> empty scopes -> public fallback (Maven Central).
        with temp_project({"README.md": "no build files"}) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        repos = server._repos_for("com.acme", "lib", ctx)
        self.assertEqual([r["url"] for r in repos], [server.MAVEN_CENTRAL_URL])
        self.assertTrue(all(r["is_public_fallback"] for r in repos))

    def test_google_group_no_declaration_routes_to_google(self):
        # No declaration + a Google-group coordinate -> the Google-Maven prefix
        # heuristic is preserved in the public fallback.
        with temp_project({"README.md": "x"}) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        repos = server._repos_for("androidx.core", "core-ktx", ctx)
        self.assertEqual(repos[0]["url"], server.GOOGLE_MAVEN_URL)
        self.assertTrue(all(r["is_public_fallback"] for r in repos))

    def test_toggle_on_appends_public_despite_declaration(self):
        # MAVEN_MCP_PUBLIC_FALLBACK=on appends the public repos even when the
        # project declares its own. A non-Central custom URL is used so the
        # appended Central is a distinct entry (no dedup collapse).
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch.dict(
                os.environ, {"MAVEN_MCP_PUBLIC_FALLBACK": "on"}
            ):
                ctx = server.build_resolution_context({"projectPath": root})
        repos = server._repos_for("com.acme", "lib", ctx)
        urls = [r["url"] for r in repos]
        self.assertIn(CUSTOM_URL, urls)
        self.assertIn(server.MAVEN_CENTRAL_URL, urls)
        by_url = {r["url"]: r for r in repos}
        self.assertFalse(by_url[CUSTOM_URL]["is_public_fallback"])
        self.assertTrue(by_url[server.MAVEN_CENTRAL_URL]["is_public_fallback"])

    def test_plugin_coord_routes_to_plugin_scope(self):
        # A .gradle.plugin marker coord resolves against the pluginManagement repo.
        files = {"settings.gradle.kts": _settings(
            'maven { url = uri("%s") }' % PLUGIN_URL, container="pluginManagement"
        )}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        repos = server._repos_for("com.acme", "com.acme.gradle.plugin", ctx)
        self.assertEqual([r["url"] for r in repos], [PLUGIN_URL])
        self.assertEqual(repos[0]["scope"], "plugin")
        self.assertFalse(repos[0]["is_public_fallback"])

    def test_library_coord_ignores_plugin_only_repo_and_falls_back(self):
        # A pluginManagement-only project has an EMPTY dependency scope, so a
        # library coord falls back to public rather than using the plugin repo.
        files = {"settings.gradle.kts": _settings(
            'maven { url = uri("%s") }' % PLUGIN_URL, container="pluginManagement"
        )}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        repos = server._repos_for("com.acme", "lib", ctx)
        self.assertEqual([r["url"] for r in repos], [server.MAVEN_CENTRAL_URL])
        self.assertTrue(repos[0]["is_public_fallback"])

    def test_build_file_present_but_scope_empty_falls_back(self):
        # A build file with no repositories block -> empty scope -> public fallback.
        with temp_project({"build.gradle.kts": 'plugins { id("x") }'}) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        repos = server._repos_for("com.acme", "lib", ctx)
        self.assertEqual([r["url"] for r in repos], [server.MAVEN_CENTRAL_URL])
        self.assertTrue(repos[0]["is_public_fallback"])

    def test_maven_local_only_does_not_count_and_falls_back(self):
        # mavenLocal() is recorded with a file:// marker that is NOT HTTP-queryable,
        # so a mavenLocal-only scope still falls back to public.
        files = {"settings.gradle.kts": _settings("mavenLocal()")}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        repos = server._repos_for("com.acme", "lib", ctx)
        self.assertEqual([r["url"] for r in repos], [server.MAVEN_CENTRAL_URL])
        self.assertTrue(repos[0]["is_public_fallback"])


# ---------------------------------------------------------------------------
# T-5 — cross-repo metadata merge (#311), raise-contract preserved
# ---------------------------------------------------------------------------
class TestMetadataMerge(unittest.TestCase):
    def _two_repo_ctx(self):
        body = ('maven { url = uri("%s") }; maven { url = uri("%s") }' % (REPO_A, REPO_B))
        with temp_project({"settings.gradle.kts": _settings(body)}) as root:
            return server.build_resolution_context({"projectPath": root})

    def test_merges_two_repos_latest_is_highest(self):
        # A[1.0,2.0] + B[3.0] -> merged latest 3.0 (#311).
        ctx = self._two_repo_ctx()
        responses = [(200, _meta(["1.0.0", "2.0.0"])), (200, _meta(["3.0.0"]))]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ) as m:
            result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["versions"], ["1.0.0", "2.0.0", "3.0.0"])
        self.assertEqual(result["latest"], "3.0.0")
        self.assertEqual(m.call_count, 2)

    def test_single_repo_versions_and_lastupdated_unchanged(self):
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _meta(["1.0.0", "2.0.0"], "20240101000000"))]),
        ):
            result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["versions"], ["1.0.0", "2.0.0"])
        self.assertEqual(result["lastUpdated"], "20240101000000")

    def test_one_repo_404_other_200_no_raise(self):
        # A 404 + B 200 -> B's versions, no raise.
        ctx = self._two_repo_ctx()
        responses = [http_error(REPO_A, 404, "Not Found"), (200, _meta(["3.0.0"]))]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ) as m:
            result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["versions"], ["3.0.0"])
        self.assertEqual(m.call_count, 2)

    def test_overlapping_versions_deduped(self):
        ctx = self._two_repo_ctx()
        responses = [(200, _meta(["1.0.0", "2.0.0"])), (200, _meta(["2.0.0", "3.0.0"]))]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ):
            result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["versions"], ["1.0.0", "2.0.0", "3.0.0"])

    def test_snapshot_repo_plus_release_repo_release_is_stable(self):
        # A SNAPSHOT-only repo merged with a release repo: `release` is the stable
        # one, never the -SNAPSHOT.
        ctx = self._two_repo_ctx()
        responses = [(200, _meta(["2.0.0-SNAPSHOT"])), (200, _meta(["1.5.0"]))]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ):
            result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["release"], "1.5.0")
        self.assertEqual(result["latest"], "1.5.0")

    def test_merged_lastupdated_is_most_recent(self):
        # Both timestamps use the full yyyyMMddHHmmss form so MAX is unambiguous.
        ctx = self._two_repo_ctx()
        responses = [
            (200, _meta(["1.0.0"], "20240101000000")),
            (200, _meta(["3.0.0"], "20250601000000")),
        ]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ):
            result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["lastUpdated"], "20250601000000")

    def test_all_repos_404_raises_same_message(self):
        # All-404 path -> ValueError with the same message string as legacy code
        # (distinct from #263, which is the all-200-no-newer guard in the handler).
        ctx = self._two_repo_ctx()
        responses = [http_error(REPO_A, 404, "x"), http_error(REPO_B, 404, "x")]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ):
            with self.assertRaises(ValueError) as cm:
                server.fetch_metadata("com.acme", "lib", ctx)
        self.assertTrue(str(cm.exception).startswith("Could not fetch metadata for com.acme:lib"))


# ---------------------------------------------------------------------------
# T-6 — handlers build ctx from projectPath and thread it down
# ---------------------------------------------------------------------------
class TestHandlerThreading(unittest.TestCase):
    def test_check_version_exists_routes_to_declared_repo_only(self):
        # check_version_exists with a custom-repo-only project routes to the
        # declared repo; Maven Central is not queried.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0", "2.0.0"]))]),
            ) as m:
                out = server.handle_check_version_exists({
                    "groupId": "com.acme", "artifactId": "lib", "version": "2.0.0",
                    "projectPath": root,
                })
        self.assertTrue(out["exists"])
        self.assertEqual(out["repository"], CUSTOM_URL)
        self.assertEqual(out["resolvedFrom"]["url"], CUSTOM_URL)
        self.assertIs(out["resolvedFrom"]["viaPublicFallback"], False)
        self.assertFalse(any(u.startswith(server.MAVEN_CENTRAL_URL) for u in _urls(m)))

    def test_get_dependency_health_single_repo_preserves_last_published(self):
        # get_dependency_health single-repo -> lastPublishedToMaven carries the
        # merged metadata's lastUpdated. POM 404 (com.acme is not guessable), so
        # the chain stops after metadata + pom with no further network.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        responses = [
            (200, _meta(["1.0.0"], "20240515000000")),
            http_error(CUSTOM_URL, 404, "Not Found"),  # POM
        ]
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen(responses)
            ):
                out = server.handle_get_dependency_health({
                    "dependencies": [{"groupId": "com.acme", "artifactId": "lib"}],
                    "projectPath": root,
                })
        result = out["results"][0]
        self.assertEqual(result["lastPublishedToMaven"], "20240515000000")


# ---------------------------------------------------------------------------
# T-7 — #317 provenance reporting (resolvedFrom / viaPublicFallback)
# ---------------------------------------------------------------------------
class TestProvenanceReporting(unittest.TestCase):
    def test_public_fallback_answers_reports_via_public_fallback(self):
        # #317 AC: a Central-only coordinate in an internal-repo-only project,
        # with MAVEN_MCP_PUBLIC_FALLBACK=on, must report viaPublicFallback=true
        # (a project-first false-negative made visible) rather than a plain
        # not-found. CUSTOM_URL 404s first; the appended public Central 200s.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        responses = [
            http_error(CUSTOM_URL, 404, "Not Found"),
            (200, _meta(["1.0.0", "2.0.0"])),
        ]
        with temp_project(files) as root:
            with unittest.mock.patch.dict(
                os.environ, {"MAVEN_MCP_PUBLIC_FALLBACK": "on"}
            ), unittest.mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen(responses)
            ):
                out = server.handle_get_latest_version({
                    "groupId": "com.acme", "artifactId": "lib", "projectPath": root,
                })
        self.assertEqual(out["resolvedFrom"]["url"], server.MAVEN_CENTRAL_URL)
        self.assertIs(out["resolvedFrom"]["viaPublicFallback"], True)

    def test_declared_repo_answers_reports_no_public_fallback(self):
        # Normal case: the project's own declared repo answers directly, no
        # fallback involved -> viaPublicFallback=false.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0"]))]),
            ):
                out = server.handle_get_latest_version({
                    "groupId": "com.acme", "artifactId": "lib", "projectPath": root,
                })
        self.assertEqual(out["resolvedFrom"]["url"], CUSTOM_URL)
        self.assertIs(out["resolvedFrom"]["viaPublicFallback"], False)


if __name__ == "__main__":
    unittest.main()

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

import http.client
import json
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
# #320 — repository content / group filtering
# ---------------------------------------------------------------------------
class TestContentGroupFiltering(unittest.TestCase):
    JITPACK_URL = "https://jitpack.io"

    def test_matching_group_includes_the_filtered_repo(self):
        files = {"settings.gradle.kts": _settings(
            'maven { url = uri("%s"); content { includeGroup("com.github.foo") } }' % self.JITPACK_URL
        )}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        repos = server._repos_for("com.github.foo", "somelib", ctx)
        self.assertEqual([r["url"] for r in repos], [self.JITPACK_URL])

    def test_non_matching_group_excludes_the_filtered_repo(self):
        # Core false-availability fix: a repo scoped to com.github.foo must NOT
        # be consulted for an unrelated group, even though it is the only
        # declared repo in scope.
        files = {"settings.gradle.kts": _settings(
            'maven { url = uri("%s"); content { includeGroup("com.github.foo") } }' % self.JITPACK_URL
        )}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        repos = server._repos_for("com.google.guava", "guava", ctx)
        self.assertEqual(repos, [])

    def test_non_matching_group_fetch_metadata_never_queries_filtered_repo(self):
        files = {"settings.gradle.kts": _settings(
            'maven { url = uri("%s"); content { includeGroup("com.github.foo") } }' % self.JITPACK_URL
        )}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        with unittest.mock.patch("urllib.request.urlopen") as m:
            with self.assertRaises(ValueError) as cm:
                server.fetch_metadata("com.google.guava", "guava", ctx)
        m.assert_not_called()
        # The error message must not degrade to the confusing "...: None"
        # (there is no per-repo last_err to fall back on when _repos_for
        # itself returns an empty list) — assert an explicit reason instead.
        self.assertIn("content/group filtering", str(cm.exception))

    def test_include_group_by_regex_matches_prefix_family(self):
        files = {"settings.gradle.kts": _settings(
            r'maven { url = uri("%s"); content { includeGroupByRegex("com\.github\..*") } }'
            % self.JITPACK_URL
        )}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        matching = server._repos_for("com.github.anyuser", "anylib", ctx)
        self.assertEqual([r["url"] for r in matching], [self.JITPACK_URL])
        non_matching = server._repos_for("com.other", "lib", ctx)
        self.assertEqual(non_matching, [])

    def test_include_group_by_regex_kotlin_double_backslash_form_matches(self):
        # Regression for the idiomatic on-disk Kotlin/Groovy form (doubled
        # backslash), matching Gradle's own JitPack docs example end-to-end
        # through _repos_for, not just the parser unit test.
        files = {"settings.gradle.kts": _settings(
            r'maven { url = uri("%s"); content { includeGroupByRegex("com\\.github\\..*") } }'
            % self.JITPACK_URL
        )}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        matching = server._repos_for("com.github.anyuser", "anylib", ctx)
        self.assertEqual([r["url"] for r in matching], [self.JITPACK_URL])

    def test_exclusive_content_shorthand_behaves_like_content_filter(self):
        body = (
            'exclusiveContent {\n'
            '  forRepository { maven { url = uri("%s") } }\n'
            '  filter { includeGroup("com.github.foo") }\n'
            '}' % self.JITPACK_URL
        )
        with temp_project({"settings.gradle.kts": _settings(body)}) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        self.assertEqual(
            [r["url"] for r in server._repos_for("com.github.foo", "lib", ctx)],
            [self.JITPACK_URL],
        )
        self.assertEqual(server._repos_for("com.google.guava", "guava", ctx), [])

    def test_unfiltered_repo_still_included_for_every_group(self):
        # Regression guard: a maven{} repo with no content{} block is queried
        # for every group, unchanged from pre-#320 behavior.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        self.assertEqual(
            [r["url"] for r in server._repos_for("com.acme", "lib", ctx)], [CUSTOM_URL]
        )
        self.assertEqual(
            [r["url"] for r in server._repos_for("com.other", "lib2", ctx)], [CUSTOM_URL]
        )

    def test_multiple_include_group_calls_or_matched(self):
        files = {"settings.gradle.kts": _settings(
            'maven { url = uri("%s"); content { '
            'includeGroup("com.github.foo"); includeGroup("com.github.bar") } }' % self.JITPACK_URL
        )}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
        self.assertEqual(
            [r["url"] for r in server._repos_for("com.github.foo", "lib", ctx)],
            [self.JITPACK_URL],
        )
        self.assertEqual(
            [r["url"] for r in server._repos_for("com.github.bar", "lib", ctx)],
            [self.JITPACK_URL],
        )
        self.assertEqual(server._repos_for("com.github.baz", "lib", ctx), [])

    def test_filtered_out_falls_back_to_public_when_toggle_on(self):
        # ctx.public_fallback ON still appends public entries even when content
        # filtering excludes every declared repo for this group — same opt-in
        # escape hatch as the no-filter case.
        files = {"settings.gradle.kts": _settings(
            'maven { url = uri("%s"); content { includeGroup("com.github.foo") } }' % self.JITPACK_URL
        )}
        with temp_project(files) as root:
            with unittest.mock.patch.dict(os.environ, {"MAVEN_MCP_PUBLIC_FALLBACK": "on"}):
                ctx = server.build_resolution_context({"projectPath": root})
        repos = server._repos_for("com.google.guava", "guava", ctx)
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

    # --- resolvedFrom is wired onto the OTHER handlers touched by #317 --------
    # The two tests above pin viaPublicFallback semantics through
    # get_latest_version; these smoke-tests confirm the field is actually
    # present (and correctly shaped) on every other success path. A
    # custom-repo-only project where that repo answers 200 must surface
    # resolvedFrom={url=CUSTOM_URL, scope="dependency", viaPublicFallback=False}.
    def _assert_declared(self, rf):
        self.assertIsNotNone(rf)
        self.assertEqual(rf["url"], CUSTOM_URL)
        self.assertEqual(rf["scope"], "dependency")
        self.assertIs(rf["viaPublicFallback"], False)

    def test_check_multiple_dependencies_includes_resolved_from(self):
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0", "2.0.0"]))]),
            ):
                out = server.handle_check_multiple_dependencies({
                    "dependencies": [{"groupId": "com.acme", "artifactId": "lib"}],
                    "projectPath": root,
                })
        self._assert_declared(out["results"][0]["resolvedFrom"])

    def test_compare_dependency_versions_includes_resolved_from(self):
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0", "2.0.0"]))]),
            ):
                out = server.handle_compare_dependency_versions({
                    "dependencies": [{
                        "groupId": "com.acme", "artifactId": "lib",
                        "currentVersion": "1.0.0",
                    }],
                    "projectPath": root,
                })
        self._assert_declared(out["results"][0]["resolvedFrom"])

    def test_get_dependency_health_includes_resolved_from(self):
        # resolvedFrom is set right after the metadata fetch, before the POM
        # probe; com.acme is not GitHub-guessable so the chain stops after
        # metadata + POM-404 with no further network.
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
        self._assert_declared(out["results"][0]["resolvedFrom"])

    def test_audit_project_dependencies_includes_resolved_from(self):
        # Gradle project with a declared dependency; vulnerabilities disabled so
        # the only network call is the metadata fetch against the custom repo.
        files = {
            "settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL),
            "build.gradle.kts": 'dependencies { implementation("com.acme:lib:1.0.0") }',
        }
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0", "2.0.0"]))]),
            ):
                out = server.handle_audit_project_dependencies({
                    "projectPath": root, "includeVulnerabilities": False,
                })
        self._assert_declared(out["dependencies"][0]["resolvedFrom"])

    def test_get_dependency_changes_impl_includes_resolved_from(self):
        # Downstream no-versions-in-range still carries resolvedFrom: the repo
        # answered, so provenance is known even though the result is an error.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            ctx = server.build_resolution_context({"projectPath": root})
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0", "2.0.0"]))]),
            ):
                out = server._get_dependency_changes_impl(
                    "com.acme", "lib", "2.0.0", "3.0.0", ctx,
                )
        self.assertIn("error", out)  # no versions in (2.0.0, 3.0.0]
        self._assert_declared(out["resolvedFrom"])

    # --- finding #1 (code-reviewer, /finalize Phase A): the two handlers below
    # used to build their error entry from a single try/except wrapping BOTH
    # fetch_metadata AND downstream selection, so a downstream "no version"
    # error dropped resolvedFrom even though a repo had actually answered. Fixed
    # by capturing resolved_from right after fetch_metadata succeeds and
    # threading it into the except-branch error entry too.
    def test_check_multiple_dependencies_downstream_error_includes_resolved_from(self):
        # The repo answers 200 but with an empty version list, so
        # find_latest_version returns None and the handler raises "No version
        # found" downstream of a successful fetch_metadata.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta([]))]),
            ):
                out = server.handle_check_multiple_dependencies({
                    "dependencies": [{"groupId": "com.acme", "artifactId": "lib"}],
                    "projectPath": root,
                })
        entry = out["results"][0]
        self.assertIn("error", entry)
        self._assert_declared(entry["resolvedFrom"])

    def test_compare_dependency_versions_downstream_error_includes_resolved_from(self):
        # Same shape as above: empty version list -> find_latest_version_for_current
        # returns None -> "No matching version found", downstream of a
        # successful fetch_metadata.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta([]))]),
            ):
                out = server.handle_compare_dependency_versions({
                    "dependencies": [{
                        "groupId": "com.acme", "artifactId": "lib",
                        "currentVersion": "1.0.0",
                    }],
                    "projectPath": root,
                })
        entry = out["results"][0]
        self.assertIn("error", entry)
        self._assert_declared(entry["resolvedFrom"])

    def test_check_multiple_dependencies_fetch_failure_omits_resolved_from(self):
        # Mirror image of the downstream-error test above: when fetch_metadata
        # itself raises (every repo in scope 404s), there is genuinely no
        # provenance to report, so resolvedFrom must be ABSENT from the error
        # entry (not present-as-None).
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([http_error(CUSTOM_URL, 404, "Not Found")]),
            ):
                out = server.handle_check_multiple_dependencies({
                    "dependencies": [{"groupId": "com.acme", "artifactId": "lib"}],
                    "projectPath": root,
                })
        entry = out["results"][0]
        self.assertIn("error", entry)
        self.assertNotIn("resolvedFrom", entry)


# ---------------------------------------------------------------------------
# #284 — relocation detection wired onto handle_get_latest_version /
# handle_check_version_exists. Both handlers now do ONE extra cached POM fetch
# (TTL_POM, 7 days) after resolving the version, on top of the metadata fetch
# they already made — so each test configures a project with a single declared
# repo (no public-fallback append) and exactly two urlopen responses in order:
# metadata, then POM.
# ---------------------------------------------------------------------------
def _pom(relocation_gav=None):
    """A minimal POM, optionally carrying a <distributionManagement><relocation>
    block. ``relocation_gav`` is a dict with any of groupId/artifactId/version."""
    if relocation_gav is None:
        return b"<project><groupId>g</groupId><artifactId>a</artifactId></project>"
    fields = "".join(f"<{k}>{v}</{k}>" for k, v in relocation_gav.items())
    return (
        f"<project><distributionManagement><relocation>{fields}"
        "</relocation></distributionManagement></project>"
    ).encode("utf-8")


class TestRelocationDetection(unittest.TestCase):
    def test_get_latest_version_reports_relocated_to(self):
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        responses = [
            (200, _meta(["1.0.0"])),
            (200, _pom({"groupId": "new.group", "artifactId": "new-artifact", "version": "9.0.0"})),
        ]
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen(responses)
            ):
                out = server.handle_get_latest_version({
                    "groupId": "old.group", "artifactId": "old-artifact", "projectPath": root,
                })
        self.assertEqual(
            out["relocatedTo"],
            {"groupId": "new.group", "artifactId": "new-artifact", "version": "9.0.0"},
        )

    def test_get_latest_version_no_relocation_block_omits_field(self):
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        responses = [(200, _meta(["1.0.0"])), (200, _pom())]
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen(responses)
            ):
                out = server.handle_get_latest_version({
                    "groupId": "com.acme", "artifactId": "lib", "projectPath": root,
                })
        self.assertNotIn("relocatedTo", out)

    def test_check_version_exists_reports_relocated_to(self):
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        responses = [
            (200, _meta(["1.0.0"])),
            (200, _pom({"artifactId": "new-artifact"})),  # partial: groupId/version carry over
        ]
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen(responses)
            ):
                out = server.handle_check_version_exists({
                    "groupId": "old.group", "artifactId": "old-artifact", "version": "1.0.0",
                    "projectPath": root,
                })
        self.assertEqual(
            out["relocatedTo"],
            {"groupId": "old.group", "artifactId": "new-artifact", "version": "1.0.0"},
        )

    def test_check_version_exists_no_relocation_block_omits_field(self):
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL)}
        responses = [(200, _meta(["1.0.0"])), (200, _pom())]
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen(responses)
            ):
                out = server.handle_check_version_exists({
                    "groupId": "com.acme", "artifactId": "lib", "version": "1.0.0",
                    "projectPath": root,
                })
        self.assertTrue(out["exists"])
        self.assertNotIn("relocatedTo", out)


# ---------------------------------------------------------------------------
# Security review (#317 finding 2) — userinfo redaction
# ---------------------------------------------------------------------------
# A hardcoded `url = "https://user:pass@host/repo"` is a discouraged but real
# pattern; repo URLs are captured verbatim from build files (no expansion), so
# without redaction the literal credential would flow into MCP tool-facing
# JSON (resolvedFrom.url, the check_version_exists/verify_coordinates
# "repository" field). _strip_userinfo is applied at the output boundary only
# — the raw, credentialed URL is still what is actually HTTP-fetched.
CREDENTIALED_URL = "https://repouser:repopass@nexus.example.com/m2"
REDACTED_URL = "https://***@nexus.example.com/m2"


class TestUserinfoRedaction(unittest.TestCase):
    def test_strip_userinfo_redacts_credentials(self):
        self.assertEqual(server._strip_userinfo(CREDENTIALED_URL), REDACTED_URL)

    def test_strip_userinfo_no_op_when_no_credentials(self):
        self.assertEqual(server._strip_userinfo(CUSTOM_URL), CUSTOM_URL)

    def test_get_latest_version_resolved_from_url_redacted(self):
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CREDENTIALED_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0"]))]),
            ):
                out = server.handle_get_latest_version({
                    "groupId": "com.acme", "artifactId": "lib", "projectPath": root,
                })
        self.assertEqual(out["resolvedFrom"]["url"], REDACTED_URL)
        self.assertNotIn("repopass", json.dumps(out))

    def test_check_version_exists_repository_field_redacted(self):
        # maven("url")/maven { url = ... } declarations set name == url (see
        # discover_repositories), so the "repository" field carries the same
        # credentialed string and needs the same redaction as resolvedFrom.url.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CREDENTIALED_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0"]))]),
            ):
                out = server.handle_check_version_exists({
                    "groupId": "com.acme", "artifactId": "lib", "version": "1.0.0",
                    "projectPath": root,
                })
        self.assertEqual(out["repository"], REDACTED_URL)
        self.assertEqual(out["resolvedFrom"]["url"], REDACTED_URL)
        self.assertNotIn("repopass", json.dumps(out))

    def test_verify_coordinates_repository_field_redacted(self):
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CREDENTIALED_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0"]))]),
            ):
                out = server.handle_verify_coordinates({
                    "dependencies": [{"groupId": "com.acme", "artifactId": "lib"}],
                    "projectPath": root,
                })
        result = out["results"][0]
        self.assertEqual(result["repository"], REDACTED_URL)
        self.assertNotIn("repopass", json.dumps(out))

    def test_verify_coordinates_transport_exception_with_credentials_does_not_leak_password(self):
        # /finalize Phase D (security-expert, follow-up to the fetch_metadata
        # fix below): _verify_one runs its OWN per-repo probe (not
        # fetch_metadata), with the same urlopen-raises-InvalidURL-on-userinfo-
        # URL hazard. Without an explicit catch it escapes to
        # handle_verify_coordinates's outer `except Exception as e: str(e)` and
        # leaks the password. Must degrade to "unknown" (an ordinary
        # unverifiable-repo outcome), never an error entry with a raw message.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CREDENTIALED_URL)}
        leak = http.client.InvalidURL("nonnumeric port: 'repopass@nexus.example.com'")
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen([leak]),
            ):
                out = server.handle_verify_coordinates({
                    "dependencies": [{"groupId": "com.acme", "artifactId": "lib"}],
                    "projectPath": root,
                })
        result = out["results"][0]
        self.assertEqual(result["existenceStatus"], "unknown")
        self.assertNotIn("repopass", json.dumps(out))

    def test_fetch_metadata_failure_message_does_not_leak_credentials(self):
        # /finalize Phase 0 (cross-file tracer) + advisor finding: fetch_metadata's
        # non-200 last_err embeds entry["name"], which can be the literal
        # credentialed URL (maven("url") declarations set name == url). That
        # message flows into handle_check_multiple_dependencies's "error" field —
        # confirm the credential does not leak there either.
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CREDENTIALED_URL)}
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([http_error(CREDENTIALED_URL, 404, "Not Found")]),
            ):
                out = server.handle_check_multiple_dependencies({
                    "dependencies": [{"groupId": "com.acme", "artifactId": "lib"}],
                    "projectPath": root,
                })
        entry = out["results"][0]
        self.assertIn("error", entry)
        self.assertIn(REDACTED_URL, entry["error"])
        self.assertNotIn("repopass", json.dumps(out))

    def test_strip_userinfo_redacts_on_parse_failure(self):
        # Copilot review finding on #335: urlsplit raises ValueError on a
        # malformed bracketed-IPv6 host, and _strip_userinfo used to fail
        # open (return the input unchanged), which would leak a literal
        # password if such a URL ever reached a tool-facing error message.
        # _strip_userinfo now falls back to a scheme/authority split on this
        # path instead of returning the raw string.
        malformed = "https://user:pass@[::1"
        redacted = server._strip_userinfo(malformed)
        self.assertNotEqual(redacted, malformed)
        self.assertNotIn("pass", redacted)

    def test_strip_userinfo_parse_failure_multi_at_fully_redacted(self):
        # Follow-up Copilot review finding on #335: a first-`@`-only regex
        # (`(://)[^/@]*@`) only strips up to the FIRST `@` in the authority.
        # When the userinfo itself contains an unescaped `@` (e.g. a
        # malformed URL with `pa@ss` as part of the password — exactly the
        # kind of input that triggers this fallback), the remainder after
        # the first `@` (`ss@host/path`) was left in place, still leaking a
        # password fragment. The fix drops everything up to and including
        # the LAST `@` in the authority instead.
        malformed = "https://user:pa@ss@[::1/path"
        redacted = server._strip_userinfo(malformed)
        self.assertEqual(redacted, "https://[::1/path")
        self.assertNotIn("user:pa", redacted)
        self.assertNotIn("ss@", redacted)

    def test_strip_userinfo_parse_failure_no_at_is_passthrough(self):
        # No `@` anywhere in a malformed URL means there is no userinfo to
        # redact — the fallback must return the input unchanged rather than
        # mangling a credential-free malformed URL.
        malformed = "https://[::1"
        self.assertEqual(server._strip_userinfo(malformed), malformed)

    def test_fetch_metadata_transport_exception_with_credentials_does_not_leak_password(self):
        # /finalize Phase C (comment-analyzer + advisor): a userinfo URL
        # (https://user:pass@host) makes urlopen raise http.client.InvalidURL,
        # NOT urllib.error.URLError — it lands in fetch_metadata's generic
        # `except Exception` branch, whose message historically embedded the
        # raw password (e.g. "nonnumeric port: 'repopass@host'"), a shape
        # _strip_userinfo's bare-URL check cannot redact. The fix builds the
        # message from known-safe components (exception type name + the
        # already-redacted repo name) instead of interpolating str(e).
        files = {"settings.gradle.kts": _settings('maven { url = uri("%s") }' % CREDENTIALED_URL)}
        leak = http.client.InvalidURL("nonnumeric port: 'repopass@nexus.example.com'")
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen([leak]),
            ):
                out = server.handle_check_multiple_dependencies({
                    "dependencies": [{"groupId": "com.acme", "artifactId": "lib"}],
                    "projectPath": root,
                })
        entry = out["results"][0]
        self.assertIn("error", entry)
        self.assertIn("InvalidURL", entry["error"])
        self.assertNotIn("repopass", json.dumps(out))


class TestAuditDownstreamErrorResolvedFrom(unittest.TestCase):
    # /finalize Phase 0 (removed-behavior auditor) finding: handle_audit_project_
    # dependencies shares the #317 finding-1 shape (fetch_metadata + downstream
    # selection in one try/except) but wasn't covered by the original fix. An
    # unexpected exception from get_upgrade_type (after a successful fetch) must
    # still carry resolvedFrom in the degraded entry, like the other handlers.
    def test_downstream_exception_after_successful_fetch_preserves_resolved_from(self):
        files = {
            "settings.gradle.kts": _settings('maven { url = uri("%s") }' % CUSTOM_URL),
            "build.gradle.kts": 'dependencies { implementation("com.acme:lib:1.0.0") }',
        }
        with temp_project(files) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0", "2.0.0"]))]),
            ):
                with unittest.mock.patch(
                    "server.get_upgrade_type", side_effect=RuntimeError("boom")
                ):
                    out = server.handle_audit_project_dependencies({
                        "projectPath": root, "includeVulnerabilities": False,
                    })
        entry = out["dependencies"][0]
        self.assertNotIn("latestVersion", entry)  # degraded entry, same as before
        self.assertIsNotNone(entry.get("resolvedFrom"))
        self.assertEqual(entry["resolvedFrom"]["url"], CUSTOM_URL)
        # silent-failure-hunter (/finalize Phase C): the degraded entry used to
        # carry no "error" key at all (bare `except Exception:`), unlike its
        # sibling handlers — fixed alongside the resolvedFrom threading above.
        self.assertEqual(entry.get("error"), "boom")


if __name__ == "__main__":
    unittest.main()

"""Tests for the project repository-discovery layer.

Covers the brace-depth block scanner (`_extract_block` / `_find_block`), the
Gradle/Maven repository parsers, and the scoped `discover_repositories`
orchestrator. Stdlib only; build files are written into real temp directories.
"""

import os
import tempfile
import unittest

from _helpers import server


def _urls(entries):
    return [e["url"] for e in entries]


class TestExtractBlock(unittest.TestCase):
    def test_nested_blocks(self):
        content = 'pluginManagement { repositories { maven("X") } }'
        body = server._extract_block(content, "pluginManagement")
        self.assertIsNotNone(body)
        self.assertIn("repositories", body)
        repos = server._extract_block(body, "repositories")
        self.assertIsNotNone(repos)
        self.assertIn('maven("X")', repos)
        self.assertNotIn("pluginManagement", repos)

    def test_sibling_blocks_extracted_independently(self):
        content = (
            'pluginManagement { repositories { maven("PLUG") } }\n'
            'dependencyResolutionManagement { repositories { maven("DEP") } }'
        )
        plug = server._extract_block(content, "pluginManagement")
        dep = server._extract_block(content, "dependencyResolutionManagement")
        # No over-capture: each body holds only its own marker.
        self.assertIn("PLUG", plug)
        self.assertNotIn("DEP", plug)
        self.assertIn("DEP", dep)
        self.assertNotIn("PLUG", dep)

    def test_brace_inside_quoted_url_does_not_terminate(self):
        content = 'repositories { maven("https://host/path}weird") }'
        body = server._extract_block(content, "repositories")
        self.assertIsNotNone(body)
        # The full call survives; the `}` inside the string was not treated as
        # the block terminator.
        self.assertIn('maven("https://host/path}weird")', body)

    def test_brace_inside_line_comment_ignored(self):
        content = 'repositories { // closing here }\n maven("X") }'
        body = server._extract_block(content, "repositories")
        self.assertIsNotNone(body)
        self.assertIn('maven("X")', body)

    def test_missing_header_returns_falsy(self):
        # Spec allows None or empty for absent header.
        self.assertFalse(server._extract_block("nothing here {}", "buildscript"))

    def test_maven_call_is_not_a_block(self):
        # `maven("url")` is a call, not a `maven { }` block.
        self.assertIsNone(server._find_block('maven("url")', "maven"))

    def test_word_boundary_does_not_match_substring(self):
        # `maven {` must not be found inside `mavenCentral { ... }`.
        self.assertIsNone(server._find_block("mavenCentral { x }", "maven"))


class TestParseGradleRepos(unittest.TestCase):
    def test_shorthands(self):
        body = " mavenCentral()\n google()\n gradlePluginPortal() "
        urls = _urls(server._parse_gradle_repos(body))
        self.assertIn(server.MAVEN_CENTRAL_URL, urls)
        self.assertIn(server.GOOGLE_MAVEN_URL, urls)
        self.assertIn(server.GRADLE_PLUGIN_PORTAL_URL, urls)

    def test_maven_local_marker(self):
        urls = _urls(server._parse_gradle_repos("mavenLocal()"))
        self.assertEqual(len(urls), 1)
        self.assertTrue(urls[0].startswith("file://"), urls[0])

    def test_explicit_maven_call(self):
        urls = _urls(server._parse_gradle_repos('maven("https://a/r")'))
        self.assertEqual(urls, ["https://a/r"])

    def test_explicit_maven_url_named_arg(self):
        urls = _urls(server._parse_gradle_repos('maven(url = "https://b/r")'))
        self.assertEqual(urls, ["https://b/r"])

    def test_maven_block_kotlin_uri(self):
        urls = _urls(server._parse_gradle_repos('maven { url = uri("https://c/r") }'))
        self.assertEqual(urls, ["https://c/r"])

    def test_maven_block_groovy_single_quote(self):
        urls = _urls(server._parse_gradle_repos("maven { url 'https://d/r' }"))
        self.assertEqual(urls, ["https://d/r"])

    def test_maven_block_url_after_credentials(self):
        # The crux: url AFTER a nested credentials{} block. A brace-naive
        # `maven\s*\{[^}]*url` regex would stop at the first `}` and miss it.
        body = 'maven { credentials { username = "u" }; url = uri("https://nexus/r") }'
        urls = _urls(server._parse_gradle_repos(body))
        self.assertEqual(urls, ["https://nexus/r"])

    def test_dedup_by_url(self):
        body = 'mavenCentral()\n maven("https://repo1.maven.org/maven2")'
        urls = _urls(server._parse_gradle_repos(body))
        self.assertEqual(urls.count(server.MAVEN_CENTRAL_URL), 1)

    def test_multiple_maven_blocks(self):
        body = 'maven { url = uri("https://a/r") }\n maven { url = uri("https://b/r") }'
        urls = _urls(server._parse_gradle_repos(body))
        self.assertEqual(urls, ["https://a/r", "https://b/r"])


class TestParseMavenRepos(unittest.TestCase):
    def test_dual_container_separation(self):
        pom = """
        <project>
          <repositories>
            <repository><id>central-mirror</id><url>https://dep/r</url></repository>
          </repositories>
          <pluginRepositories>
            <pluginRepository><id>plug</id><url>https://plug/r</url></pluginRepository>
          </pluginRepositories>
        </project>
        """
        deps, plugins = server._parse_maven_repos(pom)
        self.assertEqual(_urls(deps), ["https://dep/r"])
        self.assertEqual(deps[0]["name"], "central-mirror")
        self.assertEqual(_urls(plugins), ["https://plug/r"])

    def test_url_name_fallback(self):
        pom = "<repositories><repository><url>https://noid/r</url></repository></repositories>"
        deps, _plugins = server._parse_maven_repos(pom)
        self.assertEqual(deps[0]["name"], "https://noid/r")

    def test_empty_pom(self):
        deps, plugins = server._parse_maven_repos("<project></project>")
        self.assertEqual(deps, [])
        self.assertEqual(plugins, [])


class TestParseRepositoriesMode(unittest.TestCase):
    """Tests for server._parse_repositories_mode (#318)."""

    def test_no_declaration_returns_none(self):
        self.assertIsNone(server._parse_repositories_mode('repositories { mavenCentral() }'))

    def test_kotlin_dsl_set_call_qualified(self):
        body = 'repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)'
        self.assertEqual(server._parse_repositories_mode(body), "FAIL_ON_PROJECT_REPOS")

    def test_kotlin_dsl_set_call_bare_enum(self):
        body = 'repositoriesMode.set(PREFER_PROJECT)'
        self.assertEqual(server._parse_repositories_mode(body), "PREFER_PROJECT")

    def test_property_assignment_qualified(self):
        body = 'repositoriesMode = RepositoriesMode.FAIL_ON_PROJECT_REPOS'
        self.assertEqual(server._parse_repositories_mode(body), "FAIL_ON_PROJECT_REPOS")

    def test_property_assignment_bare_enum(self):
        body = 'repositoriesMode = PREFER_PROJECT'
        self.assertEqual(server._parse_repositories_mode(body), "PREFER_PROJECT")


class TestDiscoverRepositories(unittest.TestCase):
    def _discover(self, files):
        with tempfile.TemporaryDirectory() as root:
            for rel, content in files.items():
                with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                    fh.write(content)
            return server.discover_repositories(root)

    def test_2x2_no_leak_settings(self):
        settings = (
            'pluginManagement { repositories { maven("https://X/r") } }\n'
            'dependencyResolutionManagement { repositories { maven("https://Y/r") } }'
        )
        res = self._discover({"settings.gradle": settings})
        plugin_urls = _urls(res["plugin"])
        dep_urls = _urls(res["dependency"])
        self.assertIn("https://X/r", plugin_urls)
        self.assertNotIn("https://X/r", dep_urls)
        self.assertIn("https://Y/r", dep_urls)
        self.assertNotIn("https://Y/r", plugin_urls)

    def test_buildscript_vs_bare_repositories(self):
        build = (
            'buildscript { repositories { maven("https://A/r") } }\n'
            'repositories { maven("https://B/r") }'
        )
        res = self._discover({"build.gradle": build})
        plugin_urls = _urls(res["plugin"])
        dep_urls = _urls(res["dependency"])
        self.assertEqual(plugin_urls, ["https://A/r"])
        self.assertEqual(dep_urls, ["https://B/r"])

    def test_scope_tag_present(self):
        res = self._discover({"build.gradle": 'repositories { mavenCentral() }'})
        self.assertEqual(res["dependency"][0]["scope"], "dependency")

    def test_maven_dual_container(self):
        pom = (
            "<project>"
            "<repositories><repository><url>https://dep/r</url></repository></repositories>"
            "<pluginRepositories><pluginRepository><url>https://plug/r</url>"
            "</pluginRepository></pluginRepositories>"
            "</project>"
        )
        res = self._discover({"pom.xml": pom})
        self.assertEqual(_urls(res["dependency"]), ["https://dep/r"])
        self.assertEqual(_urls(res["plugin"]), ["https://plug/r"])

    def test_empty_dir(self):
        res = self._discover({})
        self.assertEqual(res["dependency"], [])
        self.assertEqual(res["plugin"], [])

    def test_gradle_wins_over_pom(self):
        files = {
            "settings.gradle": 'dependencyResolutionManagement { repositories { maven("https://G/r") } }',
            "pom.xml": "<repositories><repository><url>https://P/r</url></repository></repositories>",
        }
        res = self._discover(files)
        dep_urls = _urls(res["dependency"])
        self.assertIn("https://G/r", dep_urls)
        self.assertNotIn("https://P/r", dep_urls)

    # --- #318: repositoriesMode-aware dependency-scope resolution -----------
    # These replace the old always-union behavior with a mode-aware split.

    def test_mode_unset_prefers_project_repos_over_settings(self):
        # Default PREFER_PROJECT: the root build file's own repositories{}
        # wins outright -- settings repos are NOT unioned in when the project
        # declares its own (this is the #318 over-report this issue fixes).
        files = {
            "settings.gradle.kts": (
                'dependencyResolutionManagement { repositories { maven("https://SETTINGS/r") } }'
            ),
            "build.gradle.kts": 'repositories { maven("https://PROJECT/r") }',
        }
        res = self._discover(files)
        dep_urls = _urls(res["dependency"])
        self.assertEqual(dep_urls, ["https://PROJECT/r"])
        self.assertNotIn("https://SETTINGS/r", dep_urls)

    def test_mode_explicit_prefer_project_same_as_default(self):
        files = {
            "settings.gradle.kts": (
                'dependencyResolutionManagement {\n'
                '  repositoriesMode.set(RepositoriesMode.PREFER_PROJECT)\n'
                '  repositories { maven("https://SETTINGS/r") }\n'
                '}'
            ),
            "build.gradle.kts": 'repositories { maven("https://PROJECT/r") }',
        }
        res = self._discover(files)
        self.assertEqual(_urls(res["dependency"]), ["https://PROJECT/r"])

    def test_mode_fail_on_project_repos_uses_settings_only(self):
        # A real Gradle build would error under this mode if the project also
        # declared its own repositories{} -- so those project repos must be
        # dropped entirely, never merged in.
        files = {
            "settings.gradle.kts": (
                'dependencyResolutionManagement {\n'
                '  repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)\n'
                '  repositories { maven("https://SETTINGS/r") }\n'
                '}'
            ),
            "build.gradle.kts": 'repositories { maven("https://PROJECT/r") }',
        }
        res = self._discover(files)
        dep_urls = _urls(res["dependency"])
        self.assertEqual(dep_urls, ["https://SETTINGS/r"])
        self.assertNotIn("https://PROJECT/r", dep_urls)

    def test_no_project_repos_falls_back_to_settings_regardless_of_mode(self):
        # Regression guard: PREFER_PROJECT with an EMPTY project-level scope
        # must still fall back to settings repos -- unchanged from pre-#318
        # behavior.
        files = {
            "settings.gradle.kts": (
                'dependencyResolutionManagement { repositories { maven("https://SETTINGS/r") } }'
            ),
        }
        res = self._discover(files)
        self.assertEqual(_urls(res["dependency"]), ["https://SETTINGS/r"])

    def test_mode_does_not_affect_plugin_scope(self):
        # pluginManagement/buildscript repos keep unioning across settings +
        # build files exactly as before -- repositoriesMode only governs
        # dependencyResolutionManagement (dependency scope).
        files = {
            "settings.gradle.kts": (
                'dependencyResolutionManagement {\n'
                '  repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)\n'
                '  repositories { maven("https://SETTINGS/r") }\n'
                '}\n'
                'pluginManagement { repositories { maven("https://PLUGIN-SETTINGS/r") } }'
            ),
            "build.gradle.kts": (
                'repositories { maven("https://PROJECT/r") }\n'
                'buildscript { repositories { maven("https://PLUGIN-BUILD/r") } }'
            ),
        }
        res = self._discover(files)
        plugin_urls = _urls(res["plugin"])
        self.assertIn("https://PLUGIN-SETTINGS/r", plugin_urls)
        self.assertIn("https://PLUGIN-BUILD/r", plugin_urls)
        # Dependency scope still mode-aware (FAIL_ON_PROJECT_REPOS -> settings only).
        self.assertEqual(_urls(res["dependency"]), ["https://SETTINGS/r"])


class TestParseMavenParent(unittest.TestCase):
    """Tests for server._parse_maven_parent (#319)."""

    def test_no_parent_returns_none(self):
        self.assertIsNone(server._parse_maven_parent("<project></project>"))

    def test_default_relative_path(self):
        pom = (
            "<project><parent><groupId>g</groupId><artifactId>a</artifactId>"
            "<version>1.0</version></parent></project>"
        )
        parent = server._parse_maven_parent(pom)
        self.assertEqual(parent["relativePath"], "../pom.xml")
        self.assertEqual(parent["groupId"], "g")
        self.assertEqual(parent["artifactId"], "a")
        self.assertEqual(parent["version"], "1.0")

    def test_explicit_relative_path(self):
        pom = (
            "<parent><groupId>g</groupId><artifactId>a</artifactId>"
            "<relativePath>../../parent-pom</relativePath></parent>"
        )
        parent = server._parse_maven_parent(pom)
        self.assertEqual(parent["relativePath"], "../../parent-pom")

    def test_empty_relative_path_disables_local_lookup(self):
        pom = (
            "<parent><groupId>g</groupId><artifactId>a</artifactId>"
            "<relativePath/></parent>"
        )
        parent = server._parse_maven_parent(pom)
        self.assertIsNone(parent["relativePath"])

    def test_missing_artifact_id_returns_none(self):
        self.assertIsNone(server._parse_maven_parent("<parent><groupId>g</groupId></parent>"))


class TestParseMavenActiveProfileRepos(unittest.TestCase):
    """Tests for server._parse_maven_active_profile_repos (#319)."""

    def test_active_by_default_profile_repos_included(self):
        pom = (
            "<project><profiles><profile>"
            "<activation><activeByDefault>true</activeByDefault></activation>"
            "<repositories><repository><url>https://active/r</url></repository></repositories>"
            "</profile></profiles></project>"
        )
        deps, plugins = server._parse_maven_active_profile_repos(pom)
        self.assertEqual(_urls(deps), ["https://active/r"])
        self.assertEqual(plugins, [])

    def test_non_active_profile_repos_excluded(self):
        pom = (
            "<project><profiles><profile>"
            "<activation><activeByDefault>false</activeByDefault></activation>"
            "<repositories><repository><url>https://inactive/r</url></repository></repositories>"
            "</profile></profiles></project>"
        )
        deps, _plugins = server._parse_maven_active_profile_repos(pom)
        self.assertEqual(deps, [])

    def test_profile_without_activation_excluded(self):
        pom = (
            "<project><profiles><profile>"
            "<repositories><repository><url>https://noact/r</url></repository></repositories>"
            "</profile></profiles></project>"
        )
        deps, _plugins = server._parse_maven_active_profile_repos(pom)
        self.assertEqual(deps, [])

    def test_no_profiles_block(self):
        deps, plugins = server._parse_maven_active_profile_repos("<project></project>")
        self.assertEqual(deps, [])
        self.assertEqual(plugins, [])


class TestDiscoverRepositoriesParentAndProfiles(unittest.TestCase):
    """Integration tests for server.discover_repositories' Maven parent-chain
    and active-profile inheritance (#319)."""

    def _write(self, root, rel_path, content):
        full = os.path.join(root, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)

    def test_child_inherits_parent_repos_via_default_relative_path(self):
        with tempfile.TemporaryDirectory() as root:
            parent_pom = (
                "<project><groupId>g</groupId><artifactId>parent</artifactId>"
                "<version>1.0</version>"
                "<repositories><repository><url>https://parent/r</url></repository></repositories>"
                "</project>"
            )
            child_pom = (
                "<project><parent><groupId>g</groupId><artifactId>parent</artifactId>"
                "<version>1.0</version></parent>"
                "<artifactId>child</artifactId></project>"
            )
            self._write(root, "pom.xml", parent_pom)
            self._write(root, "child/pom.xml", child_pom)
            res = server.discover_repositories(os.path.join(root, "child"))
            self.assertIn("https://parent/r", _urls(res["dependency"]))

    def test_two_level_parent_chain_grandparent_only(self):
        with tempfile.TemporaryDirectory() as root:
            grandparent_pom = (
                "<project><groupId>g</groupId><artifactId>grandparent</artifactId>"
                "<version>1.0</version>"
                "<repositories><repository><url>https://grandparent/r</url></repository></repositories>"
                "</project>"
            )
            parent_pom = (
                "<project><parent><groupId>g</groupId><artifactId>grandparent</artifactId>"
                "<version>1.0</version></parent>"
                "<artifactId>parent</artifactId></project>"
            )
            child_pom = (
                "<project><parent><groupId>g</groupId><artifactId>parent</artifactId>"
                "<version>1.0</version></parent>"
                "<artifactId>child</artifactId></project>"
            )
            self._write(root, "pom.xml", grandparent_pom)
            self._write(root, "parent/pom.xml", parent_pom)
            self._write(root, "parent/child/pom.xml", child_pom)
            res = server.discover_repositories(os.path.join(root, "parent", "child"))
            self.assertIn("https://grandparent/r", _urls(res["dependency"]))

    def test_active_by_default_profile_repos_merged(self):
        with tempfile.TemporaryDirectory() as root:
            pom = (
                "<project><groupId>g</groupId><artifactId>a</artifactId><version>1.0</version>"
                "<profiles><profile>"
                "<activation><activeByDefault>true</activeByDefault></activation>"
                "<repositories><repository><url>https://profile/r</url></repository></repositories>"
                "</profile></profiles>"
                "</project>"
            )
            self._write(root, "pom.xml", pom)
            res = server.discover_repositories(root)
            self.assertIn("https://profile/r", _urls(res["dependency"]))

    def test_non_active_profile_repos_not_discovered(self):
        with tempfile.TemporaryDirectory() as root:
            pom = (
                "<project><groupId>g</groupId><artifactId>a</artifactId><version>1.0</version>"
                "<profiles><profile>"
                "<repositories><repository><url>https://profile/r</url></repository></repositories>"
                "</profile></profiles>"
                "</project>"
            )
            self._write(root, "pom.xml", pom)
            res = server.discover_repositories(root)
            self.assertNotIn("https://profile/r", _urls(res["dependency"]))

    def test_parent_not_locally_resolvable_degrades_gracefully(self):
        with tempfile.TemporaryDirectory() as root:
            child_pom = (
                "<project><parent><groupId>external.group</groupId>"
                "<artifactId>external-parent</artifactId><version>2.0</version></parent>"
                "<artifactId>child</artifactId></project>"
            )
            self._write(root, "pom.xml", child_pom)
            res = server.discover_repositories(root)
            self.assertEqual(res["dependency"], [])
            self.assertEqual(res["plugin"], [])

    def test_resolved_parent_coordinate_mismatch_is_rejected(self):
        # A file sits exactly at the default relativePath ("../pom.xml"), but
        # its own coordinate is a different artifact — e.g. an unrelated
        # sibling module's leftover pom.xml. Its repos must NOT be trusted as
        # the declared <parent>'s repos.
        with tempfile.TemporaryDirectory() as root:
            unrelated_pom = (
                "<project><groupId>other.group</groupId><artifactId>unrelated</artifactId>"
                "<version>9.9</version>"
                "<repositories><repository><url>https://unrelated/r</url></repository></repositories>"
                "</project>"
            )
            child_pom = (
                "<project><parent><groupId>g</groupId><artifactId>parent</artifactId>"
                "<version>1.0</version></parent>"
                "<artifactId>child</artifactId></project>"
            )
            self._write(root, "pom.xml", unrelated_pom)
            self._write(root, "child/pom.xml", child_pom)
            res = server.discover_repositories(os.path.join(root, "child"))
            self.assertNotIn("https://unrelated/r", _urls(res["dependency"]))

    def test_cyclic_parent_chain_does_not_infinite_loop(self):
        with tempfile.TemporaryDirectory() as root:
            # a/pom.xml declares b/pom.xml as parent via relativePath, and
            # b/pom.xml declares a/pom.xml as parent right back — a cycle.
            a_pom = (
                "<project><parent><groupId>g</groupId><artifactId>b</artifactId>"
                "<version>1.0</version><relativePath>../b/pom.xml</relativePath></parent>"
                "<groupId>g</groupId><artifactId>a</artifactId><version>1.0</version></project>"
            )
            b_pom = (
                "<project><parent><groupId>g</groupId><artifactId>a</artifactId>"
                "<version>1.0</version><relativePath>../a/pom.xml</relativePath></parent>"
                "<groupId>g</groupId><artifactId>b</artifactId><version>1.0</version></project>"
            )
            self._write(root, "a/pom.xml", a_pom)
            self._write(root, "b/pom.xml", b_pom)
            # Must return promptly (depth-capped), not hang.
            res = server.discover_repositories(os.path.join(root, "a"))
            self.assertEqual(res["dependency"], [])
            self.assertEqual(res["plugin"], [])


if __name__ == "__main__":
    unittest.main()

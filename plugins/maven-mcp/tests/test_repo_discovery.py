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


if __name__ == "__main__":
    unittest.main()

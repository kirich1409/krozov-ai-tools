"""AGP/AndroidX changelog providers + html_to_text (#308).

Mirrors the retired TypeScript suites:
  - src/html/__tests__/to-text.test.ts
  - src/agp/__tests__/url.test.ts
  - src/agp/__tests__/release-notes-parser.test.ts
  - src/androidx/__tests__/url.test.ts
  - src/androidx/__tests__/release-notes-parser.test.ts
  - src/changelog/__tests__/agp-provider.test.ts
  - src/changelog/__tests__/androidx-provider.test.ts
  - src/changelog/__tests__/resolver.test.ts (provider selection)

Network is faked via urllib.request.urlopen (same seam as the rest of the suite).
"""

import json
import unittest
import unittest.mock

from _helpers import server, mock_urlopen, http_error, empty_ctx


def _metadata_xml(versions):
    body = "".join(f"<version>{v}</version>" for v in versions)
    return (
        f"<metadata><versioning><versions>{body}</versions>"
        f"</versioning></metadata>"
    ).encode()


AGP_HTML = """
  <h3 id="fixed-issues-agp-8.5.2" data-text="Android Gradle plugin 8.5.2" tabindex="-1">Android Gradle plugin 8.5.2</h3>
  <p>Fixed critical build issue.</p>
  <h3 id="fixed-issues-agp-8.5.1" data-text="Android Gradle plugin 8.5.1" tabindex="-1">Android Gradle plugin 8.5.1</h3>
  <p>Minor improvements.</p>
  <h3 id="fixed-issues-agp-8.5.0" data-text="Android Gradle plugin 8.5.0" tabindex="-1">Android Gradle plugin 8.5.0</h3>
  <p>Initial release.</p>
"""

ANDROIDX_HTML = """
  <h3 id="1.17.0">Version 1.17.0</h3>
  <p>New features in core 1.17.0.</p>
  <h3 id="1.16.0">Version 1.16.0</h3>
  <p>Bug fixes in core 1.16.0.</p>
"""


# ---------------------------------------------------------------------------
# html_to_text — mirrors html/__tests__/to-text.test.ts
# ---------------------------------------------------------------------------
class HtmlToTextTest(unittest.TestCase):
    def test_strips_html_tags(self):
        self.assertEqual(server.html_to_text("<p>Hello <b>world</b></p>"), "Hello world")

    def test_converts_li_to_bullets(self):
        self.assertEqual(
            server.html_to_text("<ul><li>First</li><li>Second</li></ul>"),
            "- First\n- Second",
        )

    def test_converts_br_to_newline(self):
        self.assertEqual(server.html_to_text("Line 1<br/>Line 2"), "Line 1\nLine 2")

    def test_unescapes_entities(self):
        self.assertEqual(
            server.html_to_text("&lt;T&gt; &amp; &quot;foo&quot;"),
            '<T> & "foo"',
        )

    def test_collapses_multiple_newlines(self):
        self.assertEqual(server.html_to_text("<p>A</p><p>B</p><p>C</p>"), "A\n\nB\n\nC")

    def test_empty_input(self):
        self.assertEqual(server.html_to_text(""), "")

    def test_preserves_escaped_angle_brackets(self):
        self.assertIn("<Fragment>", server.html_to_text("Use &lt;Fragment&gt; here"))


# ---------------------------------------------------------------------------
# AGP URL helpers — mirrors agp/__tests__/url.test.ts
# ---------------------------------------------------------------------------
class AgpUrlTest(unittest.TestCase):
    def test_is_agp_artifact(self):
        self.assertTrue(server.is_agp_artifact("com.android.tools.build"))
        self.assertFalse(server.is_agp_artifact("androidx.core"))
        self.assertFalse(server.is_agp_artifact("com.android.tools"))

    def test_releases_url(self):
        self.assertEqual(
            server.get_agp_releases_url("8.5.1"),
            "https://developer.android.com/build/releases/agp-8-5-0-release-notes",
        )
        self.assertEqual(
            server.get_agp_releases_url("9.1.0-alpha03"),
            "https://developer.android.com/build/releases/agp-9-1-0-release-notes",
        )
        self.assertEqual(
            server.get_agp_releases_url("8.5.0"),
            "https://developer.android.com/build/releases/agp-8-5-0-release-notes",
        )

    def test_version_url_anchor(self):
        self.assertEqual(
            server.get_agp_version_url("8.5.2"),
            "https://developer.android.com/build/releases/"
            "agp-8-5-0-release-notes#fixed-issues-agp-8.5.2",
        )
        self.assertEqual(
            server.get_agp_version_url("9.1.0-rc01"),
            "https://developer.android.com/build/releases/"
            "agp-9-1-0-release-notes#fixed-issues-agp-9.1.0-rc01",
        )


# ---------------------------------------------------------------------------
# AGP parser — mirrors agp/__tests__/release-notes-parser.test.ts
# ---------------------------------------------------------------------------
class AgpParserTest(unittest.TestCase):
    def test_parses_version_sections(self):
        html = """
          <h3 id="fixed-issues-agp-8.5.2" data-text="Android Gradle plugin 8.5.2" tabindex="-1">Android Gradle plugin 8.5.2</h3>
          <p>Bug fixes for 8.5.2.</p>
          <h3 id="fixed-issues-agp-8.5.1" data-text="Android Gradle plugin 8.5.1" tabindex="-1">Android Gradle plugin 8.5.1</h3>
          <p>Bug fixes for 8.5.1.</p>
        """
        result = server.parse_agp_release_notes(html)
        self.assertEqual(set(result), {"8.5.2", "8.5.1"})
        self.assertIn("Bug fixes for 8.5.2", result["8.5.2"])
        self.assertIn("Bug fixes for 8.5.1", result["8.5.1"])

    def test_prerelease_versions(self):
        html = """
          <h3 id="fixed-issues-agp-9.1.0-rc01" data-text="Android Gradle plugin 9.1.0-rc01" tabindex="-1">Android Gradle plugin 9.1.0-rc01</h3>
          <p>Release candidate fixes.</p>
        """
        result = server.parse_agp_release_notes(html)
        self.assertIn("9.1.0-rc01", result)

    def test_strips_html_from_body(self):
        html = """
          <h3 id="fixed-issues-agp-8.5.0" data-text="Android Gradle plugin 8.5.0" tabindex="-1">Android Gradle plugin 8.5.0</h3>
          <p><b>Important:</b> New <code>dslOption</code> added.</p>
          <ul><li>Fixed build issue</li></ul>
        """
        body = server.parse_agp_release_notes(html)["8.5.0"]
        self.assertNotIn("<p>", body)
        self.assertNotIn("<b>", body)
        self.assertIn("dslOption", body)
        self.assertIn("Fixed build issue", body)

    def test_ignores_non_agp_h3(self):
        html = """
          <h3 class="devsite-footer-linkbox-heading no-link">More Android</h3>
          <p>Footer content</p>
          <h3 id="fixed-issues-agp-8.5.0" data-text="Android Gradle plugin 8.5.0" tabindex="-1">Android Gradle plugin 8.5.0</h3>
          <p>Real release notes.</p>
        """
        result = server.parse_agp_release_notes(html)
        self.assertEqual(set(result), {"8.5.0"})

    def test_empty_cases(self):
        self.assertEqual(server.parse_agp_release_notes("<h1>Some Page</h1>"), {})
        self.assertEqual(server.parse_agp_release_notes(""), {})

    def test_section_boundary(self):
        html = """
          <h3 id="fixed-issues-agp-8.5.2" data-text="Android Gradle plugin 8.5.2" tabindex="-1">Android Gradle plugin 8.5.2</h3>
          <p>Notes for 8.5.2</p>
          <h3 id="fixed-issues-agp-8.5.1" data-text="Android Gradle plugin 8.5.1" tabindex="-1">Android Gradle plugin 8.5.1</h3>
          <p>Notes for 8.5.1</p>
        """
        result = server.parse_agp_release_notes(html)
        self.assertNotIn("Notes for 8.5.1", result["8.5.2"])
        self.assertNotIn("Notes for 8.5.2", result["8.5.1"])


# ---------------------------------------------------------------------------
# AndroidX URL helpers — mirrors androidx/__tests__/url.test.ts
# ---------------------------------------------------------------------------
class AndroidXUrlTest(unittest.TestCase):
    def test_is_androidx_artifact(self):
        self.assertTrue(server.is_androidx_artifact("androidx.core"))
        self.assertTrue(server.is_androidx_artifact("androidx.compose.material3"))
        self.assertFalse(server.is_androidx_artifact("io.ktor"))
        self.assertFalse(server.is_androidx_artifact("com.google.android.material"))

    def test_releases_url_slug(self):
        self.assertEqual(
            server.get_androidx_releases_url("androidx.core"),
            "https://developer.android.com/jetpack/androidx/releases/core",
        )
        self.assertEqual(
            server.get_androidx_releases_url("androidx.compose.material3"),
            "https://developer.android.com/jetpack/androidx/releases/compose-material3",
        )
        self.assertEqual(
            server.get_androidx_releases_url("androidx.compose.ui"),
            "https://developer.android.com/jetpack/androidx/releases/compose-ui",
        )
        self.assertEqual(
            server.get_androidx_releases_url("androidx.lifecycle"),
            "https://developer.android.com/jetpack/androidx/releases/lifecycle",
        )

    def test_version_url_anchor(self):
        self.assertEqual(
            server.get_androidx_version_url("androidx.core", "1.17.0"),
            "https://developer.android.com/jetpack/androidx/releases/core#1.17.0",
        )


# ---------------------------------------------------------------------------
# AndroidX parser — mirrors androidx/__tests__/release-notes-parser.test.ts
# ---------------------------------------------------------------------------
class AndroidXParserTest(unittest.TestCase):
    def test_parses_version_sections(self):
        html = """
          <h3 id="1.2.0">Version 1.2.0</h3>
          <p>January 15, 2025</p>
          <p>Bug fixes and improvements.</p>
          <ul><li>Fixed crash on startup</li></ul>
          <h3 id="1.1.0">Version 1.1.0</h3>
          <p>December 01, 2024</p>
          <p>New features added.</p>
        """
        result = server.parse_androidx_release_notes(html)
        self.assertEqual(set(result), {"1.2.0", "1.1.0"})
        self.assertIn("Bug fixes and improvements", result["1.2.0"])
        self.assertIn("Fixed crash on startup", result["1.2.0"])
        self.assertIn("New features added", result["1.1.0"])

    def test_prerelease_and_h2(self):
        html = """
          <h3 id="1.0.0-alpha01">Version 1.0.0-alpha01</h3>
          <p>First alpha release.</p>
          <h2 id="1.5.0">Version 1.5.0</h2>
          <p>Release notes content.</p>
        """
        result = server.parse_androidx_release_notes(html)
        self.assertIn("1.0.0-alpha01", result)
        self.assertIn("1.5.0", result)

    def test_strips_tags_preserves_h4_content(self):
        html = """
          <h3 id="2.0.0">Version 2.0.0</h3>
          <p><code>androidx.core:core:2.0.0</code> is released.</p>
          <h4>Bug Fixes</h4>
          <p>Fixed a crash.</p>
        """
        body = server.parse_androidx_release_notes(html)["2.0.0"]
        self.assertNotIn("<p>", body)
        self.assertNotIn("<code>", body)
        self.assertIn("androidx.core:core:2.0.0", body)
        self.assertIn("Bug Fixes", body)
        self.assertIn("Fixed a crash", body)

    def test_empty_and_boundaries(self):
        self.assertEqual(server.parse_androidx_release_notes(""), {})
        html = """
          <h3 id="2.0.0">Version 2.0.0</h3>
          <p>Second version notes.</p>
          <h3 id="1.0.0">Version 1.0.0</h3>
          <p>First version notes.</p>
        """
        result = server.parse_androidx_release_notes(html)
        self.assertNotIn("First version notes", result["2.0.0"])
        self.assertNotIn("Second version notes", result["1.0.0"])


# ---------------------------------------------------------------------------
# Provider fetch + resolver selection
# ---------------------------------------------------------------------------
class AgpProviderTest(unittest.TestCase):
    def test_fetches_and_parses(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, AGP_HTML.encode())]),
        ):
            result = server._fetch_agp_changelog("8.5.1")
        self.assertIsNotNone(result)
        self.assertIn("agp-8-5-0-release-notes", result["repositoryUrl"])
        self.assertEqual(set(result["entries"]), {"8.5.2", "8.5.1", "8.5.0"})
        self.assertIn("Fixed critical build issue", result["entries"]["8.5.2"]["body"])
        self.assertIn("#fixed-issues-agp-8.5.2", result["entries"]["8.5.2"]["releaseUrl"])

    def test_null_on_http_error_and_empty(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error("https://developer.android.com/x", 500)]),
        ):
            self.assertIsNone(server._fetch_agp_changelog("8.5.0"))
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error("https://developer.android.com/x", 404)]),
        ):
            self.assertIsNone(server._fetch_agp_changelog("99.0.0"))
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"<h1>Empty</h1>")]),
        ):
            self.assertIsNone(server._fetch_agp_changelog("8.5.0"))


class AndroidXProviderTest(unittest.TestCase):
    def test_fetches_and_parses(self):
        html = """
          <h3 id="1.2.0">Version 1.2.0</h3>
          <p>New features.</p>
          <h3 id="1.1.0">Version 1.1.0</h3>
          <p>Bug fixes.</p>
        """
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, html.encode())]),
        ):
            result = server._fetch_androidx_changelog("androidx.core")
        self.assertIsNotNone(result)
        self.assertEqual(
            result["repositoryUrl"],
            "https://developer.android.com/jetpack/androidx/releases/core",
        )
        self.assertEqual(set(result["entries"]), {"1.2.0", "1.1.0"})
        self.assertIn("New features", result["entries"]["1.2.0"]["body"])
        self.assertIn("#1.2.0", result["entries"]["1.2.0"]["releaseUrl"])

    def test_null_on_failure(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error("https://developer.android.com/x", 404)]),
        ):
            self.assertIsNone(server._fetch_androidx_changelog("androidx.core"))
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"<h1>Empty Page</h1>")]),
        ):
            self.assertIsNone(server._fetch_androidx_changelog("androidx.core"))


class ResolveChangelogTest(unittest.TestCase):
    def test_androidx_preferred_over_github(self):
        # AndroidX HTML answers; GitHub must not be consulted.
        responses = [(200, ANDROIDX_HTML.encode())]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ) as m:
            result = server._resolve_changelog(
                "androidx.core", "core", "1.17.0", empty_ctx()
            )
        self.assertIsNotNone(result)
        self.assertIn("androidx/releases/core", result["repositoryUrl"])
        self.assertEqual(len(m.call_args_list), 1)

    def test_agp_preferred_over_github(self):
        responses = [(200, AGP_HTML.encode())]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ) as m:
            result = server._resolve_changelog(
                "com.android.tools.build", "gradle", "8.5.2", empty_ctx()
            )
        self.assertIsNotNone(result)
        self.assertIn("agp-8-5-0-release-notes", result["repositoryUrl"])
        self.assertEqual(len(m.call_args_list), 1)

    def test_androidx_falls_through_to_github_on_docs_miss(self):
        pom = (
            '<?xml version="1.0"?><project><scm>'
            "<url>https://github.com/androidx/androidx</url></scm></project>"
        )
        releases = [{
            "tag_name": "1.17.0",
            "body": "gh notes",
            "html_url": "https://github.com/androidx/androidx/releases/tag/1.17.0",
        }]
        responses = [
            http_error("https://developer.android.com/x", 404),  # androidx docs
            (200, pom.encode()),  # discover_github_repo POM
            (200, json.dumps(releases).encode()),  # gh releases
        ]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ):
            result = server._resolve_changelog(
                "androidx.core", "core", "1.17.0", empty_ctx()
            )
        self.assertEqual(result["repositoryUrl"], "https://github.com/androidx/androidx")
        self.assertEqual(result["entries"]["1.17.0"]["body"], "gh notes")


class DependencyChangesAgpAndroidXTest(unittest.TestCase):
    """End-to-end _get_dependency_changes_impl for AGP/AndroidX (#308)."""

    def test_agp_release_notes(self):
        # AGP routes Google Maven then Central — fetch_metadata queries both.
        meta = _metadata_xml(["8.5.0", "8.5.1", "8.5.2"])
        responses = [
            (200, meta),
            (200, meta),
            (200, AGP_HTML.encode()),
        ]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ):
            result = server._get_dependency_changes_impl(
                "com.android.tools.build",
                "gradle",
                "8.5.0",
                "8.5.2",
                empty_ctx(),
            )
        self.assertNotIn("error", result)
        self.assertNotIn("repositoryNotFound", result)
        self.assertIn("agp-8-5-0-release-notes", result["repositoryUrl"])
        by_version = {c["version"]: c for c in result["changes"]}
        self.assertEqual(set(by_version), {"8.5.1", "8.5.2"})
        self.assertIn("Minor improvements", by_version["8.5.1"]["body"])
        self.assertIn("#fixed-issues-agp-8.5.1", by_version["8.5.1"]["releaseUrl"])
        self.assertIn("Fixed critical build issue", by_version["8.5.2"]["body"])

    def test_androidx_release_notes(self):
        # androidx.* routes Google Maven then Central — fetch_metadata queries both.
        meta = _metadata_xml(["1.15.0", "1.16.0", "1.17.0"])
        responses = [
            (200, meta),
            (200, meta),
            (200, ANDROIDX_HTML.encode()),
        ]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ):
            result = server._get_dependency_changes_impl(
                "androidx.core", "core", "1.15.0", "1.17.0", empty_ctx()
            )
        self.assertNotIn("error", result)
        self.assertEqual(
            result["repositoryUrl"],
            "https://developer.android.com/jetpack/androidx/releases/core",
        )
        by_version = {c["version"]: c for c in result["changes"]}
        self.assertEqual(set(by_version), {"1.16.0", "1.17.0"})
        self.assertIn("Bug fixes in core 1.16.0", by_version["1.16.0"]["body"])
        self.assertIn("#1.16.0", by_version["1.16.0"]["releaseUrl"])
        self.assertIn("New features in core 1.17.0", by_version["1.17.0"]["body"])


if __name__ == "__main__":
    unittest.main()

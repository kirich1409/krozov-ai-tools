"""Maven repository resolution, Maven Central search, and OSV batch tests.

Mirrors the retired TypeScript suite:
  - src/maven/__tests__/repository.test.ts  -> TestReposFor / TestParseMetadataXml
  - src/maven/__tests__/resolver.test.ts    -> TestFetchMetadata
        Resolution is now project-first: `_repos_for(group, artifact, ctx)` returns
        the project-declared repos for the coordinate's scope, or — when none are
        declared (the empty_ctx() used here) — the static public routing. With no
        declared repos these tests assert that public fallback. `fetch_metadata`
        MERGES version sets across every answering repo (#311), so the resolveAll
        cross-repo merge IS now the Python behavior (see
        test_merges_versions_across_repos). It still diverges from TS resolveAll in
        one way: no proxy-target dedup.
  - src/search/__tests__/maven-search.test.ts     -> TestSearchMavenCentral
  - src/vulnerabilities/__tests__/osv-client.test.ts -> TestQueryOsvBatch

Network is mocked by patching urllib.request.urlopen with mock_urlopen([...]);
the list is the sequence of responses across consecutive urlopen calls. Request
shape (URL / POST body / headers) is inspected via the patched mock's
call_args_list, since the server builds a urllib.request.Request per call.
"""

import json
import unittest
import urllib.error
import unittest.mock

from _helpers import server, mock_urlopen, http_error, empty_ctx


def _metadata_xml(versions, latest=None, release=None, last_updated=None):
    """Build a maven-metadata.xml body (bytes) with the given version list."""
    vtags = "".join("<version>%s</version>" % v for v in versions)
    parts = ["<metadata><versioning>"]
    if latest is not None:
        parts.append("<latest>%s</latest>" % latest)
    if release is not None:
        parts.append("<release>%s</release>" % release)
    parts.append("<versions>%s</versions>" % vtags)
    if last_updated is not None:
        parts.append("<lastUpdated>%s</lastUpdated>" % last_updated)
    parts.append("</versioning></metadata>")
    return "".join(parts).encode("utf-8")


# ---------------------------------------------------------------------------
# _repos_for routing + URL builders + XML parse
# Mirrors src/maven/__tests__/repository.test.ts (URL construction, parse,
# well-known repo constants). With an empty_ctx() (no project-declared repos)
# `_repos_for(group, artifact, ctx)` returns the static public routing as rich
# entries {name, url, scope, is_public_fallback}; the AndroidX/Google prefix
# constant lives at server.py:29-32.
# ---------------------------------------------------------------------------
class TestReposFor(unittest.TestCase):
    def test_plain_artifact_uses_central_only(self):
        # A non-Google, non-plugin artifact resolves to Maven Central only.
        repos = server._repos_for("io.ktor", "ktor-server-core", empty_ctx())
        self.assertEqual(
            repos,
            [{"name": "Maven Central", "url": server.MAVEN_CENTRAL_URL,
              "scope": "dependency", "is_public_fallback": True}],
        )

    def test_androidx_routes_google_first_then_central(self):
        # AndroidX prefix routing (server.py:30): Google Maven is tried first,
        # Maven Central second -> most-specific-first.
        repos = server._repos_for("androidx.core", "core-ktx", empty_ctx())
        self.assertEqual(
            [(r["name"], r["url"]) for r in repos],
            [
                ("Google Maven", server.GOOGLE_MAVEN_URL),
                ("Maven Central", server.MAVEN_CENTRAL_URL),
            ],
        )
        self.assertTrue(all(r["is_public_fallback"] for r in repos))
        self.assertTrue(all(r["scope"] == "dependency" for r in repos))

    def test_google_firebase_group_routes_to_google(self):
        # Another entry of the GOOGLE_MAVEN_GROUPS prefix constant (server.py:30);
        # the prefix carries a trailing dot, so the group must be a sub-group.
        repos = server._repos_for(
            "com.google.firebase.crashlytics", "firebase-crashlytics", empty_ctx()
        )
        self.assertEqual(repos[0]["name"], "Google Maven")
        self.assertEqual(repos[0]["url"], server.GOOGLE_MAVEN_URL)
        self.assertEqual(repos[-1]["name"], "Maven Central")

    def test_gradle_plugin_marker_routes_to_plugin_portal_first(self):
        repos = server._repos_for(
            "org.jetbrains.kotlin.jvm", "org.jetbrains.kotlin.jvm.gradle.plugin",
            empty_ctx(),
        )
        self.assertEqual(
            [(r["name"], r["url"]) for r in repos],
            [
                ("Gradle Plugin Portal", server.GRADLE_PLUGIN_PORTAL_URL),
                ("Maven Central", server.MAVEN_CENTRAL_URL),
            ],
        )
        # A .gradle.plugin marker resolves in the plugin scope.
        self.assertTrue(all(r["scope"] == "plugin" for r in repos))

    def test_most_specific_first_ordering_plugin_then_google_then_central(self):
        # Plugin marker AND a Google group: portal, then Google, then Central.
        repos = server._repos_for("androidx.tooling", "x.gradle.plugin", empty_ctx())
        self.assertEqual(
            [r["name"] for r in repos],
            ["Gradle Plugin Portal", "Google Maven", "Maven Central"],
        )

    def test_metadata_url_construction(self):
        # Mirrors repository.test.ts "builds correct metadata URL".
        url = server._metadata_url(
            "https://repo.example.com/maven2", "io.ktor", "ktor-server-core"
        )
        self.assertEqual(
            url,
            "https://repo.example.com/maven2/io/ktor/ktor-server-core/maven-metadata.xml",
        )

    def test_metadata_url_strips_trailing_slash(self):
        # Mirrors repository.test.ts "builds metadata URL with trailing slash".
        url = server._metadata_url(
            "https://repo.example.com/maven2/", "io.ktor", "ktor-server-core"
        )
        self.assertEqual(
            url,
            "https://repo.example.com/maven2/io/ktor/ktor-server-core/maven-metadata.xml",
        )

    def test_pom_url_construction(self):
        url = server._pom_url(
            "https://repo.example.com/maven2", "io.ktor", "ktor-core", "3.1.1"
        )
        self.assertEqual(
            url,
            "https://repo.example.com/maven2/io/ktor/ktor-core/3.1.1/ktor-core-3.1.1.pom",
        )


class TestParseMetadataXml(unittest.TestCase):
    def test_parses_versions_latest_release(self):
        # Mirrors repository.test.ts "parses metadata XML correctly".
        xml = _metadata_xml(
            ["2.0.0", "3.0.0", "3.1.1"], latest="3.1.1", release="3.1.1",
            last_updated="20250301",
        ).decode("utf-8")
        result = server._parse_metadata_xml(xml, "io.ktor", "ktor-server-core")
        self.assertEqual(result["groupId"], "io.ktor")
        self.assertEqual(result["artifactId"], "ktor-server-core")
        self.assertEqual(result["versions"], ["2.0.0", "3.0.0", "3.1.1"])
        self.assertEqual(result["latest"], "3.1.1")
        self.assertEqual(result["release"], "3.1.1")
        self.assertEqual(result["lastUpdated"], "20250301")

    def test_missing_optional_tags_are_none(self):
        result = server._parse_metadata_xml(
            _metadata_xml(["1.0.0"]).decode("utf-8"), "g", "a"
        )
        self.assertEqual(result["versions"], ["1.0.0"])
        self.assertIsNone(result["latest"])
        self.assertIsNone(result["release"])
        self.assertIsNone(result["lastUpdated"])


# ---------------------------------------------------------------------------
# fetch_metadata (server.py)
# fetch_metadata now MERGES version sets across every repo answering 200 (#311);
# the single-repo path is unchanged. The empty_ctx() routes via the public
# fallback, so io.ktor -> Maven Central only and androidx.* -> Google + Central.
# ---------------------------------------------------------------------------
class TestFetchMetadata(unittest.TestCase):
    def test_returns_single_repo_metadata_unchanged(self):
        # Single-repo result is identical to the legacy first-hit path: io.ktor
        # routes to Maven Central only, so the merge of one set = that set.
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _metadata_xml(["1.0.0", "2.0.0"]))]),
        ):
            result = server.fetch_metadata("io.ktor", "ktor-core", empty_ctx())
        self.assertEqual(result["versions"], ["1.0.0", "2.0.0"])

    def test_merges_versions_across_repos(self):
        # #311 fix: fetch_metadata MERGES version sets across repos rather than
        # stopping at the first hit. androidx.* routes Google Maven (#1) then
        # Maven Central (#2). Google returns [1.0.0, 2.0.0]; Central returns
        # [3.0.0]. Both are queried and the union (sorted) is returned.
        responses = [
            (200, _metadata_xml(["1.0.0", "2.0.0"])),  # Google Maven (#1)
            (200, _metadata_xml(["3.0.0"])),           # Maven Central (#2)
        ]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ) as m:
            result = server.fetch_metadata("androidx.core", "core-ktx", empty_ctx())
        self.assertEqual(result["versions"], ["1.0.0", "2.0.0", "3.0.0"])  # merged
        self.assertIn("3.0.0", result["versions"])  # Central's version IS merged
        self.assertEqual(m.call_count, 2)  # both repos queried
        queried = [c.args[0].full_url for c in m.call_args_list]
        self.assertTrue(any(u.startswith(server.GOOGLE_MAVEN_URL) for u in queried))
        self.assertTrue(any(u.startswith(server.MAVEN_CENTRAL_URL) for u in queried))

    def test_skips_non_200_repo_and_merges_the_rest(self):
        # Google Maven 404 -> only Maven Central's 200 contributes to the merge.
        responses = [
            http_error(server.GOOGLE_MAVEN_URL, 404, "Not Found"),
            (200, _metadata_xml(["9.9.9"])),
        ]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ) as m:
            result = server.fetch_metadata("androidx.core", "core-ktx", empty_ctx())
        self.assertEqual(result["versions"], ["9.9.9"])
        self.assertEqual(m.call_count, 2)

    def test_network_error_on_one_repo_is_caught_and_others_merge(self):
        # http_get does NOT catch URLError (only HTTPError) -> it propagates and
        # fetch_metadata's broad `except Exception` swallows it, then continues.
        responses = [
            urllib.error.URLError("dns down"),
            (200, _metadata_xml(["4.5.6"])),
        ]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ):
            result = server.fetch_metadata("androidx.core", "core-ktx", empty_ctx())
        self.assertEqual(result["versions"], ["4.5.6"])

    def test_raises_when_all_repos_fail(self):
        # Mirrors resolver.test.ts "throws when all repos fail".
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error("u", 500, "boom")]),
        ):
            with self.assertRaises(ValueError):
                server.fetch_metadata("io.ktor", "ktor-core", empty_ctx())


# ---------------------------------------------------------------------------
# check_version_in_repos (server.py:170)
# ---------------------------------------------------------------------------
class TestCheckVersionInRepos(unittest.TestCase):
    def test_returns_repo_name_when_version_present(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _metadata_xml(["1.0.0", "2.0.0"]))]),
        ):
            name = server.check_version_in_repos("io.ktor", "ktor-core", "2.0.0", empty_ctx())
        self.assertEqual(name, "Maven Central")

    def test_returns_none_when_version_absent(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _metadata_xml(["1.0.0"]))]),
        ):
            name = server.check_version_in_repos("io.ktor", "ktor-core", "9.9.9", empty_ctx())
        self.assertIsNone(name)

    def test_checks_google_then_central_when_only_central_has_version(self):
        # Unlike fetch_metadata, this iterates ALL repos until the version is
        # found: Google Maven (200, lacks version) -> Maven Central (200, has it).
        responses = [
            (200, _metadata_xml(["1.0.0"])),          # Google Maven, no 2.0.0
            (200, _metadata_xml(["1.0.0", "2.0.0"])),  # Maven Central, has 2.0.0
        ]
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ) as m:
            name = server.check_version_in_repos("androidx.core", "core-ktx", "2.0.0", empty_ctx())
        self.assertEqual(name, "Maven Central")
        self.assertEqual(m.call_count, 2)


# ---------------------------------------------------------------------------
# fetch_pom (server.py:187)
# ---------------------------------------------------------------------------
class TestFetchPom(unittest.TestCase):
    def test_returns_pom_text_on_200(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"<project><scm/></project>")]),
        ) as m:
            pom = server.fetch_pom("io.ktor", "ktor-core", "3.1.1", empty_ctx())
        self.assertEqual(pom, "<project><scm/></project>")
        # POM URL shape includes the version directory and the -version.pom file.
        self.assertTrue(m.call_args_list[0].args[0].full_url.endswith("ktor-core-3.1.1.pom"))

    def test_returns_none_when_no_repo_has_pom(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error("u", 404, "Not Found")]),
        ):
            self.assertIsNone(server.fetch_pom("io.ktor", "ktor-core", "3.1.1", empty_ctx()))


# ---------------------------------------------------------------------------
# _gradle_plugin_marker_plugin_id / resolve_plugin_marker_implementation (#290)
# ---------------------------------------------------------------------------
class TestGradlePluginMarkerPluginId(unittest.TestCase):
    def test_detects_valid_marker(self):
        self.assertEqual(
            server._gradle_plugin_marker_plugin_id(
                "com.example.foo", "com.example.foo.gradle.plugin"
            ),
            "com.example.foo",
        )

    def test_rejects_non_marker_suffix(self):
        self.assertIsNone(
            server._gradle_plugin_marker_plugin_id("io.ktor", "ktor-core")
        )

    def test_rejects_mismatched_group_id(self):
        # Suffix matches but groupId != pluginId — not the actual marker shape.
        self.assertIsNone(
            server._gradle_plugin_marker_plugin_id(
                "com.example.other", "com.example.foo.gradle.plugin"
            )
        )


class TestResolvePluginMarkerImplementation(unittest.TestCase):
    _MARKER_POM = (
        "<project><dependencies><dependency>"
        "<groupId>com.example</groupId>"
        "<artifactId>foo-impl</artifactId>"
        "<version>1.2.3</version>"
        "</dependency></dependencies></project>"
    ).encode()

    def test_resolves_implementation_gav_from_marker_pom(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, self._MARKER_POM)]),
        ):
            result = server.resolve_plugin_marker_implementation(
                "com.example.foo", "com.example.foo.gradle.plugin", "1.0.0", empty_ctx()
            )
        self.assertEqual(
            result, {"groupId": "com.example", "artifactId": "foo-impl", "version": "1.2.3"}
        )

    def test_non_marker_coordinate_makes_zero_network_calls(self):
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([])
        ) as m:
            result = server.resolve_plugin_marker_implementation(
                "io.ktor", "ktor-core", "3.1.1", empty_ctx()
            )
        self.assertIsNone(result)
        self.assertEqual(m.call_count, 0)

    def test_mismatched_group_id_makes_zero_network_calls(self):
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([])
        ) as m:
            result = server.resolve_plugin_marker_implementation(
                "com.example.other", "com.example.foo.gradle.plugin", "1.0.0", empty_ctx()
            )
        self.assertIsNone(result)
        self.assertEqual(m.call_count, 0)

    def test_degrades_gracefully_on_pom_fetch_failure(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error("u", 404, "Not Found")]),
        ):
            result = server.resolve_plugin_marker_implementation(
                "com.example.foo", "com.example.foo.gradle.plugin", "1.0.0", empty_ctx()
            )
        self.assertIsNone(result)

    def test_degrades_gracefully_when_no_dependency_block(self):
        pom = b"<project><groupId>com.example.foo</groupId></project>"
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, pom)])
        ):
            result = server.resolve_plugin_marker_implementation(
                "com.example.foo", "com.example.foo.gradle.plugin", "1.0.0", empty_ctx()
            )
        self.assertIsNone(result)

    def test_degrades_gracefully_on_unresolved_version_property(self):
        pom = (
            "<project><dependencies><dependency>"
            "<groupId>com.example</groupId>"
            "<artifactId>foo-impl</artifactId>"
            "<version>${foo.version}</version>"
            "</dependency></dependencies></project>"
        ).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, pom)])
        ):
            result = server.resolve_plugin_marker_implementation(
                "com.example.foo", "com.example.foo.gradle.plugin", "1.0.0", empty_ctx()
            )
        self.assertIsNone(result)

    def test_returns_none_when_version_missing(self):
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([])
        ) as m:
            result = server.resolve_plugin_marker_implementation(
                "com.example.foo", "com.example.foo.gradle.plugin", None, empty_ctx()
            )
        self.assertIsNone(result)
        self.assertEqual(m.call_count, 0)

    def test_skips_dependency_inside_dependency_management_block(self):
        # A <dependencyManagement> block lists a version pin BEFORE the marker's
        # real <dependency> — the unscoped regex would match the pin first; the
        # scoped lookup must skip past dependencyManagement entirely.
        pom = (
            "<project><dependencyManagement><dependencies><dependency>"
            "<groupId>com.example</groupId>"
            "<artifactId>not-the-impl</artifactId>"
            "<version>9.9.9</version>"
            "</dependency></dependencies></dependencyManagement>"
            "<dependencies><dependency>"
            "<groupId>com.example</groupId>"
            "<artifactId>foo-impl</artifactId>"
            "<version>1.2.3</version>"
            "</dependency></dependencies></project>"
        ).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, pom)])
        ):
            result = server.resolve_plugin_marker_implementation(
                "com.example.foo", "com.example.foo.gradle.plugin", "1.0.0", empty_ctx()
            )
        self.assertEqual(
            result, {"groupId": "com.example", "artifactId": "foo-impl", "version": "1.2.3"}
        )


# ---------------------------------------------------------------------------
# search_maven_central (server.py:731)
# Mirrors src/search/__tests__/maven-search.test.ts
# ---------------------------------------------------------------------------
class TestSearchMavenCentral(unittest.TestCase):
    def test_returns_parsed_results(self):
        # Mirrors maven-search.test.ts "returns parsed search results".
        body = json.dumps({
            "response": {
                "numFound": 2,
                "docs": [
                    {"g": "io.ktor", "a": "ktor-client-core",
                     "latestVersion": "3.1.1", "versionCount": 50},
                    {"g": "io.ktor", "a": "ktor-server-core",
                     "latestVersion": "3.1.1", "versionCount": 48},
                ],
            }
        }).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)])
        ):
            result = server.search_maven_central("ktor")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["groupId"], "io.ktor")
        self.assertEqual(result[0]["artifactId"], "ktor-client-core")
        self.assertEqual(result[0]["latestVersion"], "3.1.1")
        self.assertEqual(result[0]["versionCount"], 50)

    def test_respects_limit_and_url_encodes_query(self):
        # Mirrors maven-search.test.ts "respects limit parameter"; also asserts
        # the query is URL-encoded (a Python-side detail: urllib.parse.quote).
        body = json.dumps({"response": {"numFound": 0, "docs": []}}).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)])
        ) as m:
            server.search_maven_central("g:io ktor", 5)
        url = m.call_args_list[0].args[0].full_url
        self.assertIn("rows=5", url)
        self.assertIn("g%3Aio%20ktor", url)  # ':' and ' ' percent-encoded

    def test_returns_empty_on_http_error(self):
        # Mirrors maven-search.test.ts "returns empty array on error" (500).
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error("u", 500, "boom")]),
        ):
            self.assertEqual(server.search_maven_central("fail"), [])

    def test_returns_empty_when_request_raises(self):
        # Mirrors maven-search.test.ts "returns empty array when fetch rejects".
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([urllib.error.URLError("network error")]),
        ):
            self.assertEqual(server.search_maven_central("network-fail"), [])


# ---------------------------------------------------------------------------
# query_osv_batch (server.py:689) + severity/fixed-version extraction
# Mirrors src/vulnerabilities/__tests__/osv-client.test.ts
# OSV uses http_post_json semantics (POST + JSON body + Content-Type).
# ---------------------------------------------------------------------------
class TestQueryOsvBatch(unittest.TestCase):
    def test_returns_vulnerabilities_for_affected_packages(self):
        # Mirrors osv-client.test.ts "returns vulnerabilities for affected packages".
        body = json.dumps({
            "results": [
                {"vulns": [{
                    "id": "GHSA-1234-abcd",
                    "summary": "Remote code execution",
                    "severity": [{"type": "CVSS_V3",
                                  "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
                    "database_specific": {"severity": "CRITICAL"},
                    "affected": [{"ranges": [{"type": "ECOSYSTEM",
                                  "events": [{"introduced": "0"}, {"fixed": "2.0.1"}]}]}],
                    "references": [{"type": "ADVISORY",
                                   "url": "https://github.com/advisories/GHSA-1234-abcd"}],
                }]},
                {"vulns": []},
            ]
        }).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)])
        ):
            results = server.query_osv_batch([
                {"groupId": "com.example", "artifactId": "lib", "version": "2.0.0"},
                {"groupId": "io.safe", "artifactId": "safe-lib", "version": "1.0.0"},
            ])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(results[0]["vulnerabilities"]), 1)
        v = results[0]["vulnerabilities"][0]
        self.assertEqual(v["id"], "GHSA-1234-abcd")
        self.assertEqual(v["severity"], "CRITICAL")
        self.assertEqual(v["fixedVersion"], "2.0.1")
        self.assertEqual(v["url"], "https://github.com/advisories/GHSA-1234-abcd")
        self.assertEqual(len(results[1]["vulnerabilities"]), 0)

    def test_post_body_shape_and_content_type(self):
        # Mirrors osv-client.test.ts "sends correct request format". Asserts the
        # POST URL, JSON body shape, and Content-Type header (http_post_json).
        body = json.dumps({"results": [{"vulns": []}]}).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)])
        ) as m:
            server.query_osv_batch([
                {"groupId": "io.ktor", "artifactId": "ktor-core", "version": "2.3.0"},
            ])
        req = m.call_args_list[0].args[0]
        self.assertEqual(req.full_url, server.OSV_API)
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        payload = json.loads(req.data)
        self.assertEqual(payload["queries"][0]["package"]["name"], "io.ktor:ktor-core")
        self.assertEqual(payload["queries"][0]["package"]["ecosystem"], "Maven")
        self.assertEqual(payload["queries"][0]["version"], "2.3.0")

    def test_empty_deps_short_circuits_without_request(self):
        # No deps -> [] and no network call at all (server.py:691).
        with unittest.mock.patch("urllib.request.urlopen") as m:
            self.assertEqual(server.query_osv_batch([]), [])
        m.assert_not_called()

    def test_empty_vulnerabilities_on_api_error(self):
        # Mirrors osv-client.test.ts "returns empty vulnerabilities on API error".
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error("u", 500, "boom")]),
        ):
            results = server.query_osv_batch([
                {"groupId": "com.example", "artifactId": "lib", "version": "1.0.0"},
            ])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["vulnerabilities"], [])

    def test_normalizes_moderate_severity_to_medium(self):
        # Mirrors osv-client.test.ts "normalizes MODERATE severity to MEDIUM".
        body = json.dumps({"results": [{"vulns": [{
            "id": "GHSA-mod-erat-eeee", "summary": "moderate",
            "database_specific": {"severity": "MODERATE"},
            "affected": [], "references": [],
        }]}]}).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)])
        ):
            results = server.query_osv_batch([
                {"groupId": "com.example", "artifactId": "lib", "version": "1.0.0"},
            ])
        self.assertEqual(results[0]["vulnerabilities"][0]["severity"], "MEDIUM")

    def test_rejects_unknown_severity_string(self):
        # Mirrors osv-client.test.ts "rejects unknown severity strings".
        # In Python an unrecognized database_specific severity falls through to
        # the CVSS array (none here) -> the "severity" key is omitted entirely.
        body = json.dumps({"results": [{"vulns": [{
            "id": "GHSA-unkn-own1", "summary": "unknown",
            "database_specific": {"severity": "BOGUS"},
            "affected": [], "references": [],
        }]}]}).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)])
        ):
            results = server.query_osv_batch([
                {"groupId": "com.example", "artifactId": "lib", "version": "1.0.0"},
            ])
        self.assertNotIn("severity", results[0]["vulnerabilities"][0])

    def test_cvss_numeric_score_maps_to_severity_bucket(self):
        # CVSS fallback path: no database_specific, severity=[{CVSS_V3, score}].
        # _extract_severity does float(score) -> _cvss_to_severity. NOTE: real
        # OSV puts a CVSS *vector string* in `score`, which float() cannot parse,
        # so this numeric-score branch only fires on numeric data -- exercised
        # here directly to cover _cvss_to_severity (9.8 -> CRITICAL).
        body = json.dumps({"results": [{"vulns": [{
            "id": "GHSA-cvss-only0", "summary": "cvss only",
            "severity": [{"type": "CVSS_V3", "score": "9.8"}],
            "affected": [], "references": [],
        }]}]}).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)])
        ):
            results = server.query_osv_batch([
                {"groupId": "com.example", "artifactId": "lib", "version": "1.0.0"},
            ])
        self.assertEqual(results[0]["vulnerabilities"][0]["severity"], "CRITICAL")

    def test_filters_out_withdrawn_vulnerabilities(self):
        # Mirrors osv-client.test.ts "filters out withdrawn vulnerabilities".
        body = json.dumps({"results": [{"vulns": [
            {"id": "GHSA-active-active", "summary": "active",
             "database_specific": {"severity": "HIGH"}, "affected": [], "references": []},
            {"id": "GHSA-with-drawn", "summary": "withdrawn",
             "database_specific": {"severity": "CRITICAL"},
             "withdrawn": "2024-01-01T00:00:00Z", "affected": [], "references": []},
        ]}]}).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)])
        ):
            results = server.query_osv_batch([
                {"groupId": "com.example", "artifactId": "lib", "version": "1.0.0"},
            ])
        self.assertEqual(len(results[0]["vulnerabilities"]), 1)
        self.assertEqual(results[0]["vulnerabilities"][0]["id"], "GHSA-active-active")

    def test_advisory_url_fallback_to_osv_dev(self):
        # No ADVISORY reference -> _extract_url falls back to the osv.dev URL.
        body = json.dumps({"results": [{"vulns": [{
            "id": "OSV-NO-ADVISORY", "summary": "no advisory ref",
            "database_specific": {"severity": "LOW"}, "affected": [], "references": [],
        }]}]}).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)])
        ):
            results = server.query_osv_batch([
                {"groupId": "com.example", "artifactId": "lib", "version": "1.0.0"},
            ])
        self.assertEqual(
            results[0]["vulnerabilities"][0]["url"],
            "https://osv.dev/vulnerability/OSV-NO-ADVISORY",
        )


if __name__ == "__main__":
    unittest.main()

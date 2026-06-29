"""Tests for the ``verify_coordinates`` MCP tool (server.handle_verify_coordinates).

Every case passes an EMPTY-tempdir ``projectPath`` so repository resolution is
deterministic: an empty project declares no repositories, so resolution falls
back to the static public routing — a single repo (Maven Central) for an
ordinary coordinate, and Google Maven + Maven Central for a Google-group
coordinate. Each case ENUMERATES the urlopen call sequence: the per-repo
existence probe(s) first, then (only on an absent coordinate) the search call.
Suggestion-ranking cases patch ``search_maven_central`` directly to control
candidate ``versionCount`` and the similarity-driving strings precisely.
"""

import json
import unittest
import urllib.error
from unittest import mock

from _helpers import server, mock_urlopen, http_error, temp_project


def _meta(versions):
    """A (200, bytes) maven-metadata.xml response carrying ``versions``."""
    body = (
        "<metadata><versioning><versions>"
        + "".join(f"<version>{v}</version>" for v in versions)
        + "</versions></versioning></metadata>"
    ).encode()
    return (200, body)


def _solr(docs):
    """A (200, bytes) Solr search response. ``docs`` is a list of
    ``(groupId, artifactId, versionCount)`` tuples."""
    payload = {
        "response": {
            "docs": [
                {"g": g, "a": a, "latestVersion": "", "versionCount": vc}
                for (g, a, vc) in docs
            ]
        }
    }
    return (200, json.dumps(payload).encode())


def _patch_urlopen(sequence):
    return mock.patch("urllib.request.urlopen", side_effect=mock_urlopen(sequence))


class ExistenceTriStateTest(unittest.TestCase):
    def test_real_ga_exists(self):
        # One repo (Central) answers 200 -> exists, gaExists, repository recorded.
        with temp_project({}) as root, _patch_urlopen([_meta(["1.0", "2.0"])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "lib"}],
                "projectPath": root,
            })
        item = out["results"][0]
        self.assertEqual(item["existenceStatus"], "exists")
        self.assertTrue(item["gaExists"])
        self.assertEqual(item["repository"], "Maven Central")
        self.assertFalse(item["likelyHallucination"])
        self.assertEqual(item["stability"], "stable")
        self.assertNotIn("gavExists", item)
        self.assertNotIn("suggestions", item)

    def test_real_gav_exists(self):
        with temp_project({}) as root, _patch_urlopen([_meta(["1.0", "2.0"])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "lib", "version": "2.0"}],
                "projectPath": root,
            })
        item = out["results"][0]
        self.assertEqual(item["existenceStatus"], "exists")
        self.assertTrue(item["gavExists"])
        self.assertEqual(item["version"], "2.0")

    def test_multi_repo_union_gav_from_second_repo(self):
        # androidx.* resolves to [Google Maven, Maven Central]. The target version
        # lives ONLY in the 2nd answering repo -> gavExists true via the union.
        # repository is the FIRST answering repo (Google Maven).
        with temp_project({}) as root, _patch_urlopen([
            _meta(["1.0.0"]),            # Google Maven: no target
            _meta(["1.5.0", "1.6.0"]),  # Maven Central: holds target
        ]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "androidx.core", "artifactId": "core", "version": "1.5.0"}],
                "projectPath": root,
            })
        item = out["results"][0]
        self.assertEqual(item["existenceStatus"], "exists")
        self.assertTrue(item["gavExists"])
        self.assertEqual(item["repository"], "Google Maven")

    def test_all_404_absent(self):
        url = server._metadata_url(server.MAVEN_CENTRAL_URL, "com.x", "ghost")
        with temp_project({}) as root, \
                mock.patch.object(server, "search_maven_central", return_value=[]), \
                _patch_urlopen([http_error(url, 404)]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "ghost"}],
                "projectPath": root,
            })
        item = out["results"][0]
        self.assertEqual(item["existenceStatus"], "absent")
        self.assertFalse(item["gaExists"])
        self.assertFalse(item["likelyHallucination"])
        self.assertEqual(item["suggestions"], [])

    def _assert_unknown(self, sequence, coord):
        with temp_project({}) as root, _patch_urlopen(sequence):
            out = server.handle_verify_coordinates({
                "dependencies": [coord],
                "projectPath": root,
            })
        item = out["results"][0]
        self.assertEqual(item["existenceStatus"], "unknown")
        self.assertFalse(item["gaExists"])
        self.assertFalse(item["likelyHallucination"])
        self.assertNotIn("suggestions", item)
        return item

    def test_403_unknown(self):
        url = server._metadata_url(server.MAVEN_CENTRAL_URL, "com.x", "lib")
        self._assert_unknown([http_error(url, 403)], {"groupId": "com.x", "artifactId": "lib"})

    def test_429_unknown(self):
        url = server._metadata_url(server.MAVEN_CENTRAL_URL, "com.x", "lib")
        self._assert_unknown([http_error(url, 429)], {"groupId": "com.x", "artifactId": "lib"})

    def test_503_unknown(self):
        url = server._metadata_url(server.MAVEN_CENTRAL_URL, "com.x", "lib")
        self._assert_unknown([http_error(url, 503)], {"groupId": "com.x", "artifactId": "lib"})

    def test_mixed_404_and_503_unknown(self):
        # Google-group coord -> 2 repos. 404 from one + 503 from the other is a
        # mix: NOT every repo returned 404, so existence is unknown, not absent.
        g_url = server._metadata_url(server.GOOGLE_MAVEN_URL, "androidx.core", "core")
        c_url = server._metadata_url(server.MAVEN_CENTRAL_URL, "androidx.core", "core")
        self._assert_unknown(
            [http_error(g_url, 404), http_error(c_url, 503)],
            {"groupId": "androidx.core", "artifactId": "core"},
        )

    def test_transport_error_unknown(self):
        # A raised transport error (offline) must read as unknown, never absent.
        self._assert_unknown(
            [urllib.error.URLError("offline")],
            {"groupId": "com.x", "artifactId": "lib"},
        )

    def test_empty_versions_200_exists_no_stability(self):
        # A 200 with an empty <versions> still counts as reachable -> exists, but
        # latest is None so stability is omitted and nothing crashes.
        with temp_project({}) as root, _patch_urlopen([_meta([])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "lib"}],
                "projectPath": root,
            })
        item = out["results"][0]
        self.assertEqual(item["existenceStatus"], "exists")
        self.assertTrue(item["gaExists"])
        self.assertNotIn("stability", item)


class SuggestionsAndHallucinationTest(unittest.TestCase):
    def test_commons_lang_ranking_and_flag(self):
        # org.apache.commons:commons-lang is absent. Solr returns the real,
        # high-popularity commons-lang3 plus a 1-version near-miss. The real coord
        # must rank FIRST (popularity penalty), the near-miss must NOT be first,
        # and likelyHallucination must be true.
        url = server._metadata_url(server.MAVEN_CENTRAL_URL, "org.apache.commons", "commons-lang")
        with temp_project({}) as root, _patch_urlopen([
            http_error(url, 404),
            _solr([
                ("org.apache.commons", "commons-lang3", 20),  # real, high pop
                ("io.evil", "commons-langx", 1),              # 1-version near-miss
            ]),
        ]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "org.apache.commons", "artifactId": "commons-lang"}],
                "projectPath": root,
            })
        item = out["results"][0]
        self.assertEqual(item["existenceStatus"], "absent")
        self.assertTrue(item["likelyHallucination"])
        self.assertEqual(item["suggestions"][0]["artifactId"], "commons-lang3")
        self.assertNotEqual(item["suggestions"][0]["artifactId"], "commons-langx")

    def _flag_for_candidate(self, req_group, req_artifact, candidates, suggest_limit=3):
        url = server._metadata_url(server.MAVEN_CENTRAL_URL, req_group, req_artifact)
        with temp_project({}) as root, \
                mock.patch.object(server, "search_maven_central", return_value=candidates), \
                _patch_urlopen([http_error(url, 404)]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": req_group, "artifactId": req_artifact}],
                "suggestLimit": suggest_limit,
                "projectPath": root,
            })
        return out["results"][0]

    def test_score_at_threshold_flags_true(self):
        # artifactId "aaaaa" vs candidate "aaaab": edit distance 1 over length 5 ->
        # similarity exactly 0.8 (the boundary). Candidate group differs, so the
        # raw score is the artifactId similarity = 0.8 -> flag true.
        item = self._flag_for_candidate(
            "g", "aaaaa",
            [{"groupId": "other", "artifactId": "aaaab", "versionCount": 5}],
        )
        self.assertTrue(item["likelyHallucination"])
        self.assertAlmostEqual(item["suggestions"][0]["score"], 0.8)

    def test_score_just_below_threshold_flags_false(self):
        # artifactId "aaaa" vs candidate "aaab": edit distance 1 over length 4 ->
        # similarity 0.75, just below the 0.8 boundary -> flag false.
        item = self._flag_for_candidate(
            "g", "aaaa",
            [{"groupId": "other", "artifactId": "aaab", "versionCount": 5}],
        )
        self.assertFalse(item["likelyHallucination"])
        self.assertAlmostEqual(item["suggestions"][0]["score"], 0.75)

    def test_low_pop_near_miss_deweighted_out_but_flag_still_true(self):
        # A high-similarity (0.95) 1-version near-miss vs a lower-similarity (0.85)
        # high-popularity coord. With suggestLimit=1 the penalty pushes the
        # near-miss out of the emitted top-1, yet the flag — computed over the
        # FULL pre-truncation set — is still true.
        req_artifact = "a" * 20
        high_pop = {"groupId": "z", "artifactId": "a" * 17 + "bbb", "versionCount": 100}  # sim 0.85
        low_pop = {"groupId": "z", "artifactId": "a" * 19 + "b", "versionCount": 1}       # sim 0.95
        item = self._flag_for_candidate("com.x", req_artifact, [high_pop, low_pop], suggest_limit=1)
        self.assertTrue(item["likelyHallucination"])
        self.assertEqual(len(item["suggestions"]), 1)
        self.assertEqual(item["suggestions"][0]["artifactId"], high_pop["artifactId"])
        emitted = [s["artifactId"] for s in item["suggestions"]]
        self.assertNotIn(low_pop["artifactId"], emitted)

    def test_solr_metachar_token_is_escaped_before_search(self):
        # A crafted artifactId reaches search ONLY after _solr_escape neutralizes
        # the Solr metacharacters.
        token = "foo:bar*"
        url = server._metadata_url(server.MAVEN_CENTRAL_URL, "com.x", token)
        with temp_project({}) as root, \
                mock.patch.object(server, "search_maven_central", return_value=[]) as msearch, \
                _patch_urlopen([http_error(url, 404)]):
            server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": token}],
                "projectPath": root,
            })
        msearch.assert_called_once()
        self.assertEqual(msearch.call_args.args[0], server._solr_escape(token))


class IsolationAndCapsTest(unittest.TestCase):
    def test_per_item_isolation_unexpected_error(self):
        # The first item triggers an UNEXPECTED (non-urlopen) failure deep in the
        # handler; it degrades to an error item while the sibling still resolves.
        original_classify = server.classify_version

        def boom(version):
            if version == "9.9.9":
                raise RuntimeError("downstream boom")
            return original_classify(version)

        with temp_project({}) as root, \
                mock.patch.object(server, "classify_version", side_effect=boom), \
                _patch_urlopen([_meta(["9.9.9"]), _meta(["1.0"])]):
            out = server.handle_verify_coordinates({
                "dependencies": [
                    {"groupId": "com.bad", "artifactId": "boom"},
                    {"groupId": "com.good", "artifactId": "lib"},
                ],
                "projectPath": root,
            })
        bad, good = out["results"]
        self.assertIn("error", bad)
        self.assertEqual(good["existenceStatus"], "exists")
        self.assertTrue(good["gaExists"])

    def test_caps_truncate_dependencies_over_100(self):
        # 101 deps -> the HANDLER truncates to 100 before any I/O. _repos_for is
        # stubbed to [] so no urlopen happens and each survivor reads "unknown".
        deps = [{"groupId": "com.x", "artifactId": f"a{i}"} for i in range(101)]
        with temp_project({}) as root, mock.patch.object(server, "_repos_for", return_value=[]):
            out = server.handle_verify_coordinates({
                "dependencies": deps,
                "projectPath": root,
            })
        self.assertEqual(len(out["results"]), 100)

    def test_caps_clamp_suggest_limit_over_10(self):
        # suggestLimit=50 -> the HANDLER clamps to 10 emitted suggestions.
        candidates = [{"groupId": "g", "artifactId": f"cand{i}", "versionCount": 5} for i in range(12)]
        url = server._metadata_url(server.MAVEN_CENTRAL_URL, "com.x", "ghost")
        with temp_project({}) as root, \
                mock.patch.object(server, "search_maven_central", return_value=candidates), \
                _patch_urlopen([http_error(url, 404)]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "ghost"}],
                "suggestLimit": 50,
                "projectPath": root,
            })
        self.assertEqual(len(out["results"][0]["suggestions"]), 10)


if __name__ == "__main__":
    unittest.main()

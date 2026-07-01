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

import contextlib
import json
import time
import unittest
import unittest.mock
import urllib.error

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
    return unittest.mock.patch("urllib.request.urlopen", side_effect=mock_urlopen(sequence))


@contextlib.contextmanager
def _no_gated_solr_calls():
    """Neutralize the #322 Layer 2 gated calls (group-mismatch search +
    recent-first-publish timestamp fetch) so a low/empty versionCount fixture
    doesn't need extra urlopen responses queued for a test that isn't about
    typosquatRisk. Without this, mock_urlopen's "more calls than configured"
    AssertionError gets silently swallowed by search_maven_central's /
    _fetch_gav_timestamp's own broad except-Exception degrade -- masking a
    real, if harmless, extra network attempt rather than raising it."""
    with unittest.mock.patch.object(server, "search_maven_central", return_value=[]), \
            unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=None):
        yield


class ExistenceTriStateTest(unittest.TestCase):
    def test_real_ga_exists(self):
        # One repo (Central) answers 200 -> exists, gaExists, repository recorded.
        # versionCount=2 (<=LOW_VERSION_COUNT_THRESHOLD) gates in typosquatRisk's
        # Layer 2 calls -- neutralized here since this test is about existence,
        # not typosquatRisk (see SuggestionsAndHallucinationTest for that).
        with temp_project({}) as root, _no_gated_solr_calls(), \
                _patch_urlopen([_meta(["1.0", "2.0"])]):
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
        with temp_project({}) as root, _no_gated_solr_calls(), \
                _patch_urlopen([_meta(["1.0", "2.0"])]):
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
                unittest.mock.patch.object(server, "search_maven_central", return_value=[]), \
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
        self.assertNotIn("typosquatRisk", item)  # #322: exists-only field

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
        self.assertNotIn("typosquatRisk", item)  # #322: exists-only field
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
        with temp_project({}) as root, _no_gated_solr_calls(), _patch_urlopen([_meta([])]):
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
                unittest.mock.patch.object(server, "search_maven_central", return_value=candidates), \
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
                unittest.mock.patch.object(server, "search_maven_central", return_value=[]) as msearch, \
                _patch_urlopen([http_error(url, 404)]):
            server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": token}],
                "projectPath": root,
            })
        msearch.assert_called_once()
        self.assertEqual(msearch.call_args.args[0], server._solr_escape(token))


class TyposquatRiskTest(unittest.TestCase):
    """Tests for `typosquatRisk` (#322 Layer 2, heuristic, exists-only)."""

    def _verify_exists(self, group_id, artifact_id, versions, **kwargs):
        with temp_project({}) as root, _no_gated_solr_calls(), \
                _patch_urlopen([_meta(versions)]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": group_id, "artifactId": artifact_id}],
                "projectPath": root,
                **kwargs,
            })
        return out["results"][0]

    def test_ordinary_high_version_count_signal_false(self):
        # A well-established coordinate (high versionCount, no near-name
        # candidate ever queried since the gate never opens) -> signal:false.
        item = self._verify_exists("com.x", "lib", [f"1.{i}.0" for i in range(20)])
        self.assertIn("typosquatRisk", item)
        self.assertEqual(item["typosquatRisk"], {
            "signal": False, "reasons": [], "versionCount": 20,
        })

    def test_low_version_count_fires_alone(self):
        # versionCount=1 <= LOW_VERSION_COUNT_THRESHOLD, no near-identical
        # candidate with a different group on Central -> only low_version_count.
        with temp_project({}) as root, \
                unittest.mock.patch.object(server, "search_maven_central", return_value=[]) as msearch, \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=None), \
                _patch_urlopen([_meta(["1.0.0"])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "freshlib"}],
                "projectPath": root,
            })
        item = out["results"][0]
        risk = item["typosquatRisk"]
        self.assertTrue(risk["signal"])
        self.assertEqual(risk["reasons"], ["low_version_count"])
        self.assertEqual(risk["versionCount"], 1)
        self.assertNotIn("popularMatch", risk)
        msearch.assert_called_once()  # gate opened (low_version_count fired)

    def test_group_mismatch_solr_call_not_issued_when_gate_closed(self):
        # High versionCount -> low_version_count never fires -> the group-mismatch
        # Solr call must NOT be issued at all (the lockout-risk-fix proof).
        with temp_project({}) as root, \
                unittest.mock.patch.object(server, "search_maven_central", return_value=[]) as msearch, \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp") as mts, \
                _patch_urlopen([_meta([f"1.{i}.0" for i in range(10)])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "established"}],
                "projectPath": root,
            })
        item = out["results"][0]
        self.assertFalse(item["typosquatRisk"]["signal"])
        msearch.assert_not_called()
        mts.assert_not_called()

    def test_group_mismatch_fires_above_thresholds(self):
        # Gated-in (low_version_count fires: versionCount=1). A near-identical
        # (>=0.95 similarity) candidate under a DIFFERENT group with >5x the
        # versionCount -> group_mismatch fires with popularMatch.
        candidates = [
            {"groupId": "com.impersonated", "artifactId": "popularlib", "versionCount": 50},
        ]
        with temp_project({}) as root, \
                unittest.mock.patch.object(server, "search_maven_central", return_value=candidates), \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=None), \
                _patch_urlopen([_meta(["1.0.0"])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.evil", "artifactId": "popularlib"}],
                "projectPath": root,
            })
        risk = out["results"][0]["typosquatRisk"]
        self.assertIn("group_mismatch", risk["reasons"])
        self.assertEqual(risk["popularMatch"], {
            "groupId": "com.impersonated", "artifactId": "popularlib", "versionCount": 50,
        })

    def test_group_mismatch_does_not_fire_for_comparable_popularity(self):
        # Same negative case, but the candidate's versionCount is COMPARABLE
        # (not >5x) -> group_mismatch must NOT fire even though the name matches
        # exactly and the group differs.
        candidates = [
            {"groupId": "com.other", "artifactId": "sharedname", "versionCount": 3},
        ]
        with temp_project({}) as root, \
                unittest.mock.patch.object(server, "search_maven_central", return_value=candidates), \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=None), \
                _patch_urlopen([_meta(["1.0.0"])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.mine", "artifactId": "sharedname"}],
                "projectPath": root,
            })
        risk = out["results"][0]["typosquatRisk"]
        self.assertNotIn("group_mismatch", risk["reasons"])
        self.assertNotIn("popularMatch", risk)

    def test_coverage_boundary_typo_of_popular_name_fires_at_least_one_signal(self):
        # artifactId is a 1-edit-distance typo of a popular name, different
        # group, low versionCount -> at least one sub-signal must fire even if
        # the typo'd name itself scores just under GROUP_MISMATCH_SIMILARITY
        # against the real popular candidate.
        candidates = [
            {"groupId": "com.real", "artifactId": "reallib", "versionCount": 200},
        ]
        with temp_project({}) as root, \
                unittest.mock.patch.object(server, "search_maven_central", return_value=candidates), \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=None), \
                _patch_urlopen([_meta(["1.0.0"])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.evil", "artifactId": "reallob"}],  # 1-edit typo
                "projectPath": root,
            })
        risk = out["results"][0]["typosquatRisk"]
        self.assertTrue(risk["signal"])
        self.assertIn("low_version_count", risk["reasons"])

    def test_recent_first_publish_gated_by_low_version_count_and_recent_timestamp(self):
        # Gate open (low_version_count fired) AND the mocked _fetch_gav_timestamp
        # returns a timestamp within RECENT_PUBLISH_DAYS_THRESHOLD -> reason fires.
        recent_ts = time.time() * 1000 - 1 * 86400 * 1000  # 1 day ago
        with temp_project({}) as root, \
                unittest.mock.patch.object(server, "search_maven_central", return_value=[]), \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=recent_ts) as mts, \
                _patch_urlopen([_meta(["1.0.0"])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "newlib"}],
                "projectPath": root,
            })
        risk = out["results"][0]["typosquatRisk"]
        self.assertIn("recent_first_publish", risk["reasons"])
        mts.assert_called_once_with("com.x", "newlib", "1.0.0")

    def test_recent_first_publish_absent_when_timestamp_not_recent(self):
        old_ts = time.time() * 1000 - 365 * 86400 * 1000  # 1 year ago
        with temp_project({}) as root, \
                unittest.mock.patch.object(server, "search_maven_central", return_value=[]), \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=old_ts), \
                _patch_urlopen([_meta(["1.0.0"])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "oldlib"}],
                "projectPath": root,
            })
        risk = out["results"][0]["typosquatRisk"]
        self.assertNotIn("recent_first_publish", risk["reasons"])

    def test_recent_first_publish_absent_when_gate_closed(self):
        # High versionCount -> gate never opens -> _fetch_gav_timestamp must not
        # even be called, regardless of what it would have returned.
        with temp_project({}) as root, \
                unittest.mock.patch.object(server, "search_maven_central", return_value=[]), \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp") as mts, \
                _patch_urlopen([_meta([f"1.{i}.0" for i in range(10)])]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "established"}],
                "projectPath": root,
            })
        risk = out["results"][0]["typosquatRisk"]
        self.assertNotIn("recent_first_publish", risk["reasons"])
        mts.assert_not_called()

    def test_fetch_gav_timestamp_escapes_lucene_special_characters(self):
        # groupId/artifactId/version containing Lucene special chars must still
        # produce a well-formed, correctly-scoped query (all 3 values escaped).
        body = json.dumps({"response": {"docs": [{"timestamp": 1700000000000}]}}).encode()
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, body)])
        ) as m:
            ts = server._fetch_gav_timestamp('g:"o', 'a(o)', 'v"1.0')
        self.assertEqual(ts, 1700000000000)
        url = m.call_args_list[0].args[0].full_url
        self.assertIn("core=gav", url)
        # Escaped tokens (backslash before each Lucene metachar) end up
        # percent-encoded in the URL; raw unescaped metachars would break the
        # query into extra clauses -- assert the escaped backslash made it in.
        decoded = server.urllib.parse.unquote(url)
        self.assertIn('g:"g\\:\\"o"', decoded)
        self.assertIn('a:"a\\(o\\)"', decoded)
        self.assertIn('v:"v\\"1.0"', decoded)

    def test_fetch_gav_timestamp_returns_none_on_non_200(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error("u", 500, "boom")]),
        ):
            self.assertIsNone(server._fetch_gav_timestamp("g", "a", "1.0"))

    def test_max_gated_solr_calls_per_batch_cap_enforced(self):
        # A batch where MORE coordinates than MAX_GATED_SOLR_CALLS_PER_BATCH
        # simultaneously satisfy low_version_count -> gated calls stop at the
        # cap; the excess coordinates still get typosquatRisk with ONLY
        # low_version_count in reasons (degrade, not error).
        #
        # The cap bounds actual outbound Solr HTTP CALLS, not gated-in
        # coordinates: each gated-in coordinate issues UP TO TWO Solr calls
        # (search_maven_central for group-mismatch + _fetch_gav_timestamp for
        # recent-first-publish, since every fixture here has a non-empty
        # `versions`) -- so the cap is split evenly (cap // 2 coordinates each
        # get both calls) rather than `cap` coordinates each getting one.
        cap = server.MAX_GATED_SOLR_CALLS_PER_BATCH
        n = cap + 5
        deps = [{"groupId": "com.x", "artifactId": f"lib{i}"} for i in range(n)]
        # Each coordinate: 1 existence probe (200, 1 version -> low_version_count).
        responses = [_meta(["1.0.0"]) for _ in range(n)]
        with temp_project({}) as root, \
                unittest.mock.patch.object(server, "search_maven_central", return_value=[]) as msearch, \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=None) as mts, \
                _patch_urlopen(responses):
            out = server.handle_verify_coordinates({
                "dependencies": deps,
                "projectPath": root,
            })
        # Total actual Solr calls (msearch + mts combined) never exceeds the cap.
        self.assertEqual(msearch.call_count + mts.call_count, cap)
        self.assertEqual(msearch.call_count, cap // 2)
        self.assertEqual(mts.call_count, cap // 2)
        gated_in = [r for r in out["results"] if len(r["typosquatRisk"]["reasons"]) > 1
                    or "group_mismatch" in r["typosquatRisk"]["reasons"]]
        # None of these fixtures produce group_mismatch (empty candidates), so
        # every result -- gated or not -- has exactly ["low_version_count"].
        for r in out["results"]:
            self.assertEqual(r["typosquatRisk"]["reasons"], ["low_version_count"])
        self.assertEqual(gated_in, [])  # sanity: confirms the fixture has no group_mismatch noise

    def test_two_separate_batches_each_get_a_fresh_cap_budget(self):
        # TWO SEPARATE handle_verify_coordinates calls, each individually
        # exceeding the cap -> BOTH independently hit the full budget. Proves
        # the counter is a local variable created fresh per call, not an
        # accumulating module-level global.
        cap = server.MAX_GATED_SOLR_CALLS_PER_BATCH
        n = cap + 3
        deps = [{"groupId": "com.x", "artifactId": f"lib{i}"} for i in range(n)]

        def _run_one_batch():
            responses = [_meta(["1.0.0"]) for _ in range(n)]
            with temp_project({}) as root, \
                    unittest.mock.patch.object(server, "search_maven_central", return_value=[]) as msearch, \
                    unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=None) as mts, \
                    _patch_urlopen(responses):
                server.handle_verify_coordinates({"dependencies": deps, "projectPath": root})
            return msearch.call_count + mts.call_count

        first_call_count = _run_one_batch()
        second_call_count = _run_one_batch()
        self.assertEqual(first_call_count, cap)
        self.assertEqual(second_call_count, cap)  # NOT 0 -- a fresh budget, not a depleted global

    def test_single_coordinate_triggering_both_gated_calls_consumes_two_budget_units(self):
        # Regression for the undercounting bug: a coordinate with low_version_count
        # AND a non-empty `versions` list triggers BOTH search_maven_central
        # (group-mismatch) and _fetch_gav_timestamp (recent-first-publish) --
        # that is 2 ACTUAL Solr calls for ONE coordinate, so the shared
        # per-batch counter must advance by 2, never 1.
        gated_calls = [0]
        with unittest.mock.patch.object(server, "search_maven_central", return_value=[]) as msearch, \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=None) as mts:
            server._compute_typosquat_risk("com.x", "lib", 1, ["1.0.0"], gated_calls)
        msearch.assert_called_once()
        mts.assert_called_once()
        self.assertEqual(gated_calls[0], 2)

    def test_cap_boundary_enforced_per_call_not_per_coordinate(self):
        # Cap sized to exactly 3: the first coordinate consumes both its calls
        # (search + timestamp = 2 units, budget now at 2/3). The second
        # coordinate's group-mismatch search gets the ONE remaining unit (budget
        # now at 3/3, exactly at the cap), but its recent-first-publish
        # timestamp fetch must be DENIED -- proving the cap is enforced per
        # INDIVIDUAL call, not rounded up to let a coordinate finish both of its
        # calls once it has started (which would silently allow the effective
        # ceiling to reach cap+1, drifting back toward the original 2x-cap bug).
        with unittest.mock.patch.object(server, "MAX_GATED_SOLR_CALLS_PER_BATCH", 3), \
                unittest.mock.patch.object(server, "search_maven_central", return_value=[]) as msearch, \
                unittest.mock.patch.object(server, "_fetch_gav_timestamp", return_value=None) as mts:
            gated_calls = [0]
            server._compute_typosquat_risk("com.x", "lib0", 1, ["1.0.0"], gated_calls)
            server._compute_typosquat_risk("com.x", "lib1", 1, ["1.0.0"], gated_calls)
        self.assertEqual(gated_calls[0], 3)
        self.assertEqual(msearch.call_count, 2)  # both coordinates got their group-mismatch search
        self.assertEqual(mts.call_count, 1)  # only the first coordinate got the timestamp fetch
        self.assertEqual(msearch.call_count + mts.call_count, 3)  # exactly the cap, never 4


class IsolationAndCapsTest(unittest.TestCase):
    def test_per_item_isolation_unexpected_error(self):
        # The first item triggers an UNEXPECTED (non-urlopen) failure deep in the
        # handler; it degrades to an error item while the sibling still resolves.
        original_classify = server.classify_version

        def boom(version):
            if version == "9.9.9":
                raise RuntimeError("downstream boom")
            return original_classify(version)

        with temp_project({}) as root, _no_gated_solr_calls(), \
                unittest.mock.patch.object(server, "classify_version", side_effect=boom), \
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
        with temp_project({}) as root, unittest.mock.patch.object(server, "_repos_for", return_value=[]):
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
                unittest.mock.patch.object(server, "search_maven_central", return_value=candidates), \
                _patch_urlopen([http_error(url, 404)]):
            out = server.handle_verify_coordinates({
                "dependencies": [{"groupId": "com.x", "artifactId": "ghost"}],
                "suggestLimit": 50,
                "projectPath": root,
            })
        self.assertEqual(len(out["results"][0]["suggestions"]), 10)


if __name__ == "__main__":
    unittest.main()

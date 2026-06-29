"""Tests for the string-distance and Solr-escape utilities (T-1).

Covers ``_levenshtein`` / ``_similarity`` edit-distance behavior (plain, NOT
Damerau) and ``_solr_escape`` query-metacharacter neutralization.
"""

import re
import unittest

from _helpers import server


class LevenshteinSimilarityTest(unittest.TestCase):
    def test_identical_distance_zero_similarity_one(self):
        self.assertEqual(server._levenshtein("ktor", "ktor"), 0)
        self.assertEqual(server._similarity("ktor", "ktor"), 1.0)

    def test_both_empty_similarity_one(self):
        self.assertEqual(server._levenshtein("", ""), 0)
        self.assertEqual(server._similarity("", ""), 1.0)

    def test_one_empty_similarity_zero(self):
        self.assertEqual(server._levenshtein("", "abc"), 3)
        self.assertEqual(server._levenshtein("abc", ""), 3)
        self.assertEqual(server._similarity("", "abc"), 0.0)
        self.assertEqual(server._similarity("abc", ""), 0.0)

    def test_single_substitution_distance_one(self):
        self.assertEqual(server._levenshtein("abc", "abd"), 1)

    def test_adjacent_transposition_costs_two_not_damerau(self):
        # Plain Levenshtein: a swap is two substitutions, not one transposition.
        # This pins the implementation as NOT Damerau-Levenshtein.
        self.assertEqual(server._levenshtein("ab", "ba"), 2)

    def test_realistic_near_miss_high_similarity(self):
        # commons-lang vs commons-lang3: one insertion -> ~0.92.
        sim = server._similarity("commons-lang", "commons-lang3")
        self.assertAlmostEqual(sim, 1 - 1 / 13, places=6)
        self.assertGreaterEqual(sim, 0.8)

    def test_different_short_pair_low_similarity(self):
        # guava vs guice: three substitutions over length 5 -> 0.4. Short names
        # produce low similarity even when they "look" related (the caveat that
        # makes a single similarity threshold unreliable for short artifactIds).
        sim = server._similarity("guava", "guice")
        self.assertAlmostEqual(sim, 0.4, places=6)
        self.assertLess(sim, 0.8)

    def test_callers_lowercase_convention(self):
        # The utilities are case-sensitive by design; callers lowercase before
        # comparing. Mixed case differs; the lowercased forms match.
        self.assertLess(server._similarity("Ktor", "ktor"), 1.0)
        self.assertEqual(server._similarity("Ktor".lower(), "ktor".lower()), 1.0)


class SolrEscapeTest(unittest.TestCase):
    def test_neutralizes_wildcard_field_space_and_or(self):
        token = "foo* :bar OR baz"
        escaped = server._solr_escape(token)
        # Wildcard and field-separator metachars are backslash-escaped.
        self.assertIn("\\*", escaped)
        self.assertIn("\\:", escaped)
        self.assertNotIn("foo*", escaped)
        # No bare metachar remains: every * and : is preceded by a backslash.
        self.assertEqual(re.sub(r"\\.", "", escaped).count("*"), 0)
        self.assertEqual(re.sub(r"\\.", "", escaped).count(":"), 0)
        # OR is neutralized indirectly: the surrounding spaces are escaped, so it
        # is no longer a whitespace-delimited bareword operator. Assert there is
        # no unescaped whitespace -> the whole token stays a single Solr term.
        self.assertNotIn(" ", re.sub(r"\\.", "", escaped))
        self.assertEqual(len(re.split(r"(?<!\\)\s", escaped)), 1)

    def test_plain_token_only_defined_escaping(self):
        # ktor-client-core has no wildcards/colons; only the hyphens (a defined
        # Solr metachar) are escaped -> ktor\-client\-core.
        self.assertEqual(
            server._solr_escape("ktor-client-core"), "ktor\\-client\\-core"
        )


if __name__ == "__main__":
    unittest.main()

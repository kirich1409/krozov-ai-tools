"""Tests for version classification and comparison functions in server.py.

Mirrors assertions from:
  - src/version/__tests__/classify.test.ts
  - src/version/__tests__/compare.test.ts
  - src/version/__tests__/range.test.ts

All test methods call pure functions only — no network, no mocking required.
"""

import functools
import unittest

from _helpers import server


# ---------------------------------------------------------------------------
# classify_version
# ---------------------------------------------------------------------------

class ClassifyVersionTest(unittest.TestCase):

    def test_classifies_stable(self):
        # mirrors classify.test.ts: "classifies stable versions"
        self.assertEqual(server.classify_version("3.5.11"), "stable")
        self.assertEqual(server.classify_version("1.0"), "stable")
        self.assertEqual(server.classify_version("2.0.0"), "stable")

    def test_classifies_snapshot(self):
        # mirrors classify.test.ts: "classifies snapshot versions"
        self.assertEqual(server.classify_version("1.0-SNAPSHOT"), "snapshot")
        self.assertEqual(server.classify_version("2.0.0-SNAPSHOT"), "snapshot")

    def test_classifies_alpha(self):
        # mirrors classify.test.ts: "classifies alpha versions"
        self.assertEqual(server.classify_version("1.0-alpha-1"), "alpha")
        self.assertEqual(server.classify_version("1.0.0-alpha1"), "alpha")
        self.assertEqual(server.classify_version("1.0-a1"), "alpha")

    def test_classifies_beta(self):
        # mirrors classify.test.ts: "classifies beta versions"
        self.assertEqual(server.classify_version("1.0-beta-1"), "beta")
        self.assertEqual(server.classify_version("1.0.0-beta1"), "beta")
        self.assertEqual(server.classify_version("1.0-b1"), "beta")

    def test_classifies_rc(self):
        # mirrors classify.test.ts: "classifies RC versions"
        self.assertEqual(server.classify_version("1.0-RC1"), "rc")
        self.assertEqual(server.classify_version("1.0-rc-2"), "rc")
        self.assertEqual(server.classify_version("1.0-CR1"), "rc")

    def test_no_false_positive_on_short_form_patterns(self):
        # mirrors classify.test.ts: "does not false-positive on short-form patterns"
        self.assertEqual(server.classify_version("1.0-bar"), "stable")
        self.assertEqual(server.classify_version("1.0-ace"), "stable")

    def test_classifies_milestone(self):
        # mirrors classify.test.ts: "classifies milestone versions"
        self.assertEqual(server.classify_version("1.0-M1"), "milestone")
        self.assertEqual(server.classify_version("1.0-milestone-2"), "milestone")

    def test_edge_case_empty_string(self):
        # edge case: empty string matches no pattern — falls through to "stable"
        self.assertEqual(server.classify_version(""), "stable")

    def test_edge_case_garbage_input(self):
        # edge case: unrecognised string matches no pattern — falls through to "stable"
        self.assertEqual(server.classify_version("garbage"), "stable")


# ---------------------------------------------------------------------------
# find_latest_version_for_current
# ---------------------------------------------------------------------------

_MIXED_VERSIONS = ["1.0.0", "2.0.0-alpha1", "2.0.0-beta1", "2.0.0-RC1", "2.0.0"]


class FindLatestVersionForCurrentTest(unittest.TestCase):

    def test_returns_stable_when_current_is_stable(self):
        # mirrors classify.test.ts: "returns the stable when current is stable"
        self.assertEqual(
            server.find_latest_version_for_current(_MIXED_VERSIONS, "1.0.0"),
            "2.0.0",
        )

    def test_current_rc_returns_stable_upgrade(self):
        # #312: a more-stable upgrade must win. From an RC current, the stable
        # 2.0.0 qualifies (stable >= rc) and is the highest candidate, so it is
        # returned in preference to the same-core 2.0.0-RC1.
        self.assertEqual(
            server.find_latest_version_for_current(_MIXED_VERSIONS, "1.0.0-RC1"),
            "2.0.0",
        )

    def test_skips_versions_less_stable_than_current_beta(self):
        # mirrors classify.test.ts: "skips less stable versions"
        v = ["1.0.0", "2.0.0-alpha1", "2.0.0-beta1"]
        self.assertEqual(
            server.find_latest_version_for_current(v, "1.0.0-beta1"),
            "2.0.0-beta1",
        )

    def test_returns_none_when_only_less_stable_available(self):
        # #312: a SNAPSHOT must never be offered as an upgrade from a stable
        # current. Snapshot rank (0) is below stable rank (5), so nothing
        # qualifies and None is returned.
        v = ["1.0.0-SNAPSHOT"]
        self.assertIsNone(
            server.find_latest_version_for_current(v, "1.0.0"),
        )

    def test_up_to_date_current_returns_current_not_none(self):
        # #312 correction: when current is already the highest acceptable
        # version it is present in the list, qualifies (compare == 0, same
        # stability) and is returned. The newer-OR-equal rule avoids the
        # spurious "no matching version" the strict-newer check produced for
        # already-up-to-date dependencies.
        self.assertEqual(
            server.find_latest_version_for_current(["1.0.0", "2.0.0"], "2.0.0"),
            "2.0.0",
        )

    def test_bare_release_preferred_over_compat_suffix_build(self):
        # #325: get_latest_version picked "0.8.0-0.6.x-compat" over "0.8.0".
        # The candidate list mirrors how the server actually feeds this
        # function — sorted ascending via compare_versions (server.py:557)
        # before selection — so this exercises the real selection pipeline,
        # not just the comparator in isolation.
        raw = ["0.7.0", "0.8.0-0.6.x-compat", "0.8.0"]
        versions = sorted(set(raw), key=functools.cmp_to_key(server.compare_versions))
        self.assertEqual(
            server.find_latest_version_for_current(versions, "0.7.0"),
            "0.8.0",
        )


# ---------------------------------------------------------------------------
# compare_versions
# ---------------------------------------------------------------------------

class CompareVersionsTest(unittest.TestCase):

    def test_compares_numeric_cores(self):
        # mirrors compare.test.ts: "compares numeric cores"
        self.assertLess(server.compare_versions("1.0.0", "2.0.0"), 0)
        self.assertGreater(server.compare_versions("2.0.0", "1.9.9"), 0)
        self.assertEqual(server.compare_versions("1.0.0", "1.0.0"), 0)

    def test_orders_stable_above_prerelease_of_same_core(self):
        # mirrors compare.test.ts: "orders stable above pre-release of same core"
        self.assertGreater(server.compare_versions("2.0.0", "2.0.0-RC1"), 0)

    def test_orders_prereleases_relative_to_each_other(self):
        # mirrors compare.test.ts: "orders pre-releases relative to each other"
        self.assertGreater(server.compare_versions("2.0.0-RC1", "2.0.0-beta1"), 0)
        self.assertLess(server.compare_versions("2.0.0-alpha1", "2.0.0-beta1"), 0)

    def test_bare_release_outranks_same_core_qualifier_suffix(self):
        # #325: "0.8.0" and "0.8.0-0.6.x-compat" share the same numeric core
        # and both classify as "stable" (no alpha/beta/rc/milestone/snapshot
        # match in "-compat"), so the only signal left is the prerelease-number
        # tail. A bare release (no suffix at all) must rank above a same-core
        # release carrying a numeric qualifier suffix, not below it.
        self.assertGreater(server.compare_versions("0.8.0", "0.8.0-0.6.x-compat"), 0)
        self.assertLess(server.compare_versions("0.8.0-0.6.x-compat", "0.8.0"), 0)

    def test_bare_release_outranks_digitless_qualifier_suffix(self):
        # #325: a suffix with no digits at all (e.g. "-compat", "-jre") must
        # not slip past the fix — _extract_prerelease_numbers returns [] for
        # both a truly bare version AND a digitless suffix, so the fix must
        # key on suffix presence, not on prerelease-number-list emptiness.
        self.assertGreater(server.compare_versions("0.8.0", "0.8.0-compat"), 0)
        self.assertLess(server.compare_versions("0.8.0-compat", "0.8.0"), 0)

    def test_both_prerelease_number_tails_still_compare_correctly(self):
        # #325 regression guard: the fix must not break ordering when BOTH
        # sides carry a numeric suffix — rc.2 still ranks above rc.1.
        self.assertGreater(server.compare_versions("1.0.0-rc.2", "1.0.0-rc.1"), 0)
        self.assertLess(server.compare_versions("1.0.0-rc.1", "1.0.0-rc.2"), 0)

    def test_both_suffixed_same_class_falls_back_to_prerelease_tail(self):
        # #325 regression guard: when BOTH sides carry a suffix, the new
        # suffix-presence branch must not fire (true == true), so ordering
        # still falls through to the existing prerelease-number tail compare
        # unaffected — "beta" (no digits) ranks below "beta2" exactly as
        # before this fix, both within the same classify_version() class.
        self.assertEqual(server.classify_version("1.0.0-beta"), server.classify_version("1.0.0-beta2"))
        self.assertLess(server.compare_versions("1.0.0-beta", "1.0.0-beta2"), 0)
        self.assertGreater(server.compare_versions("1.0.0-beta2", "1.0.0-beta"), 0)


# ---------------------------------------------------------------------------
# get_upgrade_type
# ---------------------------------------------------------------------------

class GetUpgradeTypeTest(unittest.TestCase):

    def test_detects_major_upgrade(self):
        # mirrors compare.test.ts: "detects major upgrade"
        self.assertEqual(server.get_upgrade_type("1.0.0", "2.0.0"), "major")

    def test_detects_minor_upgrade(self):
        # mirrors compare.test.ts: "detects minor upgrade"
        self.assertEqual(server.get_upgrade_type("1.0.0", "1.1.0"), "minor")

    def test_detects_patch_upgrade(self):
        # mirrors compare.test.ts: "detects patch upgrade"
        self.assertEqual(server.get_upgrade_type("1.0.0", "1.0.1"), "patch")

    def test_returns_none_for_downgrade(self):
        # mirrors compare.test.ts: "returns none for downgrade"
        self.assertEqual(server.get_upgrade_type("2.0.0", "1.5.0"), "none")
        self.assertEqual(server.get_upgrade_type("1.5.0", "1.3.9"), "none")

    def test_handles_two_segment_versions(self):
        # mirrors compare.test.ts: "handles two-segment versions"
        self.assertEqual(server.get_upgrade_type("1.0", "2.0"), "major")
        self.assertEqual(server.get_upgrade_type("1.0", "1.1"), "minor")

    def test_prerelease_to_stable_is_patch(self):
        # mirrors compare.test.ts: "classifies pre-release → stable as patch"
        self.assertEqual(server.get_upgrade_type("2.0.0-beta-1", "2.0.0"), "patch")
        self.assertEqual(server.get_upgrade_type("2.0.0-rc-1", "2.0.0"), "patch")

    def test_prerelease_to_higher_prerelease_is_patch(self):
        # mirrors compare.test.ts: "classifies pre-release → higher pre-release as patch"
        self.assertEqual(server.get_upgrade_type("2.0.0-beta-1", "2.0.0-beta-2"), "patch")
        self.assertEqual(server.get_upgrade_type("2.0.0-beta-1", "2.0.0-rc-1"), "patch")
        self.assertEqual(server.get_upgrade_type("2.0.0-alpha", "2.0.0-beta"), "patch")

    def test_returns_none_for_stable_to_prerelease_same_core(self):
        # mirrors compare.test.ts: "returns none for stable → pre-release of same core (downgrade)"
        self.assertEqual(server.get_upgrade_type("2.0.0", "2.0.0-beta-1"), "none")
        self.assertEqual(server.get_upgrade_type("2.0.0-rc-1", "2.0.0-beta-1"), "none")

    def test_core_level_upgrades_across_prerelease_suffixes(self):
        # mirrors compare.test.ts: "still classifies core-level upgrades across pre-release suffixes"
        self.assertEqual(server.get_upgrade_type("1.9.0", "2.0.0-beta-1"), "major")
        self.assertEqual(server.get_upgrade_type("1.3.2-1.4.0-rc", "1.3.2"), "patch")


# ---------------------------------------------------------------------------
# _filter_version_range  (mirrors TS filterVersionRange)
# ---------------------------------------------------------------------------

_RANGE_VERSIONS = ["1.0.0", "1.1.0", "1.2.0", "1.3.0", "2.0.0-beta1", "2.0.0"]


class FilterVersionRangeTest(unittest.TestCase):

    def test_returns_versions_exclusive_from_inclusive_to(self):
        # mirrors range.test.ts: "returns versions between from (exclusive) and to (inclusive)"
        self.assertEqual(
            server._filter_version_range(_RANGE_VERSIONS, "1.0.0", "1.3.0"),
            ["1.1.0", "1.2.0", "1.3.0"],
        )

    def test_includes_prerelease_versions_in_range(self):
        # mirrors range.test.ts: "includes pre-release versions in range"
        self.assertEqual(
            server._filter_version_range(_RANGE_VERSIONS, "1.2.0", "2.0.0"),
            ["1.3.0", "2.0.0-beta1", "2.0.0"],
        )

    def test_empty_when_from_equals_to(self):
        # mirrors range.test.ts: "returns empty array when from and to are the same"
        self.assertEqual(
            server._filter_version_range(_RANGE_VERSIONS, "1.0.0", "1.0.0"),
            [],
        )

    def test_from_not_found_falls_back_to_numeric_comparison(self):
        # mirrors range.test.ts: "returns empty array when fromVersion is not found"
        # Python difference: TS returns [] when fromVersion is absent from the list.
        # Python uses compare_versions, so "0.9.0" acts as a numeric lower bound
        # and all versions between 0.9.0 (exclusive) and 1.3.0 (inclusive) are returned.
        self.assertEqual(
            server._filter_version_range(_RANGE_VERSIONS, "0.9.0", "1.3.0"),
            ["1.0.0", "1.1.0", "1.2.0", "1.3.0"],
        )

    def test_to_not_found_falls_back_to_numeric_comparison(self):
        # mirrors range.test.ts: "returns empty array when toVersion is not found"
        # Python difference: TS returns [] when toVersion is absent from the list.
        # Python uses compare_versions, so "9.9.9" acts as a numeric upper bound
        # and all versions between 1.0.0 (exclusive) and 9.9.9 (inclusive) are returned.
        self.assertEqual(
            server._filter_version_range(_RANGE_VERSIONS, "1.0.0", "9.9.9"),
            ["1.1.0", "1.2.0", "1.3.0", "2.0.0-beta1", "2.0.0"],
        )


if __name__ == "__main__":
    unittest.main()

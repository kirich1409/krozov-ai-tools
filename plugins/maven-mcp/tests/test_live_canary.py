"""Live canary for the #322 Layer 1 malicious-package detection.

This is the ONE test in the suite that makes a REAL network call. It is
gated behind an explicit opt-in (MAVEN_MCP_LIVE_CANARY=1) so it is collected
by `unittest discover -s plugins/maven-mcp/tests` (matches the default
`test*.py` pattern) but SKIPPED by default -- the same opt-in-skip pattern
already used for the jq/timeout-gated hook tests in test_pre_edit_hook.py.
It is NOT part of the default CI test step; it is invoked ONLY by the
dedicated weekly scheduled workflow (.github/workflows/maven-mcp-live-canary.yml).

Why this exists: a mocked regression test (test_maven_search_osv.py's
TestMaliciousFlag) only proves the `_is_malicious_id` code branch works
against a value the test author chose -- it cannot detect the underlying LIVE
assumption breaking (OSV.dev dropping the OSSF Malicious Packages source, or
relabeling the id scheme away from the "MAL-" prefix). This test re-queries
the real, previously-confirmed-live coordinate
(io.github.leetcrunch:scribejava-core, MAL-2025-2552 -- an OSSF-reported
Maven OAuth-library typosquat that exfiltrates credentials; see
docs/plans/maven-typosquat-signal/plan.md's Verification & Sources) against
the real api.osv.dev endpoint and asserts a MAL- id still comes back.
"""

import os
import unittest

from _helpers import server

_LIVE_CANARY_ENABLED = os.environ.get("MAVEN_MCP_LIVE_CANARY", "") == "1"


@unittest.skipUnless(
    _LIVE_CANARY_ENABLED,
    "set MAVEN_MCP_LIVE_CANARY=1 to run the real-network OSV.dev canary "
    "(also runs unconditionally in the weekly scheduled CI workflow)",
)
class LiveCanaryTest(unittest.TestCase):
    def test_known_malicious_coordinate_still_flagged_live(self):
        results = server.query_osv_batch([
            {
                "groupId": "io.github.leetcrunch",
                "artifactId": "scribejava-core",
                "version": "1.0.0",
            },
        ])
        self.assertEqual(len(results), 1)
        vulns = results[0]["vulnerabilities"]
        malicious_ids = [v["id"] for v in vulns if v.get("malicious")]
        self.assertTrue(
            malicious_ids,
            "expected at least one MAL- id from the live OSV.dev querybatch "
            "response for io.github.leetcrunch:scribejava-core -- if this "
            "fails, OSV.dev/OSSF convention drift is the likely cause "
            "(see plan.md's Risks & Mitigations)",
        )


if __name__ == "__main__":
    unittest.main()

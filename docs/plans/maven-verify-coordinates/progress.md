# Progress: maven-mcp `verify_coordinates` tool (#282)

> Plan: ./plan.md · Tasks: ./tasks.md · Branch feat/maven-verify-coordinates

## Status
- [ ] T-1 — string-distance utilities
- [ ] T-2 — verify_coordinates handler + registration
- [ ] T-3 — docs + L5 smoke + open PR

## Learnings
<!-- one line per completed task -->
- Cycle-1 review (security/architecture/pr-test-analyzer) → FAIL. Convergent critical: existence-by-fetch_metadata-raise conflates absent vs unreachable → replaced with explicit tri-state per-repo probe (exists/absent/unknown) that also yields repository + avoids None-crash. Security: reframed "exists≠safe" (output never asserts safe; #322 filed for typosquat-of-existing), popularity-aware suggestion ranking (versionCount de-weight), Solr-metachar escaping, batch/suggestLimit caps. Tests: ranking max-not-min, 0.80/0.79 boundary, isolation via unexpected error, Levenshtein transposition=2, enumerated urlopen sequences.

# Progress: maven-mcp `verify_coordinates` tool (#282)

> Plan: ./plan.md · Tasks: ./tasks.md · Branch feat/maven-verify-coordinates

## Status
- [x] T-1 — string-distance + Solr-escape utilities (b816719, 10 tests)
- [x] T-2 — verify_coordinates handler + registration (ecc5fcb, 18 tests; 282 total)
- [x] T-3 — docs (ea7243e) + L5 smoke ✅ + PR (next)

## L5 smoke (stdio, real network)
- io.ktor:ktor-client-core → existenceStatus=exists, gaExists=True, likelyHallucination=False, repository=Maven Central.
- org.apache.commons:commons-lang → existenceStatus=absent, likelyHallucination=True, suggestions include real commons-lang:commons-lang (ranking among equal-artifactId candidates is versionCount-penalized; deeper popularity/ownership signal tracked #322).

## Learnings
<!-- one line per completed task -->
- Cycle-1 review (security/architecture/pr-test-analyzer) → FAIL. Convergent critical: existence-by-fetch_metadata-raise conflates absent vs unreachable → replaced with explicit tri-state per-repo probe (exists/absent/unknown) that also yields repository + avoids None-crash. Security: reframed "exists≠safe" (output never asserts safe; #322 filed for typosquat-of-existing), popularity-aware suggestion ranking (versionCount de-weight), Solr-metachar escaping, batch/suggestLimit caps. Tests: ranking max-not-min, 0.80/0.79 boundary, isolation via unexpected error, Levenshtein transposition=2, enumerated urlopen sequences.

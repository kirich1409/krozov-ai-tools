# Progress: active typosquat/popularity signal for existing coordinates (#322)

> Plan: ./plan.md · Tasks: ./tasks.md · Branch feature/typosquat-popularity-signal

## Status
- [x] T-1 — `malicious` flag on OSV vulnerability entries (Layer 1)
- [x] T-2 — `typosquatRisk` computation on `verify_coordinates` (Layer 2)
- [x] T-3 — hook decision-policy branches (`pre-edit-deps.sh`)
- [x] T-4 — live-canary + scheduled workflow, docs, adjacent-bug follow-up issue, L5 smoke, open PR

## L5 smoke (stdio, real network)

Both real-network smoke checks run directly against `plugin/server/server.py` over stdio JSON-RPC (no mocks):

1. **`get_dependency_vulnerabilities`** for the real OSSF-reported malicious coordinate
   `io.github.leetcrunch:scribejava-core@1.0.0` → live response includes
   `"vulnerabilities": [{"id": "MAL-2025-2552", ..., "malicious": true}]`. Confirms Layer 1
   end-to-end against the live `api.osv.dev` endpoint (not just the mocked unit tests).

2. **`verify_coordinates`** for a real low-versionCount `exists` coordinate,
   `com.github.thspinto:scribejava-core` (discovered via the did-you-mean suggestions returned
   for the absent `io.github.leetcrunch:scribejava-core` GA) → live response:
   `{"existenceStatus": "exists", "typosquatRisk": {"signal": true, "reasons":
   ["low_version_count", "group_mismatch"], "versionCount": 2, "popularMatch": {"groupId":
   "com.github.scribejava", "artifactId": "scribejava-core", "versionCount": 57}}}`. This is a
   REAL, live-discovered case matching the plan's exact motivating scenario: a 2-version
   `com.github.thspinto` publish of `scribejava-core` scored against the real, 57-version
   `com.github.scribejava:scribejava-core`. Confirms both the `low_version_count` gate AND the
   gated `group_mismatch` Solr call actually firing end-to-end (not just the mocked unit tests).

Live canary (`tests/test_live_canary.py`, opt-in via `MAVEN_MCP_LIVE_CANARY=1`) run manually
during implementation — passed against the same `MAL-2025-2552` coordinate. Also verified: the
test is SKIPPED (not collected/failed) in a default `unittest discover` run, so it does not affect
the default CI test step; `.github/workflows/maven-mcp-live-canary.yml` is the required weekly
schedule that runs it unconditionally (cron `22 4 * * 3`, validated with `actionlint`).

## Follow-up issue (adjacent hydration gap)

Filed separately, NOT part of this plan's scope (per the task brief — do not fix or touch
`_extract_severity`/hydration here): **#338** — "maven-mcp: query_osv_batch never hydrates
severity — pre-edit-deps.sh CRITICAL/HIGH branch is dead code"
(https://github.com/kirich1409/krozov-ai-tools/issues/338). Already existed before this
implementation started; referenced from the PR description, not duplicated.

## Learnings
<!-- one line per completed task -->
- Plan reviewed via multiexpert-review (security-expert/architecture-expert/dependency-evaluator), 3 cycles, PASS. See plan.md frontmatter `review_note` for the full history.
- BEFORE starting T-1/T-2: plan.md's `[blocking]` Open Questions need explicit user sign-off — new field names (`typosquatRisk`, `malicious`), the 5 named constants (4 detection-calibration + `MAX_GATED_SOLR_CALLS_PER_BATCH`), and whether to file the hydration-gap follow-up issue now. Resolved: implemented exactly as proposed (task brief carried the sign-off); #338 already existed for the hydration gap.
- T-1: `handle_audit_project_dependencies`'s vulnerability path does NOT forward `query_osv_batch`'s `vuln_info` unchanged as the plan assumed — it reconstructs a narrower `{id, severity, fixedVersion}` dict. Fixed by explicitly threading `malicious` through there too (one-line addition), otherwise the plan's own required test (`malicious` surfaces in both consuming handlers) would fail.
- T-2: three EXISTING `test_verify_coordinates.py` fixtures (`test_real_ga_exists`, `test_real_gav_exists`, `test_empty_versions_200_exists_no_stability`) all use versionCount <= LOW_VERSION_COUNT_THRESHOLD, which now gates in the new Layer 2 Solr calls. Without neutralizing them, `mock_urlopen`'s "more calls than configured" AssertionError gets silently swallowed by `search_maven_central`'s/`_fetch_gav_timestamp`'s own broad except-Exception degrade — tests still passed, but for the wrong reason. Added a `_no_gated_solr_calls()` helper to make these three deterministic.
- T-4: local dev environment (macOS) had no `timeout`/`gtimeout`, silently SKIPPING all `@_require_jq_and_timeout()` hook tests; installed `coreutils` (brew) to actually exercise them locally before shipping, rather than trusting the skip.

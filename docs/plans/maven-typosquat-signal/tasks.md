# Tasks: active typosquat/popularity signal for existing coordinates (#322)

> Plan: ./plan.md · One PR (branch `feat/maven-typosquat-signal`). Baseline = current green test
> suite (see `bash scripts/validate.sh`). Read-only reuse of `search_maven_central`, `_similarity`,
> `_solr_escape`, `_verify_one`'s existence probe, `query_osv_batch`'s querybatch call — no change
> to `likelyHallucination`, `fetch_metadata`, `check_version_in_repos` contracts.

## T-1 — `malicious` flag on OSV vulnerability entries (Layer 1)
- after: none
- files: `plugins/maven-mcp/plugin/server/server.py`, `plugins/maven-mcp/tests/test_maven_search_osv.py`
- acceptance: THE SYSTEM SHALL add `_is_malicious_id(vuln_id: str) -> bool` (`vuln_id.startswith("MAL-")`)
  alongside the existing `_extract_severity`/`_extract_fixed_version`/`_extract_url` extractor-function
  convention, and set `vuln_info["malicious"] = _is_malicious_id(v.get("id", ""))` in
  `query_osv_batch` (`server.py:1297-1332`), for every vuln entry, using only the `id` field already
  present on a bare querybatch response (no new network call, no hydration). The field flows
  unchanged through `handle_get_dependency_vulnerabilities` and `handle_audit_project_dependencies`'s
  vulnerability path (dict spread `{**dep, "vulnerabilities": vulns}` already forwards nested
  dict fields as-is).
- check: unit tests — `id="MAL-2025-2552"` → `malicious: true`; `id="GHSA-xxxx"` / `id="CVE-2024-1"` /
  `id="PYSEC-2022-1"` → `malicious: false`; `id=""` (missing) → `malicious: false`; a batch with a
  mix of MAL- and non-MAL- entries preserves per-entry correctness; `handle_get_dependency_vulnerabilities`
  and `handle_audit_project_dependencies` both surface `malicious` unchanged (mock `urlopen` for
  `OSV_API`, enumerate call sequence, assert on the parsed response `vulnerabilities[].malicious`).
  NO per-dependency-result aggregate `malicious: bool` convenience field is added — this is an
  explicitly declined decision (see plan.md Decisions Made), not an oversight; do not add one.
  Live-canary test moved to T-4 (bundled with its required scheduled workflow — see below).

## T-2 — `typosquatRisk` computation on `verify_coordinates` (Layer 2)
- after: none
- files: `plugins/maven-mcp/plugin/server/server.py`, `plugins/maven-mcp/tests/test_verify_coordinates.py`
- acceptance: THE SYSTEM SHALL add named constants `LOW_VERSION_COUNT_THRESHOLD=2`,
  `GROUP_MISMATCH_SIMILARITY=0.95`, `GROUP_MISMATCH_POPULARITY_RATIO=5`,
  `RECENT_PUBLISH_DAYS_THRESHOLD=30`, `MAX_GATED_SOLR_CALLS_PER_BATCH=20` (calibratable, not
  inlined — mirrors `HALLUCINATION_THRESHOLD`'s existing convention). Maintain a per-batch counter
  (shared across all coordinates in one `handle_verify_coordinates` call, not per-coordinate) of
  gated Solr calls issued (group-mismatch + recent-first-publish combined); once
  `MAX_GATED_SOLR_CALLS_PER_BATCH` is reached, remaining coordinates in the SAME batch skip both
  gated calls and keep only `low_version_count` in `reasons` (silent degrade, never raise/block —
  this bounds worst-case burst load on a cold-cache/large-batch run, which gating alone does not).
  In `_verify_one`, when (and only when) `existence_status == "exists"`:
  - compute `version_count = len(union_versions)` (already unioned by the existence probe, zero new
    I/O); fire `low_version_count` reason when `version_count <= LOW_VERSION_COUNT_THRESHOLD`.
  - **GATED behind `low_version_count` having fired, AND the per-batch cap not yet reached**
    (review correction — was originally unconditional; `search.maven.org` has a documented
    `403`-lockout history under bulk load and `_request_with_retry` does not retry 403s, so an
    unconditional per-`exists`-coordinate query risked degrading the shared endpoint for the
    existing did-you-mean/`search_artifacts` paths too): if and only if `low_version_count` fired
    AND the batch cap allows it, query
    `search_maven_central(_solr_escape(artifact_id), _SUGGEST_SEARCH_ROWS, use_cache=True)` (cached
    — this is defense-in-depth, not the anti-steering-critical did-you-mean path); among candidates
    with `_similarity(artifact_id.lower(), cand_a.lower()) >= GROUP_MISMATCH_SIMILARITY` AND
    `cand_g != group_id`, take the highest-`versionCount` one as `popular_match`; fire
    `group_mismatch` (with `popularMatch: {groupId, artifactId, versionCount}`) only when
    `popular_match["versionCount"] > GROUP_MISMATCH_POPULARITY_RATIO * version_count`. A
    coincidentally-shared short artifactId with COMPARABLE versionCount on both sides must NOT fire.
    Coverage-boundary note (document in CLAUDE.md, not left implicit): `group_mismatch` targets
    identical/near-identical-name impersonation; `low_version_count` alone is the fallback signal
    for an attacker who ALSO edits the artifactId (a 1-edit-distance typo), which may score below
    `GROUP_MISMATCH_SIMILARITY`. ALSO document the accepted residual gating-coupling risk: since
    both `group_mismatch` and `recent_first_publish` are gated behind the same `low_version_count`
    precondition, an attacker can publish trivial version bumps to push `versionCount` above
    `LOW_VERSION_COUNT_THRESHOLD` and suppress all of Layer 2 at once — accepted, not re-architected
    this round, bounded because Layer 2 stays advisory-only (`ask`, never `deny`).
  - gated enrichment: if and only if `low_version_count` fired AND the batch cap allows it (the
    SAME gate as group-mismatch above — not "low_version_count OR group_mismatch", since
    group_mismatch can now only fire when low_version_count already did), take `versions[0]` from
    the LOCAL `versions = sorted(union_versions, key=functools.cmp_to_key(compare_versions))`
    variable already in scope in `_verify_one` (`server.py:2764`) and call the NEW function
    `_fetch_gav_timestamp(group_id, artifact_id, versions[0])` (see below) to fetch that version's
    `timestamp`. **Rationale correction (review finding): `versions[0]` is the semver-MINIMUM of a
    deduplicated union across repos, NOT a chronological-XML-order first-publish version** (the
    original "Maven conventionally lists versions in release order" claim was checked against the
    actual code and found false for this code path — `versions` is explicitly sorted by
    `compare_versions`, which destroys any source document order). Document this as "semver-minimum
    under a ≤2-version gate is a reasonable, but imperfect, first-publish proxy," not as an
    XML-ordering convention. Fire `recent_first_publish` (added to `reasons`, does NOT independently
    set `signal`) when `now - timestamp <= RECENT_PUBLISH_DAYS_THRESHOLD` days. Failure of this
    extra query degrades silently (omit the reason, no raise, no impact on `signal`/other reasons).
  - **NEW function `_fetch_gav_timestamp(group_id: str, artifact_id: str, version: str) ->
    Optional[int]`** (separate from `search_maven_central` — that helper hard-codes an
    implicit-default-core request and cannot express `core=gav` or surface `timestamp`; this is
    new code, not a new call site against existing code). Builds
    `f"{SEARCH_API}?q={quote(...)}&core=gav&rows=1&wt=json"` where the query is
    `g:"<escaped group_id>" AND a:"<escaped artifact_id>" AND v:"<escaped version>"` — **ALL THREE
    values passed through `_solr_escape` before interpolation** (Solr query-injection/
    match-broadening risk otherwise — `verify_coordinates` is directly callable, not gated by the
    hook's own charset pre-filter, and Maven Central version strings are not guaranteed
    alnum-only). Uses `http_get`/`http_get_cached` per the existing HTTP seam; returns `None` on any
    non-200/parse failure (silent degrade, never raise).
  - `result["typosquatRisk"] = {"signal": bool(reasons), "reasons": [...], "versionCount":
    version_count, "popularMatch": {...}?}` — ONLY set when `existence_status == "exists"`; absent
    (key not present) on `absent`/`unknown`. `likelyHallucination` and its existing computation are
    UNTOUCHED (no shared code path, no shared threshold).
- check: unit tests (mock `urlopen`/`search_maven_central`'s underlying `http_get_cached` and the
  new `_fetch_gav_timestamp`, enumerate call sequence) — `typosquatRisk` key absent on `absent` and
  `unknown` results (regression); present with `signal:false, reasons:[]` on an ordinary
  well-established `exists` coordinate (high versionCount, no near-name group mismatch);
  `low_version_count` fires alone when versionCount<=2 and no near-identical-artifactId candidate
  with a different group exists; **the group-mismatch Solr call is asserted NOT issued when
  `low_version_count` did NOT fire** (call-count assertion — this is the test that proves the
  lockout-risk fix); `group_mismatch` fires when gated-in AND a near-identical (>=0.95 similarity)
  candidate has a different groupId AND >5x the versionCount; `group_mismatch` does NOT fire for a
  coincidental same-artifactId different-group candidate with COMPARABLE versionCount (negative
  case, explicit); a 1-edit-distance-typo-of-a-popular-name + different-group + low-versionCount
  case confirms at least one sub-signal fires (coverage-boundary test); `recent_first_publish`
  appears in `reasons` ONLY when `low_version_count` fired AND the mocked `_fetch_gav_timestamp`
  returns a recent timestamp — absent when the gating condition is false even if the mocked
  timestamp would otherwise qualify; `_fetch_gav_timestamp`'s query is built from `_solr_escape`d
  values for a groupId/artifactId/version containing Lucene special characters (`"`, `:`, `(`, `)`)
  — boundary test asserting the query stays well-formed and scoped; **a batch where MORE than
  `MAX_GATED_SOLR_CALLS_PER_BATCH` coordinates simultaneously satisfy `low_version_count`** asserts
  the gated Solr calls stop at the cap (call-count assertion) and the excess coordinates still
  return `typosquatRisk` with `low_version_count` in `reasons` but no `group_mismatch`/
  `recent_first_publish` (degrade, not error); **TWO SEPARATE `handle_verify_coordinates` calls,
  each individually exceeding the cap, both independently hit the full
  `MAX_GATED_SOLR_CALLS_PER_BATCH` budget** — proves the counter is created fresh as a LOCAL
  variable per call, not an accumulating module-level global (cycle-3 review finding; implement the
  counter as a local variable at the top of `handle_verify_coordinates`, never module-level state);
  `likelyHallucination` value and its existing test suite are unaffected (regression run).

## T-3 — hook decision-policy branches (`pre-edit-deps.sh`)
- after: T-1, T-2
- files: `plugins/maven-mcp/plugin/hooks/pre-edit-deps.sh`, `plugins/maven-mcp/tests/test_pre_edit_hook.py`
- acceptance: THE SYSTEM SHALL add, to the existing decision-accumulation logic (hook lines
  ~336-449; `deny` wins over `ask`, unchanged): (1) for each coordinate's
  `get_dependency_vulnerabilities` result, if any `vulnerabilities[].malicious == "true"` (jq
  boolean) → `DECISION="deny"` set UNCONDITIONALLY (never behind a guard) with a reason built
  entirely from structured fields via `jq -n --arg` (id + coordinate; never raw file content) —
  this check runs unconditionally, independent of and prior to the existing severity-based
  CRITICAL/HIGH scan, so it fires even though MAL- entries carry no severity; setting it
  unconditionally is what correctly upgrades a prior `ask` (from the CRITICAL/HIGH branch or from
  (2) below) to `deny` when both fire; (2) for each coordinate's `verify_coordinates` result, if
  `existenceStatus=="exists"` and `typosquatRisk.signal=="true"` → set `ask` with the SAME
  precedence guard the existing CRITICAL/HIGH branch uses: `[ "$DECISION" = "deny" ] ||
  DECISION="ask"` — this guard is REQUIRED not just for the same-coordinate case but to prevent a
  heuristic `ask` on a LATER coordinate in the same batch from clobbering a `deny` already set for
  an EARLIER coordinate (both checks run in the same per-coordinate loop over the batch); reason
  string includes `typosquatRisk.reasons` and `popularMatch` (groupId/artifactId), charset-filtered
  `[A-Za-z0-9._:-]` — REQUIRED, identical to the existing filter already applied to `suggestions`
  (same Solr-search-result provenance, same indirect-injection surface into
  `permissionDecisionReason`). Bash 3.2 compatible: no `declare -A`, no `${var,,}`, no
  `mapfile`/`readarray`, guard array expansions `"${arr[@]:-}"`, `[[:space:]]` not `\s` in grep
  EREs.
- check: `test_pre_edit_hook.py` (stub server, `@_require_jq_and_timeout()`) — `exists` +
  `malicious:true` vuln (no severity field) → `deny`; `exists` + `typosquatRisk.signal:true` (no
  malicious vuln) → `ask`; `exists` + BOTH a malicious vuln AND a typosquat signal on the SAME
  coordinate → `deny` wins (single decision emitted, not both); **a batch of TWO coordinates: A is
  `absent`+hallucination (deny), B (a DIFFERENT coordinate in the same run) is
  `exists`+`typosquatRisk.signal` (would-be ask) → overall decision stays `deny`** (the specific
  cross-coordinate precedence gap the guard fix addresses — this is a NEW test, not covered by the
  same-coordinate case above); a fabricated CRITICAL/HIGH `severity` (stub-injected — unreachable
  live today due to the hydration gap, but exercisable via the stub) processed BEFORE the
  malicious-vuln check in loop order → still ends in `deny` (locks in the ordering guarantee ahead
  of a future hydration-gap fix); `exists` + neither signal → `allow` (existing behavior,
  regression); existing `absent`/`unknown`/CRITICAL-HIGH-CVE cases stay green (regression, though
  the CRITICAL/HIGH branch is now documented-but-likely-dead — do not remove it, do not silently
  "fix" its hydration gap as part of this task); reason strings never embed raw `id`/coordinate/
  `popularMatch` content outside the `--arg`-passed, charset-filtered structured path (existing
  security-constraint test pattern, extended to cover `popularMatch`).

## T-4 — live-canary + scheduled workflow, docs, adjacent-bug follow-up issue, L5 smoke, open PR
- after: T-3
- files: `plugins/maven-mcp/tests/test_live_canary.py` (new), `.github/workflows/maven-mcp-live-canary.yml`
  (new), `plugins/maven-mcp/CLAUDE.md`, `docs/plans/maven-typosquat-signal/progress.md`
- acceptance: THE SYSTEM SHALL first add ONE separate, non-default-suite live-canary test
  (`test_live_canary.py`, NOT collected by the default `unittest discover -s
  plugins/maven-mcp/tests` invocation — gate it behind an explicit opt-in, such as requiring an env
  var or a distinct `-p` pattern) that issues a REAL request to `https://api.osv.dev/v1/querybatch`
  for `io.github.leetcrunch:scribejava-core` and asserts a `MAL-` id comes back — this is the only
  thing that can detect OSV.dev/OSSF convention drift (a mocked fixture cannot). THEN add a REQUIRED
  (not optional/future-work — cycle-2 correction) weekly-schedule GitHub Actions workflow
  (`.github/workflows/maven-mcp-live-canary.yml`) that runs this test and fails loud on drift — a
  manually-invoked-only canary provides no actual ongoing protection, so the schedule is what makes
  this mitigation real. THEN document, in `plugins/maven-mcp/CLAUDE.md`: (a) `typosquatRisk` in
  the `verify_coordinates` section — shape, `exists`-only population, the five named constants
  (including `MAX_GATED_SOLR_CALLS_PER_BATCH`), the gating relationship (group-mismatch and
  recent-first-publish both gated behind `low_version_count` AND the per-batch cap), the
  coverage-boundary note (`group_mismatch` = identical/near-identical-name impersonation,
  `low_version_count` = fallback for edited-name impersonation, PLUS the accepted
  gating-coupling-evasion residual risk), the "candidate to verify, not a verdict" framing,
  explicit statement that `likelyHallucination` is unchanged/separate; (b) the
  `malicious` field wherever `get_dependency_vulnerabilities`'s output shape is documented — `MAL-`
  id-prefix derivation, requires a pinned version (querybatch contract), version-less coordinates
  out of scope, AND in the SAME doc bullet the "best-effort convention, not schema-guaranteed"
  caveat (`malicious: false` means "not currently flagged under this convention", not "verified
  non-malicious"); (c) the two new hook decision-policy branches in the Hooks section (including
  the unconditional-vs-guarded `DECISION=` distinction and the cross-coordinate precedence
  guarantee), alongside the existing absent/unknown/exists/CVE branches; (d) **correct** the
  Environment section's persistent-file-cache sentence ("the entire `verify_coordinates` path …
  both are live on every invocation") to carve out the new gated group-mismatch/recent-first-publish
  Solr calls (`use_cache=True`) as the one cached exception — the per-repo existence probe and the
  did-you-mean search remain live-only, unchanged; (e) file a new, separate GitHub issue for the
  adjacent hydration gap (querybatch's bare `{id,modified}` vs. `query_osv_batch`'s dead
  `summary`/`references`/severity extraction), with an explicit severity/priority marker noting the
  write-time guard currently has zero working CVE-severity signal for `exists` coordinates — link
  it from this plan's progress log AND from the PR description, do not fix it here. An L5 stdio
  smoke test: (i) re-query the real `io.github.leetcrunch:scribejava-core`@any-version coordinate
  through `get_dependency_vulnerabilities` end-to-end and confirm `malicious: true` in the live
  (non-mocked) output; (ii) `verify_coordinates` a real low-versionCount `exists` coordinate
  end-to-end and confirm `typosquatRisk.signal: true` AND that the gated group-mismatch/
  recent-first-publish calls actually fired for this case (not just the ungated
  `low_version_count` reason). Then open a ready PR (`Closes #322`, link this plan, link the filed
  follow-up issue, note the CLAUDE.md framing is preserved).
- check: `bash scripts/validate.sh` rc=0; full suite green (existing + all new tests from T-1..T-3,
  live-canary test excluded from the default run per its own gating); the scheduled workflow file
  is valid YAML and its cron expression fires weekly (lint/dry-run, not waiting a full week to
  observe a real run); L5 transcript recorded in `progress.md`; follow-up issue URL recorded in
  `progress.md`; PR open with `python-tests` (3.9/3.13) + `validate-marketplace` green.

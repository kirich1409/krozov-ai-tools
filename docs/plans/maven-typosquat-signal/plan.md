---
type: plan
slug: maven-typosquat-signal
date: 2026-07-01
status: approved
spec: none
risk_areas: [security]
review_verdict: pass
review_blockers: []
review_note: "Cycle 1 (security-expert/architecture-expert/dependency-evaluator, parallel) → FAIL. Blocker (convergent, architecture+dependency-evaluator): unconditional group-mismatch Solr query on every exists coordinate risked search.maven.org 403 lockout — fixed by gating behind low_version_count. Also folded: cross-coordinate deny/ask guard; popularMatch charset filtering; _fetch_gav_timestamp as a new function with _solr_escape on all 3 values; coverage-boundary split; _is_malicious_id helper; live-canary test; CLAUDE.md Environment correction; reliance-profile escalation acknowledged; hydration-gap issue wording strengthened. Cycle 2 (same 3 reviewers, re-check + fresh pass) → no blockers, but 5 majors + several minors: (a) gating-coupling evasion (version-count padding suppresses ALL of Layer 2) — accepted as documented residual risk, not re-architected (Layer 2 stays advisory-only); (b) live-canary was manual-only, not actually protective — upgraded to a REQUIRED weekly scheduled GitHub Actions workflow; (c) gating reduces average but not worst-case Solr load on cold-cache/large-batch runs — added MAX_GATED_SOLR_CALLS_PER_BATCH=20 hard cap; (d) versions[0] rationale was factually wrong (claimed XML chronological order; code actually semver-sorts a deduped union) — corrected to 'semver-minimum under a ≤2-version gate' and pinned to the actual local `versions` variable; (e) missing decision on a per-dependency malicious convenience boolean — explicitly declined with rationale. Minor: citation for original OSV.dev integration added (commit bc2390c / #302 / maven-python-migration plan). Cycle 3 (same 3 reviewers, final cycle, cap reached) → all three explicit verdicts READY TO APPROVE, no blockers. Applied trivial corrections found: the per-batch cap's rationale wrongly cited audit_project_dependencies (which never calls handle_verify_coordinates) — corrected to cite a direct verify_coordinates batch at the handler's 100-item cap as the real worst case; pinned the cap's counter to a local variable (not module-level global, given the long-lived stdio process) with an explicit two-invocation regression test; clarified the Open Question on named constants to separate 4 detection-calibration constants from the 1 new operational load-bound constant. PASS."
---

# Plan: active typosquat/popularity signal for existing coordinates (#322)

> Branch `feat/maven-typosquat-signal` off main. Split from #282 per security review. Follow-up to
> `docs/plans/maven-verify-coordinates` (#282, merged) and feeds
> `docs/plans/maven-write-guard-hook` (#283, merged). Implemented in `server.py` + `hooks/pre-edit-deps.sh`.
> stdlib-only, zero new pip dependencies.

## Context & Decision

`verify_coordinates` (#282) detects **non-existent**/one-edit-from-real coordinates (the
"hallucination" shape). It explicitly does NOT flag malicious packages that **do** exist on
Central — `plugins/maven-mcp/CLAUDE.md`'s `verify_coordinates` section states this in bold:
`likelyHallucination: false` means "not a known-fake name", never "verified clean". The dominant
real-world Maven slopsquat vector is a malicious package that IS published (`existenceStatus:
"exists"`) — reported as safe by omission today. #322 asks for an active signal for this case,
consumed by the `pre-edit-deps.sh` write-time hook (#283).

**Decision: two independent layers, not one.** An authoritative cross-check (layer 1) plus a
best-effort heuristic (layer 2), because they cover different failure windows and neither alone is
sufficient:

1. **Layer 1 — malicious-package cross-check, reusing the existing OSV.dev integration.**
   `query_osv_batch()` (`server.py:1297`) already POSTs every dependency to
   `OSV_API = https://api.osv.dev/v1/querybatch`. OSV.dev's documented data sources
   (<https://google.github.io/osv.dev/data/>) list **OpenSSF Malicious Packages** as a current
   source covering Maven — reports use the `MAL-` id prefix (OSSF/OSV documented convention;
   confirmed against a live report, see *Verification & Sources*). **Empirically verified live**
   (not theoretical): `curl -d '{"queries":[{"package":{"name":"io.github.leetcrunch:scribejava-core","ecosystem":"Maven"},"version":"1.0.0"}]}' https://api.osv.dev/v1/querybatch` returns
   `{"results":[{"vulns":[{"id":"MAL-2025-2552","modified":"..."}]}]}` — a real, OSSF-reported
   Maven OAuth-library typosquat that exfiltrates credentials, surfacing through the **exact
   request shape the server already sends**. This is **not a new dependency** in the sense
   `rules/dependencies.md`'s plan-stage gate cares about: same host (`api.osv.dev`), same endpoint,
   same code path, already integrated and already network-approved — only new *interpretation* of
   data already being fetched (tag `id.startswith("MAL-")`). The plan-stage dependency gate does
   not apply; reviewers should not require the 4-point dependency-approval block for this layer.
   No new network call for the existing `get_dependency_vulnerabilities` path — the `pre-edit-deps.sh`
   hook already calls it today. **Provenance (audit-trail citation, review finding):** the
   `api.osv.dev` integration (`query_osv_batch`) was introduced in commit `bc2390c` ("replace npx
   with bundled Python3 MCP server", #302; documented in `docs/plans/maven-python-migration/plan.md`)
   — predating this plan, and predating the current plan-stage dependency-approval gate process; it
   is not something this plan is newly introducing or newly approving, only reinterpreting.

2. **Layer 2 — heuristic signal added to `verify_coordinates`, computed only when
   `existenceStatus == "exists"`.** Catches packages not yet ingested into OSSF malicious-packages
   (there is inherent reporting lag between a malicious publish and a community report). Two
   sub-signals, both sourced from data the tool already fetches or from the already-integrated
   Maven Central Solr search (`search_maven_central`, `SEARCH_API = search.maven.org/solrsearch/select`)
   — no new external host:
   - **Low version count** — free. `_verify_one` already unions `<versions>` across every
     200-answering repo for an `exists` coordinate; `len(union_versions)` is already computed, zero
     extra network I/O.
   - **Group-ownership mismatch** — data-driven, reusing the existing `search_maven_central` +
     `_similarity` machinery from the did-you-mean path (no hardcoded well-known-groupId table to
     maintain). **GATED behind `low_version_count` already firing, NOT run on every `exists`
     coordinate** (revised after review — see *Decisions Made*): `search.maven.org` has a
     documented history of rate-limiting/`403`-locking bulk callers, and an unconditional query on
     every `exists` result (the dominant case in a real batch) risked degrading the shared public
     endpoint for the existing did-you-mean/`search_artifacts` paths too.
   - **Recent first-publish is DOWNGRADED from a first-class sub-signal to an optional, gated
     enrichment** — see *Decisions Made* for why the issue's suggested approach ("recent-first-publish
     via Central search") does not work as a single cheap call against the public API, verified live.

Neither layer is folded into `likelyHallucination`, which stays `absent`-only per the existing,
settled documentation. Both layers get **new, separate output fields** (see *Technical Approach*).

## Technical Approach

### Layer 1 — `malicious` flag on vulnerability entries (authoritative)

`query_osv_batch()` (`server.py:1297-1332`) currently builds each `vuln_info` from the bare
`{id, modified}` querybatch returns (per-vuln `summary`/`references`/severity extraction are dead
code today against real responses — see the *Adjacent finding* decision below). Add a computed
field to each `vuln_info`:

```python
vuln_info["malicious"] = v.get("id", "").startswith("MAL-")
```

`id` IS present on every querybatch entry (confirmed live). `handle_get_dependency_vulnerabilities`
(`server.py:2342`) and `handle_audit_project_dependencies`'s vulnerability path both consume
`query_osv_batch()` output unchanged — the new field flows through both without any handler
change. `vulnerabilityCount` stays the total count (malicious entries are not excluded from it);
callers filter on `malicious` explicitly.

**Version-less coordinates are out of scope.** `/v1/querybatch` requires a `version` per query
(confirmed by OSV's own docs). `pre-edit-deps.sh`'s real inputs (extracted from build-file edits)
virtually always carry a pinned version, so this does not weaken the write-time guard. A
version-less variant (`/v1/query`, single, package-only — confirmed live to return full malicious
records without a version) is documented as explicit future work, not built here.

### Layer 2 — `typosquatRisk` field on `verify_coordinates` (heuristic, `exists`-only)

New field on each `existenceStatus == "exists"` result item (never present on `absent`/`unknown`):

```json
"typosquatRisk": {
  "signal": true,
  "reasons": ["low_version_count", "group_mismatch"],
  "versionCount": 1,
  "popularMatch": {"groupId": "com.google.guava", "artifactId": "guava", "versionCount": 150}
}
```

- `signal` — `true` only when at least one sub-signal fires. Framed identically cautiously to
  existing `suggestions`: **a candidate to verify, not a verdict** — false-positive-prone (a
  legitimately new or niche library also has a low version count).
- `reasons` — which sub-signal(s) contributed, so callers/humans can see *why*, not just a bare
  boolean.
- `versionCount` — `len(union_versions)` from the existence probe (`_verify_one`, `server.py:2717`
  onward) — already computed for every `exists` result, zero new I/O.
- `popularMatch` — present only when group-ownership mismatch fires: the highest-`versionCount`
  Central candidate whose `artifactId` is near-identical (`_similarity(artifactId, cand_a) >=
  GROUP_MISMATCH_SIMILARITY`, a new named constant, proposed `0.95` — near-identical, not
  merely similar) but whose `groupId` differs from the requested one, AND whose `versionCount`
  is meaningfully higher than the requested coordinate's own (`popularMatch.versionCount >
  GROUP_MISMATCH_POPULARITY_RATIO * result.versionCount`, proposed ratio `5`) — this asymmetry is
  what distinguishes "an established, independently-named library that happens to share an
  artifactId" from "an impostor riding a popular name". Constants are named/calibratable, mirroring
  `HALLUCINATION_THRESHOLD`'s existing convention.

**Sub-signal 1 — low version count.** `versionCount <= LOW_VERSION_COUNT_THRESHOLD` (proposed `2`
— a coordinate with 1-2 published versions on Central is either brand new or a fast-abandoned
proof-of-concept; either way it warrants a second look before pinning it in a build file). No new
network I/O — sourced from the existence probe's already-unioned versions.

**Sub-signal 2 — group-ownership mismatch — GATED behind `low_version_count`, NOT unconditional.**
Review correction (architecture + dependency-evaluator independently converged on this as a
blocker): running an extra Solr query on **every** `exists` coordinate — the dominant case in any
real dependency batch, for a hook whose latency is directly user-visible (blocks `Edit`/`Write`) —
is a materially bigger fan-out change than "minor" implies, and
`search.maven.org/solrsearch/select` has a documented history of rate-limiting/`403`-locking bulk
callers (e.g. `aquasecurity/trivy#1173`). The plugin's own `_request_with_retry` only backs off on
429/5xx/transport errors, NOT 403 — a lockout is not retried, it silently degrades to empty
results, and a burst from a direct `verify_coordinates` batch call (the handler's existing 100-item
cap, `handle_verify_coordinates`) with many low-version-count coordinates would also degrade the
EXISTING did-you-mean and `search_artifacts` paths (shared public IP allotment), not just this new
signal. **Scenario correction (review finding, third round): the realistic worst case is a direct
`verify_coordinates` batch at/near its 100-item handler cap, NOT `audit_project_dependencies`** —
`handle_audit_project_dependencies` (`server.py:2529-2658`) never calls `_verify_one`/
`handle_verify_coordinates`; it only calls `fetch_metadata` and `query_osv_batch`, so it cannot
produce `typosquatRisk`/gated Solr calls at all. The cap mechanism below is unaffected (it was
already correctly scoped to `handle_verify_coordinates` in *Affected Modules & Files*) — only the
narrative citing `audit_project_dependencies` as a trigger was inaccurate and is corrected here.

**Fix: only issue this query when `low_version_count` has already fired.** A typosquat
impersonating a popular package is virtually always also low-version-count, so this loses little
detection power while keeping the hot/common path (well-established, high-version-count
dependencies — the overwhelming majority of real `exists` verifications) at today's zero-extra-Solr
-call cost. This is the SAME gating pattern already used for `recent_first_publish` below; both
extra Solr calls (group-mismatch, recent-first-publish) now share one precondition:
`low_version_count` fired first.

**Residual risk, addressed with a hard per-batch cap (review finding, second round): gating
narrows AVERAGE load but does not BOUND WORST-CASE load.** A single direct `verify_coordinates`
call near its existing 100-item handler cap (or a monorepo with many recently-published first-party
artifacts passed in one call) can have MANY coordinates simultaneously satisfy `low_version_count`,
producing a burst of gated Solr calls that caching cannot help with on a cold cache, and that gating
alone does not cap. Add a new named constant `MAX_GATED_SOLR_CALLS_PER_BATCH` (proposed `20`,
mirroring `_SUGGEST_SEARCH_ROWS`'s existing scale) enforced in `handle_verify_coordinates` via a
counter created FRESH as a LOCAL variable at the top of each `handle_verify_coordinates` call
(explicitly NOT a module-level/global variable — this is a long-lived stdio server process, so a
global counter would accumulate across the process lifetime instead of resetting per batch, a
review-found correctness trap) across the whole `dependencies` batch (shared per-call counter, not
per-coordinate): once the cap is reached, remaining coordinates in the SAME batch skip the gated
group-mismatch/recent-first-publish calls and fall back to `low_version_count`-only `reasons` (same
silent-degrade-on-failure pattern already used elsewhere — never raise, never block the batch).
This directly closes the "gated OR rate-limited" half of the original ask that gating alone left
open.

When gated-in, query `search_maven_central(_solr_escape(artifactId), _SUGGEST_SEARCH_ROWS,
use_cache=True)` (same helper the did-you-mean path already uses; cache is safe here — this is not
the did-you-mean live-only path, it's a defense-in-depth check, not the anti-steering-critical
suggestion list) for the `exists` coordinate's own `artifactId`. Filter candidates by
`_similarity(artifactId.lower(), cand_a.lower()) >= GROUP_MISMATCH_SIMILARITY` and `cand_g !=
groupId`; if any remain, take the one with the highest `versionCount` as `popularMatch`, and flag
`group_mismatch` only if the popularity-ratio condition above holds. **Data-driven, not a curated
table** (see *Decisions Made* for the rejected alternative and why) — reuses existing Solr
infrastructure, no new maintenance burden.

**Coverage boundary, documented explicitly (not left implicit).**
`GROUP_MISMATCH_SIMILARITY=0.95` targets identical/near-identical-artifactId impersonation (an
attacker reusing a popular name verbatim under a different `groupId`). It will likely NOT catch an
attacker who *also* edits the artifactId itself (a 1-edit-distance typo under an unrelated
groupId) — that shape may score below 0.95 depending on name length. `low_version_count` is the
intended fallback for the edited-name-impersonation shape (a freshly-typosquatted name is still
low-versionCount, and — since group-mismatch is now gated behind it — is exactly the case that
still gets the group-mismatch check run against it too). Document this division of coverage in
`CLAUDE.md` rather than leaving it as an unstated gap; add an explicit test: "artifactId is a
1-edit-distance typo of a popular name AND groupId differs AND versionCount is low" confirms at
least one sub-signal (here, both) fires.

**Additional accepted residual risk from the gating fix itself (review finding, second round —
documented, not re-architected further):** because `group_mismatch` and `recent_first_publish` are
now BOTH gated behind the single `low_version_count` precondition (the fix for the 403-lockout
risk above), an attacker aware of this design can publish a handful of trivial version bumps
immediately after a typosquat lands (Maven Central has no publish review gate, so this is cheap) to
push `versionCount` above `LOW_VERSION_COUNT_THRESHOLD` — which suppresses ALL of Layer 2
simultaneously, not just the version-count signal alone, for exactly the "OSSF hasn't reported it
yet" reporting-lag window Layer 2 exists to cover. This is accepted as a documented residual gap
(see *Risks & Mitigations*) rather than solved by further re-architecting the gate: decoupling
`recent_first_publish` from the gate (a cheap, exact-match, single-row query, unlike
`group_mismatch`'s broad candidate search) was considered as an alternative but rejected for this
round to avoid re-introducing an unconditional-per-`exists`-coordinate Solr call pattern before its
own load profile is proven safe — Layer 2 is a heuristic, advisory-only (`ask`, never `deny`) layer
regardless, and Layer 1's authoritative `deny` path is unaffected by this coupling.

**Recent first-publish — gated, best-effort enrichment, NOT a required sub-signal for `signal`.**
Empirically verified live: `search.maven.org/solrsearch/select` (the `SEARCH_API` host already
integrated) **ignores a client-supplied `sort` override on the public `core=gav` endpoint** —
`curl "...&core=gav&sort=timestamp+asc"` returns `responseHeader.params.sort` unchanged as
`"score desc,timestamp desc,g asc,a asc,v desc"` (verified against `com.google.guava:guava`,
`numFound: 150`). There is **no single cheap request that returns the oldest (first-publish)
version** — fetching all versions and taking the min would require paginating `numFound` docs
(could be thousands for a popular artifact), which is neither cheap nor bounded. This directly
contradicts the issue's "very-recent first-publish date via Central search" framing as a simple
add-on; the plan does not build it as originally suggested. **What IS cheap and feasible, with a
corrected rationale (review finding — the original "chronological XML order" claim was wrong):**
in `_verify_one`, the in-scope variable at this point is `versions = sorted(union_versions,
key=functools.cmp_to_key(compare_versions))` (`server.py:2764`) — a semver-ascending sort over a
`set()`-deduplicated UNION across repos, which destroys any original document order entirely.
`versions[0]` is therefore the **semver-minimum**, not necessarily the chronologically-first-
published version — the two coincide only when version numbers happen to increase monotonically
with release time (the common case, but not a guarantee, and NOT an XML-document-order convention,
which this code path never reads). Pin the implementation explicitly to this local `versions`
variable (not the per-repo `parsed["versions"]`, which reflects only one repo's raw response and
would be strictly worse — an arbitrary single repo's view, not the merged one). Document this as
"semver-minimum under a ≤2-version gate is a reasonable, but imperfect, first-publish proxy" — the
actual limitation, not the XML-order framing. Impact stays bounded regardless: this only affects an
advisory `reasons` tag on an already-`ask` decision, gated behind `low_version_count` (≤2
versions), where semver-min vs. chronological-first only diverges in a pathological publish-order
case. If, and only if, `low_version_count`
already fired (group-mismatch, per the fix above, is now itself gated behind the same
precondition, so this enrichment's gate is effectively "`low_version_count` fired", whether or not
`group_mismatch` also fired), do ONE targeted `core=gav` query filtered to that exact known version
string to fetch its `timestamp` (epoch millis, a field the docs already confirm exists on
`gav`-core docs) and compare against `now`. Add `recent_first_publish` to `reasons` when `now -
timestamp <= RECENT_PUBLISH_DAYS_THRESHOLD` (proposed `30` days). This is an **additional
enrichment reason on top of an already-fired signal, never a signal on its own** — it never turns a
`signal: false` into `signal: true` by itself, because the "cheap oldest version" premise did not
survive the live check.

**Implementation correction (review finding): this is NOT a call to the existing
`search_maven_central` helper.** `search_maven_central()` (`server.py:1339-1357`) hard-codes an
implicit-default-core request and its response transform only extracts
`g`/`a`/`latestVersion`/`versionCount` — it has no `core` parameter and would silently drop
`timestamp` even if Solr returned it. The `core=gav` + exact-version query needed here is a
**different request shape against the same host**, requiring a new small function, e.g.
`_fetch_gav_timestamp(group_id, artifact_id, version) -> Optional[int]`, that builds
`f"{SEARCH_API}?q={quote('g:\"{g}\" AND a:\"{a}\" AND v:\"{v}\"')}&core=gav&rows=1&wt=json"` (using
`http_get`/`http_get_cached` per the existing HTTP seam) and returns the single doc's `timestamp`
(or `None` on any non-200/parse failure — silent degrade, never raise). **All three interpolated
values (`group_id`, `artifact_id`, AND the version string) MUST go through `_solr_escape` before
building this query** — `verify_coordinates` is a directly callable MCP tool (not gated by the
hook's own charset pre-filter), and Maven Central version strings are not guaranteed
alnum-only, so missing escaping here is a Solr query-syntax injection/match-broadening risk. Listed
as its own row in *Affected Modules & Files* (not folded into the group-mismatch bullet, since it's
new code, not a new call site against existing code) with a boundary test asserting a
groupId/artifactId/version containing Lucene special characters (`"`, `:`, `(`, `)`) still produces
a well-formed, correctly-scoped query.

### Hook integration (`plugins/maven-mcp/plugin/hooks/pre-edit-deps.sh`)

Current decision policy (`CLAUDE.md` Hooks section, hook lines ~336-449):

- `absent + (likelyHallucination==true OR non-empty suggestions)` → `deny`
- `absent + no signal` → `allow`
- `unknown` → `allow`
- `exists` → `allow`
- CRITICAL/HIGH CVE on versioned coord → `ask`
- `deny` wins over `ask`

New branches (added, existing branches unchanged):

- `exists` + any `vulnerabilities[].malicious == true` (Layer 1, from the SAME
  `get_dependency_vulnerabilities` call the hook already makes) → **`deny`**, set
  UNCONDITIONALLY (never behind a `[ -z "$DECISION" ]`-style guard) — same tier as
  `absent + likelyHallucination`; a confirmed OSSF-reported malicious package must never be
  silently allowed through, and must not be downgraded to `ask` just because a severity field is
  absent (see *adjacent finding* below — MAL- entries carry no CVSS severity, so the existing
  CRITICAL/HIGH branch would never catch this even if hydration were fixed). Setting it
  unconditionally (not conditionally) matters for correctness: it is what lets a prior `ask`
  (from the existing, currently-dead CRITICAL/HIGH branch, or from the new heuristic branch below)
  get correctly upgraded to `deny` when both fire in the same run, and stays correct once the
  hydration gap is eventually fixed and that branch becomes live.
- `exists` + `typosquatRisk.signal == true` (Layer 2, from `verify_coordinates`) → **`ask`**,
  guarded exactly like the existing CRITICAL/HIGH branch: `[ "$DECISION" = "deny" ] ||
  DECISION="ask"` (advisory only — heuristic, false-positive-prone; must not `deny` on this
  alone, and must not clobber a `deny` already set by an EARLIER coordinate in the same batch —
  this branch lives in the same per-coordinate loop as the `absent`+hallucination `deny` check, so
  the guard is what prevents a later coordinate's heuristic `ask` from silently downgrading an
  earlier coordinate's `deny` within one hook invocation). Reason string built from
  `typosquatRisk.reasons` + `popularMatch` (same `jq -n --arg` structured-field construction the
  hook already uses for did-you-mean suggestions — never interpolate raw content).
  **`popularMatch.groupId`/`popularMatch.artifactId` MUST go through the identical
  charset filter (`[A-Za-z0-9._:-]`) already applied to `suggestions` before entering the reason
  string** — they originate from the same Solr search results as `suggestions` and are equally
  attacker-influenceable in principle (an adversarial Central-hosted package could otherwise craft
  `groupId`/`artifactId` text that flows into `permissionDecisionReason`, which the agent then
  reads — the same indirect-injection surface the existing `suggestions` filter already guards
  against).
- `deny` still wins over `ask` when multiple branches fire (unchanged precedence rule; now also
  covers deny-from-malicious vs ask-from-heuristic, AND deny-on-coordinate-A vs
  ask-on-coordinate-B within the same batch — see the explicit cross-coordinate test in *Affected
  Modules & Files*).

### Documentation updates

`plugins/maven-mcp/CLAUDE.md`:
- `verify_coordinates` section: document `typosquatRisk` (shape, when populated, the four named
  thresholds, the gating relationship between the three sub-signals/enrichment, the
  coverage-boundary note — `group_mismatch` targets identical/near-identical-name impersonation,
  `low_version_count` is the fallback for edited-name impersonation — and the "candidate to verify
  not a verdict" framing) immediately after the existing `likelyHallucination` bullet — explicitly
  note it is a SEPARATE field, `likelyHallucination`'s semantics are unchanged.
- Repository resolution / vulnerabilities section (wherever `query_osv_batch`/
  `get_dependency_vulnerabilities` output shape is documented): document the new `malicious` field
  per vulnerability entry, its `MAL-` id-prefix derivation, that it requires a pinned version
  (querybatch contract), and — in the SAME doc bullet, not only in this plan's Decisions/Risks
  tables — that this is a **best-effort convention** (OSSF Malicious Packages reports observed to
  use this prefix), **not a schema-guaranteed contract**: `malicious: false` means "not currently
  flagged under this convention", not "verified non-malicious" (mirrors how `likelyHallucination`'s
  "never means safe" caveat already travels with the field's own doc, not only a design doc).
- **Environment section (persistent file cache) — REQUIRED correction, not just an addition.** The
  existing sentence "the entire `verify_coordinates` path — … both are live on every invocation" is
  made FALSE by this plan (the gated group-mismatch/recent-first-publish Solr calls use
  `use_cache=True`). Amend that sentence to carve out the new gated calls as the one cached
  exception within `verify_coordinates` — the per-repo existence probe and the did-you-mean search
  remain live-only, unchanged.
- Hooks section: document the two new decision-policy branches above, including the unconditional-
  vs-guarded `DECISION=` assignment distinction (Layer 1 unconditional, Layer 2 guarded) and the
  cross-coordinate deny-then-ask precedence guarantee.
- Keep the existing "never means safe" framing intact — the new signals narrow, but do not close,
  the residual gap (Layer 2 is heuristic; Layer 1 depends on OSSF's reporting lag AND the `MAL-`
  convention holding). Do not oversell as "verified clean" anywhere in the new prose.

### Sequencing (explicit, since field names are a blocking Open Question)

Implementation order matters here because the hook script and hook tests hardcode the exact field
names in `jq` queries: (1) `server.py` fields (`malicious`, `typosquatRisk`) + the four named
constants + their unit tests green, with field names LOCKED (user sign-off on the Open Questions
below) before starting; (2) hook script branches + hook tests, which depend on (1)'s exact field
names; (3) `CLAUDE.md` docs, last, describing the shipped shape. Do not start (2) against
provisional/guessed field names.

## Affected Modules & Files

| Path | Change | Note |
|---|---|---|
| `plugins/maven-mcp/plugin/server/server.py` | Modified | `query_osv_batch`: add a `_is_malicious_id(id) -> bool` helper (`id.startswith("MAL-")`) alongside the existing `_extract_severity`/`_extract_fixed_version`/`_extract_url` extractor-function convention, and set `vuln_info["malicious"] = _is_malicious_id(v.get("id", ""))`. `_verify_one`/`handle_verify_coordinates`: add `typosquatRisk` computation (low-version-count sub-signal; group-mismatch sub-signal GATED behind low-version-count; recent-first-publish enrichment GATED behind low-version-count); a shared per-batch counter enforcing `MAX_GATED_SOLR_CALLS_PER_BATCH`; new named constants `GROUP_MISMATCH_SIMILARITY`, `GROUP_MISMATCH_POPULARITY_RATIO`, `LOW_VERSION_COUNT_THRESHOLD`, `RECENT_PUBLISH_DAYS_THRESHOLD`, `MAX_GATED_SOLR_CALLS_PER_BATCH`. No change to `likelyHallucination`, `fetch_metadata`, `check_version_in_repos` contracts. |
| `plugins/maven-mcp/plugin/server/server.py` (new helper, separate line item — NOT a `search_maven_central` call site) | Modified | New `_fetch_gav_timestamp(group_id, artifact_id, version) -> Optional[int]`: builds a `core=gav`, exact-version Solr query (`_solr_escape` on ALL THREE interpolated values), returns the single doc's `timestamp` or `None` on any failure (silent degrade, never raise). `search_maven_central()` itself is UNCHANGED (no `core` param added to it — it stays the did-you-mean/group-mismatch helper it already is). |
| `plugins/maven-mcp/tests/test_maven_search_osv.py` | Modified | `malicious` flag: `MAL-` prefixed id → `true`; ordinary `GHSA-`/`CVE-`/`PYSEC-` style id → `false`; empty `id` → `false`; flows through `handle_get_dependency_vulnerabilities` and `handle_audit_project_dependencies` unchanged (both surfacing `malicious` per-entry only — no new aggregate convenience boolean, per Decisions Made). |
| `plugins/maven-mcp/tests/test_live_canary.py` (new file, separate from the default suite) | New | ONE live-canary test (real network, NOT collected by the default `unittest discover -s plugins/maven-mcp/tests` invocation — gated behind an explicit opt-in marker/env var) that re-queries the real `io.github.leetcrunch:scribejava-core` MAL-2025-2552 coordinate against the live `api.osv.dev` endpoint and asserts a `MAL-` id comes back — this is what actually detects OSV.dev/OSSF convention drift (a mocked fixture cannot). |
| `.github/workflows/` (new scheduled workflow file, e.g. `maven-mcp-live-canary.yml`) | New | REQUIRED (cycle-2 correction, not deferred future work): a weekly-schedule GitHub Actions workflow that invokes `test_live_canary.py` and fails loud (workflow failure / notification) on drift — a manually-invoked-only canary provides no actual ongoing detection, so this is what makes the canary mitigation real rather than aspirational. |
| `plugins/maven-mcp/tests/test_verify_coordinates.py` | Modified | `typosquatRisk` absent on `absent`/`unknown`; present (possibly `signal:false`) on every `exists`; low-version-count fires alone (assert the group-mismatch Solr call is NOT issued when low-version-count did not fire — call-count assertion, proves the gate); group-mismatch fires only above similarity+ratio thresholds AND only when gated-in; a coincidentally-shared short artifactId with a *comparable* versionCount must NOT fire; a 1-edit-distance-typo-of-a-popular-name + different-group + low-versionCount case confirms at least one sub-signal fires (coverage-boundary test); `recent_first_publish` reason only appears when gated by `low_version_count` firing AND the targeted single-version Solr call (mocked `_fetch_gav_timestamp`) returns a recent timestamp; a groupId/artifactId/version containing Lucene special characters (`"`, `:`, `(`, `)`) still produces a well-formed `_fetch_gav_timestamp` query (boundary test); `likelyHallucination` unaffected by any of the above (regression). |
| `plugins/maven-mcp/plugin/hooks/pre-edit-deps.sh` | Modified | new `malicious`-vuln `deny` branch, set UNCONDITIONALLY (checked alongside/before the existing CRITICAL/HIGH `ask` scan); new `typosquatRisk.signal` `ask` branch using the SAME `[ "$DECISION" = "deny" ] || DECISION="ask"` guard as the existing CRITICAL/HIGH branch; `popularMatch.groupId`/`artifactId` charset-filtered identically to `suggestions` before entering the reason string; `deny` still wins; Bash 3.2 compatible (no `declare -A`, no `${var,,}`, no `mapfile`). |
| `plugins/maven-mcp/tests/test_pre_edit_hook.py` | Modified | stub server responses covering: `exists` + `malicious:true` vuln → `deny`; `exists` + `typosquatRisk.signal:true` → `ask`; `exists` + both a malicious vuln AND a typosquat signal (same coordinate) → `deny` wins; a batch of TWO coordinates where coordinate A is `absent`+hallucination (deny) and coordinate B (a different coordinate in the same run) is `exists`+`typosquatRisk.signal` (would-be ask) → overall decision stays `deny` (cross-coordinate precedence test, the specific gap the anti-downgrade-guard fix addresses); a fabricated CRITICAL/HIGH `severity` (stub-injected, since the real hydration gap makes this unreachable live today) processed BEFORE the malicious-vuln check in loop order → still ends in `deny` (locks in the ordering guarantee ahead of the hydration-gap fix); `exists` + neither signal → `allow` (unchanged); existing absent/unknown/CVE cases stay green (regression); reason strings never embed raw `popularMatch`/`id` content outside the `--arg`-passed, charset-filtered path. |
| `plugins/maven-mcp/CLAUDE.md` | Modified | document `typosquatRisk` (incl. coverage-boundary + gating relationship), the `malicious` vuln field (incl. "convention not schema guarantee" caveat in the SAME doc bullet), the two new hook branches (incl. unconditional-vs-guarded distinction), and the Environment-section cache-exemption correction, per *Documentation updates* above. |

## Decisions Made

| Decision | Rationale | Alternatives rejected |
|---|---|---|
| Two independent layers (authoritative OSV cross-check + heuristic) rather than one | Different failure windows: OSSF reporting has lag (heuristic catches brand-new malware); the heuristic alone is false-positive-prone (authoritative cross-check gives a confident `deny`) | Heuristic-only (issue's literal "e.g." list) — no confident `deny` path, everything degrades to advisory `ask`; feed-only — misses anything not yet reported to OSSF |
| Layer 1 reuses the existing OSV.dev integration (`MAL-` id-prefix tag), not a new feed/dependency | Empirically verified live: OSSF Malicious Packages is already an OSV.dev data source, already reachable through the exact request shape `query_osv_batch` sends today; zero new host, zero new dependency, zero new network-call pattern | A separate `ossf/malicious-packages` GitHub-hosted feed integration (new host, new parsing, new caching) — redundant, since OSV.dev already aggregates it; would need the dependency-approval gate for no added benefit |
| Recent-first-publish downgraded from sub-signal to gated, best-effort enrichment | Empirically verified live: `search.maven.org/solrsearch/select`'s public `core=gav` endpoint ignores a client `sort` override (confirmed against `com.google.guava:guava`) — there is no single cheap request for "oldest version"; fetching all versions to find the min is unbounded (`numFound` can be in the thousands) | Building it as originally proposed by the issue ("very-recent first-publish date via Central search" as a primary sub-signal) — does not survive the live check; silently keeping it as a "cheap" claim would repeat the mistake the project's global rule on empirical verification exists to prevent |
| Group-ownership mismatch is data-driven (reuse `search_maven_central`/`_similarity`), not a curated well-known-groupId table | Zero maintenance burden; consistent with the existing did-you-mean ranking approach; a static table needs indefinite manual upkeep and inevitably misses libraries not on the list | Curated table (e.g. `{"guava": "com.google.guava", ...}`) — higher precision on well-known libraries but requires ongoing manual maintenance; documented here as rejected, not silently discarded |
| `typosquatRisk` is a NEW, separate field; `likelyHallucination` semantics untouched | Issue + existing docs are explicit these are two different concerns that must not be conflated | Extending `likelyHallucination` to also mean "exists but suspicious" — directly contradicts the settled, documented `absent`-only semantics and the #282 plan's scope boundary |
| `malicious` flag lives on `get_dependency_vulnerabilities`'s vulnerability entries, not on `verify_coordinates` | The hook already calls both tools; no new tool call needed; keeps each tool's concern separate (existence/similarity vs. vulnerability data) matching the existing two-tool architecture | Adding a redundant OSV lookup inside `verify_coordinates` itself — duplicate network call, duplicate logic, and blurs tool responsibilities |
| Malicious-vuln → `deny` unconditionally (not gated on severity) | MAL- entries carry no CVSS severity (confirmed: querybatch returns only `{id, modified}`); gating on severity would make the branch permanently dead, exactly like the existing CRITICAL/HIGH branch (see adjacent finding) | Requiring severity presence before denying — silently neuters the entire signal |
| Heuristic `typosquatRisk.signal` → `ask`, never `deny` | False-positive-prone by construction (legitimate new/niche libraries have low version counts too); a hard `deny` on a heuristic would block legitimate work | `deny` on heuristic alone — unacceptable false-positive rate for a write-time guard |
| Adjacent hydration gap (severity/summary/references always empty from `query_osv_batch`) is documented and filed as a SEPARATE follow-up issue, not fixed here | Empirically confirmed live and in code: `/v1/querybatch` returns only `{id, modified}` (OSV docs + live curl); `query_osv_batch` nonetheless reads `.get("summary")`/`_extract_url`/`_extract_severity` off that same bare response, so those fields are always empty/absent today, and the hook's existing CRITICAL/HIGH `ask` branch (`pre-edit-deps.sh` `select(.severity=="CRITICAL" or .severity=="HIGH")`) never matches in practice — meaning, right now, before and after this plan, the write-time guard has ZERO working CVE-severity signal for `exists` coordinates; only the new `malicious` deny branch narrows this (for OSSF-reported malicious packages specifically, not general CVEs). Fixing this needs a per-id hydration call (`GET /v1/vulns/{id}`, extra network cost per finding) — a genuinely separate, larger design decision, out of scope for #322's ask, but must not be silently lost. File it now with a severity/priority marker reflecting a currently-non-functional documented security control, cross-linked from this plan's PR description — not just left in a markdown table | Fixing it inline as part of this plan — scope creep on a pre-existing, unrelated bug; silently ignoring it — the discovery would be lost; filing it later/informally — risks the marker being lost the same way the bug itself was |
| Group-mismatch Solr query is GATED behind `low_version_count` firing (revised after review, was originally unconditional on every `exists` coordinate) | `search.maven.org` has a documented rate-limiting/`403`-lockout history under bulk load (`aquasecurity/trivy#1173`); `_request_with_retry` does not retry 403; an unconditional query on the dominant `exists` case in a real batch risked degrading the shared public endpoint for the EXISTING did-you-mean/`search_artifacts` paths too, not just this new feature — a typosquat impersonating a popular package is virtually always also low-version-count, so gating loses little detection power | Unconditional query on every `exists` coordinate (the plan's original design) — real, evidenced lockout risk on a shared public resource, understated as "minor" |
| `_fetch_gav_timestamp` is a NEW function, not an extended call to `search_maven_central` | `search_maven_central()` hard-codes an implicit-default-core request and only extracts `g`/`a`/`latestVersion`/`versionCount` — it cannot express `core=gav` or surface `timestamp`; claiming "reuse" here would understate real new code | Adding a `core`/`extra_fields` parameter to `search_maven_central` itself — conflates two different response shapes (candidate-search docs vs. a single gav-core doc) in one function |
| Malicious-vuln `deny` is set UNCONDITIONALLY in the hook; the new `typosquatRisk` `ask` is set with the SAME guard pattern (`[ "$DECISION" = "deny" ] || DECISION="ask"`) as the existing CRITICAL/HIGH branch | Correctness requirement discovered in review: without the guard, a heuristic `ask` fired for a LATER coordinate in the same batch could silently downgrade a hard `deny` already set for an EARLIER coordinate — the plan's original text stated the precedence rule but didn't specify guard placement precisely enough to prevent this cross-coordinate bug | An unguarded `ask` assignment (implicit in the plan's original phrasing) — a real, testable correctness gap, not just a style nit |
| `popularMatch.groupId`/`artifactId` go through the identical charset filter already applied to `suggestions` before entering the hook's reason text | Both originate from the same Solr search results and are equally attacker-influenceable in principle; the existing `suggestions` filter exists precisely because this text flows into `permissionDecisionReason`, which the agent then reads (indirect-injection surface) | Treating `popularMatch` as lower-risk than `suggestions` because it is a new field — no basis for that distinction; same data source, same surface |
| NO per-dependency-result convenience `malicious: bool` (aggregate over `vulnerabilities[]`) is added — explicitly declined, not a silent omission (cycle-2 review finding) | Callers already iterate `vulnerabilities[]` for severity/id/etc.; a redundant top-level boolean adds no new capability over `any(v["malicious"] for v in vulnerabilities)`, which any JSON/jq consumer (including the hook itself) already expresses trivially | Adding the convenience field for symmetry with `likelyHallucination` — `likelyHallucination` is a convenience over a `suggestions` array with no other reliable boolean signal in it; `vulnerabilities[].malicious` is already a first-class boolean per-entry, so the symmetry argument doesn't carry the same weight |
| Reliance-profile on the existing `api.osv.dev` integration is explicitly acknowledged as escalating (advisory → blocking), not treated as risk-free just because the artifact isn't new | Today, an OSV.dev failure/staleness only degrades an advisory `ask` (a missed CVE). After this plan, the SAME failure mode (OSV drops the malicious-packages source, or the `MAL-` convention shifts) means a confirmed malicious package could silently pass the exact `deny` gate built to catch it — a real increase in what this plan trusts the integration to do, independent of whether a NEW artifact was added | Treating "not a new dependency" as equivalent to "no new risk to review" — conflates artifact-identity with reliance-criticality, two different questions |
| A live canary test (real network call against `api.osv.dev`, kept separate from the default mocked unit suite) supplements the mocked `MAL-` regression test, run on a REQUIRED weekly GitHub Actions schedule (not manually-invoked-only) | A mocked-fixture regression test only proves the code branch works against a value the test author chose — it cannot detect the LIVE external assumption breaking (OSV.dev dropping the source, or relabeling the id scheme); a manually-invoked-only canary (this plan's cycle-1 design) provides no ACTUAL ongoing detection — the exact gap it exists to close persists until a human remembers to run it, which is the same reliability profile as having no canary at all | Relying on the mocked regression test alone — catches code regressions, not live convention drift; a manually-invoked-only canary (rejected in cycle 2) — technically buildable but not wired to run, so it doesn't close the loop it claims to |
| Group-mismatch/recent-first-publish's shared `low_version_count` gate is documented as an ACCEPTED residual evasion path (version-count padding), not further re-architected this round | Decoupling `recent_first_publish` from the gate was considered but rejected: it would reintroduce an unconditional-per-`exists`-coordinate Solr call before that specific call's load profile (cheap, exact-match, rows=1) is proven safe in production; Layer 2 is advisory-only (`ask`, never `deny`) regardless, so the residual gap does not weaken Layer 1's authoritative `deny` path | Decoupling `recent_first_publish` now — adds complexity/re-introduces a load-profile question this round explicitly deferred rather than resolves it cleanly; silently ignoring the coupling — the evasion path would go undocumented |
| `MAX_GATED_SOLR_CALLS_PER_BATCH=20` hard cap on gated Solr calls across one `verify_coordinates` batch invocation | Gating behind `low_version_count` reduces AVERAGE load but does not BOUND WORST-CASE load on a cold-cache/large-batch run where many coordinates simultaneously qualify; a hard per-batch cap closes the "gated OR rate-limited" half of the original ask that gating alone left open | Gating alone (this plan's cycle-1 fix) — reduces average case but leaves worst-case burst unbounded, which is exactly the failure mode (bulk-scan lockout) the fix was meant to prevent |
| The realistic worst-case scenario motivating the per-batch cap is a direct `verify_coordinates` call at/near its 100-item handler cap — NOT `audit_project_dependencies` (correction, cycle-3 review) | Verified against code: `handle_audit_project_dependencies` (`server.py:2529-2658`) never calls `_verify_one`/`handle_verify_coordinates` — it only calls `fetch_metadata` and `query_osv_batch`, so it cannot produce `typosquatRisk` or trigger the gated Solr calls at all; the cap's actual implementation target (`handle_verify_coordinates`, already correctly named in *Affected Modules & Files*) is unaffected — only the narrative was wrong | Leaving the `audit_project_dependencies` framing uncorrected — would misdirect a future reader trying to reproduce or extend the load-bound reasoning |
| `MAX_GATED_SOLR_CALLS_PER_BATCH`'s counter MUST be a local variable created fresh at the top of each `handle_verify_coordinates` call, never a module-level/global variable | `server.py` runs as a long-lived stdio process — a global counter would accumulate gated-call usage across the ENTIRE process lifetime (silently degrading Layer 2 for every call after the first 20 gated calls the process ever issues), not reset per batch as intended; this is a correctness trap an implementer could fall into by taking the "shared counter" wording too literally | A module-level counter (an easy but wrong reading of "shared counter, not per-coordinate") — reviewed and explicitly rejected; a two-invocation regression test (call `handle_verify_coordinates` twice, each batch exceeding the cap, assert BOTH calls independently hit `MAX_GATED_SOLR_CALLS_PER_BATCH` gated calls, not the second starting depleted) is added to `test_verify_coordinates.py` to pin this |

## Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| `MAL-` prefix is a convention, not a schema-enforced contract — a future OSV-ingested malicious-package source could use a different id scheme, AND this could drift silently in the LIVE service (not just in code) | major | Document the dependency on the `MAL-` convention explicitly (including in the field's own `CLAUDE.md` doc bullet, not only here); treat detection as best-effort/defense-in-depth for Layer 1 (Layer 2 still catches unreported/differently-labeled cases); a mocked regression test pinned to the convention catches CODE regressions only — it CANNOT detect a live OSV.dev convention change, so a live-canary test (re-querying a known stable `MAL-` id against the real endpoint) is added AND run on a REQUIRED weekly CI schedule (not manually-invoked-only, per cycle-2 correction) specifically to close that gap; even so, a live break between weekly canary runs would degrade Layer 1 silently for up to a week — no stronger real-time (sub-weekly) mitigation is proposed as proportionate for this architecture |
| Group-mismatch/recent-first-publish's shared `low_version_count` gate creates a version-count-padding evasion path — an attacker can publish trivial version bumps to suppress ALL of Layer 2 during exactly the OSSF-reporting-lag window Layer 2 exists to cover | major (new, found in cycle-2 review) | Accepted, documented residual risk (see Decisions Made) rather than further re-architected this round; bounded because Layer 2 is advisory-only (`ask`, never `deny`) — Layer 1's authoritative `deny` path (which does not depend on version count) is unaffected |
| Gating behind `low_version_count` reduces AVERAGE Solr load but does not BOUND WORST-CASE burst load on a cold-cache/large-batch run where many coordinates simultaneously qualify | major (new, found in cycle-2 review) | `MAX_GATED_SOLR_CALLS_PER_BATCH=20` hard cap across one batch invocation; coordinates beyond the cap fall back to `low_version_count`-only `reasons` (silent degrade, never raise/block) |
| Reliance-profile on the existing OSV.dev integration escalates from advisory (`ask`) to blocking (`deny`) even though no new artifact is added | major | Explicitly acknowledged as a deliberate, reviewed trade-off (see Decisions Made) rather than waved off by "no new dependency"; the live canary above is the concrete mitigation for the specific failure mode this escalation is most exposed to (OSV.dev/OSSF convention drift) |
| `typosquatRisk` false positives block legitimate low-adoption/new libraries | major | `ask`, never `deny`, on the heuristic; reasons + `popularMatch` surfaced so a human can override; thresholds named/calibratable constants, not buried magic numbers |
| Group-mismatch data-driven search returns a coincidental high-versionCount candidate for a very common short artifactId (e.g. "core", "util") | major | Require BOTH near-identical similarity (`>=0.95`) AND a popularity-ratio asymmetry (`>5x`) before flagging — a shared generic short name alone must not fire; test explicitly asserts a coincidental-but-comparable-popularity case does NOT flag |
| Unconditional group-mismatch Solr query on every `exists` coordinate risked `403` lockout on the shared `search.maven.org` public endpoint (documented history, e.g. `aquasecurity/trivy#1173`; `_request_with_retry` does not retry 403), degrading the EXISTING did-you-mean/`search_artifacts` paths too — RE-RATED from the plan's original "minor" after review (2 independent reviewers converged on this) | major (was minor; correction) | FIXED at the design level, not just mitigated: group-mismatch is now GATED behind `low_version_count` firing (same pattern as recent-first-publish), so the query only fires for the suspicious minority of `exists` coordinates, not the dominant well-established-dependency case; cached (`use_cache=True`) on top of gating |
| Cross-coordinate decision-precedence bug: an unguarded `ask` assignment for the new `typosquatRisk` branch could silently downgrade a `deny` already set for a different coordinate earlier in the same hook invocation | major (new, found in review) | Fixed at the design level: the new `ask` branch uses the SAME `[ "$DECISION" = "deny" ] || DECISION="ask"` guard as the existing CRITICAL/HIGH branch; explicit cross-coordinate test (coordinate A deny + coordinate B would-be-ask → deny) added |
| `popularMatch` fields could carry attacker-influenced text into the hook's `permissionDecisionReason` (same indirect-injection surface as `suggestions`) if not filtered the same way | major (new, found in review) | Fixed at the design level: `popularMatch.groupId`/`artifactId` go through the identical `[A-Za-z0-9._:-]` charset filter as `suggestions`; explicit test added |
| Gated recent-first-publish enrichment relies on `versions[0]` being the semver-minimum of a deduplicated union (corrected rationale, cycle-2 review — NOT a chronological-XML-order convention as originally claimed), which only approximates first-publish | minor | Documented limitation with the corrected rationale (see Technical Approach + Decisions Made); enrichment-only (never the sole trigger for `signal`), so an approximation error degrades a "reason" string, not the deny/ask decision |
| Adjacent hydration gap (severity always empty) discovered but left unfixed could be missed/forgotten | minor | Explicitly documented in this plan's Decisions Made + filed as a tracked follow-up issue with an explicit priority marker (see Open Questions) before this plan is marked done, cross-linked from the PR description |
| MAL- vuln `deny` on `exists` regresses the existing `exists → allow` fast path for the overwhelming majority (no malicious match) case | minor | `deny` only fires when a `malicious:true` entry is actually present in the vulnerabilities array; ordinary `exists` with no vulnerabilities remains `allow` (existing test coverage extended, not replaced) |
| `MAX_GATED_SOLR_CALLS_PER_BATCH`'s counter could be implemented as a module-level global by mistake, accumulating across the process lifetime instead of resetting per batch (cycle-3 review finding) | minor | Explicit requirement (Decisions Made): local variable created fresh at the top of each `handle_verify_coordinates` call; two-invocation regression test pins that a second call gets a fresh budget |
| The per-batch cap's counter has no ordering guarantee across coordinates within a batch — a later genuinely-suspicious coordinate could exhaust the cap before being reached if many earlier coordinates in the same batch also qualify (cycle-3 review finding) | minor | Low-realism in the `pre-edit-deps.sh` threat model (a typosquat publisher controls their own package's metadata, not the composition of a victim's dependency batch); accepted as-is given the cap already degrades to `low_version_count`-only (never blocks) rather than erroring |

## Verification & Sources

| Source of truth | Type | Status | Sufficient? |
|---|---|---|---|
| Issue #322 (requirements + candidate signals) | requirements | present | yes — defines the problem and lists candidate approaches (not prescriptive) |
| `plugins/maven-mcp/CLAUDE.md` `verify_coordinates` + Hooks sections | existing contract / before-state baseline | present | yes — defines what must NOT change (`likelyHallucination` semantics, tri-state existence, existing hook branches) |
| Live `curl` against `https://api.osv.dev/v1/querybatch` with a real OSSF-reported Maven malicious package (`io.github.leetcrunch:scribejava-core`, `MAL-2025-2552`) | empirical verification | present, captured above | yes — proves Layer 1's core premise against the actual production endpoint, not documentation alone |
| Live `curl` against `https://search.maven.org/solrsearch/select?core=gav&sort=timestamp+asc` (`com.google.guava:guava`) | empirical verification | present, captured above | yes — proves the recent-first-publish sub-signal does NOT work as originally proposed, driving the plan's gated/downgraded design |
| `plugins/maven-mcp/tests/test_maven_search_osv.py`, `test_verify_coordinates.py`, `test_pre_edit_hook.py` (existing suites) | before-state baseline | present | yes — full green baseline before this change; new tests extend, existing tests must stay green (regression gate) |

**Testing strategy:** L0 build (`python3 -m compileall`) + L1 (`bash scripts/validate.sh`) + L2 unit
tests (mock `urllib.request.urlopen` with enumerated call sequences, per existing project
convention) covering: `malicious` flag derivation (MAL- vs non-MAL- vs empty id) and its
pass-through to both consuming handlers; `typosquatRisk` presence/absence by `existenceStatus`;
each sub-signal's fire/no-fire boundary (including the coincidental-short-name non-fire case and
the 1-edit-distance-typo coverage-boundary case); the group-mismatch AND recent-first-publish Solr
calls are NOT issued when `low_version_count` did not fire (call-count assertions proving the gate,
directly addressing the review-found lockout risk); a batch where MOST coordinates simultaneously
satisfy `low_version_count` stays within `MAX_GATED_SOLR_CALLS_PER_BATCH` (assert the cap is
enforced and excess coordinates degrade to `low_version_count`-only `reasons`, not an error); TWO
SEPARATE `handle_verify_coordinates` calls, each individually exceeding the cap, both independently
hit the full `MAX_GATED_SOLR_CALLS_PER_BATCH` budget (proves the counter is a fresh local variable
per call, not an accumulating module-level global — cycle-3 review finding);
`_fetch_gav_timestamp`'s Solr-escaping on all three interpolated values (boundary test with Lucene
special characters); hook decision-policy branches (`deny` on malicious set unconditionally, `ask`
on heuristic set with the guard, `deny` wins within one coordinate AND across two different
coordinates in the same batch, `popularMatch` charset-filtered) via the existing stub-server
`test_pre_edit_hook.py` harness. Plus ONE separate, non-default-suite **live canary test**
(`test_live_canary.py`, real network, opt-in-gated, not part of `unittest discover`'s default run,
but run on a REQUIRED weekly GitHub Actions schedule — not manually-invoked-only) re-querying the
real `MAL-2025-2552` coordinate against the live `api.osv.dev` endpoint — this is what actually
detects OSV.dev/OSSF convention drift, which a mocked fixture cannot. L5 manual: one stdio smoke
test re-querying the SAME real
`io.github.leetcrunch:scribejava-core` MAL-2025-2552 coordinate end-to-end through
`get_dependency_vulnerabilities` to confirm `malicious: true` appears in the live tool output (not
just the mocked unit tests), plus one `exists` coordinate with a deliberately low version count to
confirm `typosquatRisk.signal` fires end-to-end (including the gated group-mismatch/recent-publish
calls actually firing for this specific low-version-count case). No UI surface.

## Out of Scope

- Version-less coordinate malicious-package checking (`/v1/query` single-package variant) — future
  work; `pre-edit-deps.sh`'s real inputs always carry a version.
- Fixing the adjacent `query_osv_batch` hydration gap (severity/summary/references always empty
  from querybatch) — tracked as a separate follow-up issue (see Open Questions), not built here.
- A dedicated `ossf/malicious-packages` GitHub-hosted feed integration — unnecessary; OSV.dev
  already aggregates it and is already integrated.
- A curated well-known-groupId table — explicitly rejected in favor of the data-driven approach
  (documented above as a future option if the data-driven approach proves too noisy in practice).
- Any change to `likelyHallucination`, `fetch_metadata`, `check_version_in_repos` contracts, or the
  existing `absent`/`unknown` hook decision branches.

## Open Questions

- [blocking] Confirm the exact new field names before implementation: `typosquatRisk` (verify_coordinates)
  and `malicious` (vulnerability entries) are proposed names — the issue does not mandate specific
  names and CLAUDE.md's tone favors deliberate, documented naming. User sign-off requested.
- [blocking] Confirm the four DETECTION-CALIBRATION constants are acceptable as a starting
  calibration (not proven against a labeled dataset, same caveat as `HALLUCINATION_THRESHOLD` when
  it was introduced): `LOW_VERSION_COUNT_THRESHOLD=2`, `GROUP_MISMATCH_SIMILARITY=0.95`,
  `GROUP_MISMATCH_POPULARITY_RATIO=5`, `RECENT_PUBLISH_DAYS_THRESHOLD=30`. A fifth constant,
  `MAX_GATED_SOLR_CALLS_PER_BATCH=20`, is a separate, OPERATIONAL load-bound (not a detection
  threshold) and does not need the same labeled-dataset caveat — called out explicitly here so the
  sign-off request is unambiguous about what it covers (clarified per cycle-3 review).
- [blocking] Confirm the adjacent hydration-gap finding (severity/summary/references always empty
  from `query_osv_batch`, dead CRITICAL/HIGH hook branch — meaning the write-time guard currently
  has ZERO working CVE-severity signal for `exists` coordinates) should be filed NOW as a new,
  separate GitHub issue with an explicit severity/priority marker reflecting that this is a
  currently-non-functional, documented security control (recommended), cross-linked from this
  plan's PR description, rather than only living in this plan document.
- [non-blocking] Group-mismatch cached `search_maven_central` call reuses `TTL_SEARCH` (1h) — could
  surface a stale `popularMatch` for a groupId that changed ownership very recently; acceptable
  given this is a defense-in-depth heuristic, not the anti-steering-critical did-you-mean path.
- [non-blocking] Whether `typosquatRisk` should also be computed when a project declares only
  private/non-Central repos (recall limit, same documented limitation class as did-you-mean
  suggestions being Central-Solr-only) — default: same limitation applies, document it, do not
  attempt Google-Maven/plugin-portal equivalents now (relates to #295).
- [resolved, cycle 2] ~~Add a one-line pointer to where the original `query_osv_batch`/OSV.dev
  integration was reviewed/approved~~ — resolved: cited above (commit `bc2390c` / #302 /
  `docs/plans/maven-python-migration/plan.md`).
- [resolved, cycle 2] ~~Whether the live-canary test should run on a schedule vs. remain
  manually-invoked~~ — resolved: a manually-invoked-only canary provides no actual ongoing drift
  detection (the exact gap it was meant to close persists until a human remembers to run it), so
  this plan now commits to a minimal scheduled trigger: a weekly GitHub Actions workflow
  (`.github/workflows/`) that runs the live-canary test and fails loud (issue/notification) on
  drift — see T-4 in `tasks.md`. This is a small, bounded addition relative to the rest of this
  plan and is required, not optional future work.

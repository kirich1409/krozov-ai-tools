---
type: plan
slug: maven-verify-coordinates
date: 2026-06-29
status: approved
spec: none
risk_areas: []
review_verdict: pass
review_blockers: []
review_note: "3 cycles (security/architecture/pr-test-analyzer). C1 FAIL → C2 FAIL → C3 PASS (both blocker-owners: Resolved, no blockers). Folded: tri-state existence probe (absent iff ALL-404; 401/403/429/5xx/transport/mix → unknown), exists≠safe reframe (#322), popularity-aware suggestions (raw score, penalty sort-only, flag over full set), gavExists union across 200-repos, Solr-escape, handler-enforced caps, threshold constant + boundary tests."
---

# Plan: maven-mcp `verify_coordinates` tool (#282)

> Branch `feat/maven-verify-coordinates` off main (d198332). Epic #281 Horizon-1, foundational (enables the #283 write-time hook). Implemented in `server.py` (the issue's `src/tools/*.ts` path is obsolete — TS removed in #303). stdlib-only.

## Context & Decision

LLMs invent ~19.6% of package coordinates (43% recur → predictable slopsquatting; arxiv 2406.10279); Gradle doesn't validate coordinates at edit time. `verify_coordinates` is the batch "does this `g:a` exist, and if not what's the closest real name" primitive the #283 write-time guard consumes. Closes #282.

**Scope boundary (security review):** this tool detects **non-existent** coordinates and **one-edit-from-real** names (slopsquat *shape*). It is NOT a malware/typosquat detector for coordinates that DO exist — a malicious package published to Central reports `existenceStatus: "exists"` and is NOT flagged. The output therefore never asserts "safe": absence of a hallucination signal means "not a known-fake name", not "verified clean". Active typosquat-of-existing detection is a separate follow-up (#322), which the #283 hook will layer on.

## Technical Approach

**New MCP tool `verify_coordinates`** — `handle_verify_coordinates(args)` registered in the tool list + dispatch + input schema. Builds a project-aware `ResolutionContext` via `build_resolution_context(args)` (honors declared repos + optional `projectPath`).

**Tri-state existence via an explicit per-repo probe (NOT `fetch_metadata`'s raise).** The critical design point (3 reviewers converged): `fetch_metadata` collapses "absent (404)" and "unreachable (offline/error)" into one `ValueError`, and discards which repo answered. For a write-time guard that is wrong — offline would make every coordinate look fake. So the handler runs its own probe: for each repo from `_repos_for(g, a, ctx)`, `http_get` the `maven-metadata.xml` URL and classify by the FULL status space (`http_get` returns `(code, b"")` for EVERY HTTP status incl. 401/403/429/5xx, and RAISES only on transport failure — `URLError`/timeout; verified server.py:89-96):
- any repo returns **200** → `existenceStatus: "exists"`; capture the FIRST answering `repository` name; collect the `<versions>` from EVERY 200-answering repo and UNION them (matches the #311 cross-repo merge — a first-hit short-circuit would lose versions a private repo holds).
- **`existenceStatus: "absent"` ONLY when EVERY probed repo returned a definitive `404`.** Any other non-200 status (401/403 auth, 429 throttle, any 5xx) on a repo, OR a raised transport error, OR a mix (e.g. 404 + 503) → `existenceStatus: "unknown"` (verification unavailable — the throttled/auth-protected repo might hold the artifact). This is security-critical: a 429 under load or a 403 from a private Nexus must NOT read as "absent" (which would mass-false-positive the #283 guard).
- Back-compat: `gaExists: bool = (existenceStatus == "exists")`.

**`gavExists`** (only if `version` given): membership of `version` in the UNION of versions across all 200-answering repos (matches `check_version_in_repos` semantics; a version present only in the second repo still → true) — derived from the bodies the probe already fetched, no extra round-trip. `stability`: `classify_version(latest)` ONLY when a non-empty latest exists (a 200 with empty `<versions>` → exists=true, latest=None → OMIT stability, never call classify on None).

**Suggestions (only on `existenceStatus == "absent"`) — popularity-aware, not pure string distance.** Query `search_maven_central(artifactId_token, …)`; `search_maven_central` already returns `versionCount` per candidate (security review). Rank candidates by similarity BUT down-weight very-low-`versionCount` (e.g. brand-new single-version packages — the attacker-registered slopsquat shape): a 1-version near-miss must NOT outrank a high-popularity real coordinate. Each suggestion `{groupId, artifactId, score, versionCount}`, framed in docs as "candidate real names to VERIFY, not endorsements". Search failure (offline/5xx/throttle) → empty suggestions, no raise.

**Solr query hardening (security review):** the artifactId token flows into the Solr `q=` and is parsed as Solr query syntax (`* ~ ^ : ( ) OR AND`). Escape Solr metacharacters (backslash-escape) or wrap as a quoted phrase BEFORE it reaches the query, so a crafted/odd token can't broaden the match set (which would feed the suggestion-steering vector). Applies to the new call path; if `search_maven_central` is shared, escape at the verify call site to avoid changing existing search behavior.

**`likelyHallucination`** = `(existenceStatus == "absent") AND any(raw_similarity(candidate) >= HALLUCINATION_THRESHOLD)` over the FULL candidate set returned by search (pre-truncation, pre-de-weighting), where `HALLUCINATION_THRESHOLD = 0.8` is a named constant. NOT triggered on `"unknown"` or `"exists"`. **The emitted `score` field IS the raw `_similarity`** (so the 0.80/just-below-0.8 boundary tests are deterministic); popularity de-weighting affects suggestion SORT ORDER ONLY and is never folded into `score` or into the flag — otherwise de-weighting a high-similarity low-popularity near-miss out of the top-N would silently suppress the hallucination flag (false negative).

**String distance — inline stdlib** (no new dependency): `_levenshtein(a,b)` (plain — adjacent transposition costs 2, NOT Damerau) + `_similarity(a,b) = 1 - lev/max(len(a),len(b),1)` (both-empty → 1.0). Rank uses `max(_similarity("g:a"), _similarity("a"))` (a.k.a. min-distance) — surface a candidate whose artifactId matches even if the group differs.

**Caps — ENFORCED in the handler, not just the schema (security review).** An MCP `inputSchema` `maxItems`/`maximum` is advisory client metadata; the server never validates it (existing batch handlers loop `args["dependencies"]` directly). So the handler MUST, before any network I/O: reject (or truncate with a warning in the result) when `len(dependencies) > 100`, and clamp `suggestLimit = min(suggestLimit, 10)`. This bounds the outbound fan-out (each dep → up-to-N-repo probe + a search) that the #283 hook could otherwise trigger on a large/malformed build file. The schema also declares the caps (for clients), but enforcement is in code.

## Affected Modules & Files

| Path | Change | Note |
|---|---|---|
| `plugins/maven-mcp/plugin/server/server.py` | Modified | `_levenshtein`/`_similarity`; `_solr_escape`; `handle_verify_coordinates` (per-repo existence probe + popularity-aware suggestions); register tool (schema w/ caps + dispatch); read-only reuse of `build_resolution_context`, `_repos_for`, `http_get`, `_parse_metadata_xml`/version parse, `search_maven_central`, `classify_version`. NO change to `fetch_metadata`/`check_version_in_repos` contracts |
| `plugins/maven-mcp/tests/test_verify_coordinates.py` | New | existence tri-state (exists/absent/unknown), gavExists from fetched versions, stability None-guard, likelyHallucination true/false + 0.80/0.79 boundary, popularity-aware ranking (low-pop near-miss ∉ top vs high-pop real), Solr-metachar token, per-item isolation (unexpected error in one item, sibling intact), batch caps, explicit urlopen call-sequence per case (non-google/non-plugin coords = 1 repo) |
| `plugins/maven-mcp/tests/test_string_distance.py` | New | `_levenshtein`/`_similarity` edges: identical→1.0, both-empty→1.0, one-empty, single-edit, transposition→distance 2, case (callers lowercase), `_solr_escape` |
| `plugins/maven-mcp/CLAUDE.md` | Modified | document `verify_coordinates`: purpose + the existence≠safety boundary (#322), tri-state, offline `unknown`, suggestion-source = Central-only recall limit, params/caps |

## Decisions Made

| Decision | Rationale | Alternatives rejected |
|---|---|---|
| Tri-state existence via explicit per-repo probe | `fetch_metadata` raise conflates absent vs unreachable + drops repo identity; a write-time guard must distinguish them (offline ≠ fake) | reuse fetch_metadata + catch ValueError (the convergent critical defect); extend fetch_metadata to return repo+reachability (breaks #321 contract + "additive" claim) |
| Output never implies "safe"; existence≠safety documented + #322 follow-up | dominant slopsquat = a PUBLISHED typosquat (exists=true); a "safe" framing creates false assurance for #283 | `likelyHallucination=false` read as clean (security-critical false assurance) |
| Suggestions ranked with popularity (versionCount), framed "verify not endorse" | pure-distance ranking can put an attacker's 1-version near-miss on top → tool recommends the slopsquat | similarity-only ranking (steering vector) |
| Escape Solr metachars in the search token | token is parsed as Solr query syntax → match-set broadening feeds steering | URL-encode only (≠ Solr-escape) |
| `HALLUCINATION_THRESHOLD=0.8` named, gated on `absent` | calibratable; only confirmed-reachable-absent + near-miss = slopsquat shape | hardcoded `e.g. 0.8` gated on ambiguous miss (false positives offline/private) |
| gavExists + stability from the probe's fetched versions | one fetch; no redundant round-trip; stability None-guarded | second `check_version_in_repos` fetch (redundant, complicates mock) |
| Sequential per-item try/except isolation | server.py is synchronous stdio; matches `check_multiple_dependencies` | claim concurrency (false) |

## Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Offline makes real coordinates look fake / guard silently disabled | critical | tri-state `unknown` (distinct from `absent`); `likelyHallucination` never true on `unknown`; #283 must treat `unknown` as "degraded, do not assert clean"; documented |
| Tool creates false assurance for published typosquats | major | scope boundary documented; output never says "safe"; popularity-aware suggestions; active detection → #322 |
| Suggestion steering toward attacker near-miss | major | versionCount de-weighting + "verify not endorse" framing + Solr-escape; test low-pop-near-miss ∉ top |
| `classify_version(None)` crash on 200-with-empty-versions | major | guard stability on non-empty latest; test the empty-versions case asserts no crash |
| likelyHallucination false positive for non-Central (androidx/plugin) coords | minor | suggestion source is Central-only (recall limit documented); gate likelyHallucination on `absent` + near-miss; down-weight/`g:a`-only match for non-Central group prefixes; documented |
| Threshold/ranking unverified | major | named constant + 0.80/0.79 boundary tests + discriminating ranking test (same artifactId, different group) + labeled near-miss vs coincidental (incl. short names guava/guice≈0.6) |

## Verification & Sources

| Source of truth | Type | Status | Sufficient? |
|---|---|---|---|
| Issue #282 (API + acceptance) | requirements | present | yes — tool shape + commons-lang→commons-lang3 case (existence/suggestion ACs) |
| Security review scope boundary + #322 | requirements (refinement) | present | yes — defines what the tool does NOT claim |
| Resolution layer (#321, 254 tests) | before-state baseline | present | yes — read-only reuse; existing behavior unchanged (additive) |

**Testing strategy:** L0 build + L1 (validate.sh, tests) + L2 unit (tri-state existence incl. offline `unknown`, gavExists, stability None-guard, hallucination true/false + boundary, popularity ranking, Solr-escape, batch isolation+caps, distance edges — mock urlopen with ENUMERATED call sequences) + **L5 manual** (stdio smoke: real coord → exists; `org.apache.commons:commons-lang` → absent + commons-lang3 suggested; an obviously-offline-style probe path sanity). No UI.

## Out of Scope

- The #283 PreToolUse hook (consumes this tool); coordinate extraction from edits.
- Active typosquat/popularity detection for EXISTING coordinates → **#322**.
- Compatibility matrices (#285), relocation/jcenter (#284), plugin-marker→GAV (#290).
- Modifying `fetch_metadata`/`check_version_in_repos` (read-only reuse only; tri-state probe is self-contained in the handler).

## Open Questions

- [non-blocking] Suggestion recall for non-Central scopes (androidx/plugin): Central-Solr-only. Default: document the limit + down-weight likelyHallucination for non-Central group prefixes. A Google-Maven/Plugin-Portal suggestion backend is a future enhancement (relates to #295).

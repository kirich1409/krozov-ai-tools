---
name: finalize
description: >
  This skill should be used when the user wants a code-quality pass over the current branch —
  multi-round review-and-fix loop that polishes how the code is written, not what it does.
  Runs code-reviewer, /simplify, optional pr-review-toolkit trio, and conditional expert reviews
  with /check between rounds; exits PASS when no BLOCK findings remain or ESCALATE after max rounds.
  Triggers: "finalize", "run code quality pass", "clean up the code", "prepare for review",
  "polish the code", "tidy up", "harden the implementation".
---

# Finalize

Code-quality pass over the current branch. Multi-round review-and-fix loop focused on **how** the code is written (quality, clarity, robustness), not **what** it does (functional acceptance, owned by `acceptance`) or **whether it works** (build/lint/tests, owned by `/check`).

`finalize` orchestrates `code-reviewer` + `/simplify` + the optional `pr-review-toolkit` trio + conditional expert reviews — none of those alone catches the full set of recurring patterns (over-engineered abstractions, silent failures, fragile types, weak coverage).

**Author fixes broken tests** is enforced per `~/.claude/rules/qa-and-testing.md` § 4. A `/check` between phases that surfaces test failures triggers an inline fix in the same round — owned by the engineer agent that produced the change. Round-end exit is impossible while tests remain red.

---

## Inputs

- **`slug`** — task slug for artifact naming.
- **Branch state** — reads the current branch; never switches.
- **Context artifact (optional)** — Phase A `code-reviewer` anchor: feature plan (`swarm-report/<slug>-plan.md`) or, for bug fixes, debug artifact (`swarm-report/<slug>-debug.md`).
- **Diff artifact (derived)** — before invoking `code-reviewer`, materialize the diff to `swarm-report/<slug>-diff.txt`. Do not hardcode `origin/main`: derive the remote's default branch (same as `create-pr` — `git remote show origin | grep "HEAD branch" | awk '{print $NF}'`, fallbacks `main` / `master` / `develop`), then `git merge-base origin/<base> HEAD`.

**Tolerance flags (optional):**

- `--allow-warn` — stop after 1 round on WARN-only (default: PASS on WARN-only, keep iterating BLOCKs).
- `--skip-experts` — omit Phase D (rarely useful; experts auto-skip when no triggers match).
- `--max-rounds N` (≥ 1) — override the default 3. Use after an ESCALATE for one more round without restarting.
- `--coverage-audit` / `--skip-coverage-audit` — force-on / force-off Phase D `test-coverage-expert`. Skip is discouraged; recorded verbatim in `acknowledged risks`.
- `--skip-security-review "<reason>"` — disable both `risk_areas` and pattern triggers for this round. Reason captured verbatim. Discouraged; other Phase D experts still fire.

---

## Round structure

Each round runs phases A → B → C → D sequentially. Between phases and after any auto-fix, invoke `/check`. Accumulate findings; at round end, exit or continue.

```
Round N:
  A  → code-reviewer          → fix BLOCK → /check
  B  → /simplify (auto-fixes) → /check
  C  → pr-review-toolkit trio (parallel, if installed) → fix BLOCK → /check
  D  → expert reviews (conditional, parallel)          → fix BLOCK → /check
  Any unfixed BLOCK → round N+1 (up to max_rounds, default 3); else PASS
```

**Exit criteria.** PASS — no BLOCK findings; WARN / NIT listed in report, never block. ESCALATE — after `max_rounds`, BLOCKs remain; dump unresolved findings, caller decides override or return to implementation.

**Max round budget.** Default 3, overridable via `--max-rounds N` (≥ 1). Regularly hitting the cap means Phase A's `code-reviewer` confidence threshold should be tuned (`developer-workflow-experts/agents/code-reviewer.md`), not `max_rounds` silently raised.

---

## Phase A — Semantic review (code-reviewer)

Launch `code-reviewer` (from `developer-workflow-experts`) with task description verbatim, plan artifact path (`swarm-report/<slug>-plan.md`) if it exists, and `git diff` of all branch changes. Returns PASS / WARN / FAIL with findings on the 0/25/50/75/100 confidence rubric (only above-threshold findings surface).

Non-negotiables violations from applicable `CLAUDE.md` `## Non-negotiables` are always BLOCK regardless of confidence — never moved to "acknowledged risks".

| Severity × confidence | Action |
|---|---|
| critical ≥ 75 | Fix immediately, re-run `/check`. PASS + resolved → BLOCK cleared. Doesn't converge → stays BLOCK, round ends without PASS. Never silently downgrade to "acknowledged risk". |
| major ≥ 75 | Fix if tractable. Refactor beyond diff → escalate; remains BLOCK until caller resolves or moves to "acknowledged risks" at ESCALATE. |
| minor ≥ 50 | NIT in report. Don't auto-fix; never blocks PASS. |

FAIL verdict → this phase has BLOCKs to address before continuing.

---

## Phase B — Built-in simplification (`/simplify`)

Invoke `/simplify`: parallel reuse / quality / efficiency pass that **applies fixes directly**. Treated as a behavioural contract; internal structure may evolve. Coverage: reuse (duplicated logic), quality (redundant state, parameter sprawl, leaky abstractions, stringly-typed, unnecessary comments), efficiency (redundant work, missed concurrency, hot-path bloat, TOCTOU, leaks). Don't pre-review output — trust it, then `/check`.

**On `/check` FAIL after `/simplify`:** revert the simplify commits (or the last commit if unambiguously from `/simplify`), log `phase: B, reason: revert`, continue to Phase C. Do not re-invoke `/simplify` in the same round.

**Round-budget semantic.** Phase B is transformative, not a finding-generator. A revert does NOT introduce an unresolved BLOCK and does NOT consume budget — the round continues through C and D. Distinct from `/check` failure after Phase A/C/D fix (§Mechanical verification), where the originating finding stays BLOCK.

---

## Phase C — PR review toolkit (parallel, optional)

Soft-reference to `pr-review-toolkit` (marketplace `claude-plugins-official`). Not a hard dep — that marketplace publishes plugin entries without `version` fields, breaking semver resolution.

Before invoking, check whether the three agents are available (e.g. Task agent registry). Any missing → skip Phase C, log `phase: C, status: skipped, reason: pr-review-toolkit not installed`, continue to Phase D. All available → invoke in **parallel**:

| Agent | Focus |
|---|---|
| `pr-review-toolkit:pr-test-analyzer` | Test quality in diff — edge cases, behavioral vs implementation testing |
| `pr-review-toolkit:silent-failure-hunter` | Empty catch blocks, swallowed errors, overly broad catches, errors logged but not surfaced |
| `pr-review-toolkit:type-design-analyzer` | Can invalid states be represented? Invariants in types? Missing nullability, unsafe unions |

Findings graded on the same 0–100 rubric as `code-reviewer` (inherited via prompt sharing). Apply Phase A fix-loop: BLOCK (critical/major ≥ 75) → fix → `/check`; WARN (minor ≥ 50) → report only; below threshold → drop. Test-quality fixes that need new test code → delegate to the matching engineer agent.

---

## Phase D — Expert reviews (conditional, parallel)

Trigger experts only when the diff matches their domain. Launch the matching ones in **parallel**.

| Expert | Fires when |
|---|---|
| `architecture-expert` | new module, new public API surface, cross-module dependency change, or layered structure violation in diff |
| `security-expert` | spec/plan declared `risk_areas` ∈ {auth, payment, pii, data-migration}, or any pattern in the [Security-expert pattern triggers](#security-expert-pattern-triggers) table below |
| `performance-expert` | hot-path code (rendering, query loops, batch jobs), N+1 patterns, large-buffer allocations, threading/concurrency changes |
| `ux-expert` | UI-surface changes (composables, views, screens), copy / a11y / animation diffs |
| `build-engineer` | Gradle / Bazel / npm / Cargo / Xcode build script changes, plugin upgrades, version-catalog edits |
| `devops-expert` | CI / CD config, GitHub Actions / GitLab pipelines, deploy scripts, Dockerfile, infra-as-code |
| `business-analyst` | spec / requirements / scope changes (rare in finalize — usually fires upstream) |
| `test-coverage-expert` | see [`test-coverage-expert` (conditional)](#test-coverage-expert-conditional) below |

No trigger matched → skip Phase D entirely for this round.

### `security-expert` pattern triggers

The default `risk_areas`-based trigger requires an explicit declaration in spec/plan; bug fixes and unspec'd tasks slip through. Phase D additionally fires `security-expert` on diff patterns:

| Category | Pattern (path or diff content) | Tier |
|---|---|---|
| Network layer | path under `/network/`, `/api/`, `/http/`, `/rpc/`, `/graphql/` | broad |
| Auth / Crypto | path under `/auth/`, `/crypto/`, `/token/`, `/session/` | narrow |
| Credential storage | diff mentions `SharedPreferences`, `EncryptedSharedPreferences`, `Keychain`, `UserDefaults`, `localStorage`, `sessionStorage`, `document.cookie`, `KeyStore` | narrow |
| Supply chain | new dependency line added in `build.gradle*`, `Podfile`, `Package.swift`, `package.json`, `pom.xml`, `Cargo.toml`, `requirements.txt`, `pyproject.toml`, `go.mod` | narrow |
| DB migrations | path under `migrations/`, `*.sql`, `Migration.kt`, `schema.prisma`, Flyway / Liquibase configs, `alembic/` | narrow |
| Deserialization | Jackson / Gson / `kotlinx.serialization` config blocks; unsafe Python-pickle usage, `XMLDecoder`, `ObjectInputStream` in diff | narrow |

**Threshold (false-positive control):**

- ≥ 1 narrow pattern → full security review (same as `risk_areas` trigger).
- ≥ 2 broad patterns → full security review.
- Exactly 1 broad pattern, no narrow → **scoped review**: launch `security-expert` with a narrowed prompt that names the specific surface (e.g. "audit the network layer for regressions only"), not a full audit. Reduces false-positive cost on incidental touches.
- No pattern + no `risk_areas` → security-expert does not fire. Other Phase D experts may still trigger.

**Override.** `--skip-security-review` (Tolerance flags) turns off both `risk_areas` and pattern triggers for the round. Recorded verbatim in `<slug>-finalize.md` `acknowledged risks` with user reason. Discouraged.

**Source.** Patterns evaluated against the unified diff between the remote default branch's merge-base and `HEAD` (same derivation as Phase A). Generate with rename detection (`git diff -M`). Path patterns match against the **new** path. Diff-content patterns match only added/modified hunks — a pure rename without content change cannot match content patterns but can match path patterns when the rename moves a file into a security-relevant directory.

### Handling expert findings

Same severity × confidence gate as Phase A. Specifics:

- Security-critical at confidence 50 — rely on `code-reviewer`'s **Critical-risk exception** (`developer-workflow-experts/agents/code-reviewer.md` § Critical-risk exception): finding is included with a `[please verify]` marker prefixed to `issue`. Treat as BLOCK; fix or escalate.
- Performance / architecture + critical ≥ 75: fix if local to the diff; escalate if broader rework needed.
- No parallel "always fix at 50" rule — the rubric is defined once in `code-reviewer.md` and inherited.

### `test-coverage-expert` (conditional)

Late-stage coverage audit complementing the early `/check` Phase 3.5 gate (#154). Catches declared TCs not implemented, data-layer changes without integration tests, and gaps the engineer agent missed. Public-API rule is defined in `~/.claude/rules/qa-and-testing.md` § 1; priority framework (P0–P3) in § 2.

**Trigger when ANY:** (1) diff adds a public API symbol with no matching test file (per § 1); (2) `docs/testplans/<slug>-test-plan.md` declares TCs without matching implementation in test sources for this slug — cross-reference by TC `Type` (#153) plus name / file mention, interpreted by the agent, not regex; (3) diff touches data-layer / repository / service / use-case files without introducing or updating tests; (4) `--coverage-audit`.

**Skip when ANY:** (1) trivial diff (single file, < 50 LOC, no new public API, refactor-only); (2) `--skip-coverage-audit` (recorded verbatim in finalize report); (3) no test infrastructure for the affected module — short-circuit with a follow-up issue ("add test harness for X"). Never silently skip.

Reuses existing engineer agents (`kotlin-engineer` / `swift-engineer` / `compose-developer` / `swiftui-developer`) with a coverage-audit prompt. The agent reads `docs/testplans/<slug>-test-plan.md`, the diff, and test files; writes `swarm-report/<slug>-coverage-audit.md`; on gaps, writes missing tests in the same Task call and re-runs `/check` (author-fixes-tests, qa-and-testing.md § 4).

**Schema for `swarm-report/<slug>-coverage-audit.md`:**

```markdown
# Coverage audit: <slug>

**Date:** <ISO date>
**Slug:** <slug>
**Triggered by:** new-public-api | tp-tc-mismatch | data-layer-no-tests | --coverage-audit
**Verdict:** PASS | GAPS_RESOLVED | ESCALATE

## Inputs
- Test plan: `docs/testplans/<slug>-test-plan.md` (or `N/A: no test plan`)
- Diff against: `origin/<base>` (commit hash range)
- Test files in diff: <list>

## Cross-reference

| TC ID | Type | Status | Test file |
|---|---|---|---|
| TC-1 | unit | covered | `src/test/.../FooSpec.kt` |
| TC-2 | ui-instrumentation | gap | — |

## Public API audit

| Symbol | File | Status | Test file |
|---|---|---|---|
| `LoginViewModel` | `feature/auth/.../LoginViewModel.kt` | covered | `LoginViewModelTest.kt` |
| `RateLimiter.allow()` | `core/.../RateLimiter.kt` | gap | — |

## Gaps and resolution
- (gap-1) TC-2 `Login error state` — added `LoginScreenInstrumentedTest`.
- (gap-2) `RateLimiter.allow()` — added `RateLimiterTest.allow_blocks_after_threshold`.

## /check after fixes
verdict: PASS
passed: [build, lint, typecheck, tests, coverage]
```

Verdict → Phase D outcome:

- `PASS` — all rows covered before audit; Phase D continues with other experts.
- `GAPS_RESOLVED` — agent wrote missing tests, `/check` PASS. Treated as PASS; audit file lists fixes for the finalize report.
- `ESCALATE` — agent could not produce a viable test in 3 attempts, OR a gap is structurally untestable. Treated as BLOCK; round budget applies.

`--skip-coverage-audit` is documented in §Inputs; when set, it records the skip reason in `acknowledged risks`.

---

## Mechanical verification between phases

After **any** code modification within a round, re-invoke `/check`. On FAIL:

1. Log which phase's fix introduced the failure.
2. Narrow repair — **1 attempt max**. At finalize stage the code already passed `/check` once, so a regression signals the fix itself was wrong; retrying compounds rather than converges.
3. Still failing → revert the fix and keep the originating finding **as BLOCK** for the round (not resolved, counts against budget). Continue remaining phases; never relabel a reverted BLOCK as "acknowledged risk".
4. Round ends with unresolved BLOCKs → next round. Round 3 ends with unresolved BLOCKs → ESCALATE.

Do not let `/check` failures cascade, and do not use revert-and-continue to silently ship a BLOCK.

---

## Report

Save `swarm-report/<slug>-finalize.md` on exit (PASS or ESCALATE):

```markdown
# Finalize: <slug>

**Date:** <date>
**Rounds run:** N (of 3 max)
**Exit:** PASS | ESCALATE
**Escalation reason:** <only if ESCALATE>

## Rounds

### Round 1
- Phase A (code-reviewer): verdict, N findings (K BLOCK, M WARN, L NIT). Fixes: X.
- Phase B (/simplify): Y files changed, auto-fixed.
- Phase C (pr-review-toolkit): per-agent breakdown, or `skipped` if plugin not installed.
- Phase D (experts): triggered: [security-expert, ...]; findings, fixes.
- `/check` after round: PASS | FAIL (reason)

### Round 2 ...

## Unresolved BLOCKs (ESCALATE only)
Findings that could not be fixed and were NOT downgraded — populated only on ESCALATE; lists BLOCKs after `max_rounds` rounds OR BLOCKs whose fix broke `/check` and was reverted. User decides: return to implementation, accept as risk, or re-scope.

| Severity | Confidence | Category | Finding | Phase | Round | File:Line |
|---|---|---|---|---|---|---|
| BLOCK (critical) | 75 | security | Token logged in clear | D | 3 | src/auth/Logger.kt:23 |

## Remaining findings (not auto-fixed)
Non-BLOCK items for reviewer awareness — never block PASS.

| Severity | Confidence | Category | Finding | Phase | File:Line |
|---|---|---|---|---|---|
| WARN | 60 | quality | Inconsistent error logging | A | src/foo/Bar.kt:142 |
| NIT  | 75 | consistency | Unused import in new file | B | ... |

## Acknowledged risks
Findings the user explicitly decided to accept (e.g. at escalation). Not auto-populated — distinct from "Unresolved BLOCKs".

## Commits added during finalize
- <hash> <message>
```

### Chat summary on exit (≤20 lines)

**PASS:** "Finalize: PASS after N round(s). Code is ready for acceptance." Bullets — N findings fixed by category (security X, quality Y, style Z); if 0, state so. Next step: `/acceptance`.

**ESCALATE:** "Finalize: ESCALATE after N round(s). X unresolved BLOCK(s) require decision." Bullets (max 5, top by severity): one BLOCK per bullet with category + one-line description. ONE question: which BLOCK first, or pick accept-risk / continue-implementing / re-scope. Options — proceed to `/acceptance` accepting risks, or return to implementation with a new task.

Never paste the report table into chat — the file is for reference.

---

## Scope and escalation

- **In scope:** improving quality of code *related to the current diff*; delegating fixes to engineer agents; `/check` after each mutation.
- **Out of scope:** new features, scope changes, functional acceptance, architectural redesign.
- Keep fixes inside files touched by the original change. Adjacent-file edits only when a finding explicitly requires them (e.g., `pr-test-analyzer` adding a sibling test, `/simplify` extracting a helper).
- Never re-scope under "cleanup" — structural issues beyond narrow-fix reach escalate.
- Never silently skip Phase A — `code-reviewer`'s plan-conformance check is the anchor. If it fails to launch for infrastructure reasons, stop and escalate.

**Escalate (stop and report) when:** unresolved BLOCKs after `max_rounds`; `/check` fix doesn't converge after 1 retry; BLOCK requires refactoring beyond diff scope; expert finding demands architectural change; required engineer agent (e.g. `kotlin-engineer`) is not installed but needed for a fix. State which phase escalated, what is unresolved, and what the caller must decide.

---

## Dependencies

- **Hard** (`plugin.json`): `developer-workflow-experts` — `code-reviewer`, `security-expert`, `performance-expert`, `architecture-expert`.
- **Optional soft-ref** (Phase C auto-skips when absent): `pr-review-toolkit` (marketplace `claude-plugins-official`) — `pr-test-analyzer`, `silent-failure-hunter`, `type-design-analyzer`.
- **Built-in:** `/simplify`, `/check`.

---
name: finalize
description: >
  Code-quality pass over the current branch changes. Multi-round review-and-fix loop:
  code-reviewer (plan conformance, CLAUDE.md, bugs) → /simplify (reuse/quality/efficiency) →
  pr-review-toolkit agents (test quality, silent failures, type design) → conditional expert
  reviews (security, performance, architecture). `/check` between fixes. Exits PASS when no
  BLOCK-level findings remain, or ESCALATE after 3 rounds. Invoke on: "finalize", "run code
  quality pass", "clean up the code", "prepare for review", "полируй код", "финализация",
  "доведи код", "почисти", or when an orchestrator (feature-flow, bugfix-flow) runs this
  stage between implement and acceptance.
---

# Finalize

Code-quality pass between implement and acceptance. Multi-round review-and-fix loop focused on **how** the code is written (quality, clarity, robustness), not **what** it does (that's acceptance) or **whether it works** (that's implement + `/check`).

This skill exists because agent-written code carries recurring patterns worth polishing: over-engineered abstractions, silent failures in catch blocks, weak test coverage, fragile type designs, redundant utilities. `/check` doesn't catch these; `code-reviewer` alone is too narrow; `/simplify` alone is too narrow. `finalize` orchestrates the whole pass.

---

## Three quality layers — where `finalize` fits

| Stage | Answers | Provenance |
|---|---|---|
| `implement` | Does the code work and match the plan? | build/lint/tests via `/check`, intent check |
| **`finalize`** | Is the code written well? | this skill |
| `acceptance` | Does the feature solve the user's problem? | functional verification via `manual-tester` |

---

## Inputs

The caller (orchestrator or user) provides:
- **`slug`** — the task slug used for artifact naming
- **Branch state** — finalize reads the current branch; it does not switch branches
- **Context artifact path (optional)** — Phase A's `code-reviewer` anchor. Accepts either a feature plan (`swarm-report/<slug>-plan.md`) or, for bugfix-flow invocations, the debug artifact (`swarm-report/<slug>-debug.md`). Either works — `code-reviewer` treats whichever is provided as the "what was supposed to happen" document.
- **Diff artifact path (derived)** — before invoking `code-reviewer`, materialize the diff to `swarm-report/<slug>-diff.txt` and pass that path to the agent. Matches the invocation template in `docs/ORCHESTRATION.md`. Do **not** hardcode `origin/main`: derive the remote's default branch first (the same way `create-pr` does — `git remote show origin | grep "HEAD branch" | awk '{print $NF}'`, with `main` / `master` / `develop` as ordered fallbacks), then diff `$(git merge-base origin/<base> HEAD)..HEAD`. Works on any repository regardless of default-branch naming.
- **Tolerance flags (optional):**
  - `--allow-warn` — stop after 1 round even if WARN findings remain (default: still exit PASS on WARN-only, but keep iterating BLOCKs until resolved or round budget runs out)
  - `--skip-experts` — omit Phase D (rarely useful; experts auto-skip if no triggers match)
  - `--max-rounds N` — override the default 3-round cap. Use when the user wants one more round after an ESCALATE, without restarting the whole stage. Must be ≥ 1.

---

## Round structure

Each round runs four phases A → B → C → D sequentially. Between phases and after any auto-fix, invoke `/check` to confirm the build still works. Accumulate findings. At the end of the round, decide: exit, or continue to next round.

```
Round N:
  Phase A  → code-reviewer          → fix BLOCK → /check → continue
  Phase B  → /simplify (auto-fixes) → /check               → continue
  Phase C  → pr-review-toolkit trio (parallel) → fix BLOCK → /check → continue
  Phase D  → expert reviews (conditional, parallel) → fix BLOCK → /check → continue
  Round end: did any BLOCK remain unfixed?
    yes → go to round N+1 (max 3 rounds total)
    no  → exit with PASS
```

### Exit criteria

- **PASS (exit):** no BLOCK severity findings from any phase. WARN and NIT findings listed in the report but do not block.
- **ESCALATE (stop and report to caller):** after 3 rounds, BLOCK findings still present. Dump unresolved findings, caller decides whether to override or loop back to `implement`.

### Max round budget

Default `max_rounds = 3`, overridable to any integer ≥ 1 via the `--max-rounds N` flag (see §Inputs). The caller's flag wins when present; otherwise the default applies. ESCALATE semantics key off the effective value, not the constant — "after 3 rounds" in this document means "after the effective max_rounds".

Total budget (per round: 4 phases + fixes + `/check` after each fix) can take non-trivial wall time on large diffs. If a project regularly hits the cap, the BLOCK threshold may be too strict for the project's conventions — tune Phase A's `code-reviewer` confidence threshold (see `developer-workflow-experts/agents/code-reviewer.md`) rather than silently raising `max_rounds`.

---

## Phase A — Semantic review (code-reviewer)

Launch the `code-reviewer` agent (from `developer-workflow-experts`) with:
- Original task description (verbatim)
- Plan artifact path (`swarm-report/<slug>-plan.md`) if it exists
- `git diff` of all branch changes

The agent returns a structured verdict: PASS / WARN / FAIL with findings scored on the 0/25/50/75/100 confidence rubric. Only findings passing the reporting threshold surface.

### Handling findings

| Severity × confidence | Action |
|---|---|
| critical ≥ 75 | Fix immediately. After fix, re-run `/check`. If `/check` PASSes and the finding is resolved → BLOCK cleared. If the fix does not converge, the finding stays BLOCK — the round ends without exiting PASS; counted against the 3-round budget. Do not silently downgrade a critical finding to "acknowledged risk". |
| major ≥ 75 | Fix if tractable. On successful fix + `/check` PASS → BLOCK cleared. If fix requires refactoring beyond the diff scope → escalate to caller; the finding remains BLOCK until the caller resolves it or explicitly moves it to "acknowledged risks" at ESCALATE. |
| minor ≥ 50 | Include in report as NIT. Don't fix automatically; caller/user decides. NIT never blocks PASS. |

If `code-reviewer` returns FAIL verdict → this phase has BLOCKs that must be addressed before continuing.

### Output

Summary of this phase's findings goes into the round's log.

---

## Phase B — Built-in simplification (`/simplify`)

Invoke the built-in Claude Code skill `/simplify`. It performs a parallel reuse / quality / efficiency pass and **applies fixes directly** for the findings it considers real. The exact implementation (number of sub-agents, internal structure) may evolve — finalize treats `/simplify` as a behavioural contract, not an implementation detail.

`/simplify` focuses on:
- **Reuse**: duplicated logic that should use an existing utility
- **Quality**: redundant state, parameter sprawl, copy-paste, leaky abstractions, stringly-typed code, unnecessary comments
- **Efficiency**: redundant work, missed concurrency, hot-path bloat, TOCTOU, memory leaks

Because `/simplify` is fix-oriented, do not pre-review its output — trust the built-in, then run `/check` to confirm the project still builds and tests pass.

### If `/check` fails after `/simplify`

Revert the simplify commits (or the last commit if unambiguously from `/simplify`), log the failure with `phase: B, reason: revert`, continue to Phase C. Do not re-invoke `/simplify` in the same round — if it broke something once, it's likely to repeat.

**Round-budget semantic.** Phase B is a transformative step, not a finding-generator. A Phase B revert does NOT introduce an unresolved BLOCK and does NOT consume the round budget beyond the single Phase B attempt; the round continues normally through Phases C and D. This is distinct from `/check` failure after a Phase A/C/D fix (§Mechanical verification) — there the originating finding stays BLOCK and counts against the budget.

---

## Phase C — PR review toolkit (parallel)

Invoke three agents from the `pr-review-toolkit` plugin in **parallel**:

| Agent | Focus |
|---|---|
| `pr-review-toolkit:pr-test-analyzer` | Quality of tests added in the diff: are edge cases covered? Behavioral vs. implementation testing? |
| `pr-review-toolkit:silent-failure-hunter` | Empty catch blocks, swallowed errors, catches too broad, errors logged but not surfaced |
| `pr-review-toolkit:type-design-analyzer` | Can invalid states be represented? Are invariants encoded in types? Missing nullability markers, unsafe unions |

Each agent returns findings graded by the same 0–100 confidence rubric used by our `code-reviewer` (the plugin is hard-dep'd via `plugin.json`; agents inherit the convention through prompt sharing).

### Handling Phase C findings

Apply fix-loop rules identical to Phase A:
- BLOCK (critical/major + confidence ≥ 75) → fix → `/check`
- WARN (minor ≥ 50) → report, don't auto-fix
- Below threshold → drop

Fixes for test-quality findings (e.g., "this test doesn't cover the failure path") may require writing new test code — delegate that to the appropriate engineer agent (`kotlin-engineer`, `swift-engineer`, etc.) with the finding as input.

---

## Phase D — Expert reviews (conditional, parallel)

Trigger experts only when the diff matches their domain. Launch the matching ones in **parallel**.

Trigger matrix lives in [`docs/ORCHESTRATION.md` § Phase D expert-review triggers](../../docs/ORCHESTRATION.md#phase-d-expert-review-triggers) — that document is the single source of truth. Do not duplicate it here; read the matrix before executing.

No trigger matched → skip Phase D entirely for this round.

### Handling expert findings

Experts produce deeper, higher-risk findings. Apply the same severity × confidence gate as Phase A:

- For security-critical findings that come in at confidence 50, rely on the code-reviewer's **Critical-risk exception** (see `developer-workflow-experts/agents/code-reviewer.md` § Critical-risk exception): the finding is included with a `[please verify]` marker prefixed to the `issue` field. Treat such findings as BLOCK and attempt a fix; if fix is out-of-scope, escalate.
- performance / architecture + critical at confidence ≥ 75: fix if local to the diff; escalate if requires broader rework.
- Do not introduce a parallel "always fix at 50" rule — the rubric is defined once in `code-reviewer.md` and inherited by Phase D experts.

---

## Mechanical verification between phases

After **any** code modification within a round (Phase A fix, Phase B auto-fix, Phase C fix, Phase D fix), re-invoke `/check`. If `/check` returns FAIL:

1. Log which phase's fix introduced the failure.
2. Attempt a narrow repair — **1 attempt max** (stricter than implement's 3-per-gate, which is before the first clean build). At finalize stage the code already passed `/check` once, so a regression from a finalize fix signals that the fix itself was wrong; repeated retry usually compounds the problem rather than converging.
3. If still failing → revert the fix and keep the originating finding **as BLOCK** on the round's list — the finding is not resolved, so it counts against the round budget. Continue with the remaining phases of the round (they may still find other issues), but do not mark the reverted finding as "acknowledged risk" — that label is reserved for items the user knowingly accepts at the end.
4. If the round ends with any such unresolved BLOCK, go to the next round. If round 3 ends with unresolved BLOCKs, exit with ESCALATE.

Do not let `/check` failures cascade — a broken build blocks further review and creates noise. But also do not use "revert + continue" as a way to silently ship a BLOCK.

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
- Phase A (code-reviewer): verdict, N findings (K BLOCK, M WARN, L NIT). Fixes applied: X.
- Phase B (/simplify): Y files changed, auto-fixed.
- Phase C (pr-review-toolkit): breakdown per agent.
- Phase D (experts): triggered: [security-expert, ...]; findings, fixes.
- `/check` after round: PASS | FAIL (reason)

### Round 2
...

## Unresolved BLOCKs (on ESCALATE only)

Findings that could not be fixed and were NOT downgraded. Populated only when the
finalize stage exits ESCALATE — lists BLOCKs that remain after 3 rounds, or BLOCKs
whose fix broke `/check` and was reverted (per §Mechanical verification). The user
must decide: loop back to `implement`, accept as risk, or re-scope.

| Severity | Confidence | Category | Finding | Phase | Round | File:Line |
|---|---|---|---|---|---|---|
| BLOCK (critical) | 75 | security | Token logged in clear | D | 3 | src/auth/Logger.kt:23 |

## Remaining findings (not auto-fixed)

Non-BLOCK items surfaced for reviewer awareness — they do not block exit with PASS.

| Severity | Confidence | Category | Finding | Phase | File:Line |
|---|---|---|---|---|---|
| WARN | 60 | quality | Inconsistent error logging | A | src/foo/Bar.kt:142 |
| NIT  | 75 | consistency | Unused import of X in new file | B | ... |

## Acknowledged risks

Findings that the user explicitly decided to accept (e.g., during escalation). Not auto-populated — the user marks items here when handing control back for the run to continue. Distinct from "Unresolved BLOCKs" (which the finalize stage could not close).

## Commits added during finalize

- <hash> <message>
```

---

## Scope rules

- **In scope:** reviewing and improving the quality of code *related to the current diff*. Delegating fixes to engineer agents. Invoking `/check` after each mutation.
- **Out of scope:** writing new features, changing task scope, verifying functional correctness (acceptance), architectural redesign (escalate — this is a new task).
- **Prefer** to keep fixes inside the files touched by `implement`. Minimal, necessary edits in adjacent files are allowed when a finding explicitly requires them — e.g., Phase C's `pr-test-analyzer` may demand adding tests in a sibling test file, and Phase B's `/simplify` may extract a duplicated helper into an existing utility module. In every such case, keep the edit narrowly scoped to what the finding requires.
- **Never** re-scope the task under the guise of "cleanup". If a finding points to a structural issue beyond narrow-fix reach → escalate, do not refactor.
- **Never** silently skip Phase A — `code-reviewer`'s plan-conformance check is the anchor. If the agent fails to launch for infrastructure reasons, stop and escalate.
- **Never** run forever. 3 rounds, then report.

---

## Escalation

Stop and report to caller when:

- After 3 rounds, BLOCK findings remain unresolved
- `/check` fails and the fix doesn't converge after 1 retry
- A BLOCK finding requires refactoring beyond the diff scope
- An expert finding demands architectural changes (new modules, dependency reorg)
- Required engineer agent (e.g., `kotlin-engineer`) is not installed but needed for a fix

When escalating: state which phase escalated, what the unresolved findings are, and what the caller needs to decide (accept risks, loop to implement with new task, architectural redesign, etc.).

---

## Integration notes

- **`feature-flow`** and **`bugfix-flow`** invoke this skill between `implement` and `acceptance`.
- **Manual invocation** is useful for: pre-PR cleanup on a branch that didn't come through an orchestrator, periodic quality audit on an old branch that wasn't finalized, review of a branch before marking draft PR ready (even though orchestrators already do this automatically).
- The skill assumes `code-reviewer` and `pr-review-toolkit` agents are installed. `code-reviewer` comes from `developer-workflow-experts` (sibling dependency). `pr-review-toolkit` comes from `claude-plugins-official` (hard dep in `plugin.json`).

---

## Dependencies this skill requires

- Hard deps (declared in `plugins/developer-workflow/.claude-plugin/plugin.json`):
  - `developer-workflow-experts` — for `code-reviewer`, `security-expert`, `performance-expert`, `architecture-expert`
  - `pr-review-toolkit` (marketplace: `claude-plugins-official`) — for `pr-test-analyzer`, `silent-failure-hunter`, `type-design-analyzer`
- Built-in skills:
  - `/simplify` — Claude Code's built-in reuse/quality/efficiency pass
  - `/check` — this plugin's mechanical verification utility

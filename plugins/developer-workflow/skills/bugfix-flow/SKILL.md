---
name: bugfix-flow
description: >-
  This skill should be used when the user reports a bug and wants it fixed end-to-end —
  thin orchestrator sequencing debug → (optional plan) → implement → finalize → acceptance →
  draft/ready PR → drive-to-merge. Delegates every stage to a separate skill; writes no
  code itself. Triggers: "/bugfix-flow", "bugfix flow", "fix this bug", "исправь баг",
  "почини", "это сломалось, почини", "fix and ship", "find and fix", "debug and fix".
  Do NOT use for: feature implementation (use feature-flow), investigation without fix
  (use debug), or a quick obvious fix that does not need diagnosis (invoke implement directly).
---

# Bugfix Flow — Bug Fix Orchestrator

Thin orchestrator that routes a bug through diagnosis, fix, verification, and PR.
Contains no implementation logic — each stage is a separate skill invocation via subagents.

**STRICT RULE:** The orchestrator DOES NOT write code, run tests, or perform analysis directly.
It only manages transitions, passes context between stages, and reports summaries to the user.

**Preconditions (caller's responsibility, NOT this skill's):**
- A working branch suitable for the fix is already set up (via worktree or otherwise)
  and the current working directory is where the fix should be made.
- The caller (main agent, wrapping agent, or user) has resolved this before invoking
  the skill. The skill itself does not inspect, create, switch, or clean up branches
  or worktrees.

---

## Strict State Machine

### Allowed transitions

```
Setup      -> Debug
Setup      -> Implement        (trivially obvious fix — skip debug)
Debug      -> Plan             (complex fix — needs planning)
Debug      -> Implement        (simple fix — root cause diagnosed, fix is clear)
Debug      -> Report           (not reproducible or escalated)
Plan       -> Implement
Plan       -> Debug            (multiexpert review FAIL — need more diagnostic context)
Implement  -> RegressionTest   (non-trivial fix in testable code — see Phase 2.2)
Implement  -> Finalize         (trivial fix or regression test skipped — see Phase 2.2)
RegressionTest -> Finalize
Finalize   -> Acceptance       (PASS — no BLOCKs remain)
Finalize   -> Implement        (ESCALATE after 3 rounds; user routes back)
Finalize   -> escalate         (ESCALATE after 3 rounds; user picks non-implement path)
Acceptance -> PR               (VERIFIED — bug gone)
Acceptance -> Implement        (FAILED — bug still reproduces or new bugs)
Acceptance -> Debug            (FAILED — fix didn't address root cause)
PR         -> Merged           (TERMINAL — no further transitions)
PR         -> Implement        (review feedback requires code changes)
PR         -> escalate         (drive-to-merge blocker — DISCUSSION on P0/P1,
                                unresolvable rebase, repeated same-signature CI failure)
```

Per-transition maxima for backward edges (Plan → Debug, Finalize → Implement,
Acceptance → Implement / Debug, PR → Implement) are declared in the
[Backward Transitions](#backward-transitions-strict-limits) table below. When a cap is
reached, the orchestrator **escalates** instead of looping again.

**ALL other transitions are FORBIDDEN.** Before every transition, announce:

> **Stage: [current] → Transition to: [next]. Reason: [why]**

---

## Phase 0: Setup

### 0.1 Understand the bug

Extract from the user's input:
- **Symptom** — what's broken
- **How to reproduce** (if known)
- **Expected vs actual behavior**
- **Source** — issue URL, error log, user description

Generate a slug: kebab-case, 2-4 words.

### 0.2 Profile confirmation

Auto-detect the profile. Then confirm:

> **Detected profile: Bug fix. Correct?**

If the user says it's a feature — redirect to `/feature-flow`.
If the fix is trivially obvious (typo, missing null check) — announce skip and go to Implement.

---

## Phase 1: Debug

**Context passing (MANDATORY):** pass the original bug description, source, and any
reproduction info the user provided.

Invoke `developer-workflow:debug` with the bug description.

Wait for `swarm-report/<slug>-debug.md`.

The debug artifact includes a **Reproduction Steps** section in `swarm-report/<slug>-debug.md`.
This section is persistent state — survives context compaction. Re-read it before any
action that depends on reproduction steps.

**Route by status:**
- **Diagnosed, simple fix** (single file, clear direction) → **Stage: Debug → Implement.**
- **Diagnosed, complex fix** (multiple files, architectural impact, unclear approach) → **Stage: Debug → Plan.**
- **Not Reproducible** → report to user, ask for more info. Stop.
- **Escalated** → report findings, stop. Bug needs user decision.

---

## Phase 1.5: Plan (optional — complex fixes only)

When the debug artifact indicates a complex fix (touches multiple modules, needs architectural
decisions, or the recommended fix direction has alternatives):

1. Create an implementation plan in Plan Mode based on the debug findings and save it to
   `swarm-report/<slug>-plan.md` (same convention as `feature-flow` Phase 1.3).
2. Invoke `developer-workflow:multiexpert-review` on `swarm-report/<slug>-plan.md` with
   `profile: implementation-plan` to validate.
3. If FAIL → back to Debug for more context (counted against the Plan → Debug backward cap).
4. If PASS/CONDITIONAL → proceed to Implement.

When the Plan stage ran, `swarm-report/<slug>-plan.md` **overrides** `swarm-report/<slug>-debug.md`
as the plan anchor for `finalize` (Phase 2.5) — the plan carries the chosen approach, while
debug.md stays authoritative for root cause and reproduction steps.

Skip for straightforward fixes where the debug artifact already gives a clear, single-path direction.

---

## Phase 2: Implement Fix

**Context passing (MANDATORY):** pass:
1. Original bug description (verbatim)
2. Path to `swarm-report/<slug>-debug.md`
3. If rollback — reason and what was tried

Invoke `developer-workflow:implement` with:
- Task: fix description based on debug findings
- Slug
- Path to `swarm-report/<slug>-debug.md`

Wait for `swarm-report/<slug>-implement.md` + `swarm-report/<slug>-quality.md`.

### 2.1 Create draft PR (early)

After `implement` returns a clean Quality Loop result and the branch has been pushed, invoke `developer-workflow:create-pr` with the `--draft` argument. The draft PR body references the debug artifact (root cause + reproduction steps) and the fix summary. Subsequent stages run against the pushed PR branch, keeping remote state in sync.

If a draft PR already exists for this branch (re-entry on rollback), `--draft` is idempotent — it refreshes the body instead of failing.

---

## Phase 2.2: Regression Test (optional)

After the draft PR is created, evaluate whether a focused regression test is warranted.
**Default: write the test.** Only skip with explicit user confirmation.

**Conditions that make regression testing technically impractical:**
1. Root cause is a typo, wrong string constant, configuration value, or build config change
2. Bug is purely visual — layout, rendering, styling with no testable logic path
3. Existing tests already cover the exact reproduction scenario
4. No test infrastructure found for the affected module

**If no condition holds** → proceed directly to write-tests:
**Stage: Implement → RegressionTest**

**If any condition holds** → stop and ask the user one question before proceeding:

> "A regression test for this fix may be impractical: [state the condition that fired].
> Should I skip test coverage for this bug?"

- User confirms skip → **Stage: Implement → Finalize (regression test skipped — user confirmed)**
- User wants a test despite the condition → proceed to write-tests:
  **Stage: Implement → RegressionTest**

**When writing the test:**

Invoke `developer-workflow:write-tests` with:
- **Target**: the fixed file(s) listed in `swarm-report/<slug>-implement.md`
- **Regression scenario** assembled from `swarm-report/<slug>-debug.md`:
  - Root cause
  - Reproduction steps (verbatim)
  - Expected vs actual behavior
  - Explicit instruction: "Regression Mode — write one focused test for this scenario.
    Do not sweep for other coverage gaps in this file."

**Route by result:**
- **Tests pass** → **Stage: RegressionTest → Finalize**
- **Tests fail after 3 fix attempts** (write-tests `Phase 5.3` exhausted) → continue to
  Finalize and log the failing test as a finding in the PR body; it will be visible to
  reviewers as a known issue.
- **write-tests reports a Production Bug** (test correctly fails on the fixed code — see
  `write-tests` Phase 5.2) → the fix is incomplete; route
  **RegressionTest → Implement** (max 1 time — see Backward Transitions). Pass the
  failing test assertion as the anchor for the next Implement invocation.

---

## Phase 2.5: Finalize (code-quality pass)

After `implement` passes its two gates (mechanical checks + intent check), invoke `developer-workflow:finalize` with:
- Slug
- Plan anchor — pass `swarm-report/<slug>-plan.md` when the Plan stage ran (Phase 1.5);
  otherwise pass `swarm-report/<slug>-debug.md`. The plan overrides debug.md as the
  anchor because the plan carries the chosen approach, while debug.md stays authoritative
  for root cause and reproduction steps (see Phase 1.5).

`finalize` runs a multi-round loop (max 3): code-reviewer → /simplify → optional pr-review-toolkit trio (skipped if plugin absent) → conditional expert reviews, with `/check` between fixes.

Wait for `swarm-report/<slug>-finalize.md`.

**Route by result:**
- **PASS** → **Stage: Finalize → Acceptance**
- **ESCALATE** → stop, report to user. User decides whether to accept risks, route back to implement for deeper fix, or re-scope.

---

## Phase 3: Acceptance

Bugfix-flow has no formal TestPlan stage. Code-level regression testing is handled by
Phase 2.2 (`write-tests` Regression Mode) — a focused test that prevents the bug from
re-occurring in the automated test suite. Acceptance verifies the user-facing symptom:
that the original reproduction steps no longer trigger the bug.

For bugs in critical flows that additionally need a formal structured QA plan
(external QA handoff, multi-scenario regression coverage), run `/generate-test-plan`
manually **before** `/bugfix-flow`, using the **same slug** as the bugfix so the saved
file lands at `docs/testplans/<slug>-test-plan.md`. `acceptance` Branch 2 mounts by
exact slug match; if the plan was generated under a different filename, rename it to
`docs/testplans/<slug>-test-plan.md` before running `/bugfix-flow` (see
`acceptance/references/source-branches.md` §Branch 2).

Invoke `developer-workflow:acceptance` with:
- Spec source: `swarm-report/<slug>-debug.md` (reproduction steps = acceptance criteria)
- The running app
- Explicit instruction: verify the reproduction steps no longer trigger the bug

The acceptance skill saves an E2E scenario to `swarm-report/<slug>-e2e-scenario.md`.
This file uses checkboxes — completed checks (`[x]`) survive compaction and are NOT repeated.

Wait for `swarm-report/<slug>-acceptance.md`.

**Route by result:**

| Result | Transition | Action |
|--------|-----------|--------|
| VERIFIED (bug gone) | **Acceptance → PR** | Proceed |
| FAILED — same bug | **Acceptance → Implement** | Fix again (max 2 retries — see Backward Transitions). After the 2nd retry also fails acceptance, route **Acceptance → Debug** (re-diagnose). |
| FAILED — new bug | Route per bug: trivial → Implement (counted against the `Acceptance → Implement` cap of 2), complex → Debug (counted against the `Acceptance → Debug` cap of 1). If either cap is exhausted, **escalate** — do not loop again. |
| PARTIAL — bug gone, minor issues | Ask user: fix or ship as-is |

---

## Phase 4: PR

### 4.1 Promote to ready for review

The draft PR already exists (created at 2.1) and has been updated via fix cycles and acceptance. Now mark it ready:

Invoke `developer-workflow:create-pr` with the `--promote` argument.

`--promote` refreshes the PR body with the final summary (root cause, fix, validation results, status table) and then marks the PR ready for review.

> Stage: Acceptance → PR (promoted to ready)

### 4.2 Drive to merge

After `create-pr` marks the PR ready, the orchestrator invokes
`developer-workflow:drive-to-merge`. That skill autonomously monitors CI,
handles review comments (categorize → propose concrete fixes → delegate →
reply → resolve), re-requests review including Copilot, and polls via
`ScheduleWakeup`. In default mode it pauses each round for `approve` / `skip`
/ `stop`; `--auto` skips that per-round approval gate. Both modes still ask
the user for final merge confirmation, and surface true blockers.

> Stage: PR (ready) → Drive to merge → Merged

Use `drive-to-merge --auto` to skip the per-round approval gate; the merge
gate always requires explicit confirmation.

---

## Stage result relay

When a lifecycle skill completes, **do not add a wrapper summary** on top of the skill's own
chat output. The skill's ≤30-line chat summary IS the user-facing result for that stage.

The orchestrator's job at each transition:
1. Read the skill's receipt from `swarm-report/` (for gating and state tracking)
2. Decide the next step based on verdict/status in the receipt
3. If the next step requires user input — ask ONE question (if the skill didn't already ask one)
4. Otherwise — proceed to the next stage and announce it in one line: "Starting `<skill-name>`..."

Do NOT re-summarize what the skill already told the user.

---

## Backward Transitions (STRICT limits)

| From | To | Trigger | Max |
|------|----|---------|-----|
| Plan | Debug | Plan-review FAIL — plan needs more diagnostic context | 1 |
| RegressionTest | Implement | write-tests found production bug — fix is incomplete | 1 |
| Finalize | Implement | ESCALATE — user routes back to fix root issues | 1 |
| Acceptance | Implement | Bug still reproduces or new bugs | 2 |
| Acceptance | Debug | Fix didn't address root cause (after 2 failed implementations), or acceptance finds a complex new bug that needs renewed diagnosis | 1 |
| PR | Implement | Review feedback requires code changes | 2 |

Each backward transition:
1. **Announce** the transition with reason
2. Log reason in the current artifact
3. Re-read original bug report + all artifacts (re-anchor)
4. Pass rollback reason to the next subagent
5. If max reached → escalate to user

---

## Stop Points

The orchestrator **stops and waits for the user** at:
- Profile confirmation (Phase 0.2)
- Bug not reproducible (need more info)
- Debug escalation (architectural issue, needs decision)
- PARTIAL acceptance verdict
- `drive-to-merge` merge gate — final `gh pr merge` / `glab mr merge` always requires
  explicit user confirmation, regardless of mode.
- `drive-to-merge` blockers — true DISCUSSION items on P0/P1, unresolvable rebase
  conflicts, 3 consecutive CI failures with the same error signature, integrity
  mismatch on a reply thread.

---

## Report

After Done (PR created) or Stop (escalation), save a report to
`swarm-report/<slug>-YYYY-MM-DD.md` with:
- Bug description and source
- Reproduction steps (from debug)
- Root cause (from debug)
- What was fixed (from implement)
- Validation results (from acceptance)
- Rollbacks and issues (if any)
- Status: Fixed / Not Reproducible / Escalated / Partially Fixed

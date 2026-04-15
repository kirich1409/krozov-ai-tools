---
name: bugfix-flow
description: >-
  Thin orchestrator for bug fix tasks — sequences modular skills: debug → implement → acceptance → PR.
  Invoke when the user reports a bug and wants it fixed end-to-end.
  Trigger on: "/bugfix-flow", "bugfix flow", "fix this bug", "исправь баг", "почини", "это сломалось, почини",
  "fix and ship", "find and fix", "debug and fix".
  Do NOT use for: feature implementation (use feature-flow), investigation without fix (use debug),
  quick obvious fix that doesn't need diagnosis (invoke implement directly).
---

# Bugfix Flow — Bug Fix Orchestrator

Thin orchestrator that routes a bug through diagnosis, fix, verification, and PR.
Contains no implementation logic — each stage is a separate skill invocation via subagents.

**STRICT RULE:** The orchestrator DOES NOT write code, run tests, or perform analysis directly.
It only manages transitions, passes context between stages, and reports summaries to the user.

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
Plan       -> Debug            (plan review FAIL — need more diagnostic context)
Implement  -> Acceptance
Acceptance -> PR               (VERIFIED — bug gone)
Acceptance -> Implement        (FAILED — bug still reproduces or new bugs)
Acceptance -> Debug            (FAILED — fix didn't address root cause)
PR         -> Merge
PR         -> Implement        (review feedback requires code changes)
```

**ALL other transitions are FORBIDDEN.** Before every transition, announce:

> **Stage: [current] → Transition to: [next]. Reason: [why]**

---

## Phase 0: Setup

### 0.1 Worktree

Create an isolated worktree:
1. From the default branch, create a worktree in `.worktrees/<branch-name>`
2. Branch naming: `fix/short-description` — kebab-case
3. If already in a fitting worktree — stay

### 0.2 Understand the bug

Extract from the user's input:
- **Symptom** — what's broken
- **How to reproduce** (if known)
- **Expected vs actual behavior**
- **Source** — issue URL, error log, user description

Generate a slug: kebab-case, 2-4 words.

### 0.3 Profile confirmation

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

1. Create an implementation plan in Plan Mode based on the debug findings
2. Invoke `developer-workflow:plan-review` to validate the plan
3. If FAIL → back to Debug for more context
4. If PASS/CONDITIONAL → proceed to Implement

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

---

## Phase 3: Acceptance

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
| FAILED — same bug | **Acceptance → Implement** | Fix again. If 2nd failure → **Acceptance → Debug** (re-diagnose) |
| FAILED — new bug | Route per bug: trivial → Implement, complex → Debug |
| PARTIAL — bug gone, minor issues | Ask user: fix or ship as-is |

---

## Phase 4: PR

### 4.1 Create PR

Invoke `developer-workflow:create-pr`.

### 4.2 Feedback Stage

Invoke `developer-workflow:feedback-stage` with the PR reference and all artifacts.

It reads all feedback sources, classifies items, and returns a verdict:
- **ROUTING: code/functional/approach** → route to the appropriate stage, then re-run feedback-stage
- **CLEAR** → proceed to merge (4.3)

When waiting for human review — **this orchestrator also stops**.
Resume when the user says to continue.

### 4.3 Merge

When feedback-stage returns CLEAR:

1. Confirm with the user (unless pre-approved)
2. Execute merge:
   ```bash
   gh pr merge "$PR_NUMBER" --squash --delete-branch
   ```
3. Cleanup worktree if applicable

---

## Backward Transitions (STRICT limits)

| From | To | Trigger | Max |
|------|----|---------|-----|
| Acceptance | Implement | Bug still reproduces or new bugs | 3 |
| Acceptance | Debug | Fix didn't address root cause (2 failed implementations) | 1 |
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
- Profile confirmation (Phase 0.3)
- Bug not reproducible (need more info)
- Debug escalation (architectural issue, needs decision)
- Human PR review
- PARTIAL acceptance verdict
- Merge confirmation

---

## Report

After Done (merge complete) or Stop (escalation), save a report to
`swarm-report/<slug>-YYYY-MM-DD.md` with:
- Bug description and source
- Reproduction steps (from debug)
- Root cause (from debug)
- What was fixed (from implement)
- Validation results (from acceptance)
- Rollbacks and issues (if any)
- Status: Fixed / Not Reproducible / Escalated / Partially Fixed

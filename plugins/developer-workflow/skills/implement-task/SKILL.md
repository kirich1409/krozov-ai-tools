---
name: implement-task
description: >
  Explicit-only skill — only invoke when the user directly requests it (e.g. "/developer-workflow:implement-task").
  Do NOT trigger automatically on implementation requests — the user controls when this workflow runs.
  Orchestrates the full development cycle: isolated worktree → TDD → implementation → quality loop
  (simplify + code review) → draft PR → CI/CD monitoring → merge-ready PR.
  Uses state machine transitions, receipt-based gating, and re-anchoring to prevent drift.
disable-model-invocation: true
---

# Implement Task

## Overview

**Explicit-only.** Run this skill only when directly requested via `/developer-workflow:implement-task` — not on every implementation task.

Full autonomous implementation cycle — from understanding the task to a merge-ready PR.
Ask the user only when a decision is **architecturally significant** or **irreversible**. Everything else: decide and proceed.

If any phase fails: identify the root cause — if it's in current changes, fix and re-enter the phase; if pre-existing, ask the user; if unclear, debug systematically: reproduce → isolate → hypothesize → verify → fix. Read error output fully, check logs, narrow the search space before attempting a fix.

---

## Pipeline State Machine

The implementation lifecycle is a state machine with explicit forward and backward transitions. Every task follows one of the pipeline profiles below; the orchestrator tracks the current state and enforces valid transitions.

### Forward transitions (default flow)

```
Research ──→ Plan ──→ Implement ──→ Quality ──→ Verify ──→ PR ──→ Merge
```

### Backward transitions (recovery paths)

| Transition | Trigger |
|------------|---------|
| Plan → Research | Plan review reveals knowledge gaps or missing context |
| Implement → Research | Scope is larger than expected — need more data |
| Quality → Implement | Quality gate found issues that require code changes |
| Verify → Implement | Verification fails — fix and re-verify |
| PR → Implement | Review feedback requires code changes |

**Rules for backward transitions:**
1. Log the reason in the current stage's artifact before transitioning
2. Re-anchor to original intent (see Re-Anchoring Protocol below) before re-entering the earlier stage
3. Carry forward what was learned — do not repeat completed work
4. If a backward transition would be the **3rd return to the same stage** — stop and escalate to the user

---

## Task Profile Selection

After understanding the task (Phase 0.2), classify it into a profile. This determines which pipeline stages apply.

| Profile | Pipeline | Signals |
|---------|----------|---------|
| **Feature** | Research → Plan → Implement → Quality → Verify → PR → Merge | "add", "implement", "build", "create" |
| **Bug Fix** | Reproduce → Diagnose → Fix → Quality → PR → Merge | "fix", "broken", "crash", "regression", error report |
| **Migration** | Research → Snapshot → Migrate → Verify → PR → Merge | "migrate", "replace", "switch to", "move off" — delegates to `code-migration` |
| **Research-only** | Research → Report (no implementation) | "investigate", "compare", "evaluate", "how does X work" |
| **Trivial** | Implement → Quality → PR → Merge | Single-file change, obvious fix, config tweak — no research or plan needed |

Auto-detect from keywords and context. If ambiguous — state the assumed profile and ask the user to confirm.

**Trivial profile:** not every task needs research and planning. For single-file changes, focused bugfixes, config tweaks, and other obviously scoped work — skip directly to implementation. The overhead of the full pipeline must be proportional to the task complexity.

**Bug Fix profile:** skips Research and Plan — starts at Phase 0 (understand task), then Phase 0.4 skill selection routes to systematic debugging (reproduce → isolate → hypothesize → verify → fix). Quality → PR → Merge phases apply as normal.

---

## Receipt-Based Gating

Each stage produces an artifact in `swarm-report/`. The next stage **must** read it before starting. No stage begins without the receipt from the previous one.

### Artifact table

| Stage | Artifact | Required before starting |
|-------|----------|------------------------|
| Research | `<slug>-research.md` | — (first stage; produced by the `research` skill, not by implement-task) |
| Plan | `<slug>-plan.md` | `<slug>-research.md` (Feature/Migration profiles) |
| Implement | `<slug>-implement.md` | `<slug>-plan.md` |
| Quality | `<slug>-quality.md` | `<slug>-implement.md` |
| Verify | `<slug>-verify.md` | `<slug>-quality.md` |
| PR | `<slug>-pr.md` | `<slug>-verify.md` (or `<slug>-quality.md` if no verification defined) |

**Slug derivation:** kebab-case from the task description, short (2-4 words). Example: task "Add user avatar upload" → slug `user-avatar-upload`.

**If the previous artifact is missing** → the previous stage did not complete → do not proceed. Either complete the missing stage or escalate.

**Profile-specific gating:** artifacts are required only for profiles that include the corresponding stage. Trivial profile skips Research and Plan — their artifacts are not required (first artifact is `<slug>-implement.md`). Bug Fix profile skips Research — its artifact is not required. Research-only profile produces only `<slug>-research.md`.

### Stage artifact content

Each artifact must include:
- Stage name and timestamp
- Summary of what was done / found
- Key decisions made (with reasoning)
- Files touched (if implementation stage)
- PASS/FAIL verdict (for Quality and Verify stages)
- Backward transition log (if returning to an earlier stage)

---

## Re-Anchoring Protocol

Before each stage transition, the orchestrator re-anchors to prevent drift during long sessions:

1. Re-read the **original task description** (verbatim from user request)
2. Re-read the **research report** (`swarm-report/<slug>-research.md`) — if it exists
3. Re-read the **plan** (`swarm-report/<slug>-plan.md`) — if it exists
4. Include these paths in the next agent's context prompt — the agent reads them itself

This is mandatory at every stage boundary, including backward transitions. The agent entering a stage must have the original intent loaded — not a telephone-game summary passed through multiple agents.

---

## Escalation Rules

**Stop and return to the user** when any of these conditions are met:

- Scope is **2x+ larger** than initially estimated (e.g., plan said 3 files, reality is 8+)
- A backward transition would be the **3rd return** to the same stage (loop detected)
- A **new dependency** is needed that was not in the plan
- **Multiple valid architectural approaches** exist with no clear winner
- Found a **conflict with existing code** that requires a design decision
- Verification **consistently fails after 3 implementation cycles** (Quality → Implement loop)
- The task requires **access, credentials, or information** that is unavailable

When escalating: state what was tried, what the options are, and what decision is needed. Do not silently pick an approach when escalation criteria are met.

---

## Phase 0: Setup

### 0.1 Worktree

Create an isolated worktree for the task:
1. From `main` (or the project's default branch), create a worktree in `.worktrees/<branch-name>`
2. Branch naming: `feature/short-description`, `fix/short-description`, or `chore/short-description` — kebab-case
3. If already in a worktree whose branch fits the current task — stay, do not create a new one
4. All subsequent work happens in that worktree

### 0.2 Understand the task

Establish three things before writing any code:
- **What** needs to change (behavior, not just files)
- **Why** (context for edge-case decisions)
- **Done criteria** — what does success look like?

Ask **one clarifying question** if any of these is ambiguous. Otherwise proceed.

**Timebox exploration.** Read only the entry point and immediate change surface. The goal is knowing enough to write the first failing test — you'll learn more as you implement.

### 0.2.1 Research (Feature and Migration tasks)

For Feature or Migration tasks, check if research has been done:

1. Look for `swarm-report/<slug>-research.md` — if it exists, read it and carry findings into planning
2. If no research report and the task is non-trivial (touches external APIs, introduces new libraries, requires understanding unfamiliar codebases):
   - Suggest invoking `developer-workflow:research` if it is available
   - If not available, note the gap — proceed without research but flag in the PR description that research was skipped
3. If the task is a simple bugfix or focused change — skip research entirely

The research report, when present, feeds into design (0.3) and skill selection (0.4) via receipt-based gating: include its path in the planning context so the planner builds on research findings rather than re-discovering them.

### 0.3 Task profile selection

Classify the task using the Task Profile Selection table above. This determines which pipeline stages to execute. For Trivial tasks, skip to Phase 0.5. For Migration tasks, delegate to `developer-workflow:code-migration`. For Research-only tasks, delegate to research and produce a report — no implementation phases.

### 0.4 Design (non-trivial tasks only)

For tasks that touch more than one file or introduce a new abstraction, explore the design space before writing code:
1. Launch an Explore agent to analyze the codebase — understand existing patterns, constraints, and integration points
2. Present 2-3 approaches with trade-offs (complexity, maintainability, performance, consistency with existing code)
3. Recommend one approach with reasoning
4. Proceed with the recommendation unless the user objects

Skip for single-file changes, Trivial profile, and focused bugfixes.

### 0.5 Implementation strategy

Select the strategy based on task type. If research report exists, include `swarm-report/<slug>-research.md` path in the strategy context so the chosen approach has access to research findings.

| Task type | Strategy |
|-----------|----------|
| Android/Kotlin technology migration | Invoke `developer-workflow:code-migration` |
| KMP migration | Invoke `developer-workflow:kmp-migration` |
| Multi-step feature or architecture change | **Plan then execute** (see below) |
| Bug or unexpected behavior | **Systematic debugging** (see below) |
| Any other implementation work | **TDD** (see below) |

**Plan then execute:** Create an implementation plan with sections: Scope, Approach, Files to modify, Testing Strategy, Verification Approach, Acceptance Criteria. Save to `swarm-report/<slug>-plan.md`. Then follow the plan step by step — update progress after each logical unit, commit after each meaningful stage.

**Systematic debugging:** Reproduce → isolate → hypothesize → verify → fix. Read error output fully, check logs, narrow the search space before attempting a fix.

**TDD (default):** Write a failing test first → verify it fails → implement the code → verify the test passes → refactor. If the codebase has no test infrastructure, proceed implementation-first and flag the gap in the PR description.

Follow the chosen strategy throughout implementation. Switch to a more specific one if a better match emerges.

---

## Phase 1: Draft PR (create early)

Invoke `developer-workflow:create-pr` with draft intent as soon as the first meaningful commit exists — even before implementation is complete. This gives CI a head start and keeps progress visible.

Update the PR description after each major change so it stays current.

**Stage artifact:** when implementation is complete (all planned changes committed), write `swarm-report/<slug>-implement.md` before moving to the Quality Loop. Include: files changed, key decisions made, and tests added. This artifact is the gate receipt for Phase 2.

---

## Phase 2: Quality Loop

Once implementation is complete, invoke `developer-workflow:prepare-for-pr`. It runs build, simplify, self-review, intent verification, optional expert reviews, and lint/tests in a loop — exit criteria and hook behavior are defined inside that skill.

**Backward transition:** if the quality loop finds issues requiring significant code changes → log the issues in `swarm-report/<slug>-quality.md` → re-anchor → return to implementation (Phase 0.5 strategy).

---

## Phase 2.5: Verification Gate

After the quality loop exits clean, execute the verification approach defined in the plan — if one exists.

### Procedure

1. Read `swarm-report/<slug>-plan.md` and look for a **Verification Approach** section
2. If the section exists, execute each verification step defined there:
   - Run commands listed in the verification approach
   - Perform visual inspections or manual checks as described
   - Check any acceptance criteria that require runtime verification (not just static analysis)
3. If the plan has no Verification Approach section — skip this phase (backward compatible with plans that predate this gate)
4. Save verification result to `swarm-report/<slug>-verify.md`:

```markdown
# Verification: <slug>

**Plan:** swarm-report/<slug>-plan.md
**Status:** PASS | FAIL
**Date:** {date}

## Steps Executed
- [ ] {step 1} — {result}
- [ ] {step 2} — {result}

## Evidence
{screenshots, command output, or other proof}

## Issues Found
{list, or "None"}
```

### Handling Failure

- If verification fails — return to Phase 2 (Implementation) to fix the issue, then re-run quality loop and re-verify
- This backward transition follows the state machine: `Verify → Implement` (verification fails — fix and re-verify)
- Maximum 2 verification retries. After that, escalate to the user.

**Stage artifact:** write `swarm-report/<slug>-quality.md` with gates passed/failed, issues found/fixed, and review verdicts.

---

## Phase 2.5: Verify

Run the verification approach defined in the plan (`swarm-report/<slug>-plan.md` → Verification Approach section). This typically includes running the full test suite, build checks, and any manual or automated verification steps specified during planning.

**Gate check:** `swarm-report/<slug>-quality.md` must exist and show PASS before entering verification.

**Backward transition:** if verification fails → log the failure in `swarm-report/<slug>-verify.md` → re-anchor → return to implementation (Phase 0.5 strategy) to fix the issue, then re-enter Quality Loop (Phase 2) before re-verifying.

**Stage artifact:** write `swarm-report/<slug>-verify.md` with verification steps executed, PASS/FAIL verdict, and any issues found. If no verification approach was defined in the plan (e.g., Trivial profile), skip this phase — PR gating falls back to `<slug>-quality.md`.

---

## Phase 3: Move PR to Ready for Review

**Gate check:** `swarm-report/<slug>-quality.md` must exist and show PASS before proceeding.

Undraft the PR and update its title and description using the ready-for-review template from `developer-workflow:create-pr` (the "Description template — ready-for-review PR" section). The description must be self-contained — a reviewer with no prior context should understand what changed, why, and how to verify it.

```bash
# GitHub
gh pr ready
gh pr edit --title "<final title>" --body "<final description>"

# GitLab
glab mr update --remove-draft --title "<final title>" --description "<final description>"
```

**Stage artifact:** write `swarm-report/<slug>-pr.md` with PR URL, final title, and reviewer assignments.

---

## Phase 4: CI/CD and Review

Wait for CI/CD checks to pass (monitor manually or via the platform UI). Once reviewer feedback arrives, invoke `developer-workflow:address-review-feedback` to handle review comments.

**Backward transition:** if review feedback requires code changes → log the feedback in the PR artifact → re-anchor → return to implementation. After fixing, re-enter the quality loop (Phase 2) before returning to the PR.

---

## Phase 5: Wrap-up

After the PR is merged, clean up:
1. Verify all commits are pushed and the branch is clean (no uncommitted changes, no temp files)
2. Switch back to the main worktree
3. Delete the feature worktree and its branch

---

## Stage Boundary Protocol

At **every** stage boundary (transition between phases), the orchestrator must:

1. Write the stage artifact to `swarm-report/` (receipt for the next stage)
2. Run `/compact` to free context before starting the next stage
3. Re-anchor: re-read original task, research report, and plan (see Re-Anchoring Protocol)
4. Include artifact paths in the next agent's prompt — the agent reads them itself
5. Validate the artifact before advancing: does it address the original task? Is it concrete (file paths, findings, code), not generic filler?

---

## Decision Guide

| Ask the user | Decide autonomously |
|---|---|
| Architecture choices with long-term implications | Which file to edit |
| Breaking changes visible outside the PR | Variable or method naming |
| Unclear done criteria before starting | Whether to add a test |
| Reviewer raises an architectural concern | Order of code review fixes |
| Merge confirmation | Obvious lint fixes |

---

## Commit Hygiene

- One logical change per commit — don't batch everything at the end
- Stage specific files: `git add path/to/file`, never `git add .`
- Message format: `<type>(<scope>): <what and why>` (`feat`, `fix`, `refactor`, `test`, `chore`, `docs`)
- Never `--no-verify`

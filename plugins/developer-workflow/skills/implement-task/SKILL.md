---
name: implement-task
description: >
  Explicit-only skill — only invoke when the user directly requests it (e.g. "/developer-workflow:implement-task").
  Do NOT trigger automatically on implementation requests — the user controls when this workflow runs.
  Orchestrates the full development cycle: isolated worktree → TDD → implementation → quality loop
  (simplify + code review) → draft PR → CI/CD monitoring → merge-ready PR.
disable-model-invocation: true
---

# Implement Task

## Overview

**Explicit-only.** Run this skill only when directly requested via `/developer-workflow:implement-task` — not on every implementation task.

Full autonomous implementation cycle — from understanding the task to a merge-ready PR.
Ask the user only when a decision is **architecturally significant** or **irreversible**. Everything else: decide and proceed.

If any phase fails: identify the root cause — if it's in current changes, fix and re-enter the phase; if pre-existing, ask the user; if unclear, invoke `superpowers:systematic-debugging` (if available) or debug inline by reproducing, isolating, and fixing the issue.

---

## Phase 0: Setup

### 0.1 Worktree

If `superpowers:using-git-worktrees` is available, invoke it. Otherwise, set up the worktree inline:

1. Determine the base branch: `git remote show origin 2>/dev/null | grep "HEAD branch" | awk '{print $NF}'` (fallback: main → master → develop)
2. Check current location:
   - Already in a worktree that fits the task → stay, no action needed
   - On the base branch → create a new worktree:
     ```bash
     SLUG="short-task-description"  # kebab-case, 2-4 words
     BRANCH="feature/$SLUG"         # or fix/$SLUG, chore/$SLUG
     git worktree add .worktrees/$BRANCH $BASE_BRANCH
     cd .worktrees/$BRANCH
     git checkout -b $BRANCH
     ```
3. All subsequent work happens in the worktree.

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

### 0.3 Design (non-trivial tasks only)

For tasks that touch more than one file or introduce a new abstraction, design before writing code.

**Primary approach:** if `superpowers:brainstorming` is available, invoke it.

**Inline fallback** (when superpowers is not installed):

1. Launch an Explore agent to analyze the codebase: existing patterns, related code, module boundaries, dependency direction
2. Based on exploration results, present **2-3 design approaches** with trade-offs:
   - Approach name and one-line summary
   - Pros (maintainability, consistency with existing code, simplicity)
   - Cons (complexity, breaking changes, performance impact)
   - Recommended: yes/no with reasoning
3. Ask the user to pick one. If the user prefers autonomy ("just do it", "your call"), pick the recommended approach and proceed.

If research report exists at `swarm-report/<slug>-research.md`, include its path in the Explore agent prompt so design decisions are informed by research findings.

Skip for single-file changes and focused bugfixes.

### 0.4 Skill selection

Select the most specific applicable skill and invoke it. If research report exists, include `swarm-report/<slug>-research.md` path in the skill invocation context so the chosen skill has access to research findings.

| Task type | Skill | Fallback (if skill unavailable) |
|-----------|-------|---------------------------------|
| Android/Kotlin technology migration | `developer-workflow:code-migration` | — (always available) |
| KMP migration | `developer-workflow:kmp-migration` | — (always available) |
| Multi-step feature or architecture change | `superpowers:writing-plans` → `superpowers:executing-plans` | Use Plan Mode to create a plan, then implement step by step |
| Bug or unexpected behavior | `superpowers:systematic-debugging` | Reproduce → isolate → fix → verify inline |
| Any other implementation work | `superpowers:test-driven-development` (default) | Write failing test → implement → green → refactor (inline TDD) |

Follow the chosen skill throughout implementation. Switch to a more specific skill if a better match emerges. If a `superpowers` skill is listed but not installed, use the fallback approach — the skill works without external plugins.

The core TDD contract: **write a failing test before writing the implementation code it covers.** If the codebase has no test infrastructure, proceed implementation-first and flag the gap in the PR description.

---

## Phase 1: Draft PR (create early)

Invoke `developer-workflow:create-pr` with draft intent as soon as the first meaningful commit exists — even before implementation is complete. This gives CI a head start and keeps progress visible.

Update the PR description after each major change so it stays current.

---

## Phase 2: Quality Loop

Once implementation is complete, invoke `developer-workflow:prepare-for-pr`. It runs build, simplify, self-review, and lint/tests in a loop — exit criteria and hook behavior are defined inside that skill.

After `prepare-for-pr` exits clean, run `code-review:code-review`. Fix any non-minor issues, commit, push, and repeat until only minor issues remain.

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
# Verification: {slug}

**Plan:** swarm-report/{slug}-plan.md
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

---

## Phase 3: Move PR to Ready for Review

Undraft the PR and update its title and description using the ready-for-review template from `developer-workflow:create-pr` (the "Description template — ready-for-review PR" section). The description must be self-contained — a reviewer with no prior context should understand what changed, why, and how to verify it.

```bash
# GitHub
gh pr ready
gh pr edit --title "<final title>" --body "<final description>"

# GitLab
glab mr update --remove-draft --title "<final title>" --description "<final description>"
```

---

## Phase 4: CI/CD and Review

Wait for CI/CD checks to pass (monitor manually or via the platform UI). Once reviewer feedback arrives, invoke `developer-workflow:address-review-feedback` to handle review comments.

---

## Phase 5: Wrap-up

After the PR is merged, invoke `superpowers:finishing-a-development-branch` for worktree cleanup and branch deletion.

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

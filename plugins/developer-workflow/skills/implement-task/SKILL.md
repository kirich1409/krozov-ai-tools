---
name: implement-task
description: >
  Explicit-only skill — only invoke when the user directly requests it (e.g. "/developer-workflow:implement-task").
  Do NOT trigger automatically on implementation requests — the user controls when this workflow runs.
  Orchestrates the full development cycle: isolated worktree → TDD → implementation → quality loop
  (simplify + code review) → draft PR → CI/CD monitoring → merge-ready PR.
---

# Implement Task

## Overview

**Explicit-only.** Run this skill only when directly requested via `/developer-workflow:implement-task` — not on every implementation task.

Full autonomous implementation cycle — from understanding the task to a merge-ready PR.
Ask the user only when a decision is **architecturally significant** or **irreversible**. Everything else: decide and proceed.

If any phase fails: identify the root cause — if it's in current changes, fix and re-enter the phase; if pre-existing, ask the user; if unclear, invoke `superpowers:systematic-debugging`.

---

## Phase 0: Setup

### 0.1 Worktree

Invoke `superpowers:using-git-worktrees`. All subsequent work happens in that worktree.

### 0.2 Understand the task

Establish three things before writing any code:
- **What** needs to change (behavior, not just files)
- **Why** (context for edge-case decisions)
- **Done criteria** — what does success look like?

Ask **one clarifying question** if any of these is ambiguous. Otherwise proceed.

**Timebox exploration.** Read only the entry point and immediate change surface. The goal is knowing enough to write the first failing test — you'll learn more as you implement.

### 0.3 Design (non-trivial tasks only)

For tasks that touch more than one file or introduce a new abstraction, invoke `superpowers:brainstorming` before writing code. Skip for single-file changes and focused bugfixes.

### 0.4 Skill selection

Select the most specific applicable skill and invoke it:

| Task type | Skill |
|-----------|-------|
| Android/Kotlin technology migration | `developer-workflow:code-migration` |
| KMP migration | `developer-workflow:kmp-migration` |
| Multi-step feature or architecture change | `superpowers:writing-plans` → `superpowers:executing-plans` |
| Bug or unexpected behavior | `superpowers:systematic-debugging` |
| Any other implementation work | `superpowers:test-driven-development` (default) |

Follow the chosen skill throughout implementation. Switch to a more specific skill if a better match emerges.

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

Invoke `developer-workflow:pr-drive-to-merge` and let it run. This skill pauses only when human input is needed (out-of-scope issues, merge confirmation, stale review).

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
| Merge confirmation (handled by pr-drive-to-merge) | Obvious lint fixes |

---

## Commit Hygiene

- One logical change per commit — don't batch everything at the end
- Stage specific files: `git add path/to/file`, never `git add .`
- Message format: `<type>(<scope>): <what and why>` (`feat`, `fix`, `refactor`, `test`, `chore`, `docs`)
- Never `--no-verify`

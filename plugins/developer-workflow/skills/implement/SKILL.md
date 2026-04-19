---
name: implement
description: >-
  Implementation stage — takes a task with optional context artifacts and produces working code.
  Designed to be called by an orchestrator or directly by the user. Accepts any task source:
  plain text description, GitHub/Jira/Linear issue URL, or a reference to an existing artifact
  (research.md, debug.md, plan.md).

  Pipeline: understand task → write code → quality loop (/check + intent check) → produce artifacts.
  Semantic review, simplification, expert review, and PR-level quality checks live in the
  separate `finalize` stage. Does NOT create worktrees, PRs, or run live QA — those are
  separate stages.

  Use when: "implement", "write the code", "fix this", "сделай", "реализуй", "напиши код",
  "пофикси", or when an orchestrator delegates the implementation stage.
  Do NOT use for: debugging/investigation (use debug), research (use research),
  PR creation (use create-pr), live QA (use acceptance).
disable-model-invocation: true
---

# Implement

Implementation stage for the development pipeline. Takes a task with context, writes code,
ensures quality, produces artifacts for the next stage.

---

## Phase 1: Understand Task

### 1.1 Normalize input

The task can arrive from any source. Extract from whatever is provided:

- **What** needs to change (behavior, not files)
- **Why** (context for edge-case decisions)
- **Type**: feature or bug fix (infer from context)
- **Done criteria** — what does success look like?

| Input | How to extract |
|-------|---------------|
| Plain text | Parse directly |
| GitHub/Jira/Linear URL | Fetch the issue, read title + body + comments |
| `research.md` artifact | Read findings, recommended approach, constraints |
| `debug.md` artifact | Read root cause, reproduction steps, recommended fix direction |
| `plan.md` artifact | Read scope, approach, files to modify, acceptance criteria |
| Combination | Cross-reference all sources |

### 1.2 Read context artifacts

If artifact paths are provided (by orchestrator or user), read them:

- `swarm-report/<slug>-research.md` — approach recommendations, library choices, risks
- `swarm-report/<slug>-debug.md` — root cause, reproduction steps, fix direction
- `swarm-report/<slug>-plan.md` — scope, file list, testing strategy, acceptance criteria

If no artifacts exist — proceed from the task description alone. Do a minimal codebase
exploration to understand the change surface before writing code.

### 1.3 Generate slug

If not provided by the orchestrator, derive a slug from the task: kebab-case, 2-4 words.
Example: "Fix login crash on empty email" → `fix-login-empty-email`.

---

## Phase 2: Implement

### 2.1 Choose implementation approach

| Context | Approach |
|---------|----------|
| `plan.md` exists | Follow the plan step by step |
| `debug.md` exists | Apply fix in the direction indicated by root cause analysis |
| Neither, multi-file change | Explore codebase → design approach → implement |
| Neither, single-file change | Implement directly |

### 2.2 Delegate to specialist agents

Route code writing to the appropriate agent based on the technology:

| Domain | Agent |
|--------|-------|
| Kotlin business logic, data layer, ViewModels | `kotlin-engineer` |
| Jetpack Compose / Compose Multiplatform UI | `compose-developer` |
| Swift business logic, data layer | `swift-engineer` |
| SwiftUI screens and components | `swiftui-developer` |
| Gradle / build system | `build-engineer` |

For changes spanning multiple domains — delegate each part to the appropriate specialist
sequentially or in parallel when independent.

If the change is small and doesn't require specialist knowledge — implement directly
without delegation.

### 2.3 Commit incrementally

One logical change per commit. For multi-step implementations — one commit per meaningful
stage (e.g., model, repository, UI layer). Stage specific files, never `git add .`.

---

## Phase 3: Quality Loop

Run two quality gates sequentially. A failure triggers a fix cycle before advancing. Implement is strictly "write the code and verify it works per the plan" — everything beyond is the `finalize` stage (see `docs/ORCHESTRATION.md` § Finalize).

After code is written, run the Quality Loop defined in [`docs/ORCHESTRATION.md`](../../docs/ORCHESTRATION.md#implement--quality-loop-2-gates) — that document is the single source of truth for gate definitions, verdict handling, and iteration limits.

Summary for this skill's callers:
- Gate 1 invokes `/check` (mechanical: build + lint + typecheck + tests)
- Gate 2 is the intent check — re-read task + plan, verify the diff addresses them; scope creep or drift → fix or flag
- A gate failure triggers a fix cycle; total loop is capped per ORCHESTRATION.md

Do not duplicate gate details here — read ORCHESTRATION.md before executing. If ORCHESTRATION.md is missing, escalate rather than guessing the current rules.

---

## Phase 4: Produce Artifacts

### Implementation artifact

Save to `swarm-report/<slug>-implement.md`:

```
# Implementation: <slug>

**Task:** <original task description>
**Type:** Feature / Bug fix
**Date:** <date>

## What Was Done
<summary of changes>

## Files Changed
- <file path> — <what and why>

## Key Decisions
- <decision> — <reasoning>

## Commits
- <hash> <message>
```

### Quality artifact

Save to `swarm-report/<slug>-quality.md`:

```
# Quality: <slug>

**Date:** <date>
**Status:** PASS / FAIL (escalated)

## Gates
| # | Gate | Result | Attempts |
|---|------|--------|----------|
| 1 | Mechanical checks (`/check`) | PASS/FAIL | N |
| 2 | Intent check | PASS/DRIFT | — (single-pass; DRIFT triggers full loop re-entry, counted as an additional total iteration) |

## Issues Found and Fixed
- <issue> — <fix applied>

## Intent Check
<PASS / DRIFT with explanation>

## Notes for finalize
<anything surfaced during implement that the finalize stage should know about: test gaps, security concerns, structural concerns that did not block mechanical checks>
```

---

## Escalation

Stop and report to the orchestrator / user when:

- Scope is **2x+ larger** than initially estimated
- A quality gate fails after **3 fix attempts**
- A **new dependency** is needed that wasn't in the plan
- **Multiple valid approaches** exist with no clear winner
- Found a **conflict with existing code** requiring a design decision
- Task requires **access or information** that is unavailable

When escalating: state what was tried, what the options are, what decision is needed.

---

## Scope Rules

- **In scope:** everything described in the task / plan / debug artifact
- **Adjacent obvious fixes** (missing import, typo in new code): fix silently
- **Out of scope, non-obvious** (pre-existing failures, unrelated issues): note in report, don't fix
- **No "while I'm here" improvements** — no refactoring, no extra features, no docs for unchanged code

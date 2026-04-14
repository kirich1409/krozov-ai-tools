---
name: feature-flow
description: >-
  Thin orchestrator for feature tasks — sequences modular skills through the full pipeline.
  Invoke when the user gives a feature task and wants it done end-to-end autonomously.
  Trigger on: "/feature-flow", "implement this feature", "сделай эту фичу от начала до конца",
  "full cycle", "autonomous implementation".
  Do NOT use for: bug fixes (use bugfix-flow), research-only (use research), single quick change
  (invoke implement directly).
---

# Feature Flow — Feature Orchestrator

Thin orchestrator that routes a feature task through modular skills. Contains no implementation
logic — each stage is a separate skill invocation via subagents.

**STRICT RULE:** The orchestrator DOES NOT write code, run tests, or perform analysis directly.
It only manages transitions, passes context between stages, and reports summaries to the user.

---

## Strict State Machine

### Allowed transitions

```
Setup      -> Research         (unknown APIs, libraries, or architectural decisions)
Setup      -> Implement        (trivial/simple task — skip research/planning)
Research   -> Decompose        (large feature — split into tasks)
Research   -> PlanReview       (complex single-task — needs plan review)
Research   -> Implement        (simple single-task — research was enough)
Decompose  -> PlanReview
PlanReview -> Implement
PlanReview -> Research         (FAIL — knowledge gaps)
Implement  -> Acceptance
Acceptance -> PR               (VERIFIED)
Acceptance -> Implement        (FAILED — bugs to fix)
Acceptance -> Debug            (FAILED — unclear root cause)
PR         -> Merge
PR         -> Implement        (review feedback requires code changes)
```

**Decision criteria for skipping stages:**
- **Skip Research:** task is well-understood, no external APIs, no unfamiliar libraries
- **Skip Decompose:** task is a single logical unit, no independent sub-parts
- **Skip PlanReview:** change is straightforward, touches 1-3 files, no architectural impact

**ALL other transitions are FORBIDDEN.** Before every transition, announce:

> **Стадия: [текущая] → Переход на: [следующая]. Причина: [почему]**

---

## Phase 0: Setup

### 0.1 Worktree

Create an isolated worktree for the task:
1. From the default branch, create a worktree in `.worktrees/<branch-name>`
2. Branch naming: `feature/short-description` — kebab-case
3. If already in a fitting worktree — stay

### 0.2 Understand the task

Extract from the user's input:
- **What** needs to change
- **Why** (context)
- **Done criteria**

Generate a slug: kebab-case, 2-4 words.

Ask **one clarifying question** if ambiguous. Otherwise proceed.

### 0.3 Profile confirmation

Auto-detect the profile from keywords and context. Then confirm:

> **Определён профиль: Бизнес-фича. Верно?**

If the user says it's a bug — redirect to `/bugfix-flow`.
If the task is trivial (single-file, obvious change) — announce skip and go to Implement.

---

## Phase 1: Research and Planning

### 1.1 Research

Invoke `developer-workflow:research` with the task description and constraints.
Wait for `swarm-report/<slug>-research.md`.

Skip if the task is well-understood and doesn't touch external APIs, unfamiliar libraries,
or architectural decisions.

### 1.2 Decompose (optional)

If the task is large enough to split into independent sub-tasks:
- Invoke `developer-workflow:decompose-feature` with the research artifact
- Wait for `swarm-report/<slug>-decomposition.md`

Skip for single-task features.

### 1.3 Create plan (optional)

If the task remains a single task after research but is complex enough to benefit from review:
- Create a short implementation plan in Plan Mode
- Save it to `swarm-report/<slug>-plan.md`

Skip if decomposition already produced the execution plan, or if the task is simple enough
to implement directly.

### 1.4 Plan review (optional)

If `swarm-report/<slug>-plan.md` or `swarm-report/<slug>-decomposition.md` was produced:
- Invoke `developer-workflow:plan-review` with that artifact
- If FAIL → **Стадия: PlanReview → Research.** Back to 1.1 with gaps identified
- If CONDITIONAL → proceed with noted concerns
- If PASS → proceed

---

## Phase 2: Implement and Verify (per task)

For each task (or the single task if no decomposition):

### 2.1 Implement

**Context passing (MANDATORY):** when invoking the implement skill, pass:
1. Original user request (verbatim)
2. Summary of previous stage result
3. Paths to all artifacts produced so far
4. If rollback — reason for the rollback

Invoke `developer-workflow:implement` with:
- Task description
- Slug
- Paths to available artifacts (`research.md`, `plan.md`, `decomposition.md`)

Wait for `swarm-report/<slug>-implement.md` + `swarm-report/<slug>-quality.md`.

### 2.2 Acceptance

Invoke `developer-workflow:acceptance` with:
- Spec source: requirements from the task / plan / decomposition
- The running app

The acceptance skill saves an E2E scenario to `swarm-report/<slug>-e2e-scenario.md`.
This file uses checkboxes for each verification step — completed steps (`[x]`) survive
context compaction and are NOT re-checked on resume.

Wait for `swarm-report/<slug>-acceptance.md`.

**Route by result:**
- VERIFIED → **Стадия: Acceptance → PR**
- FAILED (P0/P1, obvious cause) → **Стадия: Acceptance → Implement.** Max 3 round-trips.
- FAILED (P0/P1, unclear cause) → **Стадия: Acceptance → Debug.** Then Implement.
- PARTIAL (P2/P3) → ask user: fix now or ship as-is
- Out-of-scope bugs → create issues, don't block

---

## Phase 3: PR

### 3.1 Create PR

Invoke `developer-workflow:create-pr`.

**PR granularity** (when decomposed):
- Independent tasks → one PR per task (invoke create-pr after each task's acceptance)
- Tightly coupled tasks → bundled PR after all tasks pass acceptance

### 3.2 Drive to merge

Invoke `developer-workflow:pr-drive-to-merge`.

This skill handles CI monitoring, bot review polling, and review feedback.
When it stops for human review — **this orchestrator also stops**.

Resume when the user says to continue.

---

## Backward Transitions (STRICT limits)

| From | To | Trigger | Max |
|------|----|---------|-----|
| PlanReview | Research | FAIL — knowledge gaps | 2 |
| Acceptance | Implement | FAILED bugs | 3 |
| Acceptance | Debug | P0/P1 with unclear cause | 1 |
| PR | Implement | Significant code changes requested | 2 |

Each backward transition:
1. **Announce** the transition with reason
2. Log reason in the current artifact
3. Re-read original task + all artifacts (re-anchor)
4. Pass rollback reason to the next subagent
5. If max reached → escalate to user

---

## Stop Points

The orchestrator **stops and waits for the user** at:
- Profile confirmation (Phase 0.3)
- Human PR review (via pr-drive-to-merge)
- PARTIAL acceptance verdict (user decides: fix or ship)
- Escalation (scope explosion, repeated failures, architectural decision needed)
- Merge confirmation

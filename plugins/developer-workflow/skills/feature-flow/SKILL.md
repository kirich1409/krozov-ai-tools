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

**AUTONOMY RULE:** After the user approves the plan (Phase 0.4), work autonomously without
stopping. Interrupt the user ONLY for critical blockers listed in the Escalation section.
The goal: all interaction happens upfront, execution runs unattended.

---

## Strict State Machine

### Allowed transitions

```
Setup         -> Research         (unknown APIs, libraries, or architectural decisions)
Setup         -> GenerateTestPlan (trivial/simple task — skip research)
Setup         -> Implement        (trivial single-file task — skip all planning)
Research      -> GenerateTestPlan
GenerateTestPlan -> Decompose     (large feature — split into tasks)
GenerateTestPlan -> PlanReview    (complex single-task — needs plan review)
GenerateTestPlan -> Implement     (simple single-task — planning enough)
Decompose     -> PlanReview       (complex decomposition — needs review)
Decompose     -> Implement        (straightforward tasks — skip review)
PlanReview    -> Approval         (plan ready — present to user)
PlanReview    -> Research         (FAIL — knowledge gaps)
Approval      -> Implement        (user confirmed)
Implement     -> Acceptance
Acceptance    -> FeedbackStage    (VERIFIED)
Acceptance    -> Implement        (FAILED — code bug, max 3 round-trips)
Acceptance    -> Research         (FAILED — wrong approach)
Acceptance    -> PlanReview       (FAILED — design issue)
FeedbackStage -> Implement        (code issue in feedback)
FeedbackStage -> Research         (approach issue in feedback)
FeedbackStage -> Acceptance       (functional issue in feedback)
FeedbackStage -> Done             (all feedback resolved, merged)
```

**Decision criteria for skipping stages:**
- **Skip Research:** task is well-understood, no external APIs, no unfamiliar libraries
- **Skip GenerateTestPlan:** task is trivial, single obvious change
- **Skip Decompose:** task is a single logical unit, no independent sub-parts
- **Skip PlanReview:** change is straightforward, touches 1-3 files, no architectural impact
- **Skip Approval:** user has already said "start immediately" or equivalent

**ALL other transitions are FORBIDDEN.** Before every transition, announce:

> **Stage: [current] → Transition to: [next]. Reason: [why]**

---

## Phase 0: Setup

### 0.1 Understand the task

**Note: worktree is created outside this flow** — by the environment or a parent orchestrator
before feature-flow is invoked. Do not create worktrees here.

Extract from the user's input:
- **What** needs to change
- **Why** (context)
- **Done criteria**

Generate a slug: kebab-case, 2-4 words.

Ask **one clarifying question** if ambiguous. Otherwise proceed.

### 0.2 Profile confirmation

Auto-detect the profile from keywords and context. Then confirm:

> **Detected profile: Feature. Correct?**

If the user says it's a bug — redirect to `/bugfix-flow`.
If the task is trivial (single-file, obvious change) — announce skip and go to Implement.

---

## Phase 1: Research and Planning

### 1.1 Research (optional)

Invoke `developer-workflow:research` with the task description and constraints.
Wait for `swarm-report/<slug>-research.md`.

Skip if the task is well-understood and doesn't touch external APIs, unfamiliar libraries,
or architectural decisions.

### 1.2 Generate Test Plan

Invoke `developer-workflow:generate-test-plan` with:
- Task description and done criteria
- Research artifact path (if exists)

Wait for `swarm-report/<slug>-test-plan.md`.

The test plan is the acceptance contract — it defines exactly what will be verified
before the feature is considered done. It is produced before implementation so that
the implementor knows what success looks like.

Skip only for truly trivial tasks (single-file, obvious change with no user-facing behavior).

### 1.3 Decompose (optional)

If the task is large enough to split into independent sub-tasks:
- Invoke `developer-workflow:decompose-feature` with the research artifact and test plan
- Wait for `swarm-report/<slug>-decomposition.md`

Skip for single-task features.

### 1.4 Plan Review (optional)

If decomposition was produced or the task is complex:
- Invoke `developer-workflow:plan-review` with the plan/decomposition artifact
- If FAIL → **Stage: PlanReview → Research.** Back to 1.1 with gaps identified
- If CONDITIONAL → proceed with noted concerns
- If PASS → proceed to Approval

### 0.4 Consolidated Approval (stop point)

Before starting implementation, present a summary to the user:

```
## Ready to implement

**Task:** <original task>
**Approach:** <1-2 sentence summary from research/plan>

**Test plan:** swarm-report/<slug>-test-plan.md
  - <list top 3-5 test cases>

**Implementation plan:** <source artifact>
  - <list tasks/steps>

**Estimated scope:** <N files, N tasks>

Proceed? (say "go" to start, or give corrections)
```

If the user has already said "start immediately" / "just do it" / equivalent — skip this stop
and proceed autonomously.

After approval — run autonomously. Do not stop unless a critical escalation condition is met.

---

## Phase 2: Implement and Verify

### Task parallelism

When decomposition produced multiple tasks:
- Group tasks by wave (as defined in `<slug>-decomposition.md`)
- Within each wave: launch tasks in parallel (independent tasks have no shared state)
- Between waves: wait for the previous wave to complete before starting the next
- Each task runs its own Implement → Acceptance cycle independently

### 2.1 Implement (per task)

**Context passing (MANDATORY):** when invoking the implement skill, pass:
1. Original user request (verbatim)
2. Summary of previous stage result
3. Paths to all artifacts produced so far
4. If rollback — reason for the rollback

Invoke `developer-workflow:implement` with:
- Task description
- Slug
- Paths to available artifacts (`research.md`, `plan.md`, `decomposition.md`, `test-plan.md`)

Wait for `swarm-report/<slug>-implement.md` + `swarm-report/<slug>-quality.md`.

### 2.2 Acceptance (per task)

Invoke `developer-workflow:acceptance` with:
- Spec source: `swarm-report/<slug>-test-plan.md` (pre-built contract)
- Implementation artifact: `swarm-report/<slug>-implement.md`

The acceptance skill executes the test plan and verifies requirements are met.
It saves the result to `swarm-report/<slug>-acceptance.md`.

**Route by result and failure type:**

| Result | Failure type | Transition | Max |
|--------|-------------|------------|-----|
| VERIFIED | — | → FeedbackStage | — |
| FAILED | Code bug (P0/P1) | → Implement | 3 |
| FAILED | Wrong approach / design flaw | → PlanReview or Research | 2 |
| FAILED | Requirements misunderstood | → escalate to user | — |
| PARTIAL | P2/P3 only | → ask user: fix or ship | — |

Out-of-scope bugs → create issues, don't block.

---

## Phase 3: Feedback Stage

### 3.1 Create PR

Before invoking `feedback-stage`, create a PR:
- Invoke `developer-workflow:create-pr`

**PR granularity** (when decomposed):
- Independent tasks → one PR per task (create-pr after each task's acceptance)
- Tightly coupled tasks → bundled PR after all tasks pass acceptance

### 3.2 Feedback Stage

Invoke `developer-workflow:feedback-stage` with:
- PR reference (URL or number)
- All artifacts: `research.md`, `test-plan.md`, `implement.md`, `acceptance.md`
- Full git diff of changes

The feedback-stage reads all feedback sources, classifies each item, and returns a verdict
to this orchestrator. It does NOT fix code or execute merges.

**Route by feedback-stage verdict:**

| Verdict | Orchestrator action |
|---------|-------------------|
| ROUTING: code issue | → Implement, then re-run Acceptance → feedback-stage |
| ROUTING: approach issue | → Research or PlanReview, then Implement → Acceptance → feedback-stage |
| ROUTING: functional issue | → Acceptance, then feedback-stage |
| CLEAR | → Merge (see 3.3) |

### 3.3 Merge

When feedback-stage returns CLEAR (no actionable items, CI green, approved):

1. Confirm with the user (unless pre-approved: "merge when ready")
2. Execute merge:
   ```bash
   # GitHub
   gh pr merge "$PR_NUMBER" --squash --delete-branch
   # GitLab
   glab mr merge "$MR_IID" --squash --remove-source-branch --yes
   ```
3. Cleanup worktree if applicable:
   ```bash
   git checkout "$BASE" && git pull origin "$BASE"
   git worktree remove ".worktrees/$HEAD" 2>/dev/null
   ```

---

## Backward Transitions (STRICT limits)

| From | To | Trigger | Max |
|------|----|---------|-----|
| PlanReview | Research | FAIL — knowledge gaps | 2 |
| Acceptance | Implement | FAILED code bug | 3 |
| Acceptance | Research / PlanReview | FAILED approach | 2 |
| FeedbackStage | Implement | code issue | 3 |
| FeedbackStage | Research | approach issue | 2 |
| FeedbackStage | Acceptance | functional issue | 2 |

Each backward transition:
1. **Announce** the transition with reason
2. Log reason in the current artifact
3. Re-read original task + all artifacts (re-anchor)
4. Pass rollback reason to the next subagent
5. If max reached → escalate to user

---

## Stop Points

The orchestrator stops and waits for the user **only** at:

| Point | When |
|-------|------|
| Profile confirmation | Phase 0.2 (always) |
| Consolidated approval | Phase 0.4 (unless user said "start immediately") |
| PARTIAL acceptance verdict | User decides: fix or ship |
| Escalation | See Escalation section below |

Everything else — handle autonomously, log in artifacts, continue.

---

## Escalation

Stop and escalate to the user when:

- Scope is **2x+** larger than the initial estimate (plan: 3 files, reality: 8+)
- **3rd return** to the same stage (loop detected)
- A **new dependency** is required, not covered by the plan
- **Multiple architectural approaches** with no clear winner
- **Conflict with existing code** requiring a design decision
- Verification **consistently fails** after 3 Implement → Acceptance cycles
- **Access or credentials** are needed that are not available
- Requirements are **fundamentally misunderstood** — needs user clarification

When escalating: state what was tried, what the options are, what decision is needed.

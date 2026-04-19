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

**Preconditions (caller's responsibility, NOT this skill's):**
- A working branch suitable for the feature is already set up (via worktree or otherwise)
  and the current working directory is where the work should happen.
- The caller (main agent, wrapping agent, or user) has resolved this before invoking
  the skill. The skill itself does not inspect, create, switch, or clean up branches
  or worktrees.

---

## Strict State Machine

### Allowed transitions

```
Setup          -> Research         (unknown APIs, libraries, or architectural decisions)
Setup          -> Implement        (trivial/simple task — skip research/planning)
Research       -> Decompose        (large feature — split into tasks)
Research       -> PlanReview       (complex single-task — needs multiexpert review)
Research       -> DesignOptions    (high-arch-risk single-task — explore alternatives first)
DesignOptions  -> PlanReview       (user picked an option)
DesignOptions  -> Research         (options exposed missing requirements — re-research)
Research       -> TestPlan         (simple single-task, test-plan stage not skipped)
Research       -> Implement        (simple single-task, test-plan stage skipped)
Decompose      -> PlanReview       (complex decomposition — needs review)
Decompose      -> TestPlan         (straightforward tasks, test-plan stage not skipped)
Decompose      -> Implement        (straightforward tasks, test-plan stage skipped)
PlanReview     -> TestPlan         (test-plan stage not skipped)
PlanReview     -> Implement        (test-plan stage skipped)
PlanReview     -> Research         (FAIL — knowledge gaps)
TestPlan       -> TestPlanReview
TestPlanReview -> Implement        (PASS or WARN)
TestPlanReview -> TestPlan         (FAIL — revise loop, max 3 cycles)
TestPlanReview -> escalate         (after 3 failed revise cycles)
Implement      -> Finalize
Finalize       -> Acceptance       (PASS — no BLOCKs remain)
Finalize       -> Implement        (ESCALATE after 3 rounds; user routes back to implement)
Finalize       -> escalate         (ESCALATE after 3 rounds; user picks non-implement path)
Acceptance     -> PR               (VERIFIED)
Acceptance     -> Implement        (FAILED — bugs to fix; Implement then re-runs Finalize)
Acceptance     -> TestPlan         (FAILED — add Regression TC for new bugs)
Acceptance     -> Debug            (FAILED — unclear root cause)
PR             -> Merge
PR             -> Implement        (review feedback requires code changes)
```

**Decision criteria for skipping stages:**
- **Skip Research:** task is well-understood, no external APIs, no unfamiliar libraries
- **Skip Decompose:** task is a single logical unit, no independent sub-parts
- **Skip PlanReview:** change is straightforward, touches 1-3 files, no architectural impact
- **Skip TestPlan (+ TestPlanReview):** see [TestPlan Stage Skip Detection](#testplan-stage-skip-detection) — default-on stage, skipped only when a detector condition fires.

**ALL other transitions are FORBIDDEN.** Before every transition, announce:

> **Stage: [current] → Transition to: [next]. Reason: [why]**

---

## Phase 0: Setup

### 0.1 Understand the task

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

### 1.3a Design options (optional, default-skip)

Between creating a plan and reviewing it, optionally insert a `design-options` stage to generate and compare 2-3 alternative architectures. Useful when one of these fires:

1. The task is marked **high architectural risk** (touches module boundaries, introduces new abstractions, replaces a core pattern).
2. The plan at 1.3 describes the "what" clearly but leaves the "how" open (multiple plausible approaches).
3. User explicitly asks for "alternatives", "variants", "options" before committing to one.

If any trigger fires, invoke `developer-workflow:design-options` with:
- Slug
- Spec / plan artifact path — any of `docs/specs/<YYYY-MM-DD>-<slug>.md` (from `write-spec`), `swarm-report/<slug>-plan.md`, or `swarm-report/<slug>-decomposition.md`
- Research artifact path (optional) — `swarm-report/<slug>-research.md`

The skill launches 2–3 `architecture-expert` agents in parallel under distinct style constraints (Minimal / Clean / Pragmatic), presents the options as `swarm-report/<slug>-design-options.md`, and waits for the user's choice. The chosen option is persisted to `swarm-report/<slug>-design.md`. When this stage ran, pass that path to Plan Review as additional context alongside the plan/decomposition artifact.

**Skip** for tasks where a single approach is obvious, bug fixes with a pre-determined fix direction, or single-file changes — overhead not justified.

Announce: **Stage: Plan → DesignOptions → PlanReview** (or **Plan → PlanReview** when skipped).

### 1.4 Plan review (optional)

If `swarm-report/<slug>-plan.md` or `swarm-report/<slug>-decomposition.md` was produced:
- Invoke `developer-workflow:multiexpert-review` with that artifact. Prepend an explicit
  profile hint to the args so the engine does not fall through to `AskUserQuestion` when
  the artifact has no frontmatter / path match:

  ```
  profile: implementation-plan
  ---
  <rest of args: artifact path + context>
  ```
- If FAIL → **Stage: PlanReview → Research.** Back to 1.1 with gaps identified
- If CONDITIONAL → proceed with noted concerns
- If PASS → proceed

### 1.5 TestPlan (default-on)

Generate the test plan for the feature before implementation starts. Default-on stage:
runs unless the skip detector or the `--skip-test-plan` override fires (see
[TestPlan Stage Skip Detection](#testplan-stage-skip-detection) and
[Override: --skip-test-plan](#override---skip-test-plan)).

**Pre-check — mount existing permanent test plan:** before invoking
`generate-test-plan`, check whether a pre-orchestration test plan already exists. If
`docs/testplans/<slug>-test-plan.md` exists AND `swarm-report/<slug>-test-plan.md`
receipt does NOT exist — this is a user-authored plan. Do NOT regenerate. The
orchestrator owns this write: emit a mount-receipt following the canonical format from
`generate-test-plan/SKILL.md` §Receipt (field overrides: `status: Mounted`,
`review_verdict: skipped`, `source_spec: existing (pre-orchestration)`). Skip both
TestPlan and TestPlanReview; announce **Stage: \<current\> → Implement (test plan mounted
from existing)**, where `<current>` is whichever stage actually routed here (PlanReview,
Decompose, or Research — any of these can feed Phase 1.5 when later stages were skipped).
To regenerate, the user must re-invoke with `--regenerate-test-plan`.

Otherwise, invoke `developer-workflow:generate-test-plan` with the feature slug and
paths to the available artifacts (`research.md`, `decomposition.md`, `plan.md`, any spec
document). Wait for the permanent test plan at `docs/testplans/<slug>-test-plan.md` and
the receipt at `swarm-report/<slug>-test-plan.md` (receipt `status: Draft`,
`review_verdict: pending`). Announce: **Stage: PlanReview → TestPlan** (or from Research
/ Decompose when earlier stages were skipped).

### 1.6 TestPlanReview (default-on)

Review the generated test plan via the test-plan profile of `multiexpert-review`.

- Invoke `developer-workflow:multiexpert-review` with the permanent test-plan file
  (`docs/testplans/<slug>-test-plan.md`) as input. Prepend an explicit profile hint so the
  engine routes deterministically even if the file's frontmatter or path-glob were ever
  refactored:

  ```
  profile: test-plan
  ---
  <rest of args: permanent test-plan path + context>
  ```

  (Path-glob `docs/testplans/**` already matches, but the explicit hint is symmetric with
  other callsites and removes detector-dependency from the orchestrator.)
- Route by verdict — see [TestPlanReview Verdict Handling](#testplanreview-verdict-handling).
- On completion (PASS or WARN) the receipt is updated with `review_verdict` and
  `status: Ready`; the pipeline transitions to Implement.

---

## TestPlan Stage Skip Detection

The TestPlan stage (and its paired TestPlanReview) is **default-on**. It is skipped if
**any one** of the following conditions holds (boolean OR):

1. **Single-file change without behavior change** — the planned change touches exactly one
   file (per `git diff` stats or the decomposition artifact) AND the spec/task introduces
   **no** new Acceptance Criteria (AC delta = 0 vs. prior state).
2. **Pure refactor** — the task commit prefix is `refactor:`, OR the spec contains no new
   AC and only lists technical / structural changes (no observable behavior change).
3. **Internal utility without external contract change** — every affected file is internal:
   not exported from the module's public API surface (not under `exports/` or equivalent,
   not a `public` class/function in the module manifest, not an HTTP/RPC endpoint, not
   a published library symbol).
4. **Single-task decompose with low complexity** — `decompose-feature` produced ≤ 2 tasks
   AND every task is complexity `S` (small). Taken straight from the decomposition
   artifact's complexity column.

(Bug profiles route to `bugfix-flow` at Phase 0.2 and never reach this gate, so they do
not need a dedicated skip condition here.)

When the detector triggers, announce the reason on the stage transition, e.g.:

> **Stage: PlanReview → Implement. Reason: TestPlan skipped — single-file change with no
> new AC (skip condition #1).**

## Override: --skip-test-plan

The user can force the TestPlan stage off via a slash-argument on the `feature-flow` call:

```
/feature-flow --skip-test-plan "task description"
```

Semantics: **force-off**. Even if the skip detector would return `false` (TestPlan would
normally run), the stage is **not** executed — neither TestPlan nor TestPlanReview. The
orchestrator transitions directly to Implement.

Use case: rare cases where the user is certain test-plan effort is not justified —
experimental prototype, throwaway demo feature, exploratory spike. Announce it explicitly:

> **Stage: PlanReview → Implement. Reason: TestPlan skipped — `--skip-test-plan` override.**

## Test Plan Regeneration

The permanent artifact `docs/testplans/<slug>-test-plan.md` can be modified after the
initial TestPlan stage in two scenarios:

**On rollback Acceptance → Implement (bugs discovered):**
- Whenever a fix is undertaken — regardless of P0/P1/P2/P3 severity — append a new
  `## Regression TC` section to the permanent file covering the new bugs.
- The receipt keeps its existing `review_verdict` (no re-review required for appended
  regression TCs); only the `updated` timestamp is refreshed.

**On spec change (full regeneration):**
- Full regeneration happens only through an **explicit** re-invocation of `/feature-flow`
  with a `--regenerate-test-plan` flag. The orchestrator does NOT regenerate silently.
- Before overwriting, the previous permanent file is renamed to
  `docs/testplans/<slug>-test-plan.md.prev` for fast diff.
- The receipt is rewritten with `status: Draft`, `review_verdict: pending`, and updated
  `source_spec` / `phase_coverage` / `updated` fields. The next TestPlanReview run sets a
  fresh verdict.

## TestPlanReview Verdict Handling

The TestPlanReview stage maps `multiexpert-review` verdicts (test-plan profile — see
`plugins/developer-workflow/skills/multiexpert-review/profiles/test-plan.md`) to
pipeline transitions:

- **PASS** — all five checklist items satisfied. Unconditional transition to Implement.
  Receipt: `review_verdict: PASS`, `status: Ready`.
- **WARN** — items (a)–(c) satisfied, but (d) or (e) violated. **Does not block.**
  Transition to Implement. Receipt: `review_verdict: WARN`, warnings list enumerating the
  violated items — preserved for downstream review and acceptance context. No revise-loop.
- **FAIL** — any of (a), (b), (c) violated. Run the revise-loop: **TestPlan ← TestPlanReview**
  up to 3 cycles. Each cycle patches the permanent test-plan file, re-reviews with the
  same agents, and appends to the multiexpert-review state file's `Verdict History` (see
  `multiexpert-review/SKILL.md` §Persistence — the receipt itself carries only the latest
  `review_verdict`, not the per-cycle history). After 3 failed cycles →
  **escalate to the user** with three options: (a) accept WARN manually and proceed,
  (b) revise the spec and restart the pipeline, (c) use `--skip-test-plan` to bypass the
  stage for this run.

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

### 2.1a Create draft PR (early)

After `implement` returns a clean Quality Loop result and the branch has been pushed, invoke `developer-workflow:create-pr` with the `--draft` argument:

> Stage: Implement → Finalize (draft PR created)

Rationale: the remote branch + draft PR become the source of truth for the work in progress. Reviewers can inspect the code online, the description carries the plan and available artifacts, and later stages push refinements to the same PR rather than accumulating local-only changes.

If a draft PR already exists for this branch (e.g., re-entry on rollback), `create-pr --draft` refreshes the body instead of creating a new PR — idempotent by design.

### 2.2 Finalize (code-quality pass)

After `implement` passes its two gates (mechanical checks + intent check), invoke `developer-workflow:finalize` with:
- Slug
- Path to `swarm-report/<slug>-plan.md` (for Phase A code-reviewer anchor)

`finalize` runs a multi-round loop (max 3 rounds): code-reviewer → /simplify → pr-review-toolkit trio → conditional expert reviews, with `/check` between fixes.

Wait for `swarm-report/<slug>-finalize.md`.

**Route by result:**
- **PASS** (no BLOCKs remain) → **Stage: Finalize → Acceptance**
- **ESCALATE** (3 rounds with BLOCKs) — orchestrator stops and reports to user. User decides: (a) accept the risks and go to acceptance manually; (b) route back to `implement` to address root issues; (c) escalate as a task-level re-scope.

### 2.3 Acceptance

Invoke `developer-workflow:acceptance` with:
- Spec source: requirements from the task / plan / decomposition
- The running app
- Test-plan receipt path (when TestPlan stage ran): `swarm-report/<slug>-test-plan.md` —
  the acceptance skill reads `permanent_path` from the receipt and feeds the permanent
  test plan to `manual-tester` as the primary source (see `acceptance/SKILL.md` Step 1).
  When the TestPlan stage was skipped and no receipt exists, acceptance falls back to its
  existing mount-as-existing or on-the-fly generation logic.

The acceptance skill saves an E2E scenario to `swarm-report/<slug>-e2e-scenario.md`.
This file uses checkboxes for each verification step — completed steps (`[x]`) survive
context compaction and are NOT re-checked on resume.

Wait for `swarm-report/<slug>-acceptance.md`.

**Route by result:**
- VERIFIED → **Stage: Acceptance → PR**
- FAILED (P0/P1, obvious cause) → **Stage: Acceptance → Implement.** Max 3 round-trips.
- FAILED (P0/P1, unclear cause) → **Stage: Acceptance → Debug.** Then Implement.
- FAILED (P0/P1, new bugs need test coverage) → **Stage: Acceptance → TestPlan.** Append
  `## Regression TC` to the permanent test plan (see
  [Test Plan Regeneration](#test-plan-regeneration)), then continue with Implement.
- PARTIAL (P2/P3) → ask user: fix now or ship as-is
- Out-of-scope bugs → create issues, don't block

---

## Phase 3: PR

### 3.1 Promote to ready for review

The draft PR already exists (created at 2.1a) and has been pushed with fix cycles and acceptance updates. Now mark it ready:

Invoke `developer-workflow:create-pr` with the `--promote` argument.

`--promote` will:
1. Refresh the PR body with the final summary (what changed, how to test, artifacts, status table showing all stages PASS).
2. Mark the PR ready for review. The exact platform command (`gh pr ready`, version-specific `glab` flag, etc.) is `create-pr`'s responsibility — the orchestrator does not repeat it here.

> Stage: Acceptance → PR (promoted to ready)

**PR granularity** (when decomposed):
- Independent tasks → one PR per task (create + promote per task's acceptance)
- Tightly coupled tasks → single bundled PR; promote only after all tasks pass acceptance

### 3.2 Hand-off to user

The orchestrator stops after `create-pr` finishes. CI monitoring and merge
execution are outside this pipeline.

When review feedback arrives (bot or human), the user invokes
`developer-workflow:triage-feedback` to categorize and prioritize it. The
resulting `swarm-report/<slug>-triage.md` becomes the input for a new
Implement cycle if FIXABLE items exist — the orchestrator resumes at
Implement on the user's instruction.

---

## Backward Transitions (STRICT limits)

| From | To | Trigger | Max |
|------|----|---------|-----|
| PlanReview | Research | FAIL — knowledge gaps | 2 |
| TestPlanReview | TestPlan | FAIL — test-plan revise loop | 3 |
| Finalize | Implement | ESCALATE — user routes back to fix root issues | 1 |
| Acceptance | Implement | FAILED bugs | 3 |
| Acceptance | TestPlan | FAILED — append Regression TC for new bugs | 3 |
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
- Profile confirmation (Phase 0.2)
- After `create-pr` — hand-off to user. User runs `triage-feedback` when review
  feedback arrives and decides whether to resume at `implement` with FIXABLE items;
  CI monitoring and merge execution are outside this pipeline.
- PARTIAL acceptance verdict (user decides: fix or ship)
- TestPlanReview FAIL after 3 revise cycles — user picks: accept WARN manually, revise
  spec, or rerun with `--skip-test-plan`.
- Escalation (scope explosion, repeated failures, architectural decision needed)

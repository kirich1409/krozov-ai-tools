# Feature-Flow State Machine

Full set of allowed transitions for the orchestrator, decision criteria for skipping
optional stages, and the backward-transition limits. Consult when routing between stages
or deciding whether to skip an optional stage.

## Allowed Transitions

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

**ALL other transitions are FORBIDDEN.** Before every transition, announce:

> **Stage: [current] → Transition to: [next]. Reason: [why]**

## Decision Criteria for Skipping Stages

- **Skip Research:** task is well-understood, no external APIs, no unfamiliar libraries.
- **Skip Decompose:** task is a single logical unit, no independent sub-parts.
- **Skip PlanReview:** change is straightforward, touches 1-3 files, no architectural impact.
- **Skip TestPlan (+ TestPlanReview):** see
  [TestPlan Stage](./test-plan-stage.md#skip-detection) — default-on stage, skipped only
  when a detector condition fires.

## Backward Transitions — Strict Limits

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

1. **Announce** the transition with reason.
2. Log the reason in the current artifact.
3. Re-read the original task + all artifacts (re-anchor).
4. Pass the rollback reason to the next subagent.
5. If the max is reached → escalate to user.

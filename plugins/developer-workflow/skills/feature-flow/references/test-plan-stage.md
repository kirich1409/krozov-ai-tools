# TestPlan / TestPlanReview Stages

Detailed rules for the default-on TestPlan stage and its paired TestPlanReview: when to
skip, how to override, how regeneration works, and how verdicts map to transitions.

## Skip Detection

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

## Override: `--skip-test-plan`

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
initial TestPlan stage in two scenarios.

### On rollback Acceptance → Implement (bugs discovered)

- Whenever a fix is undertaken — regardless of P0/P1/P2/P3 severity — append a new
  `## Regression TC` section to the permanent file covering the new bugs.
- The receipt keeps its existing `review_verdict` (no re-review required for appended
  regression TCs); only the `updated` timestamp is refreshed.

### On spec change (full regeneration)

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

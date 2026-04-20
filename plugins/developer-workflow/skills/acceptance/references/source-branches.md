Referenced from: `plugins/developer-workflow/skills/acceptance/SKILL.md` (§Step 1: Gather Inputs).

# Acceptance — Source Branches and Spec Frontmatter

Detailed input-resolution logic for Step 1. Acceptance requires at least one verification
source (spec, test plan, or `debug.md`); this file specifies how each branch fires and
what artifacts it produces.

## 1.1 Spec Source (optional if a test plan or debug.md is provided)

Accept any combination of: Figma mockups, PRD / requirements, acceptance criteria list, PR
description, GitHub/Linear issue. Read all provided sources.

**Read the spec frontmatter.** If present, load `platform`, `surfaces`, `risk_areas`,
`non_functional`, `acceptance_criteria_ids`, `design.figma`. These drive the conditional
triggers in Step 3 plus two invariant guards on the base plan:

- `surfaces` contains `ui` forces `manual-tester` into the fan-out when a scenario source
  exists, even if Step 0 detected a non-UI project (hybrid products with both UI and
  non-UI surfaces).
- `surfaces` is set but does not contain `ui` on a UI-detected project means the spec
  explicitly excludes UI — skip `manual-tester` even if `has_ui_surface` is true, and note
  this in the Check Plan section of the receipt.

If the spec has no frontmatter (pre-iteration-2 specs, external specs, or plain-text
issues) — every conditional defaults to "not triggered" and `surfaces` is treated as
unspecified; only the base checks keyed off `has_ui_surface` run. This preserves backward
compatibility.

## 1.2 Probe available artifacts (parallel)

Before branching, read the following in a single batched Read call set. Each may
error-as-absent — that is expected:

- `swarm-report/<slug>-test-plan.md` (receipt)
- `docs/testplans/<slug>-test-plan.md` (permanent)
- `swarm-report/<slug>-debug.md` (bug-fix reproduction steps)

Combined with inline inputs and spec sources, one of the branches below fires. Record the
selected branch as `test_plan_source` in the receipt.

### Branch 1 — Receipt present (`test_plan_source: receipt`)

**Condition:** `swarm-report/<slug>-test-plan.md` exists.

Read the receipt's YAML frontmatter and load `permanent_path`. Interpret `review_verdict`
per the canonical definition in `generate-test-plan/SKILL.md` §Receipt: treat
`PASS` / `WARN` / `skipped` as proceed; `FAIL` and `pending` as blockers that escalate
back to the invoking orchestrator or the user (acceptance is called from `feature-flow`,
`bugfix-flow`, or standalone — it does not assume which), recommending revision via
`multiexpert-review` before acceptance runs again. Pass the **permanent file** to
`manual-tester` as the primary test-plan source. If the receipt has a `platform:` field,
use it as an additional input to Step 0's override policy.

### Branch 2 — Permanent file exists without receipt (`test_plan_source: mounted`)

**Condition:** Branch 1 did not fire **and** `docs/testplans/<slug>-test-plan.md` exists
on disk without a matching receipt.

Acceptance owns the mount-receipt when invoked outside `feature-flow`. Emit a
mount-receipt at `swarm-report/<slug>-test-plan.md` following the canonical format in
`generate-test-plan/SKILL.md` §Receipt. Apply the mount overrides: `status: Mounted`,
`review_verdict: skipped`, `source_spec: existing (pre-orchestration)`. Derive
`phase_coverage` from the permanent file's phase headings; omit the field if coverage
cannot be determined reliably. Pass the permanent file to `manual-tester`.

### Branch 3 — Inline test plan, spec, or `debug.md` available (`test_plan_source: on-the-fly`)

**Condition:** Branches 1 and 2 did not fire **and** the invocation provides a test plan
inline, a spec source, `swarm-report/<slug>-debug.md`, or any combination of these.
`debug.md` is treated as a spec-like source for bug-fix verification when no receipt or
permanent test plan exists, so this branch also covers the standalone "debug-only" case.

Four modes:

- **Test plan only (no spec / no debug.md)** — execute as-is; verdict depends on TC
  pass/fail.
- **Test plan + spec and/or debug.md** — execute the plan, cross-reference against the
  spec or reproduction steps, flag obvious gaps to the user ("spec/debug mentions X but
  the test plan doesn't cover it — add a TC?").
- **Spec only (no test plan)** — generate a test plan from the spec: identify testable
  flows, write TC-prefixed cases with tiers/steps/expected results, present for approval,
  adjust per feedback.
- **`debug.md` only (no test plan, no spec)** — derive E2E from the inverted reproduction
  steps (Step 2 owns the inversion); record `test_plan_source: on-the-fly`. No on-the-fly
  TC generation beyond what Step 2 already produces.

### Branch 4 — Nothing available (`test_plan_source: absent`)

**Condition:** no receipt, no permanent file, no inline test plan, no spec source, and no
`swarm-report/<slug>-debug.md` (bug-fix path).

Proceed to SKILL.md §Step 1.5 Source-Missing Gate. Do not run any checks.

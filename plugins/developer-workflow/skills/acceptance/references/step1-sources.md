# Step 1 — Source Branching Detail

Acceptance requires at least one verification source. Step 1.2 probes artifacts in parallel,
then one of the four branches below fires. Record the selected branch as `test_plan_source`
in the receipt.

## 1.1 Spec source

Accept any combination of: Figma mockups, PRD / requirements, acceptance criteria list, PR
description, GitHub/Linear issue. Read all provided sources.

**Read the spec frontmatter.** If present, load `platform`, `surfaces`, `risk_areas`,
`non_functional`, `acceptance_criteria_ids`, `design.figma`. These drive the conditional
triggers in Step 3 plus two invariant guards on the base plan:

- `ui ∈ surfaces` forces `manual-tester` into the fan-out when a scenario source exists,
  even if Step 0 detected a non-UI project (hybrid products with both UI and non-UI
  surfaces).
- `surfaces` set and does not contain `ui` on a UI-detected project means the spec
  explicitly excludes UI — skip `manual-tester` even if `has_ui_surface` is true, and note
  this in the Check Plan section of the receipt.

If the spec has no frontmatter (pre-iteration-2 specs, external specs, or plain-text issues)
— every conditional defaults to "not triggered" and `surfaces` is treated as unspecified;
only the base checks keyed off `has_ui_surface` run. This preserves backward compatibility.

## 1.2 Probe available artifacts (parallel)

Before branching, read the following in a single batched Read call set. Each may error-as-absent
— that is expected:

- `swarm-report/<slug>-test-plan.md` (receipt)
- `docs/testplans/<slug>-test-plan.md` (permanent)
- `swarm-report/<slug>-debug.md` (bug-fix reproduction steps)

## Branch 1 — Receipt present (`test_plan_source: receipt`)

**Condition:** `swarm-report/<slug>-test-plan.md` exists.

Read the receipt's YAML frontmatter and load `permanent_path`. Interpret `review_verdict`
per the canonical definition in `generate-test-plan/SKILL.md` §Receipt: treat
`PASS` / `WARN` / `skipped` as proceed; `FAIL` and `pending` as blockers that escalate back
to the invoking orchestrator or the user (acceptance is called from `feature-flow`,
`bugfix-flow`, or standalone — it does not assume which), recommending revision via
`multiexpert-review` before acceptance runs again. Pass the **permanent file** to
`manual-tester` as the primary test-plan source. If the receipt has a `platform:` field,
use it as an additional input to Step 0's override policy.

## Branch 2 — Permanent file exists without receipt (`test_plan_source: mounted`)

**Condition:** Branch 1 did not fire **and** `docs/testplans/<slug>-test-plan.md` exists
on disk without a matching receipt.

Acceptance owns the mount-receipt when invoked outside `feature-flow`. Emit a mount-receipt
at `swarm-report/<slug>-test-plan.md` following the canonical format in
`generate-test-plan/SKILL.md` §Receipt. Apply the mount overrides: `status: Mounted`,
`review_verdict: skipped`, `source_spec: existing (pre-orchestration)`. Derive
`phase_coverage` from the permanent file's phase headings; omit the field if coverage
cannot be determined reliably. Pass the permanent file to `manual-tester`.

## Branch 3 — Inline test plan or spec available (`test_plan_source: on-the-fly`)

**Condition:** Branches 1 and 2 did not fire **and** the invocation provides a test plan
inline, a spec source, or both.

Three modes:

- **Test plan only (no spec)** — execute as-is; verdict depends on TC pass/fail.
- **Test plan + spec** — execute the plan, cross-reference against the spec, flag obvious
  gaps to the user ("spec mentions X but the test plan doesn't cover it — add a TC?").
- **Spec only (no test plan)** — generate a test plan from the spec: identify testable
  flows, write TC-prefixed cases with tiers/steps/expected results, present for approval,
  adjust per feedback.

## Branch 4 — Nothing available (`test_plan_source: absent`)

**Condition:** no receipt, no permanent file, no inline test plan, no spec source, no
`swarm-report/<slug>-debug.md` (bug-fix path).

Proceed to Step 1.5. Do not run any checks.

## Step 1.5 — Source-missing gate proposal table

| Situation | Proposal |
|---|---|
| No spec, no test plan, implement receipt exists (feature) | Run `/write-spec` (requirements doc) or `/generate-test-plan` (tests only), then re-run acceptance. |
| Spec exists without acceptance criteria, no test plan, UI project | Run `/generate-test-plan` to produce executable TCs, or add acceptance criteria to the spec. |
| Bugfix path with no `swarm-report/<slug>-debug.md` | Run `/debug` to capture reproduction steps, then re-run acceptance. |
| Only `design.figma` in spec, no test plan, UI project | Design-only review possible via ux-expert; for functional acceptance also run `/generate-test-plan`. |

Options offered to the user:

1. **Create the missing source** — invoke the proposed upstream skill, then re-run acceptance.
2. **Abort acceptance** — exit without a receipt; user re-invokes when ready.

Exploratory QA without a scenario is the `bug-hunt` skill's responsibility. Do not offer it
as a fallback inside acceptance.

From `feature-flow` / `bugfix-flow` this gate rarely fires — upstream skills guarantee a
source. Standalone invocations are the main user.

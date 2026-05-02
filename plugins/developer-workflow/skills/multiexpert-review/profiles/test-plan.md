---
name: test-plan
description: Profile for test-plan artifacts (docs/testplans/<slug>-test-plan.md and swarm-report/<slug>-test-plan.md receipts). Verdict alphabet PASS/WARN/FAIL with 5-item checklist. Primary reviewer business-analyst; adds domain specialists when spec invokes their concerns.

detect:
  frontmatter_type: [test-plan, test-plan-receipt]
  path_globs:
    - "docs/testplans/**"
    - "swarm-report/*-test-plan.md"
  structural_signatures:
    - "^## Test Cases"
    - "^#{1,6}\\s+TC-[\\w-]+"
    - "P[0-3]"

reviewer_roster:
  primary: [business-analyst]
  optional_if:
    - when: "auth|token|encryption|PII|credential"
      agent: security-expert
    - when: "SLA|latency|throughput|budget"
      agent: performance-expert
    - when: "a11y|accessibility"
      agent: ux-expert

allow_single_reviewer: true

verdicts: [PASS, WARN, FAIL]

severity_mapping:
  - items: ["a", "b", "c"]
    severity: critical
  - items: ["d", "e", "g"]
    severity: major

source_routing:
  plan_mode: N/A
  file: edit-in-place
  conversation: N/A

receipt:
  path_template: "swarm-report/<slug>-test-plan.md"
  fields_to_update: [review_verdict, review_warnings, review_blockers]
---

## Rubric

Every reviewer must evaluate the test-plan against these items and report the status of each one explicitly in their response. Copy the items verbatim into the review prompt so findings are comparable across agents:

- **(a) AC coverage** — every Acceptance Criterion from the linked spec has ≥1 Test Case that verifies it. Missing or weak mapping is a violation.
- **(b) Negative balance** — every happy-path (positive) TC has ≥2 unhappy/negative TCs covering the same flow (invalid input, error states, boundary violations, concurrent or race conditions). A plan that is mostly happy paths violates this item.
- **(c) Edge cases present** — at least one TC is explicitly tagged as an edge case (boundary value, empty/null, maximum size, timezone/locale boundaries, concurrency, resource exhaustion, etc.). If the plan has no edge-case TC at all, this item is violated.
- **(d) Non-functional scenarios where applicable** — if the linked spec mentions any of {SLA, latency budget, throughput, a11y, auth, encryption, PII, resource limits, rate limits}, there must be ≥1 non-functional TC covering that concern (performance, accessibility, security). Applicability is driven by spec content — if the spec mentions none of these triggers, this item is trivially satisfied.
- **(e) Priority-risk alignment** — priorities (P0–P3) are consistent with risk assessment: any high-risk flow (data loss, auth, payment, destructive actions) is at P0–P1; any user-facing critical path is at P0–P1; trivial/informational cases are at P2–P3. Mismatch between stated risk and assigned priority violates this item.
- **(g) Instrumentation declared** — when the spec / task is `user-facing` or `prod-bound`, or the feature touches an observability hot-path (network calls, payments, background jobs, auth, data migrations), the test plan ends with a `## Non-functional / Instrumentation` section that lists Log events / Metrics / Traces / Alerts / Dashboards (or sub-headings filled with concrete declarations). For internal / dev-only / pure-refactor work, an explicit `N/A: <reason>` (one line) is acceptable. A missing section, or one labelled simply `TBD` / `?` / blank, violates this item.

## Verdict policy

| Verdict | Trigger | Exit condition |
|---------|---------|----------------|
| **FAIL** (blocker) | Any of items **(a)**, **(b)**, **(c)** is violated | Plan MUST be revised. Engine drives the revise-loop up to 3 cycles. After 3 cycles still FAIL → escalate to user. Pipeline is blocked. |
| **WARN** (non-blocking) | Items (a)–(c) all satisfied, but **(d)**, **(e)**, or **(g)** is violated | Pipeline continues. Engine records `review_verdict: WARN` in the receipt with the explicit list of violated items. No revise-loop required. |
| **PASS** (clean) | Every item satisfied | Pipeline continues unconditionally. Engine records `review_verdict: PASS` in the receipt. |

A single critical from any agent with medium-or-higher confidence is enough to trigger FAIL, matching the engine's aggregation rules.

## Prompt augmentation

Every agent reviewing a test-plan receives the following checklist verbatim in their Step 3 prompt (the engine substitutes this section into `{PROFILE_PROMPT_AUGMENTATION}` literally — not by reference to the Rubric section above). Each agent must explicitly report the status of each item (satisfied / violated, with rationale). The engine parses these into the severity mapping.

---

**Test-plan rubric — evaluate each item explicitly:**

- **(a) AC coverage** — every Acceptance Criterion from the linked spec has ≥1 Test Case that verifies it. Missing or weak mapping is a violation.
- **(b) Negative balance** — every happy-path (positive) TC has ≥2 unhappy/negative TCs covering the same flow (invalid input, error states, boundary violations, concurrent or race conditions). A plan that is mostly happy paths violates this item.
- **(c) Edge cases present** — at least one TC is explicitly tagged as an edge case (boundary value, empty/null, maximum size, timezone/locale boundaries, concurrency, resource exhaustion, etc.). If the plan has no edge-case TC at all, this item is violated.
- **(d) Non-functional scenarios where applicable** — if the linked spec mentions any of {SLA, latency budget, throughput, a11y, auth, encryption, PII, resource limits, rate limits}, there must be ≥1 non-functional TC covering that concern (performance, accessibility, security). Applicability is driven by spec content — if the spec mentions none of these triggers, this item is trivially satisfied.
- **(e) Priority-risk alignment** — priorities (P0–P3) are consistent with risk assessment: any high-risk flow (data loss, auth, payment, destructive actions) is at P0–P1; any user-facing critical path is at P0–P1; trivial/informational cases are at P2–P3. Mismatch between stated risk and assigned priority violates this item.
- **(g) Instrumentation declared** — when the spec / task is `user-facing` or `prod-bound`, or the feature touches an observability hot-path (network calls, payments, background jobs, auth, data migrations), the test plan ends with a `## Non-functional / Instrumentation` section that lists Log events / Metrics / Traces / Alerts / Dashboards (or sub-headings filled with concrete declarations). For internal / dev-only / pure-refactor work, an explicit `N/A: <reason>` (one line) is acceptable. A missing section, or one labelled simply `TBD` / `?` / blank, violates this item.

For every Issue you raise, use the item ID as the title stem — e.g. `(a) AC coverage: API X has no test case`. This keeps synthesizer aggregation greppable.

## Receipt integration

After Step 4 synthesis, the engine updates `swarm-report/<slug>-test-plan.md` (the receipt, not the permanent file at `docs/testplans/<slug>-test-plan.md`) with:

- `review_verdict: PASS | WARN | FAIL`
- On WARN: `review_warnings:` list enumerating violated items `(d)`, `(e)` with one-line rationale each
- On FAIL: `review_blockers:` list enumerating violated items from `(a)–(c)` with the blocking finding and suggested fix

The receipt format is owned by the `generate-test-plan` skill — this profile only writes the three fields listed in `receipt.fields_to_update`.

## Revise-loop (FAIL only)

Same state machine as the engine default: Verdict:FAIL → Fix Plan → Re-review, max 3 cycles. The "Fix Plan" action edits the permanent test-plan file at `docs/testplans/<slug>-test-plan.md`. Each cycle appends to `Verdict History` in the state file with the new verdict and remaining blockers.

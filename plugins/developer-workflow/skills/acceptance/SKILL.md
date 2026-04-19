---
name: acceptance
description: >
  Acceptance verification — confirm implementation meets spec (feature) or that a bug no longer
  reproduces (bug fix). Orchestrator: detects project type, verifies a source exists (spec AC,
  test plan, or debug.md), fans out parallel checks to `manual-tester` (UI + scenario),
  `code-reviewer` (delta), plus `business-analyst` / `ux-expert` / `security-expert` /
  `performance-expert` and a build smoke as triggered by spec frontmatter and project type,
  then aggregates via PoLL rules. Without a source, proposes `/write-spec`,
  `/generate-test-plan`, or `/debug`. Trigger on: "test this", "verify against spec",
  "QA the implementation", "run the test plan", "validate acceptance criteria",
  "verify the PR", "verify the fix", "confirm bug is gone", "acceptance", "приёмка",
  "проверь", "протестируй".
disable-model-invocation: true
---

# Acceptance

Choreographer skill. Detects project type, confirms a verification source exists, fans out
parallel checks to specialized agents, aggregates verdicts into one receipt. Acceptance
executes a pre-existing verification contract — it does not invent checks. When no contract
is available, it halts and proposes the correct upstream skill.

---

## Vocabulary

Canonical values used throughout this skill. Downstream consumers (feature-flow, bugfix-flow,
create-pr) read these from the receipt.

- **`project_type`** — one of: `android`, `ios`, `web`, `desktop`, `backend-jvm`,
  `backend-node`, `cli`, `library`, `generic`. Source of truth: ORCHESTRATION.md §Project
  type detection.
- **`has_ui_surface`** — boolean derived from `project_type`. True for `android`, `ios`,
  `web`, `desktop`. False otherwise (`generic` → ask user).
- **`ecosystem`** — build stack: `gradle`, `node`, `rust`, `go`, `python`, `xcode`. Used for
  build-smoke command selection only; orthogonal to `project_type`.
- **Per-check verdict** — each sub-check reports `PASS | WARN | FAIL | SKIPPED`, plus
  `severity` (`critical | major | minor`), `confidence` (`high | medium | low`), and
  `domain_relevance` (`high | medium | low`) for aggregation.
- **Bug severity** — `P0 | P1 | P2 | P3`. Unchanged from prior receipt schema, primary axis
  for `feature-flow`/`bugfix-flow` routing.
- **Aggregated Status** — `VERIFIED | FAILED | PARTIAL`. Derived; see §Aggregation.

---

## Step 0: Detect Project Type

Follow the canonical heuristic in `plugins/developer-workflow/docs/ORCHESTRATION.md` §Project
type detection. Output: `project_type`, `has_ui_surface`, `ecosystem`.

**Override policy.** If the spec frontmatter `platform:` list is non-empty, **spec wins** —
take the first platform value as `project_type` (or mark multi-platform when the list has
more than one), and record `project_type_override: spec` in the receipt. If the user corrects
detection mid-run, record `project_type_override: user`.

Step 0 file reads and Step 1 file reads are disjoint. You MAY issue both sets in one batched
Read call set to avoid serial round-trips.

---

## Step 1: Gather Inputs

Acceptance requires at least one verification source. If none is available, Step 1.5 halts.

### 1.1 Spec Source (optional if a test plan or debug.md is provided)

Accept any combination of: Figma mockups, PRD / requirements, acceptance criteria list, PR
description, GitHub/Linear issue. Read all provided sources.

**Read the spec frontmatter.** If present, load `platform`, `surfaces`, `risk_areas`,
`non_functional`, `acceptance_criteria_ids`, `design.figma`. These drive the conditional
triggers in Step 3. If the spec has no frontmatter (pre-iteration-2 specs, external specs,
or plain-text issues) — every conditional defaults to "not triggered"; only the base checks
run. This preserves backward compatibility.

### 1.2 Probe available artifacts (parallel)

Before branching, read the following in a single batched Read call set. Each may error-as-absent
— that is expected:

- `swarm-report/<slug>-test-plan.md` (receipt)
- `docs/testplans/<slug>-test-plan.md` (permanent)
- `swarm-report/<slug>-debug.md` (bug-fix reproduction steps)

Combined with inline inputs and spec sources, one of the branches below fires. Record the
selected branch as `test_plan_source` in the receipt.

#### Branch 1 — Receipt present (`test_plan_source: receipt`)

**Condition:** `swarm-report/<slug>-test-plan.md` exists.

Read the receipt's YAML frontmatter and load `permanent_path`. Interpret `review_verdict` per
the canonical definition in `generate-test-plan/SKILL.md` §Receipt: treat `PASS` / `WARN` /
`skipped` as proceed; `FAIL` and `pending` as blockers that escalate back to the orchestrator.
Pass the **permanent file** to `manual-tester` as the primary test-plan source. If the
receipt has a `platform:` field, use it as an additional input to Step 0's override policy.

#### Branch 2 — Permanent file exists without receipt (`test_plan_source: mounted`)

**Condition:** Branch 1 did not fire **and** `docs/testplans/<slug>-test-plan.md` exists on
disk without a matching receipt.

Acceptance owns the mount-receipt when invoked outside `feature-flow`. Emit a mount-receipt
at `swarm-report/<slug>-test-plan.md` following the canonical format in
`generate-test-plan/SKILL.md` §Receipt with mount overrides: `status: Mounted`,
`review_verdict: skipped`, `source_spec: existing (pre-orchestration)`. Derive
`phase_coverage` from the permanent file's phase headings; omit the field if coverage cannot
be determined reliably. Pass the permanent file to `manual-tester`.

#### Branch 3 — Inline test plan or spec available (`test_plan_source: on-the-fly`)

**Condition:** Branches 1 and 2 did not fire **and** the invocation provides a test plan
inline, a spec source, or both.

Three modes:

- **Test plan only (no spec)** — execute as-is; verdict depends on TC pass/fail.
- **Test plan + spec** — execute the plan, cross-reference against the spec, flag obvious gaps
  to the user ("spec mentions X but the test plan doesn't cover it — add a TC?").
- **Spec only (no test plan)** — generate a test plan from the spec: identify testable flows,
  write TC-prefixed cases with tiers/steps/expected results, present for approval, adjust per
  feedback.

#### Branch 4 — Nothing available (`test_plan_source: absent`)

**Condition:** no receipt, no permanent file, no inline test plan, no spec source, no
`swarm-report/<slug>-debug.md` (bug-fix path).

Proceed to Step 1.5. Do not run any checks.

---

## Step 1.5: Source-Missing Gate

### Proposal table

| Situation | Proposal |
|---|---|
| No spec, no test plan, implement receipt exists (feature) | Run `/write-spec` (requirements doc) or `/generate-test-plan` (tests only), then re-run acceptance. |
| Spec exists without acceptance criteria, no test plan, UI project | Run `/generate-test-plan` to produce executable TCs, or add acceptance criteria to the spec. |
| Bugfix path with no `swarm-report/<slug>-debug.md` | Run `/debug` to capture reproduction steps, then re-run acceptance. |
| Only `design.figma` in spec, no test plan, UI project | Design-only review possible via ux-expert; for functional acceptance also run `/generate-test-plan`. |

### Options

1. **Create the missing source** — invoke the proposed upstream skill, then re-run acceptance.
2. **Abort acceptance** — exit without a receipt; user re-invokes when ready.

Exploratory QA without a scenario is the `bug-hunt` skill's responsibility. Do not offer it as
a fallback inside acceptance.

From `feature-flow` / `bugfix-flow` this gate rarely fires — upstream skills guarantee a
source. Standalone invocations are the main user.

---

## Step 2: Persist E2E Scenario

**Only relevant if `has_ui_surface == true` and a scenario source exists** (test plan, spec
with AC, or debug.md). Re-anchoring against this file is enforced by `manual-tester` —
acceptance writes it once here; re-reads during aggregation only.

The running-app environment (device, simulator, emulator, browser) is **owned by
`manual-tester` itself** — see its Step 0 Environment Setup. This skill does not probe
devices, run `gradlew installDebug`, or start dev servers; it delegates that responsibility
wholesale to the agent.

Save to `swarm-report/<slug>-e2e-scenario.md`:

```markdown
# E2E Scenario: <task name>
Type: Feature / Bug fix
Project type: <project_type>
Spec source: <what was used>

## Steps
- [ ] 1. <concrete user action> → Expected: <result>
- [ ] 2. <concrete user action> → Expected: <result>
```

For bug fixes, steps come from `debug.md` reproduction steps inverted:
- Original: "Step X triggers the bug" → E2E: "Step X no longer triggers the bug".

Compaction-resilience (enforced by `manual-tester`, not by this skill): checkbox marks survive
compaction; completed steps (`[x]`) are not repeated; resume from the first incomplete step.

---

## Step 2.5: Dedup Probe

Read `swarm-report/<slug>-quality.md` (produced by `implement`'s Quality Loop). If its
`Status:` is `PASS`, `code-reviewer` is skipped in Step 3. Field name matches `implement`'s
receipt schema — this skill does **not** rely on any `diff_hash` or similar field, and will
not skip on that basis alone.

When `code-reviewer` is skipped, write a stub artifact at
`swarm-report/<slug>-acceptance-code.md` with the per-check schema, `verdict: SKIPPED`, and a
one-line body. This preserves the one-file-per-check invariant the aggregation in Step 4
depends on.

If `<slug>-quality.md` does not exist or `Status:` is `FAIL`, run `code-reviewer` normally.

This probe is synchronous — it decides the Step 3 fan-out composition and emits the stub
before fan-out.

---

## Step 3: Run Checks (parallel fan-out)

Pick the check plan by `has_ui_surface` plus conditional triggers read from spec frontmatter.
Emit **one** message containing all tool calls simultaneously (Agent calls + Bash smoke). Do
not wait for any to return before dispatching the others.

### Base check plan

| `has_ui_surface` | Base fan-out |
|---|---|
| `true` | `manual-tester` + `code-reviewer` (unless skipped by Step 2.5) |
| `false` | `code-reviewer` (unless skipped by Step 2.5) + build smoke (Bash) |

### Conditional triggers (iteration 2)

Add to the fan-out only when the trigger fires. Each trigger maps to a specialist agent with a
narrow prompt. When no trigger fires for an agent, the agent is not spawned.

| Trigger (in spec frontmatter) | Agent | Role |
|---|---|---|
| `acceptance_criteria_ids` is a non-empty list | `business-analyst` | AC coverage — every `AC-N` has evidence in the diff, TC list, or manual-tester report |
| `design.figma` is set, `has_ui_surface == true` | `ux-expert` | Design-review mode — verify UI matches the referenced mockup + project design system |
| `risk_areas` includes any of `auth`, `payment`, `pii`, `data-migration` | `security-expert` | Security review against diff and any persisted state changes |
| `non_functional.sla` set, **or** `risk_areas` includes `perf-critical` | `performance-expert` | Bench/regress check against the declared SLA |
| `non_functional.a11y` set, `has_ui_surface == true` | `ux-expert` in a11y focus | Accessibility audit against the declared WCAG level |

When both design-review and a11y triggers fire, combine into one `ux-expert` invocation with
mode `both`. When no trigger fires, acceptance runs the base plan only — preserving
backward compatibility with specs written before iteration 2.

**Future iterations** will add `architecture-expert` (API contract), `build-engineer` (when
build files changed), `devops-expert` (when CI config changed).

### Per-check artifact schema (shared by all sub-checks)

Each sub-check writes `swarm-report/<slug>-acceptance-<check>.md` with this frontmatter:

```yaml
---
type: acceptance-check
check: manual | code | build | ac-coverage | design | security | performance | a11y
agent: <agent-name or "bash">
verdict: PASS | WARN | FAIL | SKIPPED
severity: critical | major | minor | null
confidence: high | medium | low | null
domain_relevance: high | medium | low | null
blocked_on: <optional — what the user must resolve>
---
```

`severity`, `confidence`, `domain_relevance` are required when `verdict` is `WARN` or `FAIL`;
null for `PASS` / `SKIPPED`. These drive the PoLL aggregation in Step 4.

### 3.1 Spawn `manual-tester` (UI branch)

`manual-tester` owns the runtime environment end-to-end per its Step 0 Environment Setup.
Acceptance does not pre-launch — that is intentional delegation.

Prompt contents:
1. **Spec context** — full text or clear pointers.
2. **Test plan** — the complete set of test cases.
3. **Target hints** (optional) — device/URL if the user already named one.
4. **Scope** — which tiers (default: Smoke + Feature).
5. **Output path** — `swarm-report/<slug>-acceptance-manual.md` with the per-check schema.

If the agent returns `WARN` with `blocked_on`, surface that text to the user as the primary
next-step requirement before re-running acceptance.

### 3.2 Spawn `code-reviewer` (delta review, skipped if Step 2.5 matched)

Prompt contents:
1. **Task description** — one sentence from spec or PR title.
2. **Plan pointer** — path to implement receipt or research report if present.
3. **Git diff** — current diff.
4. **Output path** — `swarm-report/<slug>-acceptance-code.md`.

Verdict rules: `PASS` if no semantic bugs, logic errors, or security issues; `WARN` for
style/minor; `FAIL` for blockers.

### 3.3 Build smoke (non-UI branch)

Pick the command by `ecosystem` (see ORCHESTRATION.md §Build system detection):

| `ecosystem` | Command |
|---|---|
| `gradle` | `./gradlew build -x test --quiet` (single-module) or `./gradlew :check` (multi-module) |
| `node` | `npm run build` (or `pnpm build` / `yarn build`) |
| `rust` | `cargo build --release --quiet` |
| `go` | `go build ./...` |
| `python` | `python -m compileall .` or package-specific build |

Multi-module detection: scan `settings.gradle*` for `include(` statements. If subprojects are
declared and the user did not specify a target module, ask which module is the smoke target
**before** entering Step 3 (do not block the fan-out message with a question).

If the `ecosystem` or command is not resolvable, skip with `verdict: SKIPPED` and
`blocked_on: build command unknown`. On success write `verdict: PASS`; on failure capture the
last ~50 lines and write `verdict: FAIL`. Receipt at
`swarm-report/<slug>-acceptance-build.md`.

### 3.4 Spawn `business-analyst` (conditional — AC coverage)

Fires when `acceptance_criteria_ids` in spec frontmatter is a non-empty list.

Prompt contents:
1. **Spec** — the spec file path.
2. **Diff / implement receipt** — evidence for each AC.
3. **Test plan** (if any) — TC list mapped to AC by `AC-ref:` fields.
4. **manual-tester output** (if running) — pointer to
   `swarm-report/<slug>-acceptance-manual.md`.
5. **Output path** — `swarm-report/<slug>-acceptance-ac-coverage.md`.

Verdict rules: `PASS` if every `AC-N` has at least one evidence pointer; `WARN` for weak
coverage (single witness on high-risk AC); `FAIL` for any missing AC. Severity: `FAIL` on
missing AC is `critical`; weak coverage is `major`.

### 3.5 Spawn `ux-expert` (conditional — design-review or a11y)

Fires when `design.figma` is set (design-review mode) **or** `non_functional.a11y` is set
(a11y mode). Either mode runs in one agent invocation; combine prompts if both triggers fire.

Prompt contents:
1. **Mode** — `design-review` / `a11y` / `both`.
2. **Spec** — file path.
3. **Design source** — `design.figma` URL (design-review mode).
4. **a11y target** — value of `non_functional.a11y` (e.g. `wcag-aa`).
5. **Running app pointer** (if `has_ui_surface`) — target hints; the agent reads running-app
   state via MCP only when the environment is already prepared, otherwise works from
   screenshots/code.
6. **Output path** — `swarm-report/<slug>-acceptance-ux.md`.

Verdict rules: `PASS` if design matches reference and a11y criteria met; `WARN` for minor
spacing/color deviations or AA soft failures; `FAIL` for missing components, broken
interaction paths, or hard a11y violations (keyboard trap, contrast below threshold).

### 3.6 Spawn `security-expert` (conditional)

Fires when `risk_areas` intersects `{auth, payment, pii, data-migration}`.

Prompt contents:
1. **Risk list** — the intersection subset.
2. **Diff** — full git diff.
3. **Spec** — file path.
4. **Output path** — `swarm-report/<slug>-acceptance-security.md`.

Verdict rules: `PASS` if no applicable OWASP / project-security-rule violations; `WARN` for
minor hardening opportunities; `FAIL` for exploitable issues, secret leaks, or regulation
breaches.

### 3.7 Spawn `performance-expert` (conditional)

Fires when `non_functional.sla` is set **or** `risk_areas` contains `perf-critical`.

Prompt contents:
1. **SLA target** — from `non_functional.sla`, or implicit `perf-critical` baseline.
2. **Diff** — full git diff.
3. **Output path** — `swarm-report/<slug>-acceptance-performance.md`.

Verdict rules: `PASS` if no regression; `WARN` for borderline; `FAIL` for violations.

---

## Step 4: Aggregate and Write Receipt

Read frontmatter of each `swarm-report/<slug>-acceptance-<check>.md` first (verdict +
severity + confidence + domain_relevance + blocked_on). Read the body only if
`verdict != PASS`. Do not inline artifact bodies — link them.

**Missing per-check artifact.** Step 2.5 writes a stub for skipped `code-reviewer`; Step 3.3
writes an artifact even on build-smoke failure. If a planned per-check artifact is
nonetheless missing at aggregation time, treat the check as `verdict: FAIL` with
`error: per-check artifact missing` — do not silently drop it.

### Aggregation — PoLL rules

Acceptance uses the same aggregation protocol as `plan-review` (see `plan-review/SKILL.md`
§"Aggregation Rules"). Input shape is per-check (not per-reviewer), reduction logic identical:

| Signal | Action |
|---|---|
| **`critical` severity** from any sub-check with `confidence: high` | → Blocker. Aggregated Status = `FAILED`. |
| **Same issue** (same file:line or same AC id) raised by 2+ sub-checks independently | → Escalate to `critical` regardless of individual severity. Multiple specialists seeing the same problem = real problem. |
| **`major` severity** from a sub-check with `domain_relevance: high` | → Important. Aggregated Status = `PARTIAL` if not already escalated. |
| **Contradicting verdicts** (one `PASS`, another `FAIL` on the same item) | → "Uncertainty — requires decision". Aggregated Status = `PARTIAL`, contradiction listed in the receipt. |
| **`minor` severity** or **`low` confidence** from a single check | → Note, not blocker. Does not affect aggregated Status. |
| **`low` domain_relevance** check flagging an issue | → Note, weight lower. |

**Bug severities (P0–P3) remain the primary routing axis** for
`feature-flow`/`bugfix-flow`. Any P0/P1 bug reported by any sub-check maps directly to
`FAILED` regardless of the PoLL above; PoLL layers additional rules on top for cases not
covered by bug severity alone (e.g. AC coverage FAIL without an associated P0 bug).

### Aggregated Status — final table

| Input | Aggregated Status |
|---|---|
| All checks `PASS` or `SKIPPED`, no P0–P3 bugs, no PoLL blocker | `VERIFIED` |
| Any P0 / P1 bug **or** PoLL blocker (critical high-confidence, or 2+-agent escalation) | `FAILED` |
| P2 / P3 bugs only, **or** PoLL important, **or** contradicting verdicts, **or** any `WARN` not otherwise classified | `PARTIAL` |
| `manual-tester` returned `WARN` with `blocked_on` | `PARTIAL` with `blocked_on` surfaced in Summary |

### Receipt format

Save to `swarm-report/<slug>-acceptance.md`. Legacy fields preserved; new sections appended.

```markdown
# Acceptance: <slug>

**Status:** VERIFIED / FAILED / PARTIAL
**Date:** <date>
**Type:** Feature / Bug fix
**Project type:** <project_type>
**Project type override:** <spec | user | none>
**Ecosystem:** <ecosystem>
**Spec source:** [what was used]
**Test plan:** [resolved permanent path / generated on-the-fly / none]
**test_plan_source:** receipt | mounted | on-the-fly | absent
**Context artifacts:** [paths to research.md, debug.md, implement.md, quality.md used as input]

## Check Plan
- list of checks that ran, one per line, with their trigger
- e.g. `business-analyst` (AC coverage) — triggered by spec.acceptance_criteria_ids
- e.g. `ux-expert` — not triggered (no design.figma)

## Check Results

| Check | Agent / Tool | Verdict | Severity | Confidence | Artifact |
|---|---|---|---|---|---|
| Manual QA | manual-tester | … | … | … | swarm-report/<slug>-acceptance-manual.md |
| Code review | code-reviewer | … | … | … | swarm-report/<slug>-acceptance-code.md |
| AC coverage | business-analyst | … | … | … | swarm-report/<slug>-acceptance-ac-coverage.md |
| Design / a11y | ux-expert | … | … | … | swarm-report/<slug>-acceptance-ux.md |
| Security | security-expert | … | … | … | swarm-report/<slug>-acceptance-security.md |
| Performance | performance-expert | … | … | … | swarm-report/<slug>-acceptance-performance.md |
| Build smoke | bash | … | … | … | swarm-report/<slug>-acceptance-build.md |

## Convergence signals
Issues raised by 2+ sub-checks independently. Strongest signal of real problems.
List one line each with the file:line or AC id and the list of checks that flagged it.

## Summary
[1–3 sentences. If PARTIAL with blocked_on — state the blocker first. If any convergence
signal — mention it in the first sentence.]

## Test Results
- Total: [n] | Passed: [n] | Failed: [n] | Blocked: [n]

## Bugs Found
[List by severity — P0 first, then P1, P2, P3. Link each to the per-check artifact that
reported it.]

## Bug Reproduction Check (bug fix only)
- Reproduction steps from debug.md: [executed / not applicable]
- Bug reproduces after fix: [yes / no]

## Recommendation
[Ship / Do not ship / Ship with known issues — and why]
```

### Routing (consumed by orchestrators)

- **VERIFIED** → `create-pr` (or mark existing PR ready for review).
- **FAILED** with P0/P1 and obvious cause → `implement` with the bug list as input. Max 3
  round-trips.
- **FAILED** with P0/P1 and unclear cause → `debug` first, then `implement`.
- **FAILED** with P0/P1 requiring regression coverage → `test-plan` append `## Regression TC`,
  then `implement`.
- **PARTIAL** with P2/P3 only or WARN — orchestrator asks the user: fix now or ship with
  known issues (continue to `create-pr`, include in PR description).
- **PARTIAL** with `blocked_on` — surface the blocker; do not continue until resolved.

---

## Re-verification Loop

On fix-loop re-entry:

1. Re-probe Step 0 and Step 1 (project type rarely changes; inputs may).
2. Re-run checks with this policy:
   - **Failed checks** — re-run in full.
   - **Passed checks** — re-run only if the current diff touches files the check inspected
     (`code-reviewer`, `security-expert`, `performance-expert`), or build inputs changed
     (`build smoke`), or the spec changed (`business-analyst`, `ux-expert`).
     `manual-tester` re-runs previously-failed TCs plus a Smoke tier by default.
   - Record `re-used previous verdict` in the new per-check receipt for skipped re-runs.
3. Aggregate into a fresh `swarm-report/<slug>-acceptance.md`, overwriting the previous one.
4. Repeat until VERIFIED or the user decides to ship as-is.

Full `diff_hash`-based idempotency will be added in a later iteration; the policy above is
the cheap interim.

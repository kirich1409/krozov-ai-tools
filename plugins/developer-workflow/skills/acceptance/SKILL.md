---
name: acceptance
description: >
  Acceptance verification — confirm implementation meets spec (feature) or that a bug no longer
  reproduces (bug fix). Orchestrator: detects project type, verifies a source exists (spec AC,
  test plan, or debug.md), fans out parallel checks to `manual-tester` (UI + scenario) and
  `code-reviewer` (delta), then aggregates into a single receipt. No improvisation — without a
  source, proposes `/write-spec`, `/generate-test-plan`, or `/debug`. Trigger on: "test this",
  "verify against spec", "QA the implementation", "run the test plan", "validate acceptance
  criteria", "verify the PR", "verify the fix", "confirm bug is gone", "acceptance", "приёмка",
  "проверь", "протестируй", or when implementation is finished and wants verification before PR.
disable-model-invocation: true
---

# Acceptance

Verify that an implementation meets its acceptance contract. This skill is a **choreographer**:
it detects the project type, confirms that a verification source exists, then fans out parallel
checks to specialized agents and aggregates their verdicts into a single receipt.

Acceptance is an **executor of a pre-existing verification contract**, not a generator of
checks. The contract comes from upstream skills (`/write-spec`, `/generate-test-plan`,
`/debug`). Without a contract, acceptance does not improvise — it stops and proposes the
correct upstream skill.

---

## Step 0: Detect Project Type

Determine what kind of project this is. The result drives which checks are even meaningful:
UI projects get `manual-tester`; non-UI projects skip it and rely on static review plus build
smoke.

Run a cheap heuristic over repository root files — no external tools required:

| Signal found at repo root | Project type |
|---|---|
| `AndroidManifest.xml` anywhere under `app/`, `android/`, or `build.gradle*` with `com.android.application` plugin | `android` (UI) |
| `*.xcodeproj` / `*.xcworkspace`, `Package.swift` with iOS/macOS target, or `Podfile` with iOS pods | `ios` (UI) |
| `package.json` with a frontend framework (`react`, `vue`, `svelte`, `next`, `vite`, `astro`) or `index.html` in project root | `web` (UI) |
| `package.json` with `electron`, or native desktop entrypoint (Compose Desktop, Swift AppKit main) | `desktop` (UI) |
| `build.gradle*` with Spring / Ktor / Micronaut / Quarkus / `application` plugin without Android | `backend-jvm` (non-UI) |
| `package.json` with pure Node server (`express`, `fastify`, `koa`, `nest`) and no frontend framework | `backend-node` (non-UI) |
| `Cargo.toml`, `pyproject.toml`, `go.mod` without web/GUI frameworks; or `bin/` entrypoints | `cli` (non-UI) |
| `*.claude-plugin`, Gradle/Maven library packaging without application plugin | `library` (non-UI) |
| None of the above matches unambiguously | `generic` (ask user) |

Set `project_type` and `has_ui_surface` (bool) for downstream steps. If the heuristic returns
`generic`, ask the user once: "project type is ambiguous — is this a UI app, a backend/CLI/library,
or something else?" then record the answer.

**Do not read build files exhaustively** — a root-level glance is enough for iteration 1.
If the user disagrees with the detection at any point, record the override and proceed.

---

## Step 1: Gather Inputs

At least one verification source is required. If none are available, Step 1.5 (Source-missing
gate) halts execution and proposes the correct upstream skill — acceptance never improvises.

### 1.1 Spec Source (optional if a test plan or debug.md is provided)

The specification defines what "correct" looks like. Accept any combination of:
- **Figma mockups** — URLs or exported frames
- **PRD / requirements document** — file path, URL, or inline text
- **Acceptance criteria** — bullet list, user stories, or a checklist
- **PR description** — when verifying a PR, the description itself is a spec
- **Issue / ticket** — GitHub issue, Linear ticket, or similar

Read all provided spec sources.

### 1.2 Test Plan — Source Priority

Select the test-plan source by walking the four branches below in order. The first branch
whose condition holds is the one used; record which branch fired so the verification report
can set `test_plan_source` accordingly.

#### Branch 1 — Receipt present (`test_plan_source: receipt`)

**Condition:** `swarm-report/<slug>-test-plan.md` exists (produced by `generate-test-plan`
when invoked from the orchestrator).

**Actions:**
1. Read the receipt's YAML frontmatter and load `permanent_path`.
2. Read `review_verdict`:
   - `PASS` — proceed.
   - `WARN` — proceed; carry WARN findings forward into the verification report as context.
   - `skipped` — proceed. The receipt was written as a mount (pre-orchestration permanent
     file adopted without regeneration — see `feature-flow/SKILL.md` §1.5 Pre-check or
     Branch 2 below). No review was performed; treat the plan as user-authored and
     authoritative.
   - `FAIL` — do not execute. Stop and escalate back to `feature-flow`: the plan must be
     revised via `plan-review` before acceptance runs.
   - `pending` — treat as not-yet-reviewed; escalate to `feature-flow` to run plan-review
     first instead of proceeding blindly.
3. Pass the **permanent file** (resolved via `permanent_path`, not the receipt itself) to
   the `manual-tester` agent as the primary test-plan source.
4. In the verification report set `test_plan_source: receipt`.

#### Branch 2 — Permanent file exists without receipt (`test_plan_source: mounted`)

**Condition:** Branch 1 did not fire **and** `docs/testplans/<slug>-test-plan.md` exists on
disk without a matching receipt in `swarm-report/`.

**Ownership:** the `feature-flow` orchestrator normally emits the mount-receipt in its
Phase 1.5 Pre-check. This branch runs only when `acceptance` is invoked outside of
`feature-flow` (standalone QA session, `bugfix-flow`, user-triggered mid-flow), so the
receipt has not been produced yet.

**Actions:**

1. Emit a mount-receipt at `swarm-report/<slug>-test-plan.md` following the canonical
   format in `plugins/developer-workflow/skills/generate-test-plan/SKILL.md` §Receipt
   with the mount overrides: `status: Mounted`, `review_verdict: skipped`,
   `source_spec: existing (pre-orchestration)`, and `phase_coverage` derived from the
   permanent file's phase labels when present (scan for `### Phase N ...` headings
   under `## Test Cases`). Do **not** hardcode `phase_coverage: []`; use the empty
   list only when the permanent file genuinely has no phase segmentation. When phase
   coverage cannot be determined reliably from the permanent file (malformed headings,
   mixed conventions), omit the `phase_coverage` field entirely rather than recording
   an incorrect value.
2. Pass the **permanent file** to the `manual-tester` agent as the primary test-plan source.
3. In the verification report set `test_plan_source: mounted`.

#### Branch 3 — Inline test plan or spec available (`test_plan_source: on-the-fly`)

**Condition:** Branches 1 and 2 did not fire **and** the invocation provides a test plan
inline, a spec source, or both.

The test plan defines what to check. Three modes:

**Test plan only (no spec)** — the test plan is the single source of truth. Execute it as-is.
The verification result will be based entirely on whether the test cases pass or fail.

**Test plan + spec** — accept the plan as-is, but cross-reference it against the spec. If the
plan has obvious gaps (spec mentions flows the plan doesn't cover), flag them: "The spec
mentions X but the test plan doesn't cover it — should I add test cases for that?" Let the
user decide.

**Spec only (no test plan)** — generate a test plan from the spec:
1. Read the spec source thoroughly
2. Identify all testable flows: happy paths, edge cases, error states, empty states
3. Write test cases in the manual-tester format (TC-prefixed, with tiers, steps, expected results)
4. Present the generated plan to the user for approval before executing
5. Adjust based on their feedback

In the verification report set `test_plan_source: on-the-fly`.

#### Branch 4 — Nothing available → Source-missing gate

**Condition:** no receipt, no permanent file, no inline test plan, no spec source, and no
`swarm-report/<slug>-debug.md` for bug-fix flows.

**Behavior:** proceed to Step 1.5 — do not attempt to run checks without a contract.

---

## Step 1.5: Source-Missing Gate

Acceptance does not improvise checks. When no verification source is available, halt and
propose the correct upstream skill.

### Decision table

| Situation | Proposal |
|---|---|
| No spec, no test plan, implement receipt exists (feature path) | "Verification source is missing. Run `/write-spec` (if you need a requirements document) or `/generate-test-plan` (if only a test plan is needed), then re-run acceptance." |
| Spec present but has no acceptance criteria and no test plan; UI project | "Spec exists but lacks acceptance criteria. Run `/generate-test-plan` to produce executable test cases, or add acceptance criteria to the spec, then re-run acceptance." |
| Bugfix path: no `swarm-report/<slug>-debug.md` | "Bug-fix acceptance requires reproduction steps. Run `/debug` first to capture the reproduction scenario, then re-run acceptance." |
| Only `design.figma` in spec, no test plan, UI project | "Only a design source is available. A design-review check is possible in a later iteration; for functional acceptance run `/generate-test-plan` first." |

### Options presented to the user

1. **Create the missing source** (primary) — invoke the proposed upstream skill, then re-run
   acceptance.
2. **Abort acceptance** — exit without a receipt; the user addresses the gap and re-invokes
   when ready.

**Do not offer a third option.** Exploratory QA without a scenario is the `bug-hunt` skill's
responsibility — a sibling, not a fallback inside acceptance. Mixing verification and
exploration erodes the contract boundary between the two skills.

When invoked from `feature-flow` or `bugfix-flow`, this gate should rarely fire — upstream
skills in those orchestrators guarantee a source. The gate exists primarily for standalone
invocation.

---

## Step 2: Ensure the App is Running

**Only relevant if `has_ui_surface == true`.** For non-UI projects skip directly to Step 3.

Before launching QA, verify the app is accessible. The approach depends on what's being tested:

### Mobile / Desktop App

1. Check if a device/simulator/emulator is already connected — call `list_devices` via the mobile MCP
2. If a device is available and the app is installed, try launching it
3. If no device is available or the app isn't installed:
   - Look for a run configuration in the project (Gradle `installDebug`, Xcode build, etc.)
   - Build and install: pick the appropriate command for the project
   - If the build system isn't obvious, ask the user how to build and deploy

### Web App

1. Check if a dev server is already running (look for running processes on common ports, or check if the URL responds)
2. If not running, look for a start command in the project (`npm start`, `npm run dev`, `./gradlew bootRun`, etc.)
3. Start the dev server and wait for it to be ready
4. If the start command isn't obvious, ask the user

### Already Running

If the user says the app is already running or provides a URL / device target, skip the launch
step and proceed directly.

---

## Step 2.5: Persist E2E Scenario

**Only relevant if `has_ui_surface == true` and a scenario source exists** (test plan, spec
with AC, or debug.md). This file is the persistent state of manual QA — it survives context
compaction.

Save to `swarm-report/<slug>-e2e-scenario.md`:

```markdown
# E2E Scenario: <task name>
Type: Feature / Bug fix
Project type: <android | ios | web | desktop>
Spec source: <what was used>

## Steps
- [ ] 1. <concrete user action> → Expected: <result>
- [ ] 2. <concrete user action> → Expected: <result>
- [ ] 3. <concrete user action> → Expected: <result>
...
```

For bug fixes, the steps come from `debug.md` reproduction steps — inverted:
- Original: "Step X triggers the bug"
- E2E: "Step X no longer triggers the bug"

**Compaction resilience rules:**
- Before EVERY verification action — re-read this file via Read tool
- After each step passes — update the file, mark as `[x]`:
  ```
  - [x] 1. Open screen X → Expected: shows data ✅
  - [ ] 2. Tap button Y → Expected: navigates to Z
  ```
- Completed steps (`[x]`) — do NOT re-check
- Resume from the first incomplete step (`[ ]`)
- This guarantees no wasted work after compaction

---

## Step 3: Run Checks (parallel fan-out)

Based on `project_type` and `has_ui_surface`, pick the check plan and spawn agents in parallel
via the `Agent` tool. **All agent calls must go out in a single message** to maximize
parallelism.

### Check-plan branches (iteration 1 — hardcoded)

| Inputs | Checks to run |
|---|---|
| `has_ui_surface == true` AND scenario source present | `manual-tester` (scenario-driven) + `code-reviewer` (delta) |
| `has_ui_surface == false` | `code-reviewer` (delta) + build smoke (Bash) |
| `has_ui_surface == true` AND no scenario source | impossible — Step 1.5 would have halted execution |

Future iterations will add conditional checks (`security-expert`, `ux-expert` design review,
`business-analyst` AC coverage, `performance-expert`, `build-engineer`). Iteration 1 is
intentionally minimal: the primary goal is to stop producing false PASS for non-UI projects.

### 3.1 Spawn `manual-tester` (UI branch only)

The agent prompt must include:

1. **Spec context** — the full spec content or clear pointers to where the spec lives (URLs, file paths)
2. **Test plan** — the complete set of test cases to execute
3. **Target** — how to reach the app (device name, URL, etc.)
4. **Scope** — which test tiers to run (default: Smoke + Feature)
5. **Output path** — "Write your Test Execution Summary to
   `swarm-report/<slug>-acceptance-manual.md` when done."

Example agent prompt structure:

```
You are testing a feature against its specification.

## Spec
[Paste or reference the spec source here]

## Test Plan
[Paste the test cases here]

## Target
[Device/URL/connection details]

## Scope
Run Smoke + Feature tiers. Report all bugs with severity and evidence.

## Output
Save your Test Execution Summary to swarm-report/<slug>-acceptance-manual.md with frontmatter:
---
type: acceptance-check
check: manual
agent: manual-tester
verdict: PASS | WARN | FAIL
---
Then produce a ship/no-ship recommendation inline.
```

Do not interfere with the agent's process unless it asks a question or reports a P0 blocker.

### 3.2 Spawn `code-reviewer` (always — delta review)

Check first whether a quality-loop review already passed on the current diff by reading
`swarm-report/<slug>-quality.md` (produced by the `implement` skill's quality loop). If the
receipt's verdict is PASS **and** the recorded diff matches the current diff, skip this check
and record `verdict: SKIPPED (quality-loop already passed)` in the receipt section for the
`code-reviewer` line.

Otherwise, spawn `code-reviewer` via the `Agent` tool with:

1. **Task description** — one sentence from the spec / PR title
2. **Plan pointer** — path to the implement receipt or research report if present
3. **Git diff** — the current diff under review (`git diff <base-branch>...HEAD` or the
   staged/unstaged changes on the working branch)
4. **Output path** — "Save your review to `swarm-report/<slug>-acceptance-code.md`."

Example prompt:

```
Independent code review of the current changes.

## Task
[One-line task description]

## Plan / Spec
[Path or content]

## Diff
[Full git diff]

## Output
Save your findings to swarm-report/<slug>-acceptance-code.md with frontmatter:
---
type: acceptance-check
check: code
agent: code-reviewer
verdict: PASS | WARN | FAIL
---
Then list issues with severity (critical/major/minor). PASS if no semantic bugs, logic errors,
or security issues; WARN for style/minor; FAIL for blockers.
```

### 3.3 Build smoke (non-UI branch only)

For non-UI projects run a build smoke via Bash. Pick the command by `project_type`:

| Project type | Smoke command |
|---|---|
| `backend-jvm` / `library` (Gradle) | `./gradlew build -x test --no-daemon --quiet` — adjust project path if multi-module |
| `backend-node` / `cli` (Node) | `npm run build` (or `pnpm build` / `yarn build`) |
| `cli` (Rust) | `cargo build --release --quiet` |
| `cli` (Go) | `go build ./...` |
| `cli` (Python) | `python -m compileall .` or package-specific build |

If the command succeeds, treat it as `PASS`. If it fails, capture the last ~50 lines of output
and treat the check as `FAIL`. Record the result in `swarm-report/<slug>-acceptance-build.md`
with the same frontmatter shape as the agent checks.

If the project type is `generic` or the build command isn't obvious, ask the user once for the
smoke command, then run it.

---

## Step 4: Aggregate and Write Receipt

When all parallel checks complete, read each `swarm-report/<slug>-acceptance-<check>.md` file
and aggregate into a single receipt.

### Aggregation rules (iteration 1 — simple)

| Inputs | Final Status |
|---|---|
| Every check reports `PASS` (or `SKIPPED` for quality-loop dedup) | `VERIFIED` |
| Any check reports `FAIL` | `FAILED` |
| At least one `WARN`, no `FAIL` | `PARTIAL` |

Future iterations will replace this with the full PoLL aggregation rules from `plan-review`
(critical-from-any-agent, 2+ agents on same issue, contradicting opinions). Iteration 1 keeps
it minimal.

### Verification Report

Save the report to `swarm-report/<slug>-acceptance.md` — this artifact is the receipt for
the PR stage. `create-pr` references it for the PR description.

The schema is **additive**: all fields from prior versions remain; new fields (`Project type`,
`Check plan`, `Check results`) are appended as new sections.

```markdown
# Acceptance: <slug>

**Status:** VERIFIED / FAILED / PARTIAL
**Date:** <date>
**Type:** Feature / Bug fix
**Project type:** <android | ios | web | desktop | backend-jvm | backend-node | cli | library | generic>
**Spec source:** [what was used — requirements, debug.md reproduction steps, etc.]
**Test plan:** [resolved permanent path if sourced via receipt or mounted receipt | generated on-the-fly from spec | none]
**test_plan_source:** receipt | mounted | on-the-fly | absent
**Context artifacts:** [paths to research.md, debug.md, implement.md used as input]

## Check Plan
- List of checks that ran, one per line (e.g., `manual-tester`, `code-reviewer`, `build smoke`)
- Include `SKIPPED` checks with the reason (e.g., `code-reviewer: SKIPPED — quality-loop passed`)

## Check Results

| Check | Agent / Tool | Verdict | Artifact |
|---|---|---|---|
| Manual QA | manual-tester | PASS / WARN / FAIL | swarm-report/<slug>-acceptance-manual.md |
| Code review | code-reviewer | PASS / WARN / FAIL / SKIPPED | swarm-report/<slug>-acceptance-code.md |
| Build smoke | bash | PASS / FAIL | swarm-report/<slug>-acceptance-build.md |

## Summary
[1-3 sentences on the overall state]

## Test Results
- Total: [n] | Passed: [n] | Failed: [n] | Blocked: [n]

## Bugs Found
[List bugs by severity — P0 first, then P1, P2, P3]
[Each with a one-line summary and link to full bug report]

## Bug Reproduction Check (bug fix only)
- Reproduction steps from debug.md: [executed / not applicable]
- Bug reproduces after fix: [yes / no]

## Recommendation
[Ship / Do not ship / Ship with known issues — and why]
```

### What Happens Next

Based on the verification state, the orchestrator decides the next transition:

- **VERIFIED** → proceed to `create-pr` (or mark existing PR as ready for review)
- **FAILED** → back to `implement` with the bug list from `<slug>-acceptance.md` as input.
  After fix, re-run `acceptance`. Max 3 round-trips before escalating to the user.
- **PARTIAL** (WARN-level findings only) → orchestrator asks the user: fix now (back to
  `implement`) or ship with known issues (proceed to `create-pr`, include issues in PR
  description).

---

## Re-verification Loop

When the user fixes bugs and wants to re-test:

1. Re-use the same test plan and project-type detection (unless the user changed repo
   structure)
2. Tell `manual-tester` to focus on previously failed test cases + a smoke pass
3. Re-run `code-reviewer` against the updated diff
4. Re-run build smoke if it was the failure signal
5. Aggregate into a fresh `<slug>-acceptance.md`, overwriting the previous one
6. Repeat until VERIFIED or the user decides to ship as-is

Future iterations will add `diff_hash`-based idempotency to skip checks whose inputs did not
change between runs; for iteration 1 every cycle re-runs all relevant checks.

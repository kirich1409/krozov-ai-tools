---
name: acceptance
description: >
  Acceptance verification — confirm that implementation meets requirements (feature) or that a bug
  no longer reproduces (bug fix). Runs manual QA on a live app against a spec source.
  Accepts any spec: PRD, Figma mockup, acceptance criteria, PR description, GitHub issue,
  debug.md artifact (reproduction steps), or a test plan.
  Trigger on: "test this", "verify against spec", "QA the implementation", "check if it matches
  the design", "run the test plan", "validate the acceptance criteria", "does it match the mockup",
  "verify the PR", "verify the fix", "confirm bug is gone", "acceptance", "приёмка", "проверь",
  "протестируй", or any request to compare a running app against a specification source.
  Also trigger when the user finishes implementing a feature or bug fix and wants confirmation
  it works before creating or finalizing a PR.
disable-model-invocation: true
---

# Acceptance

Verify that a running application meets its acceptance criteria. This skill bridges implementation and
review — it takes a spec source and/or a test plan, ensures the app is running, launches QA
against it, and produces a verification result.

---

## Step 1: Gather Inputs

At least one of the two inputs below is required. Both together give the best results, but
either one alone is enough to proceed.

### 1.1 Spec Source (optional if test plan is provided)

The specification defines what "correct" looks like. Accept any combination of:
- **Figma mockups** — URLs or exported frames
- **PRD / requirements document** — file path, URL, or inline text
- **Acceptance criteria** — bullet list, user stories, or a checklist
- **PR description** — when verifying a PR, the description itself is a spec
- **Issue / ticket** — GitHub issue, Linear ticket, or similar

Read all provided spec sources. If neither a spec nor a test plan is provided, ask the user
for at least one before proceeding.

### 1.2 Test Plan (optional if spec is provided)

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

---

## Step 2: Ensure the App is Running

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

Before launching the tester, save the verification scenario to disk. This file is the
persistent state of acceptance — it survives context compaction.

Save to `swarm-report/<slug>-e2e-scenario.md`:

```markdown
# E2E Scenario: <task name>
Type: Feature / Bug fix
Platforms: <selected platforms>
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

## Step 3: Launch Manual Tester

Spawn the `manual-tester` agent with all gathered context. The agent prompt must include:

1. **Spec context** — the full spec content or clear pointers to where the spec lives (URLs, file paths)
2. **Test plan** — the complete set of test cases to execute (user-provided or generated in step 1)
3. **Target** — how to reach the app (device name, URL, etc.)
4. **Scope** — which test tiers to run (default: Smoke + Feature)

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
Deliver a Test Execution Summary with a ship/no-ship recommendation when done.
```

Let the manual-tester agent handle the full QA cycle: environment setup, test execution,
bug reporting, and summary generation. Do not interfere with its process unless it asks
a question or reports a P0 blocker.

---

## Step 4: Collect and Present Verification Result

When the manual-tester agent completes, process its output into a verification result.

### Verification State

The result is one of three states:

| State | Meaning | Condition |
|-------|---------|-----------|
| **VERIFIED** | Feature matches spec | All test cases passed, no P0/P1 bugs |
| **FAILED** | Feature does not match spec | Any P0 or P1 bug, or critical test cases failed |
| **PARTIAL** | Feature partially matches spec | Only P2/P3 bugs found, or non-critical test cases failed |

### Verification Report

Save the report to `swarm-report/<slug>-acceptance.md` — this artifact is the receipt for
the feedback stage. Later stages (`create-pr`, `feedback-stage`) reference it for PR description
and merge readiness.

```
# Acceptance: <slug>

**Status:** VERIFIED / FAILED / PARTIAL
**Failure type:** code bug / design flaw / wrong approach / requirements misunderstood / — (if VERIFIED)
**Date:** <date>
**Type:** Feature / Bug fix
**Spec source:** [what was used — requirements, test-plan.md, debug.md reproduction steps, etc.]
**Test plan:** swarm-report/<slug>-test-plan.md
**Context artifacts:** [paths to research.md, debug.md, implement.md used as input]

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

### Intent Check

Before producing the final verdict, verify that the implementation matches the original intent:

1. Re-read the original task description (verbatim)
2. Re-read `swarm-report/<slug>-test-plan.md` — the pre-agreed acceptance contract
3. Re-read `swarm-report/<slug>-implement.md` — what was actually built
4. Check: does the implementation address the original task, not a misinterpretation of it?

If drift is detected — classify it:
- **Minor drift** (e.g. a missing edge case) → treat as a test failure, include in bug list
- **Major drift** (e.g. wrong feature built) → FAILED with failure type: requirements misunderstood

### Failure Classification

When the result is FAILED, classify the root cause to guide the orchestrator's routing:

| Failure type | Signals | Orchestrator routes to |
|---|---|---|
| **Code bug** | Logic error, crash, wrong output — code does the wrong thing | Implement |
| **Design flaw** | Approach works but is architecturally wrong, causes side effects | PlanReview |
| **Wrong approach** | Solution direction is fundamentally misguided | Research |
| **Requirements misunderstood** | Implemented the wrong thing entirely | Escalate to user |

Include `failure_type` in the acceptance artifact.

### What Happens Next

Based on the verification state and failure type, the orchestrator decides the next transition:

- **VERIFIED** → proceed to `feedback-stage`
- **FAILED, code bug** (P0/P1) → back to `implement` with bug list. Max 3 round-trips.
- **FAILED, design flaw** → back to `plan-review`. Max 2 round-trips.
- **FAILED, wrong approach** → back to `research`. Max 2 round-trips.
- **FAILED, requirements misunderstood** → escalate to user immediately.
- **PARTIAL** (P2/P3 only) → orchestrator asks the user: fix now (back to `implement`) or
  ship with known issues (proceed to `feedback-stage`, include issues in PR description)

---

## Re-verification Loop

When the user fixes bugs and wants to re-test:

1. Re-use the same test plan (unless the user modified it)
2. Tell the manual-tester to focus on previously failed test cases + a smoke pass
3. Update the verification state based on new results
4. Repeat until VERIFIED or the user decides to ship as-is

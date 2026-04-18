---
name: generate-test-plan
description: >-
  This skill should be used when the user asks to "create a test plan", "write test cases",
  "generate QA scenarios", "prepare a testing checklist", "identify what to test", "find edge cases",
  "plan testing coverage", "document test scenarios", "create a QA handoff document", "what should
  I test?", "what are the edge cases?", or "how would you test this?". Also use when the user
  describes requirements or acceptance criteria and asks how to verify them, or wants to plan testing
  before actually running tests. Produces a structured, prioritized test plan document saved to
  docs/testplans/ with risk analysis, coverage matrix, automation candidates, and proper TC format.
  Do NOT trigger when: the user wants to execute tests on a running app (use acceptance or
  bug-hunt), the user wants automated unit/integration tests written in code (out of scope),
  or the user wants to run an existing test plan (use acceptance). This skill never launches an
  app, device, or browser — it only produces a document.
---

# Generate Test Plan

Analyze a feature from its specification, design, or implementation and produce a structured,
prioritized test plan as a markdown document. No tests are executed — the output is a plan ready
for a human QA engineer or the `manual-tester` agent to pick up later.

## Output

Save every test plan to the repository:

```
docs/testplans/<feature-name>-test-plan.md
```

Create the `docs/testplans/` directory if it doesn't exist. Use kebab-case for the feature name.
Examples: `user-authentication-test-plan.md`, `cart-checkout-test-plan.md`.

### Receipt (when invoked from orchestrator with a slug)

When this skill is invoked from the `feature-flow` orchestrator, a `slug` argument is passed
explicitly. In that case, in addition to the permanent document above, produce a **receipt**
at `swarm-report/<slug>-test-plan.md` that the orchestrator and downstream stages
(`plan-review`, `acceptance`) can consume for receipt-based gating.

The permanent file remains the source of truth. The receipt is metadata + pointer.

Receipt format:

```markdown
---
name: test-plan-receipt
description: Test plan artifact for <slug>
slug: <slug>
type: test-plan-receipt
status: Draft | Ready | Approved | Mounted
permanent_path: docs/testplans/<slug>-test-plan.md
source_spec: <path to spec if any, or "inline spec">
review_verdict: pending | PASS | WARN | FAIL | skipped
review_warnings: []            # populated by plan-review on WARN — list of short strings
review_blockers: []            # populated by plan-review on FAIL — list of short strings
phase_coverage: [Phase 1, Phase 2, ...]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Test Plan Receipt: <slug>

**Status:** <status>
**Permanent artifact:** [`docs/testplans/<slug>-test-plan.md`](../docs/testplans/<slug>-test-plan.md)
**Source spec:** <path or description>
**Review verdict:** <verdict>
```

Field conventions:
- `status`: `Draft` right after generation; `Ready` after plan-review returns PASS/WARN;
  `Approved` when the user explicitly signs off; `Mounted` when a user-authored permanent
  file is adopted without regeneration (see `feature-flow/SKILL.md` §1.5 Pre-check).
- `review_verdict`: `pending` at creation; updated by `plan-review` to
  `PASS | WARN | FAIL`; `skipped` on mount (no review occurs).
- `review_warnings` / `review_blockers`: arrays of short strings populated by `plan-review`.
  `review_warnings` is written on WARN verdicts (items d or e of the checklist violated —
  non-blocking); `review_blockers` is written on FAIL (items a, b, or c violated —
  blocks transition to Implement). Both remain empty arrays on PASS / pending / skipped.
  Frontmatter is the single source of truth for review findings — the receipt body does
  not re-list them, keeping downstream YAML parsers authoritative.
- `phase_coverage`: list of phase labels present in the permanent file. Empty list if the
  feature has no phase segmentation.
- `created` / `updated`: ISO dates (`YYYY-MM-DD`). `updated` must change whenever either the
  permanent file or any receipt field is modified.
- Relative path in the markdown link assumes the conventional `swarm-report/` ↔ `docs/`
  sibling layout at the repo root.

### Backward compatibility — standalone invocation without slug

When a user invokes this skill directly (e.g. "create a test plan for X") without the
orchestrator passing a `slug`, the receipt is **not** produced. Behavior matches the
pre-orchestration flow exactly:

- Permanent file generated at `docs/testplans/<feature-name>-test-plan.md` as described above.
- No `swarm-report/<slug>-test-plan.md` is written.
- No `phase_coverage` or receipt metadata tracked elsewhere.

The `slug` parameter is therefore **mandatory only when invoked from the `feature-flow`
orchestrator**. Standalone usage continues to work unchanged — existing callers,
documentation references, and QA workflows that treat `docs/testplans/*-test-plan.md` as
the single artifact are not broken by this change.

## Input Discovery

Determine what the user has provided and gather context accordingly.

### 1. Text specification (PRD, acceptance criteria, user story)

Read the document. Extract:
- Functional requirements (what the feature does)
- Non-functional requirements (performance, accessibility, security constraints)
- Acceptance criteria (explicit pass/fail conditions)
- User roles and permissions mentioned

### 2. Figma mockup

Use Figma MCP tools (`get_design_context`, `get_screenshot`) to retrieve the design.
Extract:
- Screen states (default, loading, empty, error, populated)
- Interactive elements and their expected behavior
- Navigation flows between screens
- Responsive or platform-specific variants

### 3. Existing code

When code is the primary (or only) source of truth, read the implementation thoroughly:
- Public API surface — endpoints, functions, UI entry points
- State transitions and conditional branches
- Error handling paths and fallback behavior
- Input validation rules and boundary values
- Integration points (APIs, databases, third-party services)

When deriving test cases from code alone, be explicit about assumptions. Mark any inferred
behavior that has no spec backing with `[inferred from code]` so reviewers know what to verify
against product intent.

### Combining sources

Often the user provides more than one source. Cross-reference them:
- Spec says X, but code implements Y → flag the discrepancy as a finding, write test cases for both
- Design shows a state the spec doesn't mention → note it, write a test case
- Code handles an edge case not in the spec → include it with `[inferred from code]`

### Non-UI detector — when to use the lightweight template

Not every feature has a user interface. Pure backend services, CLI tools, internal libraries,
and data pipelines should use a reduced TC format where the full Steps / Expected Result
columns add noise without signal — the behavior is fully captured by Given/When/Then.

**Detector (all must hold to trigger lightweight mode):**
- The spec or input contains **no** references to any of: mockups, wireframes, Figma frames,
  screens, screen states, UI components, Jetpack Compose composables, SwiftUI views, React /
  Vue / Svelte / HTML components, CSS selectors, navigation flows, or visible user actions
  (tap, click, scroll, swipe, type in field).
- The feature surface is API / library / CLI / background job / data transformation.
- No `ux-expert` or front-end agent was consulted during research.

If any one of the signals above **is** present, use the standard Test Plan Format
(with full Steps and Expected Result). Mixed features (backend + thin UI) default to the
standard format.

When the detector triggers, note it in the Findings section of the permanent file:
`**Lightweight template applied** — no UI surface detected; TCs use Given/When/Then only.`

## Analysis

Before writing test cases, identify:

1. **Risk areas** — parts of the feature most likely to break or cause user-visible issues.
   Consider: complexity, number of integration points, data sensitivity, new vs. changed behavior.

2. **Edge cases** — boundary values, empty/null inputs, concurrent actions, permission boundaries,
   network failures, locale/timezone effects, large datasets.

3. **State combinations** — which states interact and which transitions are possible. A simple
   matrix helps: list states on one axis, user actions on the other, mark which intersections need
   coverage.

## Test Plan Format

Every generated test plan must follow this exact structure:

```markdown
---
type: test-plan
slug: <feature-slug>
generated: YYYY-MM-DD
---

# Test Plan: [Feature Name]

| Field | Value |
|-------|-------|
| **Source** | [spec link / Figma link / code path — whatever was provided] |
| **Generated** | [YYYY-MM-DD] |
| **Scope** | [one-line summary of what is covered] |
| **Status** | Draft / Ready for Review / Approved |

The `type: test-plan` frontmatter lets `plan-review` and `acceptance` identify the
artifact deterministically (Signal #1 of the classifier). `slug` matches the receipt and
any decomposition artifact for the same feature.

---

## Findings

Discrepancies, ambiguities, or assumptions discovered during analysis.
Each finding has a short title and explanation.

- **[Finding title]** — [explanation]

> Omit this section entirely if there are no findings.

---

## Risk Areas

| Area | Risk Level | Reason |
|------|-----------|--------|
| [area name] | High / Medium / Low | [why this area is risky] |

---

## Test Cases

### [Group Name]

Group related test cases by feature area, screen, or workflow
(e.g., Authentication, Cart Checkout, Error Handling).

#### TC-[N]: [Short descriptive title]

| Field | Value |
|-------|-------|
| **Priority** | P0 Critical / P1 High / P2 Medium / P3 Low |
| **Tier** | Smoke / Feature / Regression |
| **Preconditions** | What must be true before starting |
| **Steps** | 1. First step  2. Second step  3. Third step |
| **Expected Result** | Observable outcome that means the test passed |
| **Source** | Spec §section / Figma frame name / `path/to/file.kt:42` / [inferred from code] |

---

## Edge Cases & Negative Scenarios

Same TC format as above. Grouped separately for visibility.
Includes: boundary values, invalid inputs, error states, permission denials,
network failures, empty/null data, concurrent operations.

---

## Coverage Matrix

| Requirement / Screen / Flow | Test Cases | Risk |
|-----------------------------|-----------|------|
| [requirement or screen name] | TC-1, TC-3 | High |
| [another requirement] | TC-2 | Low |

---

## Suggested Automation Candidates

Test cases that are good candidates for automated testing.

| Test Case | Rationale |
|-----------|-----------|
| TC-[N] | [why this is a good automation candidate] |

> Omit this section if no test cases are suitable for automation.
```

### Phase Segmentation

When the feature reaches this skill via `decompose-feature` with phases (e.g. T-1..T-3 in
Phase 1, T-4..T-6 in Phase 2), the permanent file splits the `## Test Cases` section by
phase so each phase can ship and be re-verified independently. One permanent document per
feature remains the rule — phases are sections inside it, not separate files.

Apply segmentation when the decomposition artifact contains two or more phases **and** test
cases can be grouped by which phase introduces the behavior they cover. Otherwise keep a
single flat `## Test Cases` section.

Example for a feature with two phases:

```markdown
## Test Cases

### Phase 1 (T-1..T-3) — Core login flow

#### TC-1: Successful login with valid credentials
| Field | Value |
|-------|-------|
| **Priority** | P0 Critical |
| **Tier** | Smoke |
| **Preconditions** | User account exists, email is verified |
| **Steps** | 1. Open login screen  2. Enter email  3. Enter password  4. Tap Login |
| **Expected Result** | Home screen is shown, session token stored |
| **Source** | Spec §2.1 |

#### TC-2: Invalid password shows inline error
...

#### TC-3: Rate-limit after 5 failed attempts
...

### Phase 2 (T-4..T-6) — Password reset flow

#### TC-4: Request reset email from login screen
| Field | Value |
|-------|-------|
| **Priority** | P0 Critical |
| **Tier** | Feature |
| **Preconditions** | User account exists |
| **Steps** | 1. Tap "Forgot password?"  2. Enter email  3. Submit |
| **Expected Result** | Confirmation screen shown, reset email dispatched |
| **Source** | Spec §3.2 |

#### TC-5: Reset link expires after 15 minutes
...

#### TC-6: Reset flow rejects reused link
...
```

When segmentation is applied, the receipt's `phase_coverage` field lists the phase labels
present (e.g. `[Phase 1, Phase 2]`), and the TC ranges covered by each phase appear in the
receipt's Phase Coverage section.

### Lightweight template (non-UI features)

When the non-UI detector triggers (see Input Discovery), use this reduced TC format in place
of the standard one. The entire behavior of each TC is captured in Given/When/Then — no
numbered Steps, no separate Expected Result field, since both collapse into the Then clause
for non-interactive surfaces.

```markdown
#### TC-[N]: [Short title]
| **Priority** | P0/P1/P2/P3 |
| **Tier** | Smoke/Feature/Regression |
| **Preconditions** | [state] |
| **Scenario (Given/When/Then)** | Given X, When Y, Then Z |
| **Source** | [Spec §section / inferred from code] |
```

Example:

```markdown
#### TC-3: Token refresh succeeds before expiry
| **Priority** | P0 Critical |
| **Tier** | Feature |
| **Preconditions** | Valid refresh token stored, access token within 60s of expiry |
| **Scenario (Given/When/Then)** | Given an access token with <60s TTL, When the client calls `refresh()`, Then a new access token is returned with the original refresh-token scope preserved |
| **Source** | `src/auth/TokenManager.kt:142` |
```

All other sections of the Test Plan Format (front-matter table, Findings, Risk Areas,
Coverage Matrix, Suggested Automation Candidates, Phase Segmentation when applicable) are
used unchanged — only the TC blocks switch to this reduced form.

## Field Definitions

### Priority

| Priority | Meaning | Guideline |
|----------|---------|-----------|
| **P0 Critical** | Core happy path | If this fails, the feature is unusable |
| **P1 High** | Important flows | Security, data integrity, key user journeys |
| **P2 Medium** | Secondary flows | Edge cases with moderate impact |
| **P3 Low** | Minor scenarios | Cosmetic, rare edge cases, minor UX |

### Tier

| Tier | Meaning | Guideline |
|------|---------|-----------|
| **Smoke** | Is it alive? | Minimum set to confirm the feature works at all (3-5 tests max) |
| **Feature** | Does it work correctly? | Thorough coverage of the feature's behavior |
| **Regression** | Did we break anything? | Guards against breaking existing functionality |

### Source

| Source type | Format | Example |
|-------------|--------|---------|
| Spec section | `Spec §[section]` | `Spec §3.2 — Login flow` |
| Figma frame | `Figma: [frame name]` | `Figma: Login / Error State` |
| Code path | backtick-wrapped path with line | `src/auth/LoginViewModel.kt:87` |
| Inferred | `[inferred from code]` | Behavior derived from code with no spec backing |

## Guidelines

- Number test cases sequentially: TC-1, TC-2, TC-3, ...
  (the manual-tester agent will assign session-scoped IDs when executing)
- Each test case tests exactly one thing — split multi-outcome verifications
- Steps must be concrete and actionable — a QA engineer unfamiliar with the feature
  should follow them without asking questions
- Expected results describe observable behavior, not implementation details:
  "user sees error toast with message 'Invalid email'" not "catch block executes"
- Mark inferred behavior with `[inferred from code]` so reviewers can verify against
  product intent
- Target 15-30 test cases for a medium feature; fewer for simple changes, more for
  complex flows — every test case should earn its place

---
name: generate-test-plan
description: >-
  IMPORTANT: You MUST use this skill whenever the user wants test cases, a test plan, QA scenarios,
  or a testing checklist created from a spec, PRD, Figma mockup, requirements, or existing code.
  This skill produces a structured, prioritized test plan document saved to docs/testplans/ — you
  cannot produce the same quality of output (risk analysis, coverage matrix, automation candidates,
  proper TC format) without it. Use this skill even for simple-sounding requests like "what should
  I test?" or "what are the edge cases?" — the structured output is what makes it valuable.

  Trigger on ANY of these patterns: the user asks to create a test plan, write test cases, generate
  QA scenarios, prepare a testing checklist, identify what to test, find edge cases for a feature,
  plan testing coverage, document test scenarios, or create a QA handoff document. Also trigger
  when: the user describes requirements or acceptance criteria and asks how to verify them, the user
  points at code and asks "how would you test this?", or the user wants to plan testing before
  actually running tests.

  Do NOT trigger when: the user wants to execute tests on a running app (use test-feature or
  exploratory-test), the user wants automated unit/integration tests written in code (out of scope),
  or the user wants to run an existing test plan (use test-feature). This skill never launches an
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
# Test Plan: [Feature Name]

| Field | Value |
|-------|-------|
| **Source** | [spec link / Figma link / code path — whatever was provided] |
| **Generated** | [YYYY-MM-DD] |
| **Scope** | [one-line summary of what is covered] |
| **Status** | Draft / Ready for Review / Approved |

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

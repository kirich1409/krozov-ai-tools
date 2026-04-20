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
docs/testplans/<slug>-test-plan.md
```

Create the `docs/testplans/` directory if it doesn't exist. The slug is the canonical
filename anchor — downstream stages (`feature-flow` Phase 1.5, `acceptance` Branch 2)
mount by exact slug match, so the filename must be slug-based regardless of invocation
mode.

Slug resolution rules (apply in order):

1. **Orchestrator invocation** — when this skill is invoked from `feature-flow`, a
   `slug` argument is passed explicitly. Use it as-is.
2. **Standalone invocation, slug provided inline** — the user or caller may supply
   a slug directly (e.g. `"slug: login-flow"`). Use it as-is.
3. **Standalone invocation, no slug** — derive one from the feature name with the
   stable kebab-case convention used elsewhere in workflow docs: lowercase the
   name, replace runs of spaces or punctuation with `-`, trim leading/trailing `-`.

Examples of derivation (rule 3): `"User authentication"` → `user-authentication`,
`"Cart & checkout"` → `cart-checkout`, `"Token refresh (auth)"` → `token-refresh-auth`.
The resulting filename is then `docs/testplans/<slug>-test-plan.md` (for example,
`docs/testplans/user-authentication-test-plan.md`).

### Receipt (when invoked from orchestrator with a slug)

When invoked from `feature-flow` with a `slug` argument, also emit a receipt at
`swarm-report/<slug>-test-plan.md` so `multiexpert-review` and `acceptance` can mount
the artifact via receipt-based gating. The permanent file remains the source of truth;
the receipt is metadata + pointer. Standalone invocations (no slug passed) skip the
receipt entirely and write only the canonical `docs/testplans/<slug>-test-plan.md` file.

See [`references/receipt-format.md`](references/receipt-format.md) for the full YAML schema, field conventions
(`status`, `review_verdict`, `review_warnings` / `review_blockers`, `phase_coverage`,
`platform`, `created` / `updated`), and the standalone-without-slug backward-compatibility
rules.

## Input Discovery

Determine what the user has provided and gather context accordingly.

### 1. Text specification (PRD, acceptance criteria, user story)

Read the document. Extract:
- Functional requirements (what the feature does)
- Non-functional requirements (performance, accessibility, security constraints)
- Acceptance criteria (explicit pass/fail conditions)
- User roles and permissions mentioned

**Spec frontmatter (when the source is a file with YAML frontmatter).** Read the frontmatter
block first. If it contains a `platform:` list, copy that list verbatim into the receipt's
`platform:` field (same canonical values as `write-spec` and ORCHESTRATION.md §Project type
detection). When the orchestrator invokes this skill without a file-based spec, or the spec
has no frontmatter, leave `platform:` empty in the receipt — `acceptance` will fall back to
its project-type heuristic.

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

Every generated test plan has the same top-level layout: YAML frontmatter with `type: test-plan`
and `slug`, a header metadata table, then `Findings`, `Risk Areas`, `Test Cases`,
`Edge Cases & Negative Scenarios`, `Coverage Matrix`, and `Suggested Automation Candidates`.
Each `TC-[N]` block is itself a table with `Priority`, `Tier`, `Preconditions`, `Steps`,
`Expected Result`, and `Source` rows.

Two variants exist:

- **Standard format** — the default; full Steps + Expected Result columns.
- **Lightweight format (non-UI features)** — when the non-UI detector triggers, TC blocks
  collapse Steps and Expected Result into a single `Scenario (Given/When/Then)` row.
  All other sections are unchanged.

When the feature arrives via `decompose-feature` with two or more phases and test cases can
be grouped by phase, split the `## Test Cases` section into `### Phase N (T-i..T-j) — <label>`
subsections (still one permanent file per feature). The receipt's `phase_coverage` then lists
the phase labels present.

See [`references/format-templates.md`](references/format-templates.md) for the full standard and lightweight templates (verbatim
markdown), the phase-segmentation worked example, and the rules for when each variant applies.

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

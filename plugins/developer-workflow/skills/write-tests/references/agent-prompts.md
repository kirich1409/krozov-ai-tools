# Agent Prompt Templates

Reference for `write-tests` Phase 4.2 — see `../SKILL.md` for the skill entry point.

Pick the template that matches the agent you selected in Phase 4.1 and fill in the `{…}`
placeholders from Phases 1-3. Keep the section headings exactly as written so downstream
agents can locate the slots reliably.

Every delegation prompt must include:

1. **Target code paths** — full file paths to the code being tested
2. **Test Infrastructure Summary** — from Phase 2
3. **Test cases to implement** — from Phase 3 plan
4. **Existing test examples** — path to 1-2 representative test files for style reference
5. **Test plan** — if one was found in Phase 1.5, include its path
6. **Regression scenario** — in Regression Mode only: the structured bug description from
   Phase 1.1 (`regression-scenario` input). Omit or set to "N/A" in normal mode.

## Prompt template for kotlin-engineer

```
Write unit tests for the following code. Match the project's existing test conventions exactly.

## Target code
Read these files:
{list of file paths}

## Test Infrastructure
{Test Infrastructure Summary from Phase 2}

## Regression scenario (Regression Mode only — omit or "N/A" otherwise)
{regression_scenario: root cause + reproduction steps + expected vs actual behavior}

## Test cases to write
{list of test cases from Phase 3}

## Style reference
Read this existing test for style and conventions: {path to example test}

## Test plan (optional)
{path to test plan from docs/testplans/, or "No test plan available"}

## Requirements
- Write complete, compilable test files — no TODOs, no placeholders
- Follow the project's existing naming, assertion, and setup conventions exactly
- Use the same mocking approach as existing tests (MockK/Mockito-Kotlin/fakes)
- Cover happy path, edge cases, and error paths as specified in the test case list
- Place test files in the correct test source set and package
- Each test function tests exactly one behavior
- Test names describe the behavior being verified, not the implementation
- IF Regression Mode (regression scenario is set): write EXACTLY ONE test for the
  regression scenario above — do NOT sweep for other coverage gaps; add a one-line
  comment on the test function: `// Regression: verifies fix for [root cause]`

Respond in the same language as the user's request.
```

## Prompt template for compose-developer

```
Write Compose UI tests for the following composables. Match the project's existing test conventions.

## Target composables
Read these files:
{list of file paths}

## Test Infrastructure
{Test Infrastructure Summary from Phase 2}

## Regression scenario (Regression Mode only — omit or "N/A" otherwise)
{regression_scenario: root cause + reproduction steps + expected vs actual behavior}

## Test cases to write
{list of test cases from Phase 3}

## Style reference
Read this existing test for style and conventions: {path to example test}

## Requirements
- Use createComposeRule() or createAndroidComposeRule() as used in existing tests
- Test UI state rendering, user interactions, and state changes
- Use semantic matchers (onNodeWithText, onNodeWithTag) over implementation details
- Write complete, compilable test files — no TODOs, no placeholders
- Follow the project's existing conventions exactly
- IF Regression Mode (regression scenario is set): write EXACTLY ONE test for the
  regression scenario above — do NOT sweep for other coverage gaps; add a one-line
  comment on the test function: `// Regression: verifies fix for [root cause]`

Respond in the same language as the user's request.
```

## Prompt template for swift-engineer

```
Write unit tests for the following Swift code. Match the project's existing test conventions exactly.

## Target code
Read these files:
{list of file paths}

## Test Infrastructure
{Test Infrastructure Summary from Phase 2}

## Regression scenario (Regression Mode only — omit or "N/A" otherwise)
{regression_scenario: root cause + reproduction steps + expected vs actual behavior}

## Test cases to write
{list of test cases from Phase 3}

## Style reference
Read this existing test for style and conventions: {path to example test}

## Test plan (optional)
{path to test plan from docs/testplans/, or "No test plan available"}

## Requirements
- Write complete, compilable test files — no TODOs, no placeholders
- Follow the project's existing naming and structure conventions (Swift Testing `@Test` / `@Suite`
  vs XCTest `XCTestCase`) — do not mix the two in the same file
- Use the project's existing test-double approach (protocol-backed fakes, stubs, spies); do not
  introduce a new mocking library
- Cover happy path, edge cases, and error paths as specified in the test case list
- Place test files in the correct test target / Tests directory and module namespace
- For async code use `async` tests and structured concurrency; avoid `DispatchSemaphore` hacks
- Each test function tests exactly one behavior; names describe behavior, not implementation
- IF Regression Mode (regression scenario is set): write EXACTLY ONE test for the
  regression scenario above — do NOT sweep for other coverage gaps; add a one-line
  comment on the test function: `// Regression: verifies fix for [root cause]`

Respond in the same language as the user's request.
```

## Prompt template for swiftui-developer

```
Write SwiftUI UI tests for the following views. Match the project's existing test conventions.

## Target views
Read these files:
{list of file paths}

## Test Infrastructure
{Test Infrastructure Summary from Phase 2}

## Regression scenario (Regression Mode only — omit or "N/A" otherwise)
{regression_scenario: root cause + reproduction steps + expected vs actual behavior}

## Test cases to write
{list of test cases from Phase 3}

## Style reference
Read this existing test for style and conventions: {path to example test}

## Test plan (optional)
{path to test plan from docs/testplans/, or "No test plan available"}

## Requirements
- Match the project's existing approach — ViewInspector-style unit tests, XCUITest UI tests,
  or snapshot tests — do not introduce a new UI-testing library
- Test view state rendering, user interactions, and state changes
- Prefer accessibility identifiers / labels over view-tree internals for queries
- Write complete, compilable test files — no TODOs, no placeholders
- Follow the project's existing conventions exactly
- IF Regression Mode (regression scenario is set): write EXACTLY ONE test for the
  regression scenario above — do NOT sweep for other coverage gaps; add a one-line
  comment on the test function: `// Regression: verifies fix for [root cause]`

Respond in the same language as the user's request.
```

---
name: write-tests
description: >-
  Write retroactive tests for existing code — classes, modules, or directories that lack test
  coverage. Discovers the project's test infrastructure (framework, assertions, mocking, naming
  conventions), plans test cases, delegates code generation to kotlin-engineer (or
  compose-developer for Compose UI), verifies tests compile and pass, and reports findings.
  Use when the user says: "write tests for", "add tests to", "test this class", "increase
  coverage", "add unit tests", "this code has no tests", "cover with tests", "retroactive tests".
  Do NOT trigger when: the user wants a test plan document without code (use generate-test-plan),
  the user wants to run tests on a live app (use test-feature), the user wants exploratory QA
  (use exploratory-test), or tests are part of a new feature being implemented (kotlin-engineer
  handles this within the implement skill). This skill orchestrates — it does not write test code
  directly; kotlin-engineer or compose-developer agents produce the test files.
  Cross-references: consumes test plans from generate-test-plan (docs/testplans/) when available;
  feeds into the Quality Loop as additional coverage.
---

# Write Tests

Orchestrate retroactive test generation for existing code that lacks coverage. The skill
discovers what needs testing, understands the project's test infrastructure, plans test cases,
delegates code generation to the appropriate agent, verifies the tests, and reports results.

**Key principle:** this skill is an orchestrator. It never writes test code directly — it
delegates to `kotlin-engineer` (business logic, data layer, domain) or `compose-developer`
(Compose UI code). The skill's job is discovery, planning, delegation, and verification.

---

## Phase 1: Scope Target

### 1.1 Accept target

The user provides one or more of:
- A file path (`src/main/kotlin/com/example/UserRepository.kt`)
- A class name (`UserRepository`)
- A module or directory (`feature/auth`, `:core:network`)
- A vague reference ("the auth module", "this class")

Resolve vague references using `ast-index search` or `ast-index class`. If ambiguous, ask
**one clarifying question** before proceeding.

### 1.1.1 Generate slug

Create a short kebab-case slug from the target name for artifact naming:
`<slug>` (e.g., `user-repository`, `auth-module`, `network-client`)

Used in: `swarm-report/<slug>-test-findings.md`

### 1.2 Read target code

Read all source files in the target scope. For each file, identify:
- Public API surface (public/internal classes, functions, properties)
- Dependencies (constructor parameters, injected services)
- Complexity indicators (branching, state management, error handling)
- Whether the code is Compose UI or non-UI Kotlin

### 1.3 Find existing tests

Search for existing tests:
- Check the corresponding test source set (`src/test/`, `src/androidTest/`, `src/commonTest/`)
- Use `ast-index search "TargetClass"` or `ast-index usages "TargetClass"` to find test classes that reference the target classes
- Check for `@Test` annotations that exercise target functions

### 1.4 Identify untested code

Compare the public API surface against existing test coverage:
- Functions/classes with no test references → fully untested
- Functions with some tests but missing edge cases → partially tested
- Functions with comprehensive tests → already covered (skip)

### 1.5 Check for existing test plan

Look for a test plan in `docs/testplans/` that covers the target feature or module.
If found, read it and use its test cases as input for Phase 3. If not found, proceed
without one — a test plan is helpful but not required.

---

## Phase 2: Discover Test Infrastructure

Analyze the project's existing test setup to ensure generated tests match the codebase
conventions. Inspect existing test files (at least 3-5 if available) and build configuration.

### 2.1 Detect frameworks and libraries

| Category | What to detect | Where to look |
|----------|---------------|---------------|
| Test framework | JUnit 4, JUnit 5, Kotest | `build.gradle(.kts)` dependencies, existing test imports |
| Assertion library | Truth, AssertJ, Kotest matchers, kotlin.test | Existing test imports and assertions |
| Mocking | MockK, Mockito-Kotlin, fakes (manual) | Existing test imports, `@MockK`, `mock()`, `Fake*` classes |
| Coroutine testing | `kotlinx-coroutines-test` (`runTest`), Turbine | Existing test imports, `build.gradle(.kts)` |
| Compose testing | `compose-ui-test`, `createComposeRule` | Existing test imports, `build.gradle(.kts)` |
| DI in tests | Hilt test, Koin test, manual construction | Existing test setup patterns |

### 2.2 Detect conventions

| Convention | What to detect | How |
|-----------|---------------|-----|
| Naming | `should verb`, `test verb`, backtick names, `given_when_then` | Read existing test function names |
| File placement | Same package as source? Separate test package? | Compare test file locations to source |
| Test class naming | `ClassNameTest`, `ClassNameSpec`, `ClassNameTests` | Read existing test class names |
| Setup pattern | `@Before`/`@BeforeEach`, `init {}`, builder/factory | Read existing test setup blocks |
| Assertion style | Fluent (`assertThat(x).isEqualTo(y)`) vs plain (`assertEquals`) | Read existing assertions |

### 2.3 Produce Test Infrastructure Summary

Compile findings into a structured summary for the code generation agent:

```
## Test Infrastructure Summary

**Framework:** {JUnit 4 / JUnit 5 / Kotest}
**Assertions:** {Truth / AssertJ / Kotest matchers / kotlin.test}
**Mocking:** {MockK / Mockito-Kotlin / fakes / none}
**Coroutine testing:** {runTest + Turbine / runTest only / runBlocking / none}
**Compose testing:** {compose-ui-test / none}

**Naming convention:** {description — e.g., "backtick names with 'should' prefix"}
**Class naming:** {e.g., "ClassNameTest"}
**File placement:** {e.g., "same package in src/test/kotlin/"}
**Setup pattern:** {e.g., "@Before with MockK annotations"}
**Assertion style:** {e.g., "Truth fluent assertions"}

**Example test file:** {path to a representative existing test for reference}
```

---

## Phase 3: Plan Test Cases

### 3.1 Generate test cases

For each untested or partially tested class/function, determine:

- **What to test:** public API, edge cases, error paths, state transitions
- **Test type:** unit (isolated, mocked dependencies) or integration (real collaborators)
- **Dependencies to mock/fake:** which collaborators need test doubles
- **Input scenarios:** happy path, boundary values, null/empty, error conditions

### 3.2 Prioritize

If the target is large (more than 5 classes to test), ask the user which classes or areas
to prioritize. Present the list with a brief note on each:

```
Found 12 untested classes in :feature:auth. Which should I prioritize?

1. LoginUseCase — complex branching, 4 public functions
2. AuthRepository — network + cache interaction
3. TokenManager — security-sensitive, encryption
4. SessionStore — simple data holder, 2 functions
...

Recommend starting with 1-3 (highest complexity and risk).
```

Wait for user response before proceeding. If the target is small (5 or fewer classes),
proceed without asking.

### 3.3 Lightweight plan

Create an internal (not saved to file) plan listing:
- Target class/function
- Test cases with one-line descriptions
- Dependencies to mock/fake
- Any special setup needed (coroutine dispatcher, test database, etc.)

---

## Phase 4: Generate Tests

Delegate test code generation to the appropriate agent. The skill provides all context;
the agent writes the code.

### 4.1 Select agent

| Target code type | Agent |
|-----------------|-------|
| Business logic, data layer, domain, ViewModel | `kotlin-engineer` |
| Compose UI composables | `compose-developer` |

If the target includes both UI and non-UI code, launch separate agents for each.

### 4.2 Agent prompt

Include in the delegation prompt:

1. **Target code paths** — full file paths to the code being tested
2. **Test Infrastructure Summary** — from Phase 2
3. **Test cases to implement** — from Phase 3 plan
4. **Existing test examples** — path to 1-2 representative test files for style reference
5. **Test plan** — if one was found in Phase 1.5, include its path

**Prompt template for kotlin-engineer:**
```
Write unit tests for the following code. Match the project's existing test conventions exactly.

## Target code
Read these files:
{list of file paths}

## Test Infrastructure
{Test Infrastructure Summary from Phase 2}

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

Respond in the same language as the user's request.
```

**Prompt template for compose-developer:**
```
Write Compose UI tests for the following composables. Match the project's existing test conventions.

## Target composables
Read these files:
{list of file paths}

## Test Infrastructure
{Test Infrastructure Summary from Phase 2}

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

Respond in the same language as the user's request.
```

---

## Phase 5: Verify

### 5.1 Run tests

Run the test suite for the target module:

```bash
# Unit tests
./gradlew :module:test
# or more specific: ./gradlew :module:testDebugUnitTest

# Instrumentation / Compose UI tests (if generated into src/androidTest/)
./gradlew :module:connectedAndroidTest
```

Choose the appropriate command based on where tests were generated. If both unit and
instrumentation tests were created, run both.

### 5.2 Handle failures

If tests fail, classify each failure:

| Failure type | Action |
|-------------|--------|
| **Test bug** — incorrect assertion, wrong setup, missing mock | Fix via `kotlin-engineer` (max 3 attempts) |
| **Production bug** — test correctly exposes a real bug in the target code | Do NOT fix. Record as a finding. |

**How to distinguish:**
- Read the stack trace and the failing assertion
- If the test expectation contradicts the actual code behavior and the code behavior
  looks intentional → test bug (fix the test)
- If the test expectation matches the documented/expected contract but the code violates
  it → production bug (report it)
- If unclear → err on the side of reporting as a finding rather than silently fixing

### 5.3 Fix cycle

For test bugs:
1. Delegate the fix to `kotlin-engineer` with the failure output and the test file path
2. Re-run the tests
3. Repeat up to 3 times total

If tests still fail after 3 attempts — stop and report the failing tests with details
in the final report.

---

## Phase 6: Report

Present a concise report to the user covering:

### 6.1 Files created

List all new test files with their paths:
```
Created:
- src/test/kotlin/com/example/auth/LoginUseCaseTest.kt (8 tests)
- src/test/kotlin/com/example/auth/AuthRepositoryTest.kt (12 tests)
```

### 6.2 Coverage summary

What is now tested that wasn't before:
```
Coverage:
- LoginUseCase: 4 public functions, all now tested (happy path + error cases)
- AuthRepository: 3 of 5 functions tested (getUser, login, logout)
  - Not tested: refreshToken (requires integration test setup), clearCache (trivial)
```

### 6.3 Test results

```
Results: 20 tests passed, 0 failed
```

Or if there were issues:
```
Results: 18 tests passed, 2 failed after 3 fix attempts
- LoginUseCaseTest.`should handle concurrent login attempts` — timing-dependent, needs TestDispatcher configuration
- AuthRepositoryTest.`should retry on network error` — mock setup issue with suspend functions
```

### 6.4 Findings (production bugs)

If any tests exposed real bugs in the target code, list them:
```
Findings:
- LoginUseCase.login() does not check for empty password — allows login with blank credentials
- AuthRepository.getUser() swallows IOException instead of propagating, returns stale cached data silently
```

Save findings to `swarm-report/<slug>-test-findings.md` only if production bugs were
discovered. Format:

```markdown
# Test Findings: {target description}

Date: {YYYY-MM-DD}
Target: {file/module path}

## Production Bugs Found

### 1. {short description}
- **Location:** {file:line}
- **Issue:** {what the code does wrong}
- **Expected:** {what the correct behavior should be}
- **Test:** {test that exposed this — file:testName}
- **Severity:** Critical / Major / Minor

### 2. {short description}
...
```

---

## Constraints

- **Orchestrator only** — this skill plans and delegates; `kotlin-engineer` and
  `compose-developer` write the actual test code
- **No production code changes** — if tests reveal bugs, report them as findings.
  Do not fix the production code. The user decides what to do with findings.
- **Match existing conventions** — generated tests must be indistinguishable from
  hand-written tests in the project. Never introduce a new framework or style.
- **No new dependencies** — use only what's already in the project's test dependencies.
  If a needed library is missing, note it in the report and ask the user before adding.
- **Test plans are optional input** — this skill consumes test plans from
  `generate-test-plan` when they exist, but works independently without one.
- **No swarm-report artifact for tests** — the test files themselves are the artifact.
  Only create `swarm-report/<slug>-test-findings.md` if production bugs are found.

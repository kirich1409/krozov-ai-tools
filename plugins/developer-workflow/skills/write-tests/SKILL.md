---
name: write-tests
description: "Write retroactive tests for existing code — classes, modules, or directories lacking test coverage. Discovers test infrastructure (framework, assertions, mocking, naming), plans test cases, delegates generation to platform engineer agents (kotlin-engineer, compose-developer, swift-engineer, swiftui-developer) matched to the target code, verifies tests compile and pass, reports findings. Use when: \"write tests for\", \"add tests to\", \"test this class\", \"increase coverage\", \"add unit tests\", \"this code has no tests\", \"cover with tests\", \"retroactive tests\". Do NOT use when: user wants a test plan document without code (use generate-test-plan), run tests on live app (use acceptance), exploratory QA (use bug-hunt), or tests are part of a new feature (the engineer agent handles tests within implement). Orchestrator — delegates actual test code to engineer agents. Consumes test plans from generate-test-plan when available."
---

# Write Tests

Orchestrate retroactive test generation for existing code that lacks coverage. The skill
discovers what needs testing, understands the project's test infrastructure, plans test cases,
delegates code generation to the appropriate agent, verifies the tests, and reports results.

**Key principle:** this skill is an orchestrator. It never writes test code directly — it
delegates to a platform engineer agent: `kotlin-engineer` / `compose-developer` for
Kotlin/Android targets, or `swift-engineer` / `swiftui-developer` for Swift/iOS targets.
The skill's job is discovery, planning, delegation, and verification.

---

## Phase 1: Scope Target

### 1.1 Accept target

The user provides one or more of:
- A file path (`src/main/kotlin/com/example/UserRepository.kt`, `Sources/Auth/LoginService.swift`)
- A class or type name (`UserRepository`, `LoginService`)
- A module or directory (`feature/auth`, `:core:network`, `Sources/Auth`, an Xcode target)
- A vague reference ("the auth module", "this class", "the login view")

Resolve vague references using a code-index tool when one is available in the environment;
fall back to `Grep` / `Glob` + `Read` otherwise. If the reference remains ambiguous after
resolution, ask **one clarifying question** before proceeding.

### 1.1.1 Generate slug

Create a short kebab-case slug from the target name for artifact naming:
`<slug>` (e.g., `user-repository`, `auth-module`, `network-client`)

Used in: `swarm-report/<slug>-test-findings.md`

### 1.2 Read target code

Read all source files in the target scope. For each file, identify:
- Public API surface (public/internal classes, functions, properties)
- Dependencies (constructor parameters, injected services)
- Complexity indicators (branching, state management, error handling)
- Whether the code is UI (Compose composables, SwiftUI views) or non-UI code (Kotlin business
  logic / data layer, Swift services / models / repositories)

### 1.3 Find existing tests

Search for existing tests:
- Check the corresponding test location — Kotlin/Android: `src/test/`, `src/androidTest/`,
  `src/commonTest/`; Swift: `Tests/<TargetName>Tests/` (SwiftPM) or the Xcode test target
  (often `<AppName>Tests/` or `<AppName>UITests/`)
- Prefer a code-index tool when one is available in the environment to locate test classes
  that reference the target by symbol (search / usages / class lookups); fall back to
  `Grep "TargetClass" path/to/test-src-set` when no index is available
- Check for `@Test` (JUnit / Swift Testing) or `XCTestCase` subclasses that exercise target functions

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

Inspect 3-5 existing test files plus build configuration (`build.gradle(.kts)`,
`Package.swift`, Xcode project) to discover the framework, assertion library, mocking /
test-double approach, async-testing helpers, UI-testing stack, and naming / file-placement
conventions in use. Compile the results into a structured **Test Infrastructure Summary**
that the Phase 4 engineer agent consumes verbatim.

The goal is simple: generated tests must look hand-written. Never introduce a new framework
or style that isn't already present in the project.

See `references/test-infrastructure-discovery.md` for the detection tables (frameworks,
assertions, mocking, async, UI, DI, naming, placement, setup, assertion style) and the exact
Test Infrastructure Summary template.

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
| Kotlin business logic, data layer, domain, ViewModel | `kotlin-engineer` |
| Compose UI composables | `compose-developer` |
| Swift business logic, data layer, services, models, repositories | `swift-engineer` |
| SwiftUI views, screens, modifiers, navigation | `swiftui-developer` |

Route by both language and layer: Kotlin/Android targets go to `kotlin-engineer` or
`compose-developer`; Swift/iOS/macOS targets go to `swift-engineer` or `swiftui-developer`.
If the target includes both UI and non-UI code, launch separate agents for each. If the
required platform plugin is not installed, the Task call will fail with a clear message —
report it and ask the user to install the matching platform plugin.

### 4.2 Agent prompt

Every delegation prompt must include: target code paths, the Phase 2 Test Infrastructure
Summary, the Phase 3 test cases, a style-reference test file, and the Phase 1.5 test plan
if one exists.

See `references/agent-prompts.md` for the full prompt templates for `kotlin-engineer`,
`compose-developer`, `swift-engineer`, and `swiftui-developer`. Fill in the `{…}`
placeholders and keep the section headings intact.

---

## Phase 5: Verify

### 5.1 Run tests

Run the test suite for the target module. Pick the command family that matches the project
build system:

```bash
# Kotlin / Android (Gradle)
./gradlew :module:test
# or more specific: ./gradlew :module:testDebugUnitTest

# Android instrumentation / Compose UI tests (if generated into src/androidTest/)
./gradlew :module:connectedAndroidTest

# Swift — SwiftPM package
swift test
# or narrow to one target: swift test --filter <TargetName>Tests

# Swift — Xcode project / workspace (iOS, macOS, etc.)
xcodebuild test -scheme <Scheme> -destination 'platform=iOS Simulator,name=iPhone 15'
# For a macOS scheme: -destination 'platform=macOS'
# Narrow with: -only-testing:<TestTarget>/<TestClass>/<testMethod>
```

Choose the appropriate command based on where tests were generated and what build system the
project uses. If both unit and UI / instrumentation tests were created, run both.

### 5.2 Handle failures

If tests fail, classify each failure:

| Failure type | Action |
|-------------|--------|
| **Test bug** — incorrect assertion, wrong setup, missing mock | Fix via the same engineer agent that wrote the test (max 3 attempts) |
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
1. Delegate the fix to the engineer agent that wrote the test (`kotlin-engineer` /
   `compose-developer` / `swift-engineer` / `swiftui-developer`) with the failure output and
   the test file path
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

- **Orchestrator only** — this skill plans and delegates; the platform engineer agents
  (`kotlin-engineer`, `compose-developer`, `swift-engineer`, `swiftui-developer`) write the
  actual test code
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

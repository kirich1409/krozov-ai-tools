---
name: write-tests
description: "This skill should be used to write retroactive tests for existing code — classes, modules, or directories lacking coverage — and to write a focused regression test for a specific bug fix (Regression Mode: pass regression-scenario from debug.md). Discovers test infrastructure, plans test cases, delegates generation to platform engineer agents (kotlin-engineer, compose-developer, swift-engineer, swiftui-developer), verifies tests pass. Use when: \"write tests for\", \"add tests to\", \"test this class\", \"increase coverage\", \"add unit tests\", \"this code has no tests\", \"cover with tests\", \"retroactive tests\", \"add regression test for this fix\", \"write a test that catches this bug\", \"regression test after fixing\", \"test to verify the fix\". Do NOT use when: user wants a test plan document (use generate-test-plan), run tests on live app (use acceptance), exploratory QA (use bug-hunt), or tests are part of a new feature (engineer agent handles within implement)."
---

# Write Tests

Orchestrate retroactive test generation for existing code that lacks coverage. The skill
discovers what needs testing, understands the project's test infrastructure, plans test cases,
delegates code generation to the appropriate agent, verifies the tests, and reports results.

**Key principle:** this skill is an orchestrator. It never writes test code directly — it
delegates to a platform engineer agent: `kotlin-engineer` / `compose-developer` for
Kotlin/Android targets, or `swift-engineer` / `swiftui-developer` for Swift/iOS targets.
The skill's job is discovery, planning, delegation, and verification.

**Author fixes broken tests (non-negotiable).** Any test broken by the changes this skill produces — the new test, the file it covers, or a directly adjacent test whose behaviour shifted because of the new assertions — is fixed by the engineer agent in the same `write-tests` run. Tests already failing on `main` before this run are NOT in scope; surface them in the final report and continue. Skipping or `@Ignore`-ing the in-scope set without a recorded follow-up issue is not allowed. Disambiguation rules (intentional behaviour change vs unintentional break vs pre-existing failure on `main`) and the single skip-marker escape hatch live in [`docs/TESTING-STRATEGY.md`](../../docs/TESTING-STRATEGY.md#author-fixes-broken-tests-non-negotiable).

---

## Phase 1: Scope Target

### 1.1 Accept target

The user provides one or more of:
- A file path (`src/main/kotlin/com/example/UserRepository.kt`, `Sources/Auth/LoginService.swift`)
- A class or type name (`UserRepository`, `LoginService`)
- A module or directory (`feature/auth`, `:core:network`, `Sources/Auth`, an Xcode target)
- A vague reference ("the auth module", "this class", "the login view")

**Regression Mode:** the caller may additionally pass a `regression-scenario` — a structured
description of the bug's root cause, reproduction steps, and expected vs actual behavior
(typically from `swarm-report/<slug>-debug.md`). When present, the skill enters **Regression
Mode**: it skips the broad coverage sweep (Phase 1.4), uses the scenario as the sole test
case (Phase 3.1), and skips the prioritization question (Phase 3.2). The output is one
focused test that would fail on the original buggy code and passes with the fix applied.

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

**Skip this phase in Regression Mode.** The test case comes from the `regression-scenario`,
not from a coverage gap analysis.

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

See [`references/test-infrastructure-discovery.md`](references/test-infrastructure-discovery.md) for the detection tables (frameworks,
assertions, mocking, async, UI, DI, naming, placement, setup, assertion style) and the exact
Test Infrastructure Summary template.

### Framework detection (canonical algorithm)

Engineer agents (`kotlin-engineer`, `compose-developer`, `swift-engineer`, `swiftui-developer`) follow this fixed order. Stop at the first step that yields a definite answer.

1. **Inspect existing test files** in the **module being modified** first, then the wider project, in conventional locations: `src/test/`, `src/androidTest/`, `Tests/`, `spec/`. Identify framework, assertion library, mocking approach, naming convention, and arrange-act-assert / given-when-then style. Existing tests are the strongest signal — they win over build-file dependencies, since a project may keep multiple test libraries declared but actually use only one.
2. **Inspect the build file** for test-framework dependencies (used only when the module under change has no existing tests).
   - `build.gradle.kts` / `build.gradle` — JUnit 4/5, MockK, Mockito, `kotlin.test`, Kotest, `androidx.compose.ui:ui-test-junit4`, Paparazzi, Robolectric.
   - `Package.swift` / `Podfile` / `*.xcodeproj` — XCTest, `swift-testing` (Apple), Quick / Nimble, ViewInspector, swift-snapshot-testing.
   - `pom.xml` — JUnit, Mockito, TestNG.
3. **Match the existing project**, even when multiple frameworks coexist.
   - In a mixed project, follow the framework already in use **in the module being modified**.
   - Never introduce a new framework or style without explicit user approval.
4. **Apply the platform default** only when no signal exists in the project (no tests, no test-framework deps).

Other ecosystems (Java-only, JS/TS, Rust, etc.) are out of scope for `write-tests` delegation in this plugin; surface them to the user.

#### Platform defaults

| Platform | Default |
|---|---|
| Android / Kotlin (JVM) | JUnit 5 + MockK |
| Kotlin Multiplatform | `kotlin.test` (with `expect` / `actual` test doubles) |
| Compose UI | `androidx.compose.ui:ui-test-junit4` |
| iOS / Swift, toolchain ≥ 5.9 | `swift-testing` |
| iOS / Swift, toolchain < 5.9 | XCTest |
| SwiftUI | engineer asks one question to choose between XCUITest (end-to-end UI flow), ViewInspector (view-tree assertions), or preview-based snapshot — there is no single SwiftUI testing default; record the answer in the Test Infrastructure Summary |

#### Escalation rules

- **More than one framework in existing tests** → engineer picks by majority of files in the affected module; if the split is even, asks one clarifying question before generating.
- **Detected framework is unavailable in the toolchain** (e.g. `swift-testing` on toolchain < 5.9) → fall back to the older platform default; record the fallback in the Test Infrastructure Summary and in a header comment of the generated test.
- **Required framework dependency is missing entirely** → engineer stops and asks the user before adding the dependency. `write-tests` does not auto-add dependencies.

---

## Phase 3: Plan Test Cases

### 3.1 Generate test cases

**Regression Mode:** use the `regression-scenario` as the single test case. Derive:
- **What to test:** the exact reproduction scenario — no broader sweep
- **Test type:** unit (preferred); integration only if the reproduction requires real
  collaborators (e.g., database + service interaction)
- **Dependencies to mock/fake:** only those required for the specific scenario
- **Pass/fail contract:** the test must fail on the original buggy code and pass with
  the fix applied; document this expectation as a comment in the test body

**Normal Mode:**

For each untested or partially tested class/function, determine:

- **What to test:** public API, edge cases, error paths, state transitions
- **Test type:** unit (isolated, mocked dependencies) or integration (real collaborators)
- **Dependencies to mock/fake:** which collaborators need test doubles
- **Input scenarios:** happy path, boundary values, null/empty, error conditions

### 3.2 Prioritize

**Skip this phase in Regression Mode** — a regression scenario is always a single focused
test case; no prioritization is needed.

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

See [`references/agent-prompts.md`](references/agent-prompts.md) for the full prompt templates for `kotlin-engineer`,
`compose-developer`, `swift-engineer`, and `swiftui-developer`. Fill in the `{…}`
placeholders and keep the section headings intact.

---

## Phase 5: Verify

### 5.0 Regression Mode: verify pass/fail contract

**Regression Mode only — skip in Normal Mode.**

A regression test written after the fix is green "by construction" and may assert something
that would have been green even before the fix. Before running the full test suite, verify
the contract: the test MUST fail on the original buggy code.

Steps:
1. **Identify fix commits** from `swarm-report/<slug>-implement.md` (field "Commit" or
   "Commits"). If a single hash → use it directly. If multiple hashes → collect all of them;
   revert in reverse order (newest first). If the field is absent — use
   `git log origin/main..HEAD --pretty=format:"%H" -- <fixed-files>` to list them.
2. **Temporarily revert the fix** without committing. For each fix commit, check if it is a
   merge commit (`git show --no-patch --format="%P" <hash>` returns two hashes):
   ```bash
   # Single non-merge commit:
   git revert <fix-commit-hash> --no-commit

   # Merge commit — must specify mainline parent:
   git revert <fix-commit-hash> -m 1 --no-commit

   # Multiple commits — revert in reverse order:
   git revert <hash-N> ... <hash-1> --no-commit
   ```
3. Run **only the new regression test** (use the narrowest filter available):
   ```bash
   # Kotlin — run single test class
   ./gradlew :module:test --tests "*.ClassName"
   # Swift — run single test
   swift test --filter Suite/testMethod
   ```
4. **If RED** (test fails) → contract verified. Restore tracked files to pre-revert state
   while keeping the untracked test file intact (it has not been committed yet):
   ```bash
   git reset --hard HEAD
   ```
   Record in `swarm-report/<slug>-implement.md` (append one line):
   `Regression contract: VERIFIED — test RED on revert of fix commits (<hash-1>…<hash-N>), GREEN with fix.`
   Proceed to Phase 5.1 (full test suite).
5. **If GREEN on buggy code** → the test does NOT capture the regression. It is ineffective.
   Discard both the revert changes AND the test file — the test is structurally wrong and
   should not be salvaged; the next Implement invocation needs a different approach:
   ```bash
   git reset HEAD -- . && git checkout -- . && git clean -fd
   ```
   (`git clean -fd` intentionally removes the untracked test file here.)
   Before returning to the caller, produce a Coverage Diagnosis (see Phase 6.5) that explains:
   - What the test asserts and why that assertion passes even without the fix
   - What aspect of the bug the test missed (wrong entry point, wrong layer, assertion
     on a side effect rather than the cause, etc.)
   - What would need to change for the test to actually catch the regression
   Report to `bugfix-flow` as an **Ineffective Test** (not a Production Bug — see Phase 6.5
   status `INEFFECTIVE`), attaching the Coverage Diagnosis so the next Implement invocation
   has a concrete direction for addressing the test design, not just the fix.
   Do NOT continue to Phase 5.1.

**Conflict handling:** if `git revert` produces a merge conflict, accept the buggy side
(`--theirs`) to ensure the working tree contains the original broken code:
```bash
git checkout --theirs <conflicting-file>
git add <conflicting-file>
```
Then run step 3. Do NOT resolve toward the fix side — that would produce a false GREEN.

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
# Narrow by test-product (test target): swift test --test-product <TestTargetName>
# Narrow by identifier pattern: swift test --filter <Suite>/<method>  (e.g. LoginTests/testSignIn)
# Note: --filter matches test identifiers/regex, not targets.

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

If tests still fail after 3 attempts — produce a Coverage Diagnosis (see Phase 6.5)
that summarises what was attempted in each round and what the specific technical obstacle is.
Stop and include the diagnosis in the final report.

### 5.4 Commit and push (Regression Mode only)

**Regression Mode only — skip in Normal Mode.**

After all tests pass (Phase 5.1 green), commit the generated test file(s) and push to the
current branch. Normal Mode leaves file management to the user; Regression Mode is invoked
by `bugfix-flow` which expects the test to land as a commit on the PR branch automatically.

```bash
git add <test-file-paths>
git commit -m "Add regression test: <scenario — subject line ≤72 chars total>"
git push
```

The commit message should name the bug scenario, not just say "add test" — it becomes part
of the permanent history explaining why this test exists.

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

### 6.5 Coverage Diagnosis (Regression Mode — when test could not be completed)

**Regression Mode only.** Produce this section when the regression test failed for any
reason: ineffective test (GREEN on buggy code in Phase 5.0), tests still failing after
3 fix attempts (Phase 5.3), or test could not be written at all.

The diagnosis must answer three questions concisely:
1. **What was tried** — what assertion / test approach was used
2. **What blocked it** — the specific technical obstacle (not just "test failed"); e.g.:
   - "The assertion targets the return value, but the bug is in a side effect on a
     non-injectable static field"
   - "The reproduction requires two threads interleaving; TestCoroutineDispatcher
     serialises all work on one thread, preventing the race"
   - "The affected code path is guarded by a native method with no test double"
3. **What would make it testable** — what change to the code or test setup would
   allow a reliable regression test in the future

Save to `swarm-report/<slug>-regression-coverage.md`:

```markdown
# Regression Coverage Diagnosis: {bug slug}

Date: {YYYY-MM-DD}
Status: INEFFECTIVE | FAILED | NOT_ATTEMPTED

## What was tried
{test approach and assertion used, or why no test was written}

## Technical obstacle
{specific reason — concrete, not generic}

## To make testable
{what would need to change in code or test setup}
```

Reference this file in the PR body and in the report to `bugfix-flow`.

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

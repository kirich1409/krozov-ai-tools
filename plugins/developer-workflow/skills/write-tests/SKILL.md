---
name: write-tests
description: "Write retroactive tests for existing code — classes, modules, or directories lacking coverage — and write a focused regression test for a specific bug fix. Discovers test infrastructure, plans test cases, delegates generation to platform engineer agents (kotlin-engineer, compose-developer, swift-engineer, swiftui-developer), verifies tests pass. Use when: \"write tests for\", \"add tests to\", \"test this class\", \"increase coverage\", \"add unit tests\", \"this code has no tests\", \"cover with tests\", \"retroactive tests\", \"add regression test for this fix\", \"write a test that catches this bug\", \"regression test after fixing\", \"test to verify the fix\". Do NOT use when: user wants a test plan document (use generate-test-plan), run tests on live app (use acceptance), exploratory QA (call manual-tester agent directly), or tests are part of a new feature (engineer agent handles inline)."
---

# Write Tests

Orchestrate retroactive test generation for existing code that lacks coverage. The skill
discovers what needs testing, understands the project's test infrastructure, plans test cases,
delegates code generation to the appropriate agent, verifies the tests, and reports results.

**Key principle:** this skill is an orchestrator. It never writes test code directly — it
delegates to a platform engineer agent: `kotlin-engineer` / `compose-developer` for
Kotlin/Android targets, or `swift-engineer` / `swiftui-developer` for Swift/iOS targets.
The skill's job is discovery, planning, delegation, and verification.

**Author-fixes-broken-tests rule** — see `~/.claude/rules/qa-and-testing.md` § 4. Skipping or `@Ignore`-ing without a tracked follow-up issue is not allowed.

**Disambiguation:**
- *Intentional behaviour change* — your new test asserts a different (intentional) outcome from a pre-existing test → update the older test in the same run, with a one-line comment explaining the new contract.
- *Unintentional break* — a previously green test fails after your change and the change shouldn't have affected that behaviour → the change is wrong; revise it.
- *Pre-existing failure on main* — a test was already red before this run → out of scope; report it and continue.

---

## Phase 1: Scope Target

### 1.1 Accept target

Target may be a file path, class/type name, module or directory, or a vague reference ("the auth module"). Resolve vague references via a code-index tool when available; fall back to `Grep` / `Glob` + `Read`. If still ambiguous, ask **one clarifying question** before proceeding.

**Regression Mode:** the caller may pass a `regression-scenario` — root cause, reproduction steps, expected vs actual behaviour (typically from `swarm-report/<slug>-debug.md`). When present, the skill skips the broad coverage sweep (1.4), uses the scenario as the sole test case (3.1), and skips prioritization (3.2). Output is one focused test that fails on the original buggy code and passes with the fix.

### 1.1.1 Generate slug

Short kebab-case slug from the target name (e.g. `user-repository`, `auth-module`). Used in `swarm-report/<slug>-test-findings.md`.

### 1.2 Read target code

For each file in scope identify: public API surface, dependencies (constructor params, injected services), complexity indicators (branching, state, error handling), and whether the code is UI (Compose / SwiftUI) or non-UI (business logic / data layer / services / models / repositories).

### 1.3 Find existing tests

Check standard test locations — Kotlin: `src/test/`, `src/androidTest/`, `src/commonTest/`; Swift: `Tests/<TargetName>Tests/` (SwiftPM) or the Xcode test target. Prefer a code-index tool to locate test classes by symbol; fall back to `Grep`. Look for `@Test` (JUnit / Swift Testing) or `XCTestCase` subclasses that exercise the target.

### 1.4 Identify untested code

**Skip in Regression Mode.** Compare the public API surface against existing test coverage: no references → fully untested; partial references missing edge cases → partially tested; comprehensive coverage → skip.

Public-API coverage gate — see `~/.claude/rules/qa-and-testing.md` § 1.

### 1.5 Check for existing test plan

Look for a test plan in `docs/testplans/` covering the target. If found, read it and feed its test cases into Phase 3. If not found, proceed without one — a test plan is helpful but not required.

---

## Phase 2: Discover Test Infrastructure

Testing infra detection — see `~/.claude/rules/qa-and-testing.md` § 5 for project-marker files. Inspect 3-5 existing test files plus the relevant build configuration to discover the framework, assertion library, mocking / test-double approach, async-testing helpers, UI-testing stack, and naming / file-placement conventions. Compile results into a structured **Test Infrastructure Summary** that the Phase 4 engineer agent consumes verbatim.

The goal is simple: generated tests must look hand-written. Never introduce a new framework or style that isn't already present in the project.

See [`references/test-infrastructure-discovery.md`](references/test-infrastructure-discovery.md) for the detection tables (frameworks, assertions, mocking, async, UI, DI, naming, placement, setup, assertion style) and the exact Test Infrastructure Summary template.

### Framework detection

Engineer agents follow the canonical algorithm from [`references/test-infrastructure-discovery.md`](references/test-infrastructure-discovery.md): existing test files in the module under change → build-file dependencies → match the project's existing framework → platform default (Android/Kotlin JVM: JUnit 5 + MockK; KMP: `kotlin.test`; Compose UI: `ui-test-junit4`; iOS ≥ 5.9: `swift-testing`; iOS < 5.9: XCTest; SwiftUI: ask one question). Stop at the first step that yields a definite answer; never introduce a new framework without explicit user approval.

Other ecosystems (Java-only, JS/TS, Rust, etc.) are out of scope for `write-tests` delegation in this plugin; surface them to the user.

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

**Skip this phase in Regression Mode** — a regression scenario is always a single focused test case; no prioritization is needed.

Test priority — see `~/.claude/rules/qa-and-testing.md` § 2. If the target is large (more than 5 classes to test), present the list with a one-line note on each (complexity, risk surface) and ask the user which to prioritize; recommend starting with the highest-complexity / highest-risk subset. If the target is small (5 or fewer classes), proceed without asking.

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
1. **Identify fix commits.** Primary source: `git log origin/main..HEAD --pretty=format:"%H" -- <fixed-files>`
   on the branch — that is the authoritative list of fix commits for the affected files. If the
   caller passed a hint (e.g. an `<slug>-debug.md` with a "Commit"/"Commits" field, or commit
   hashes provided in chat), use it to narrow the set; otherwise use the full git-log output.
   If a single hash → use it directly. If multiple hashes → collect all of them; revert in
   reverse order (newest first).
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
   Record the verification in the write-tests receipt (`swarm-report/<slug>-write-tests.md`,
   append one line):
   `Regression contract: VERIFIED — test RED on revert of fix commits (<hash-1>…<hash-N>), GREEN with fix.`
   Proceed to Phase 5.1 (full test suite).
5. **If GREEN on buggy code** → the test does NOT capture the regression. It is ineffective.
   Discard both the revert changes AND the test file — the test is structurally wrong and
   should not be salvaged; the next implementation pass needs a different approach:
   ```bash
   git reset HEAD -- . && git checkout -- . && git clean -fd
   ```
   (`git clean -fd` intentionally removes the untracked test file here.)
   Before returning to the caller, produce a Coverage Diagnosis (see Phase 6.5) that explains:
   - What the test asserts and why that assertion passes even without the fix
   - What aspect of the bug the test missed (wrong entry point, wrong layer, assertion
     on a side effect rather than the cause, etc.)
   - What would need to change for the test to actually catch the regression
   Report this to the caller as an **Ineffective Test** (not a Production Bug — see Phase 6.5
   status `INEFFECTIVE`), attaching the Coverage Diagnosis so the next implementation pass
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

Run the test suite for the target module using the build system already in the project — Gradle (`./gradlew :module:test` or `:module:connectedAndroidTest` for instrumentation / Compose UI tests in `src/androidTest/`), SwiftPM (`swift test`, optionally `--filter <Suite>/<method>`), or Xcode (`xcodebuild test -scheme <Scheme> -destination ... -only-testing:<TestTarget>/<TestClass>/<testMethod>`). If both unit and UI / instrumentation tests were created, run both.

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
current branch. Normal Mode leaves file management to the user; Regression Mode commits and
pushes so the test lands on the PR branch automatically as part of the bugfix work.

```bash
git add <test-file-paths>
git commit -m "Add regression test: <scenario — subject line ≤72 chars total>"
git push
```

The commit message should name the bug scenario, not just say "add test" — it becomes part
of the permanent history explaining why this test exists.

---

## Phase 6: Report

Present a concise report covering:

- **6.1 Files created** — list of new test files with their paths and per-file test counts.
- **6.2 Coverage summary** — what is now tested that wasn't before; for partial coverage, list what was skipped and why.
- **6.3 Test results** — pass/fail counts; for failures after 3 fix attempts, name each failing test with a one-line reason.
- **6.4 Findings (production bugs)** — list real bugs the tests exposed (do NOT fix). Save to `swarm-report/<slug>-test-findings.md` only when production bugs are discovered. Schema:

```markdown
# Test Findings: {target description}

Date: {YYYY-MM-DD}
Target: {file/module path}

## Production Bugs Found

### 1. {short description}
- **Location:** {file:line}
- **Issue:** {what the code does wrong}
- **Expected:** {correct behavior}
- **Test:** {file:testName that exposed it}
- **Severity:** Critical / Major / Minor
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

Reference this file in the PR body.

---

## Constraints

- **Test plans are optional input** — this skill consumes test plans from
  `generate-test-plan` when they exist, but works independently without one.
- **No swarm-report artifact for tests** — the test files themselves are the artifact.
  Only create `swarm-report/<slug>-test-findings.md` if production bugs are found.

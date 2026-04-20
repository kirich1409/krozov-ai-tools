# Test Infrastructure Discovery

Reference for `write-tests` Phase 2 — see `../SKILL.md` for the skill entry point.

Use these tables while inspecting existing tests (3-5 samples if available) and build
configuration to produce the Test Infrastructure Summary that drives downstream code
generation. Generated tests must be indistinguishable from hand-written tests in the
project — do not introduce a new framework, assertion library, or mocking tool.

## Detect frameworks and libraries

| Category | What to detect | Where to look |
|----------|---------------|---------------|
| Test framework (Kotlin) | JUnit 4, JUnit 5, Kotest | `build.gradle(.kts)` dependencies, existing test imports |
| Test framework (Swift) | Swift Testing (`@Test` / `@Suite`), XCTest (`XCTestCase`), Quick | `Package.swift` dependencies, Xcode test targets, existing test imports |
| Assertion library | Truth, AssertJ, Kotest matchers, kotlin.test, `#expect`, `XCTAssert*`, Nimble matchers | Existing test imports and assertions |
| Mocking / test doubles | MockK, Mockito-Kotlin, manual fakes; protocol-backed fakes/stubs/spies in Swift | Existing test imports, `@MockK`, `mock()`, `Fake*`/`Stub*`/`Spy*` classes |
| Async testing | `kotlinx-coroutines-test` (`runTest`), Turbine; Swift `async` tests, `withCheckedContinuation`, `XCTestExpectation` | Existing test imports, build config |
| UI testing | Compose `createComposeRule`, `compose-ui-test`; ViewInspector, XCUITest, snapshot tests | Existing test imports, build config |
| DI in tests | Hilt test, Koin test, manual construction (both stacks) | Existing test setup patterns |

## Detect conventions

| Convention | What to detect | How |
|-----------|---------------|-----|
| Naming | `should verb`, `test verb`, backtick names, `given_when_then`, Swift Testing descriptive strings (`@Test("Empty cart shows zero total")`) | Read existing test function / `@Test` names |
| File placement | Kotlin: same package as source, or separate test package; Swift: `Tests/<Target>Tests/` (SwiftPM) or Xcode test target matching the module | Compare test file locations to source |
| Test class naming | `ClassNameTest`, `ClassNameSpec`, `ClassNameTests`; Swift `@Suite` structs or `XCTestCase` subclasses named `<Type>Tests` | Read existing test class / suite names |
| Setup pattern | `@Before`/`@BeforeEach`, `init {}`, builder/factory; Swift Testing `init` / `deinit`, XCTest `setUp` / `tearDown` | Read existing test setup blocks |
| Assertion style | Fluent (`assertThat(x).isEqualTo(y)`) vs plain (`assertEquals`); `#expect(...)` vs `XCTAssertEqual(...)` | Read existing assertions |

## Test Infrastructure Summary template

Compile findings into a structured summary that the code-generation agent consumes verbatim:

```
## Test Infrastructure Summary

**Platform:** {Kotlin/Android / Swift/iOS / Swift/macOS / KMP}
**Framework:** {JUnit 4 / JUnit 5 / Kotest / Swift Testing / XCTest / Quick}
**Assertions:** {Truth / AssertJ / Kotest matchers / kotlin.test / #expect / XCTAssert / Nimble}
**Test doubles:** {MockK / Mockito-Kotlin / manual fakes / protocol-backed fakes / stubs / spies / none}
**Async testing:** {runTest + Turbine / runTest / runBlocking / async tests / XCTestExpectation / none}
**UI testing:** {compose-ui-test / ViewInspector / XCUITest / snapshot / none}

**Naming convention:** {description — e.g., "backtick names with 'should' prefix", or "Swift Testing descriptive strings"}
**Class / suite naming:** {e.g., "ClassNameTest", "@Suite struct FooTests"}
**File placement:** {e.g., "same package in src/test/kotlin/", or "Tests/AuthTests/"}
**Setup pattern:** {e.g., "@Before with MockK annotations", or "Swift Testing init/deinit"}
**Assertion style:** {e.g., "Truth fluent assertions", or "#expect with descriptive tests"}

**Example test file:** {path to a representative existing test for reference}
```

Keep the section headings and field names stable — downstream prompts assume this structure.

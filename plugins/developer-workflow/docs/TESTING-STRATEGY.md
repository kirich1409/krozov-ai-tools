# Testing Strategy

The contract that ties together how `feature-flow` and `bugfix-flow` produce, audit, and maintain test coverage. Skills (`implement`, `write-tests`, `generate-test-plan`, `finalize`, `acceptance`, `check`) read from this document; engineer agents (`kotlin-engineer`, `swift-engineer`, `compose-developer`, `swiftui-developer`) follow it when picking frameworks and types.

## Position

**Single-phase: tests live inside Implement.** Engineer agents own production code AND its tests in the same stage. The pipeline does not have a separate "Lock-in tests" stage — that proposal was rejected for three reasons:

1. **Duplicates Implement.** Engineers already produce tests with code; a second pass either repeats or rewrites them.
2. **Fails the [min-bar checklist](ORCHESTRATION.md#min-bar-for-a-new-orchestrator-stage).** Coverage auditing is reachable through a Finalize Phase D conditional trigger (`test-coverage-expert`) — extension over a new stage.
3. **Breaks TDD-like feedback.** Engineers depend on fast test feedback during Implement; deferring tests to a later stage forces them to lean on the slow Acceptance loop.

Acceptance is not the source of truth for correctness — the source is `spec.md` / `<slug>-test-plan.md` / acceptance criteria. Tests written in Implement run against the same source, so consistency with Acceptance follows naturally; divergence is healed through the existing `Acceptance → Implement` backward edge.

## Test types

Picked per acceptance criterion using the [Selection heuristic](#selection-heuristic) below. The pyramid bias is real: many `unit`, fewer `integration`, fewer `ui-instrumentation`, occasional `ui-scenario` and `screenshot`, rare `e2e`.

| Type | Scope | Use when |
|---|---|---|
| **unit** | One class or function with mocked collaborators | Pure logic, domain rules, mappers, parsers, validators, state holders with mocked dependencies |
| **integration** | Several classes plus real or in-memory dependencies | Repositories + in-memory DB, services + test API, data pipelines |
| **ui-instrumentation** | Single UI component inside its framework | Compose UI tests (Android), XCUITest / ViewInspector (iOS) — one screen / component at a time |
| **ui-scenario** | Running app driven by `mobile` / `playwright` MCP | Re-runnable scripted journey (markdown / YAML) executed by an agent. Cross-platform, critical journeys. See the `ui-scenario` skill (#155). |
| **screenshot** | Visual render | Visual-regression coverage (Paparazzi, swift-snapshot-testing) — only where visual fidelity is part of the contract |
| **e2e / application** | Whole application | Release-critical user journeys (UIAutomator on Android, full XCUITest on iOS). Keep the count small. |

`ui-scenario` is distinct from one-shot Acceptance: Acceptance verifies a feature once against a spec; `ui-scenario` ships a reusable test artifact that can be re-run on demand or in CI.

## Selection heuristic

For every acceptance criterion, take the **smallest scope that catches a real failure of that criterion**, then climb only when needed.

| AC shape | Type |
|---|---|
| "Given X, when Y, then Z" — pure transform | `unit` |
| "Component A and B together yield Z" | `integration` |
| "User taps / sees / types on screen X" | `ui-instrumentation` |
| "Full journey across N screens" | `ui-scenario` (cheaper to maintain than `e2e`) |
| "Visual regression matters" | `screenshot` (additive, not a replacement) |
| "Release-critical end-to-end flow" | `e2e` (use sparingly) |

The `generate-test-plan` skill records the chosen `type` per test case (#153) so downstream stages and reviewers can see the rationale.

## Framework detection

The engineer agent picks the testing framework. Detection order:

1. **Build file evidence.** Inspect `build.gradle.kts`, `Package.swift`, `pom.xml`, `Cargo.toml`, etc. — existing test dependencies are the source of truth.
2. **Existing test files.** Read `src/test/`, `Tests/`, etc. — match the framework already in use.
3. **Same as existing tests.** If multiple frameworks coexist, follow the one used in the module being modified.
4. **Platform default.** Apply only when no signal exists in the project.

Platform defaults:

| Platform | Default |
|---|---|
| Android / Kotlin | JUnit 5 + MockK |
| Kotlin Multiplatform | `kotlin.test` |
| iOS / Swift | XCTest (or `swift-testing` when toolchain ≥ 5.9) |
| Compose UI | `androidx.compose.ui:ui-test-junit4` |
| SwiftUI | XCUITest or ViewInspector |

The `write-tests` skill documents the algorithm in detail (#156). Engineer agents (`kotlin-engineer`, `swift-engineer`, `compose-developer`, `swiftui-developer`) cross-reference that section.

## Coverage audit

`implement` is the producer. Audit happens later, conditionally:

- **Phase D `test-coverage-expert` trigger** in `finalize` (#152) — fires when the diff introduces new public APIs without matching tests, when `<slug>-test-plan.md` declares cases that have no corresponding test file, or when an explicit `--coverage-audit` override is set.
- **`/check` gate** in `implement` (#154) — a new public API in the diff with no matching test file fails `/check`. Engineer addresses it before exit; `--skip-test` is not a path. The trigger is keyed off the diff, not coverage percentage.

The orchestrators do not gate on a numerical coverage threshold. The criterion is "every acceptance criterion has a test that would catch its failure"; numbers are a side effect, not the contract.

## Skip rules

- **Trivial diff.** Single file, < 50 LOC, pure refactor with no new public API → no new tests required. The Phase D audit and `/check` gate both honour this.
- **`--skip-coverage-audit`** override on `finalize` Phase D — used only when the user has consciously accepted the trade-off; recorded in the finalize report.
- **No test infrastructure** in the affected module → short-circuit with a follow-up issue ("add test harness for X"), not silent skip.

## Author fixes broken tests (non-negotiable)

A change that breaks tests is fixed by the author of the change in the same PR. `/check` is the gate. There is no `--skip-test-fix`, no "TODO fix later", no "merge red". The only escape hatch is an explicit, justified skip-marker on a single test plus a follow-up issue — treated as an exception, not a routine.

This rule lives in `CLAUDE.md` (project) and is reinforced in `implement`, `finalize`, and `write-tests` SKILLs (#157).

## Cross-cutting child issues

Implementation of this strategy is split across:

- #152 — Finalize Phase D conditional `test-coverage-expert` trigger (engineer-agent based, no new agent role)
- #153 — `generate-test-plan` `type` field per TC + selection heuristic
- #154 — `/check` gate: new public API without matching test → not exit
- #155 — `ui-scenario` test type: format, directory convention, MCP runner, integration with `acceptance`
- #156 — `write-tests` framework detection documentation + engineer-agent cross-references
- #157 — Non-negotiable rule: author of breaking change fixes tests in the same PR

Each child PR cross-links to this document. The strategy is a contract; the children deliver the mechanics.

## Non-goals

- No automated CI runner for `ui-scenario` in the current scope — follow-up.
- No numerical coverage threshold — the contract is per-AC, not per-percentage.
- Acceptance is not replaced or downgraded — it remains the one-time manual / agent-driven verification at the end of the pipeline.

# developer-workflow

Claude Code plugin with skills for developer workflow habits — safe code migration, test plan generation, exploratory QA testing, feature verification, preparing branches for code review, and managing the full PR lifecycle.

## Skills

### `decompose-feature`

Breaks a feature idea, PRD, or epic into a structured task list with dependencies, acceptance criteria, complexity estimates, and implementation order:
- Accepts text, URLs, PRDs, or Figma links as input
- Launches parallel expert agents (codebase, architecture, business analyst) for context gathering
- Decomposes into tasks with IDs, dependencies, acceptance criteria, and complexity (S/M/L)
- Orders tasks into waves via topological sort by dependency graph
- Auto-reviews via business-analyst for completeness and scope creep
- Saves artifact to `swarm-report/<slug>-decomposition.md`

Use when breaking down a feature idea into implementable tasks before starting work.

### `implement-task`

Orchestrates the full development cycle for any implementation task:
- Creates an isolated worktree, timeboxes exploration, selects the best-matching sub-skill
- Brainstorms design for multi-file changes; follows TDD throughout
- Creates a draft PR early, runs quality loop (simplify + quality gates + `code-reviewer` agent), then marks the PR ready
- Delegates review comment handling to `address-review-feedback`

Explicit-only — invoke directly with `/developer-workflow:implement-task`.

### `create-pr`

Creates a pull request or merge request for the current branch:
- Auto-generates title from branch name and commit history
- Produces a structured description from the diff
- Selects labels from the repo's existing label set
- Suggests reviewers from recent git history on changed files
- Supports GitHub and GitLab, draft or ready-for-review

### `code-migration`

Guides safe, verified technology migrations in Gradle/Android/Kotlin/KMP projects:
- Discovers what needs migrating by reading the target (file, class, directory, or module)
- Chooses the right strategy: **in-place** (small, well-tested targets) or **parallel** (many callers, large scope, module restructuring)
- Snapshots current behavior before touching any code (tests / screenshots / API checklist)
- Migrates with green builds at every step
- Verifies nothing changed; presents visual diffs to user for approval
- Cleans up old technology: dead code, unused Gradle deps, stale imports

Examples: Java Date → Kotlin Date, XML layouts → Jetpack Compose, data binding → view binding, RxJava → coroutines.

Use when migrating code from one technology to another within an existing project.

### `pr-drive-to-merge`

Drives an existing PR/MR from its current state to a successful merge:
- Monitors CI/CD pipelines, investigates failures, and auto-fixes issues caused by PR changes
- Handles multi-round code review by delegating to `address-review-feedback`
- Undrafts the PR when CI passes, updates the branch when behind base
- Merges with user confirmation (squash + delete branch)
- Persists state for compaction resilience across long-running merge cycles

Use when a PR already exists and needs to be driven through CI, review, and merge.

### `address-review-feedback`

Handles reviewer comments on an existing PR/MR:
- Analyzes and categorizes all open review comments (BLOCKING / IMPORTANT / SUGGESTION / NIT / QUESTION / PRAISE / OUT_OF_SCOPE)
- Produces follow-up tasks for actionable comments; delegates code changes to implementation agents
- Responds to reviewers and resolves comment threads
- Asks user for decisions on out-of-scope or architectural concerns

Use after receiving reviewer feedback on a PR.

### `kmp-migration`

Guides a full migration of an Android module to Kotlin Multiplatform (KMP):
- Assesses the module, confirms target platforms, checks Kotlin version and module isolation
- Audits every dependency for KMP compatibility using `maven-mcp` tools
- Walks through plugin setup, source set restructuring, and dependency splitting
- Covers iOS framework exposure (CocoaPods, SPM, direct XCFramework)
- Verifies all targets compile and tests pass; cleans up Android-only artifacts

Use when migrating a module to share code with iOS, JVM, or other platforms.

### `generate-test-plan`

Creates a structured, reusable test plan from a specification source without executing any tests:
- Accepts Figma mockups, PRDs, acceptance criteria, issues, or existing code as input
- Identifies risk areas, edge cases, and state combinations
- Writes prioritized test cases (P0–P3) across Smoke / Feature / Regression tiers
- Cross-references multiple spec sources and flags discrepancies
- Produces a `docs/testplans/<feature>-test-plan.md` ready for `manual-tester` or `test-feature`

Use when planning testing separately from execution — for review, reuse, or handoff.

### `test-feature`

Verifies a running application against a specification:
- Accepts a spec (Figma, PRD, acceptance criteria) and/or a test plan
- Ensures the app is running on device/simulator/browser
- Launches the `manual-tester` agent for full QA execution
- Produces a verification result: VERIFIED, FAILED, or PARTIAL
- Supports re-verification loops after bug fixes

Use after implementing a feature to confirm it matches the spec before PR.

### `exploratory-test`

Undirected bug hunting on a running app — no spec or test plan required:
- Explores screens guided by usability heuristics, error handling checks, and input edge cases
- Reports bugs (standard format with severity) and observations (non-bug UX findings)
- Produces a coverage map showing which screens were visited and what was checked
- Scope-bounded by screen count: Quick (~5), Standard (~15), or Deep (30+)
- Recommends next steps based on severity of findings

Use for pre-release QA sweeps, sanity checks, or finding issues specs don't anticipate.

## Agents

### `manual-tester`

Performs manual-style QA testing of a running mobile or web application:
- Connects to a real device, simulator, or browser; handles authentication before testing begins
- Writes structured test cases (Smoke / Feature / Regression tiers) from a spec, mockup, or PRD
- Executes every step as a real tool call via `mobile` MCP tools (native apps) or `playwright` MCP tools (web)
- Reports bugs with severity, reproduction steps, and screenshot evidence
- Runs a lightweight accessibility pass alongside functional tests
- Produces a Test Execution Summary with a ship/no-ship recommendation
- Supports re-test loops: re-executes failed cases after fixes and marks them VERIFIED or STILL FAILING

Use when you need a running app validated against a spec — or just exploratory smoke-tested.

### `code-reviewer`

Independent code reviewer for Quality Loop gate 4 (semantic self-review):
- Receives only task description, plan, and git diff — never the implementation conversation
- Reviews 5 dimensions: semantic correctness, logic errors, basic security, code quality, consistency
- Produces structured output with PASS/WARN/FAIL verdict
- Recommends specialist agents (security, performance, architecture) when findings exceed scope
- Read-only — cannot modify code, only report issues

Use when running the quality loop before PR, or when independent code review is needed.

### `compose-developer`

Writes production-ready Jetpack Compose and Compose Multiplatform UI code:
- Implements screens from Figma mockups, screenshots, wireframes, or feature specs
- Discovers project Compose patterns (theme, state model, shared components) before writing code
- Follows modern best practices: Modifier.Node API, Slot API, stateless screen pattern, proper state hoisting
- Produces `@Preview` functions for every significant composable and distinct visual state
- Handles KMP targets — enforces `commonMain` import restrictions and Compose Multiplatform resource API
- Also used by the `migrate-to-compose` skill for View → Compose migration implementation

Use when you need Compose UI code written from a design, spec, or migration brief.

### `kotlin-engineer`

Writes production-ready Kotlin for Android and KMP client applications — business logic, data layer, and domain layer:
- Implements ViewModels, UseCases, Repositories, data sources, mappers, and DI wiring
- Discovers project architecture patterns (MVI, DI framework, error handling) before writing code
- Uses modern Kotlin: sealed interfaces, value classes, coroutines, Flow
- Follows Clean Architecture: domain models first, explicit layer boundaries, no DTOs in presentation
- Handles KMP targets — enforces `commonMain` import restrictions and `kotlinx.*` library choices
- Writes unit tests alongside implementation (fakes over mocks, Turbine for Flow testing)

Use when you need Kotlin feature code — everything except Compose UI (which goes to `compose-developer`).

## Installation

Via marketplace (recommended):

```
/plugin marketplace add kirich1409/krozov-ai-tools
/plugin install developer-workflow@krozov-ai-tools
```

Or locally from the repo root:

```bash
claude plugin install plugins/developer-workflow
```

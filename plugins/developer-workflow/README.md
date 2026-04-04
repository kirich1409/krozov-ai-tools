# developer-workflow

Claude Code plugin with skills for developer workflow habits — safe code migration, test plan generation, exploratory QA testing, feature verification, preparing branches for code review, and managing the full PR lifecycle.

## Skills

### `implement-task`

Orchestrates the full development cycle for any implementation task:
- Creates an isolated worktree, timeboxes exploration, selects the best-matching sub-skill
- Brainstorms design for multi-file changes; follows TDD throughout
- Creates a draft PR early, runs quality loop (`prepare-for-pr` + `code-review`), then marks the PR ready
- Delegates CI/CD monitoring and review to `pr-drive-to-merge`

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

### `prepare-for-pr`

Runs a quality loop over branch changes before creating a PR:
- Build → Simplify → Self-review → Lint/Tests
- Loops until only minor issues remain
- Fixes only what belongs to the current changes
- Asks the user when a problem is caused by something outside the current scope

Use after implementation is complete, before creating the PR.

### `pr-drive-to-merge`

Drives an existing PR/MR to merge:
- Monitors CI/CD checks; fixes failures caused by current changes
- Triages reviewer comments autonomously (BLOCKING/IMPORTANT → fix, OPTIONAL → acknowledge, OUT OF SCOPE → ask user)
- Responds to and resolves every comment thread
- Requests re-review after fixes, loops until merge requirements are met
- Asks the user only when a problem is outside the current PR scope

Use after the PR is created.

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

### `compose-ui-architect`

Writes production-ready Jetpack Compose and Compose Multiplatform UI code:
- Implements screens from Figma mockups, screenshots, wireframes, or feature specs
- Discovers project Compose patterns (theme, state model, shared components) before writing code
- Follows modern best practices: Modifier.Node API, Slot API, stateless screen pattern, proper state hoisting
- Produces `@Preview` functions for every significant composable and distinct visual state
- Handles KMP targets — enforces `commonMain` import restrictions and Compose Multiplatform resource API
- Also used by the `migrate-to-compose` skill for View → Compose migration implementation

Use when you need Compose UI code written from a design, spec, or migration brief.

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

# developer-workflow

Claude Code plugin with skills for developer workflow habits — safe code migration, preparing branches for code review, and managing the full PR lifecycle.

## Skills

### `code-migration`

Guides safe, verified technology migrations in Gradle/Android/Kotlin/KMP projects:
- Discovers what needs migrating by reading the target (file, class, directory, or module)
- Chooses the right strategy: **in-place** (small, well-tested targets) or **parallel** (many callers, large scope, module restructuring)
- Snapshots current behavior before touching any code (tests / screenshots / API checklist)
- Migrates with green builds at every step
- Verifies nothing changed; presents visual diffs to user for approval
- Cleans up old technology: dead code, unused Gradle deps, stale imports

Examples: Java Date → Kotlin Date, XML layouts → Jetpack Compose, data binding → view binding, Android → Kotlin Multiplatform.

Use when migrating any code from one technology to another.

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

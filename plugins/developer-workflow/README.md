# developer-workflow

Claude Code plugin with skills for developer workflow habits — preparing branches for code review and managing the full PR lifecycle.

## Skills

### `prepare-for-pr`

Runs a quality loop over branch changes before creating a PR:
- Build → Simplify → Self-review → Lint/Tests
- Loops until only minor issues remain
- Fixes only what belongs to the current changes
- Asks the user when a problem is caused by something outside the current scope

Use after implementation is complete, before creating the PR.

### `pr-lifecycle`

Drives an existing PR/MR to merge:
- Monitors CI/CD checks; fixes failures caused by current changes
- Triages reviewer comments autonomously (BLOCKING/IMPORTANT → fix, OPTIONAL → acknowledge, OUT OF SCOPE → ask user)
- Responds to and resolves every comment thread
- Requests re-review after fixes, loops until merge requirements are met
- Asks the user only when a problem is outside the current PR scope

Use after the PR is created.

## Installation

```bash
claude plugin install plugins/developer-workflow
```

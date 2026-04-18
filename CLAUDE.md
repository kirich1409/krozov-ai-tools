# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Monorepo for Claude Code plugins by krozov. Contains six plugins:

| Plugin | Directory | Description |
|--------|-----------|-------------|
| maven-mcp | `plugins/maven-mcp/` | MCP server for Maven dependency intelligence |
| sensitive-guard | `plugins/sensitive-guard/` | Scans files for secrets and PII before they reach AI servers |
| developer-workflow | `plugins/developer-workflow/` | Lifecycle pipeline — research, decomposition, spec, plan review, test planning, implementation, debugging, QA, PR workflow |
| developer-workflow-experts | `plugins/developer-workflow-experts/` | 9 reusable review/consult agents (code-reviewer, architecture-expert, security-expert, …) — safe standalone |
| developer-workflow-kotlin | `plugins/developer-workflow-kotlin/` | Kotlin/Android/KMP specialists and migration skills |
| developer-workflow-swift | `plugins/developer-workflow-swift/` | Swift/iOS/macOS specialists and Swift/SwiftUI references |

## Structure

```
plugins/
  maven-mcp/                    # TypeScript, npm package @krozov/maven-central-mcp
  sensitive-guard/              # Shell-based Claude Code plugin
  developer-workflow/           # Lifecycle skills + manual-tester agent
  developer-workflow-experts/   # 9 reusable expert agents (library)
  developer-workflow-kotlin/    # Kotlin/Android/KMP specialists and migrations
  developer-workflow-swift/     # Swift/iOS specialists and references
```

The `developer-workflow-*` plugins form a family connected through `dependencies` in plugin.json: core depends on `-experts`; `-kotlin` and `-swift` depend on core and `-experts`. Installing any of them automatically pulls the rest of the chain.

See each plugin's own `CLAUDE.md` for plugin-specific instructions.

## Plugin Standards

All plugins must comply with [`docs/PLUGIN-STANDARDS.md`](docs/PLUGIN-STANDARDS.md). Before every release:

1. Run `bash scripts/validate.sh` — must be green
2. Run `plugin-dev:plugin-validator` agent on each plugin listed in `.claude-plugin/marketplace.json` — must be PASS or only Minor findings
3. Go through the pre-release checklist in `docs/PLUGIN-STANDARDS.md` section 10

Any Critical or Major violations block the release — fix first, release later.

## PR Workflow

Always work on changes in a separate branch using a worktree (`.worktrees/`). Create a **draft PR** early and push changes as you go. When implementation is complete: run checks locally (build, test, lint), fix any issues, then mark the PR as ready for review. After that, wait for CI checks to pass and review comments. Fix any failures or address reviewer feedback — do everything needed to get the PR merged. Ask the user if something is unclear or requires a decision.

## Publishing

**Never run `npm publish` locally.** Publishing happens exclusively via GitHub Actions.

Each plugin versions independently, managed via [Changesets](https://github.com/changesets/changesets). Workspace `package.json` files in each plugin directory are the source of truth for Changesets; `scripts/changesets-version.mjs` mirrors the bumps into `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`. Contributor instructions live in [`.changeset/README.md`](.changeset/README.md).

Release flow:

1. **Contributor** — when a PR touches `plugins/*`, run `npx changeset` and pick the affected plugins + bump kind. Use `npx changeset --empty` for docs/CI-only PRs that don't ship anything. Commit the generated `.changeset/<id>.md`.
2. **Merge** the PR to `main`. The `Release` workflow runs and either:
   - Opens (or updates) a **Version Packages** PR that contains the version bumps + CHANGELOG updates, or
   - If no `.changeset/*.md` content files are present, runs the publish script (idempotent — no-op when nothing was bumped).
3. **Reviewer** — review and merge the Version Packages PR. This is the human gate before any release artifact ships.
4. **CI** — the next workflow run sees no pending changesets, runs `scripts/changesets-publish.mjs`: publishes `@krozov/maven-central-mcp` to npm if its version changed, then creates one per-plugin tag `{plugin-name}--v{version}` for each plugin in `marketplace.json` (idempotent — existing tags are skipped). These per-plugin tags are what Claude Code uses to resolve `dependencies` semver ranges between plugins in the `developer-workflow*` family.

Internal `dependencies` semver ranges in each `developer-workflow-*` `plugin.json` are rewritten by `scripts/changesets-version.mjs` to `^MAJOR.MINOR.0` of the dependency's new version — no manual bookkeeping required.

## Worktrees

Worktree directory: `.worktrees/` (gitignored). Clean up stale worktrees after merging feature branches.

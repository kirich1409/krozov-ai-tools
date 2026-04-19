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
2. Run `plugin-dev:plugin-validator` agent on each of the 6 plugins listed in `.claude-plugin/marketplace.json` — must be PASS or only Minor findings
3. Go through the pre-release checklist in `docs/PLUGIN-STANDARDS.md` section 10

Any Critical or Major violations block the release — fix first, release later.

## PR Workflow

Always work on changes in a separate branch using a worktree (`.worktrees/`). Create a **draft PR** early and push changes as you go. When implementation is complete: run checks locally (build, test, lint), fix any issues, then mark the PR as ready for review. After that, wait for CI checks to pass and review comments. Fix any failures or address reviewer feedback — do everything needed to get the PR merged. Ask the user if something is unclear or requires a decision.

## Publishing

**Never run `npm publish` locally.** Releases happen exclusively via GitHub Actions.

Each plugin versions independently. To release:

1. GitHub → **Actions** → **Release** workflow → **Run workflow**.
2. Pick the plugin, bump type (patch/minor/major), and whether to cascade patch-bumps to family dependents (`developer-workflow*` family only — defaults on).
3. The workflow bumps `plugin.json` + `marketplace.json` (+ `package.json` for `maven-mcp`), commits, creates per-plugin tag `{plugin-name}--v{version}`, publishes `@krozov/maven-central-mcp` to npm if releasing `maven-mcp`, and creates a GitHub Release.

Pre-release checklist in [`docs/PLUGIN-STANDARDS.md`](docs/PLUGIN-STANDARDS.md) §10 stays manual (run `plugin-dev:plugin-validator` on each plugin before clicking Run).

## Worktrees

Worktree directory: `.worktrees/` (gitignored). Clean up stale worktrees after merging feature branches.

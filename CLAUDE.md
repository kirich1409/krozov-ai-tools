# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Monorepo for Claude Code plugins by krozov. Contains seven plugins:

| Plugin | Directory | Description |
|--------|-----------|-------------|
| maven-mcp | `plugins/maven-mcp/` | MCP server for Maven dependency intelligence |
| sensitive-guard | `plugins/sensitive-guard/` | Scans files for secrets and PII before they reach AI servers |
| developer-workflow | `plugins/developer-workflow/` | Lifecycle pipeline — research, decomposition, spec, plan review, implementation, debugging, QA, PR workflow |
| developer-workflow-experts | `plugins/developer-workflow-experts/` | 9 reusable review/consult agents (code-reviewer, architecture-expert, security-expert, …) — safe standalone |
| developer-workflow-kotlin | `plugins/developer-workflow-kotlin/` | Kotlin/Android/KMP specialists and migration skills |
| developer-workflow-swift | `plugins/developer-workflow-swift/` | Swift/iOS/macOS specialists and Swift/SwiftUI references |
| extend | `plugins/extend/` | Extend Claude Code built-in features: agent review, skill optimization, configuration audit |

## Structure

```
plugins/
  maven-mcp/                    # TypeScript, npm package @krozov/maven-central-mcp
  sensitive-guard/              # Shell-based Claude Code plugin
  developer-workflow/           # Lifecycle skills + manual-tester agent
  developer-workflow-experts/   # 9 reusable expert agents (library)
  developer-workflow-kotlin/    # Kotlin/Android/KMP specialists and migrations
  developer-workflow-swift/     # Swift/iOS specialists and references
  extend/                       # Meta-tools for improving Claude Code setup
```

The `developer-workflow-*` plugins form a family connected through `dependencies` in plugin.json: core depends on `-experts`; `-kotlin` and `-swift` depend on core and `-experts`. Installing any of them automatically pulls the rest of the chain.

See each plugin's own `CLAUDE.md` for plugin-specific instructions.

## Plugin Standards

All plugins must comply with [`docs/PLUGIN-STANDARDS.md`](docs/PLUGIN-STANDARDS.md). Before every release:

1. Run `bash validate.sh` — must be green
2. Run `plugin-dev:plugin-validator` agent on each of the 4 plugins — must be PASS or only Minor findings
3. Go through the pre-release checklist in `docs/PLUGIN-STANDARDS.md` section 10

Any Critical or Major violations block the release — fix first, release later.

## PR Workflow

Always work on changes in a separate branch using a worktree (`.worktrees/`). Create a **draft PR** early and push changes as you go. When implementation is complete: run checks locally (build, test, lint), fix any issues, then mark the PR as ready for review. After that, wait for CI checks to pass and review comments. Fix any failures or address reviewer feedback — do everything needed to get the PR merged. Ask the user if something is unclear or requires a decision.

## Publishing

**Never run `npm publish` locally.** Publishing happens exclusively via GitHub Actions.

All plugins use **unified versioning** — every release bumps all plugins to the same version.

To release a new version:
1. Bump `version` in all of these files to the new version:
   - `plugins/maven-mcp/package.json`
   - `plugins/maven-mcp/plugin/.claude-plugin/plugin.json`
   - `plugins/sensitive-guard/.claude-plugin/plugin.json`
   - `plugins/developer-workflow/.claude-plugin/plugin.json`
   - `plugins/developer-workflow-experts/.claude-plugin/plugin.json`
   - `plugins/developer-workflow-kotlin/.claude-plugin/plugin.json`
   - `plugins/developer-workflow-swift/.claude-plugin/plugin.json`
   - `plugins/extend/.claude-plugin/plugin.json`
   - `.claude-plugin/marketplace.json` (all 7 plugin entries)
2. Inside the `developer-workflow-*` family, also bump the semver ranges in each `dependencies` array if the range needs to widen (usually `^MAJOR.MINOR.0` is stable).
3. Merge to `main`.
4. Push a git tag matching the version: `git tag v0.9.0 && git push origin v0.9.0`.
5. GitHub Actions (`.github/workflows/release.yml`) triggers on `v*` tags: verifies all versions match, runs lint/tests/build, publishes to npm, **then creates one per-plugin tag `{plugin-name}--v{version}` for each plugin in `marketplace.json`**. These per-plugin tags are what Claude Code uses to resolve `dependencies` semver ranges.

## Worktrees

Worktree directory: `.worktrees/` (gitignored). Clean up stale worktrees after merging feature branches.

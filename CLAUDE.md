# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Monorepo for Claude Code plugins by krozov. Contains four plugins:

| Plugin | Directory | Description |
|--------|-----------|-------------|
| maven-mcp | `plugins/maven-mcp/` | MCP server for Maven dependency intelligence |
| sensitive-guard | `plugins/sensitive-guard/` | Scans files for secrets and PII before they reach AI servers |
| developer-workflow | `plugins/developer-workflow/` | Full dev workflow pipeline — task decomposition, research, implementation, code review, QA testing, PR lifecycle |
| extend | `plugins/extend/` | Extend Claude Code built-in features: agent review, skill optimization, configuration audit |

## Structure

```
plugins/
  maven-mcp/           # TypeScript, npm package @krozov/maven-central-mcp
  sensitive-guard/      # Shell-based Claude Code plugin
  developer-workflow/   # Skills + agents for the full development lifecycle
  extend/               # Meta-tools for improving Claude Code setup
```

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
   - `plugins/extend/.claude-plugin/plugin.json`
   - `.claude-plugin/marketplace.json` (all plugin entries)
2. Merge to `main`
3. Push a git tag matching the version: `git tag v0.5.0 && git push origin v0.5.0`
4. GitHub Actions (`.github/workflows/release.yml`) triggers on `v*` tags, verifies all versions match the tag, runs lint/tests/build, then publishes to npm

## Worktrees

Worktree directory: `.worktrees/` (gitignored). Clean up stale worktrees after merging feature branches.

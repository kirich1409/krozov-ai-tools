# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Monorepo for Claude Code plugins by krozov. Contains three plugins:

| Plugin | Directory | Description |
|--------|-----------|-------------|
| maven-mcp | `plugins/maven-mcp/` | MCP server for Maven dependency intelligence |
| sensitive-guard | `plugins/sensitive-guard/` | Scans files for secrets and PII before they reach AI servers |
| developer-workflow | `plugins/developer-workflow/` | Skills for developer workflow — code migration, PR preparation and lifecycle |

## Structure

```
plugins/
  maven-mcp/           # TypeScript, npm package @krozov/maven-central-mcp
  sensitive-guard/      # Shell-based Claude Code plugin
  developer-workflow/   # Skills-only plugin for developer workflow habits
```

See each plugin's own `CLAUDE.md` for plugin-specific instructions.

## PR Workflow

Always work on changes in a separate branch using a worktree (`.worktrees/`). Create a **draft PR** early and push changes as you go. When implementation is complete: run checks locally (build, test, lint), fix any issues, then mark the PR as ready for review. After that, wait for CI checks to pass and review comments. Fix any failures or address reviewer feedback — do everything needed to get the PR merged. Ask the user if something is unclear or requires a decision.

## Publishing

**Never run `npm publish` locally.** Publishing happens exclusively via GitHub Actions.

To release a new version of `@krozov/maven-central-mcp`:
1. Bump `version` in `plugins/maven-mcp/package.json` and `plugins/maven-mcp/plugin/.claude-plugin/plugin.json`
2. Merge to `main`
3. Push a git tag matching the version: `git tag v0.4.0 && git push origin v0.4.0`
4. GitHub Actions (`.github/workflows/release.yml`) triggers on `v*` tags, runs lint/tests/build, then publishes to npm

The workflow verifies that the tag matches `package.json` version before publishing.

## Worktrees

Worktree directory: `.worktrees/` (gitignored). Clean up stale worktrees after merging feature branches.

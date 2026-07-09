# AGENTS.md

Instructions for AI coding agents (Cursor Agent and others) working in this repository.

## Non-negotiables

Rules that are not open for discussion. Violating these is an error, not a judgment call.

- **Never run `npm publish` locally.** Publishing is exclusively via GitHub Actions — prevents partial releases and version skew.
- **All 3 version locations must stay in sync.** A version bump touches `plugin.json`, `marketplace.json`, and the bundled server `server.py` (`SERVER_VERSION` + `USER_AGENT`) simultaneously — see Publishing for the list.
- **Critical or Major violations of PLUGIN-STANDARDS.md block the release.** Fix first, release later.
- **All extension content is written in English.** Skills (`SKILL.md`, references, evals), agents (`agents/*.md`), hooks, MCP servers, plugin manifests (`plugin.json`, `marketplace.json`), and any prompt/instruction text shipped inside `plugins/` must be in English. User-facing chat in any language is fine; the shipped extension content itself targets an international audience and must not contain non-English prose. Code identifiers and external API field names keep their original form regardless of language. **Excluded:** repository documentation under `docs/` and top-level `README.md` — these are maintainer-facing and may be in any language. Do not "fix" them to English.

## Project

Monorepo for Claude Code plugins by krozov. Contains one plugin:

| Plugin | Directory | Description |
|--------|-----------|-------------|
| maven-mcp | `plugins/maven-mcp/` | MCP server for Maven dependency intelligence |

## Structure

```
plugins/
  maven-mcp/                    # Python MCP server (stdlib only, zero pip deps)
```

See the plugin's own `AGENTS.md` for plugin-specific instructions.

## Plugin Standards

All plugins must comply with [`docs/PLUGIN-STANDARDS.md`](docs/PLUGIN-STANDARDS.md). Before every release:

1. Run `bash scripts/validate.sh` — must be green
2. Validate each plugin listed in `.claude-plugin/marketplace.json` (currently maven-mcp) against PLUGIN-STANDARDS.md — must be PASS or only Minor findings. Claude Code users: run the `plugin-dev:plugin-validator` agent.
3. Go through the pre-release checklist in `docs/PLUGIN-STANDARDS.md` section 10

Any Critical or Major violations block the release — fix first, release later.

## PR Workflow

Always work on changes in a separate branch using a worktree (`.worktrees/`). Create a **draft PR** early and push changes as you go. When implementation is complete: run checks locally (build, test, lint), fix any issues, then mark the PR as ready for review. After that, wait for CI checks to pass and review comments. Fix any failures or address reviewer feedback — do everything needed to get the PR merged. Ask the user if something is unclear or requires a decision.

## Publishing

All plugins use **unified versioning** — every release bumps all plugins to the same version.

To release a new version:
1. Bump the version in all three of these locations to the new version:
   - `plugins/maven-mcp/plugin/.claude-plugin/plugin.json` (`version`)
   - `.claude-plugin/marketplace.json` (`version`)
   - `plugins/maven-mcp/plugin/server/server.py` (`SERVER_VERSION` and `USER_AGENT`)
2. Merge to `main`.
3. Push a git tag matching the version: `git tag v0.9.0 && git push origin v0.9.0`.
4. GitHub Actions (`.github/workflows/release.yml`) triggers on `v*` tags: verifies all versions match the tag (`validate.sh --check-tag`), runs the Python test suite, **then creates one per-plugin tag `{plugin-name}--v{version}` for each plugin in `marketplace.json`**. These per-plugin tags are what Claude Code uses to resolve `dependencies` semver ranges.

## Worktrees

Worktree directory: `.worktrees/` (gitignored). Clean up stale worktrees after merging feature branches.

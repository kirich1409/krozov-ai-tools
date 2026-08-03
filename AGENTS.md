# AGENTS.md

Instructions for AI coding agents (Cursor Agent and others) working in this repository.

## Non-negotiables

Rules that are not open for discussion. Violating these is an error, not a judgment call.

- **Never run `npm publish` locally.** Publishing is exclusively via GitHub Actions — prevents partial releases and version skew.
- **All 3 version locations of a plugin must stay in sync.** Each plugin carries its version in three places, and a bump touches all three of *that plugin* simultaneously — the other plugin is not touched. See Publishing for the per-plugin list.
- **Critical or Major violations of PLUGIN-STANDARDS.md block the release.** Fix first, release later.
- **All extension content is written in English.** Skills (`SKILL.md`, references, evals), agents (`agents/*.md`), hooks, MCP servers, plugin manifests (`plugin.json`, `marketplace.json`), and any prompt/instruction text shipped inside `plugins/` must be in English. User-facing chat in any language is fine; the shipped extension content itself targets an international audience and must not contain non-English prose. Code identifiers and external API field names keep their original form regardless of language. **Excluded:** repository documentation under `docs/` and top-level `README.md` — these are maintainer-facing and may be in any language. Do not "fix" them to English.

## Project

Monorepo for Claude Code plugins by krozov. Contains two plugins:

| Plugin | Directory | Description |
|--------|-----------|-------------|
| maven-mcp | `plugins/maven-mcp/` | MCP server for Maven dependency intelligence |
| youtube-transcript | `plugins/youtube-transcript/` | MCP server that fetches existing YouTube subtitles via the InnerTube API |

## Structure

```
plugins/
  maven-mcp/                    # Python MCP server (stdlib only, zero pip deps)
  youtube-transcript/           # Python MCP server (stdlib only, zero pip deps)
```

See the plugin's own `AGENTS.md` for plugin-specific instructions.

## Plugin Standards

All plugins must comply with [`docs/PLUGIN-STANDARDS.md`](docs/PLUGIN-STANDARDS.md). Before every release:

1. Run `bash scripts/validate.sh` — must be green
2. Validate each plugin listed in `.claude-plugin/marketplace.json` (currently maven-mcp, youtube-transcript) against PLUGIN-STANDARDS.md — must be PASS or only Minor findings. Claude Code users: run the `plugin-dev:plugin-validator` agent.
3. Go through the pre-release checklist in `docs/PLUGIN-STANDARDS.md` section 10

Any Critical or Major violations block the release — fix first, release later.

## PR Workflow

Always work on changes in a separate branch using a worktree (`.worktrees/`). Create a **draft PR** early and push changes as you go. When implementation is complete: run checks locally (build, test, lint), fix any issues, then mark the PR as ready for review. After that, wait for CI checks to pass and review comments. Fix any failures or address reviewer feedback — do everything needed to get the PR merged. Ask the user if something is unclear or requires a decision.

## Publishing

**Plugin versions are independent.** Each plugin moves on its own version line; a release does not drag the others along.

Each plugin's version lives in three places:

| Plugin | Locations |
|--------|-----------|
| maven-mcp | `plugins/maven-mcp/plugin/.claude-plugin/plugin.json` (`version`), `.claude-plugin/marketplace.json` (its entry's `version`), `plugins/maven-mcp/plugin/server/server.py` (`SERVER_VERSION`, `USER_AGENT` derives from it) |
| youtube-transcript | `plugins/youtube-transcript/plugin/.claude-plugin/plugin.json` (`version`), `.claude-plugin/marketplace.json` (its entry's `version`), `plugins/youtube-transcript/plugin/server/server.py` (`SERVER_VERSION`, `USER_AGENT` derives from it) |

To release:
1. Bump all three locations of the plugin(s) you are releasing to the new version. Plugins that are not being released keep their current version.
2. Merge to `main`.
3. Push a git tag matching that version: `git tag v0.9.0 && git push origin v0.9.0`.
4. GitHub Actions (`.github/workflows/release.yml`) triggers on `v*` tags. **Tag `vX.Y.Z` releases exactly the plugins whose version is `X.Y.Z`**: `validate.sh --check-tag` verifies those plugins' three locations and logs a `SKIP:` line for every plugin on another version (a tag matching no plugin at all is an error), the Python suites of all plugins run, and a per-plugin tag `{plugin-name}--v{version}` is created **only for the released plugins**. Those per-plugin tags are what Claude Code uses to resolve `dependencies` semver ranges.

Consequence: two plugins can only be released under the same tag when they happen to stand on the same version. Making the per-plugin tag (`youtube-transcript--v0.1.0`) the release trigger itself is the next step; it is deferred until the `workflow_dispatch` dry-run exists, because that path cannot be tested before a tag is pushed.

## Worktrees

Worktree directory: `.worktrees/` (gitignored). Clean up stale worktrees after merging feature branches.

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

**The release trigger is the per-plugin tag `<plugin>--v<version>`.** A unified `vX.Y.Z` tag releases nothing: `.github/workflows/release.yml` triggers on `*--v*` only, and `.github/workflows/legacy-tag-guard.yml` makes a `v*` push fail loudly instead of silently doing nothing. Historical `v*` tags stay as history.

To release one plugin:
1. Bump all three locations of that plugin to the new version. The other plugin is not touched.
2. Merge to `main`. `gate` refuses a tag whose commit is not reachable from `origin/main`.
3. Tag that commit and push the tag:
   ```
   git tag -a youtube-transcript--v0.2.0 -m "Release youtube-transcript 0.2.0"
   git push origin youtube-transcript--v0.2.0
   ```
   The name must match `^[a-z0-9-]+--v[0-9]+\.[0-9]+\.[0-9]+$` and the plugin must be listed in `.claude-plugin/marketplace.json`; anything else fails in `gate`.
4. `release.yml` then runs four jobs:
   - **gate** — resolves plugin and version from the tag, verifies the tagged commit is reachable from `origin/main`, runs `validate.sh --check-tag <tag>` (asserting *that* plugin's three locations) and plain `validate.sh`, and runs every plugin's Python suite on 3.9.
   - **pack** — only when `plugins/<plugin>/mcpb/manifest.template.json` exists; installs the pinned mcpb toolchain, runs the npm audit gate, builds the `.mcpb`, smoke-tests it, and exports its SHA-256 as a job output.
   - **attest** — push events only; re-checks the downloaded bytes against `pack`'s checksum, then mints build provenance (`actions/attest`) *before* anything is published.
   - **publish** — re-checks the bytes, then creates the GitHub Release titled `<plugin> <version>` with the `.mcpb` and `.mcpb.sha256` attached. A plugin without a bundle still gets a release, with no assets.

That per-plugin tag is also what Claude Code resolves plugin `dependencies` semver ranges through, so it must never be moved or deleted after publication — a repository ruleset over `*--v*` forbids deletion and non-fast-forward updates. A botched release is recovered with a new patch version, not by re-pointing the tag (see `docs/PLUGIN-STANDARDS.md` §12).

`workflow_dispatch` on `release.yml` is **always** a dry run: it runs `gate` and `pack` for the chosen plugin and can neither attest nor publish (there is deliberately no `dry_run` input). Use it before the first tag under a changed workflow.

Scope of the ancestry check, stated honestly: it guards against a maintainer tagging an unreviewed commit by accident, not against a party with push access — the workflow that runs for a tag is the workflow *at the tagged commit*. It is not a security boundary.

## Worktrees

Worktree directory: `.worktrees/` (gitignored). Clean up stale worktrees after merging feature branches.

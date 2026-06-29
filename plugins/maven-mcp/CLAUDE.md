# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in `plugins/maven-mcp/`.

## Non-negotiables

Rules that are not open for discussion. Violating these is an error, not a judgment call.

- **No XML parser dependency.** All XML parsing is regex-based — avoids a heavyweight dependency for the small subset of XML used in Maven metadata and POM files.

## Project

MCP server for Maven dependency intelligence. Provides tools to query artifact versions from Maven repositories (Maven Central, Google Maven, Gradle Plugin Portal).

**Implementation:** `plugin/server/server.py` — a single-file Python 3 server (stdlib only, zero pip dependencies). It speaks MCP over stdio (JSON-RPC 2.0 on stdin/stdout) and is registered via `plugin/.claude-plugin/plugin.json` as `command: python3`. Works in Claude cloud and local environments without Node.js or npm.

**Stack:** Python 3.9+ standard library only (`urllib`, `json`, `re`, `typing`). No build step, no install step.

## Commands

All commands run from the repository root.

```bash
python3 -m unittest discover -s plugins/maven-mcp/tests       # Run all tests
python3 -m unittest discover -s plugins/maven-mcp/tests -v    # Verbose
python3 -m compileall plugins/maven-mcp/plugin/server         # Zero-dep syntax gate
```

Run a single test module:

```bash
python3 -m unittest discover -s plugins/maven-mcp/tests -p test_handlers.py
```

## Architecture

`server.py` is one file organised into logical sections (no package tree):

- **Constants & routing** — `MAVEN_CENTRAL_URL`, `GOOGLE_MAVEN_URL`, `GRADLE_PLUGIN_PORTAL_URL`, `GOOGLE_MAVEN_GROUPS`. `_repos_for(group_id, artifact_id)` returns the candidate repos for an artifact by **static group-prefix routing** (most-specific first): Gradle Plugin Portal for plugin markers, Google Maven for the AndroidX/Google group prefixes, Maven Central always as fallback.
- **HTTP** — `http_get` / `http_post_json` over `urllib.request.urlopen`; both return `(status, bytes)` and map `urllib.error.HTTPError → (code, b"")`. Single attempt — no retry/backoff.
- **Versioning** — `classify_version` (stability detection), `compare_versions`, `find_latest_version` / `find_latest_version_for_current` (selection), plus `_parse_segments` / `_extract_prerelease_numbers`.
- **Metadata & POM** — `fetch_metadata`, `check_version_in_repos`, `fetch_pom`, `_parse_metadata_xml` (regex).
- **Project scanning** (local, no network) — `_detect_build_system` + parsers: `_parse_gradle_deps`, `_parse_gradle_plugins_block`, `_parse_buildscript_classpath`, `_parse_settings_modules`, `_parse_settings_catalogs`, `_parse_maven_deps`, `_parse_maven_modules`, `_parse_toml_catalog`; orchestrated by `scan_project`.
- **GitHub & changelog** — `gh_repo_exists` / `gh_fetch_repo` / `gh_fetch_releases` / `gh_fetch_user` / `gh_fetch_issue_stats`, `discover_github_repo` (POM SCM → groupId guess), and `_get_dependency_changes_impl` + `_filter_version_range` (GitHub releases only).
- **Vulnerabilities** — OSV.dev batch query (`api.osv.dev/v1/querybatch`).
- **Tool handlers** — `handle_*`, one per MCP tool, plus the stdio JSON-RPC dispatch loop.

**Tools:** `get_latest_version`, `check_version_exists`, `check_multiple_dependencies`, `compare_dependency_versions`, `get_dependency_changes`, `scan_project_dependencies`, `get_dependency_vulnerabilities`, `get_dependency_health`, `search_artifacts`, `audit_project_dependencies`.

**Repository resolution:** `fetch_metadata` returns the metadata of the **first** repo in `_repos_for` that responds successfully — first-hit, no cross-repo merge. Routing is static group-prefix only; the server does **not** parse build files for custom/private repositories (`maven { url = ... }`), so version answers for projects relying on custom repos can be incomplete.

## Environment

- `GITHUB_TOKEN` — optional, enables higher GitHub API rate limits (5000 req/h vs 60) for `get_dependency_changes` and `get_dependency_health` (the health tool also uses the rate-limited Search API for issue stats).
- No persistent cache. Memoization is in-memory per call only (e.g. the `metadata_cache` dict inside `audit_project_dependencies` dedupes lookups within a single audit run); nothing is written to disk.

## Conventions

- No XML parser dependency — all XML parsing is regex-based.
- Network seam is `urllib.request.urlopen`; tests mock it with `unittest.mock.patch("urllib.request.urlopen", ...)`.
- Tests live dev-only at `plugins/maven-mcp/tests/` (outside `plugin/`, so they are not shipped). They import `server` via a `__file__`-resolved `sys.path` shim in `tests/_helpers.py`; filesystem-touching parsers are exercised against real files written into a `TemporaryDirectory`.
- Version constants (`SERVER_VERSION`, `USER_AGENT`) in `server.py` are part of the 3 version locations that must stay in sync on a release; `scripts/validate.sh --check-tag` enforces this.
- `import server` is side-effect-free (the `if __name__ == "__main__": main()` guard at the tail).

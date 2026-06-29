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

- **Constants & routing** — `MAVEN_CENTRAL_URL`, `GOOGLE_MAVEN_URL`, `GRADLE_PLUGIN_PORTAL_URL`, `GOOGLE_MAVEN_GROUPS`. `_public_repos(group_id, artifact_id)` is the **static well-known routing** (most-specific first): Gradle Plugin Portal for plugin markers, Google Maven for the AndroidX/Google group prefixes, Maven Central always last. This is only the **public fallback** — the live entry point is `_repos_for(group_id, artifact_id, ctx)`, which is project-first (see *Repository resolution* below).
- **HTTP** — `http_get` / `http_post_json` over `urllib.request.urlopen`; both return `(status, bytes)` and map `urllib.error.HTTPError → (code, b"")`. Single attempt — no retry/backoff.
- **Versioning** — `classify_version` (stability detection), `compare_versions`, `find_latest_version` / `find_latest_version_for_current` (selection), plus `_parse_segments` / `_extract_prerelease_numbers`.
- **Metadata & POM** — `fetch_metadata`, `check_version_in_repos`, `fetch_pom`, `_parse_metadata_xml` (regex).
- **Project scanning** (local, no network) — `_detect_build_system` + parsers: `_parse_gradle_deps`, `_parse_gradle_plugins_block`, `_parse_buildscript_classpath`, `_parse_settings_modules`, `_parse_settings_catalogs`, `_parse_maven_deps`, `_parse_maven_modules`, `_parse_toml_catalog`; orchestrated by `scan_project`.
- **GitHub & changelog** — `gh_repo_exists` / `gh_fetch_repo` / `gh_fetch_releases` / `gh_fetch_user` / `gh_fetch_issue_stats`, `discover_github_repo` (POM SCM → groupId guess), and `_get_dependency_changes_impl` + `_filter_version_range` (GitHub releases only).
- **Vulnerabilities** — OSV.dev batch query (`api.osv.dev/v1/querybatch`).
- **Tool handlers** — `handle_*`, one per MCP tool, plus the stdio JSON-RPC dispatch loop.

**Tools:** `get_latest_version`, `check_version_exists`, `check_multiple_dependencies`, `compare_dependency_versions`, `get_dependency_changes`, `scan_project_dependencies`, `get_dependency_vulnerabilities`, `get_dependency_health`, `search_artifacts`, `audit_project_dependencies`.

## Repository resolution

Version answers resolve through the repositories the **project actually declares**, not a hardcoded public list — public well-known repos are only a fallback.

**Project-first resolution.** `discover_repositories(project_root)` parses the project's build files for declared repositories and scopes them into `{"dependency": [...], "plugin": [...]}`:

- **Gradle** (preferred when any Gradle build/settings file is present): `repositories {}` (dependency scope), `pluginManagement {}` and `buildscript {}` (plugin scope), `dependencyResolutionManagement {}` (dependency scope). Shorthands (`mavenCentral()`, `google()`, `gradlePluginPortal()`, `mavenLocal()`), `maven("url")` / `maven(url = "url")`, and `maven { url = ... }` blocks are all recognised. Block bodies are read with a hand-written brace-depth scanner (`_scan_balanced` / `_find_block`), not a brace-naive regex, so `maven { credentials {…}; url = uri("…") }` is parsed correctly.
- **Maven** (read only when no Gradle file exists — gradle-first / pom-exclusive): `<repositories>` (dependency scope) and `<pluginRepositories>` (plugin scope).

**Scoping by coordinate kind.** `_repos_for(group_id, artifact_id, ctx)` (the live entry point; `ctx` is REQUIRED — a public-only default would silently resurrect the bug) picks the scope from the coordinate: a `.gradle.plugin` marker artifact resolves in the **plugin** scope, everything else in the **dependency** scope. If that scope declares ≥1 HTTP-queryable repository, those declared repos are returned **exactly** — no implicit public append. Only when the scope declares none does the static public routing (`_public_repos`) act as the fallback.

**Cross-repo merge.** `fetch_metadata(group_id, artifact_id, ctx)` queries **every** repo in the resolved set and **merges** the results from those answering HTTP 200: version sets are unioned, deduped, and sorted, so a private repo's extra versions are not lost to a first-hit short-circuit; `lastUpdated` carries the most-recent value across answering repos. If no repo answers, it raises `ValueError` with the legacy message so unwrapped callers keep working. A single-repo result is identical to the legacy path (union/sort of one set = itself). This intentionally diverges from the retired TS `resolveAll`: no proxy-target dedup.

**`MAVEN_MCP_PUBLIC_FALLBACK`** (default OFF — see *Environment*): when ON, the public repos are appended even when the project declares its own repositories in that scope (escape hatch for implicit/inherited-repo builds), deduped by URL.

**Optional `projectPath`.** Every resolution tool accepts an optional `projectPath` arg; it defaults to the current working directory. `build_resolution_context(args)` builds the `ResolutionContext` once at the handler boundary (project path + discovered repos + the toggle, read once) and threads it down to every leaf resolver.

### Documented limitations

- **Root-only discovery** — only the project-root build files are read; per-submodule `build.gradle*` / `pom.xml` repositories are not discovered.
- **`mavenLocal()`** is recorded (as a `file://` marker) but never HTTP-queried, so it does not count as a queryable repo for fallback decisions.
- **Variable-interpolated repo URLs are unsupported** — a `url = "…/${repoPath}"` is captured verbatim (the `${...}` is not expanded), so such a URL will not resolve.
- **Resolved plugin impl-GAV scoping** — only the `.gradle.plugin` marker suffix classifies as plugin scope; a resolved plugin implementation GAV classifies as a library (deferred to #290; documented, not a defect).
- **Deferred #299 pieces** (this layer addresses the core; the rest are follow-ups): provenance reporting (`resolvedFrom` / `viaPublicFallback`) — #317; `repositoriesMode` semantics — #318 (current behavior unions settings + project repos, so it **may over-report** when a build restricts project-level repos); parent-POM / Maven-profile inheritance — #319; content / group filtering — #320.

## Environment

- `GITHUB_TOKEN` — optional, enables higher GitHub API rate limits (5000 req/h vs 60) for `get_dependency_changes` and `get_dependency_health` (the health tool also uses the rate-limited Search API for issue stats).
- `MAVEN_MCP_PUBLIC_FALLBACK` — optional toggle (default OFF; accepts `1`/`true`/`on`/`yes`). When ON, public well-known repos are appended even for a scope that declares its own repositories. Read once at the handler boundary into the `ResolutionContext`, never sniffed in leaf resolvers. See *Repository resolution*.
- No persistent cache. Memoization is in-memory per call only (e.g. the `metadata_cache` dict inside `audit_project_dependencies` dedupes lookups within a single audit run); nothing is written to disk.

## Conventions

- No XML parser dependency — all XML parsing is regex-based.
- Network seam is `urllib.request.urlopen`; tests mock it with `unittest.mock.patch("urllib.request.urlopen", ...)`.
- Tests live dev-only at `plugins/maven-mcp/tests/` (outside `plugin/`, so they are not shipped). They import `server` via a `__file__`-resolved `sys.path` shim in `tests/_helpers.py`; filesystem-touching parsers are exercised against real files written into a `TemporaryDirectory`.
- Version constants (`SERVER_VERSION`, `USER_AGENT`) in `server.py` are part of the 3 version locations that must stay in sync on a release; `scripts/validate.sh --check-tag` enforces this.
- `import server` is side-effect-free (the `if __name__ == "__main__": main()` guard at the tail).

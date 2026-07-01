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
- **HTTP** — `http_get` / `http_post_json` over `urllib.request.urlopen`; both return `(status, bytes)` and map `urllib.error.HTTPError → (code, b"")`. A shared `_request_with_retry` helper adds bounded retry/backoff on transient failures (HTTP 429/5xx and transport errors) — exponential backoff with jitter, `Retry-After` honored (capped), total-time budget, injectable `_sleep`. Retry is internal: the tri-state contract is preserved (a final 429/5xx still returns `(code, b"")`; a transport error raises only when EVERY attempt hit one).
- **Versioning** — `classify_version` (stability detection), `compare_versions`, `find_latest_version` / `find_latest_version_for_current` (selection), plus `_parse_segments` / `_extract_prerelease_numbers`.
- **Metadata & POM** — `fetch_metadata`, `check_version_in_repos`, `fetch_pom`, `_parse_metadata_xml` (regex).
- **Project scanning** (local, no network) — `_detect_build_system` + parsers: `_parse_gradle_deps`, `_parse_gradle_plugins_block`, `_parse_buildscript_classpath`, `_parse_settings_modules`, `_parse_settings_catalogs`, `_parse_maven_deps`, `_parse_maven_modules`, `_parse_toml_catalog`; orchestrated by `scan_project`. `buildSrc/` (kind `buildsrc`) and `build-logic/` subproject convention-plugin scripts (kind `convention-plugin`) are also walked, in addition to settings-listed modules.
- **GitHub & changelog** — `gh_repo_exists` / `gh_fetch_repo` / `gh_fetch_releases` / `gh_fetch_user` / `gh_fetch_issue_stats`, `discover_github_repo` (POM SCM → groupId guess), and `_get_dependency_changes_impl` + `_filter_version_range` (GitHub releases only).
- **Vulnerabilities** — OSV.dev batch query (`api.osv.dev/v1/querybatch`).
- **Tool handlers** — `handle_*`, one per MCP tool, plus the stdio JSON-RPC dispatch loop.

**Tools:** `get_latest_version`, `check_version_exists`, `check_multiple_dependencies`, `compare_dependency_versions`, `get_dependency_changes`, `scan_project_dependencies`, `get_dependency_vulnerabilities`, `get_dependency_health`, `search_artifacts`, `audit_project_dependencies`, `verify_coordinates` (see *`verify_coordinates`* below).

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
- **Resolved plugin impl-GAV scoping** — only the `.gradle.plugin` marker suffix classifies as plugin scope for repo routing; a resolved plugin implementation GAV (see `resolve_plugin_marker_implementation`, used by the vulnerability-checking path) is never re-resolved through `_repos_for` itself — it is passed straight to OSV. This is intentional, not a defect.
- **Deferred #299 pieces** (this layer addresses the core; the rest are follow-ups): provenance reporting (`resolvedFrom` / `viaPublicFallback`) — #317; `repositoriesMode` semantics — #318 (current behavior unions settings + project repos, so it **may over-report** when a build restricts project-level repos); parent-POM / Maven-profile inheritance — #319; content / group filtering — #320.

## Gradle plugin-marker resolution for vulnerabilities (#290)

Gradle plugin-marker coordinates (`{pluginId}:{pluginId}.gradle.plugin`) are not indexed by OSV directly — OSV indexes the real implementation artifact, not the marker. `resolve_plugin_marker_implementation(group_id, artifact_id, version, ctx)` fetches the marker's POM (via the existing `fetch_pom` / `_repos_for` plugin-scope routing) and extracts its single `<dependency>` block — the implementation GAV — before the coordinate is sent to OSV. `audit_project_dependencies` calls this on every scanned coordinate (deduplicated per-GAV). `get_dependency_vulnerabilities` calls this per input coordinate too, but only builds the `ResolutionContext` (`build_resolution_context` → `discover_repositories`, a filesystem read of the project's build files) when at least one requested coordinate actually has the marker shape — a request with no marker-shaped dependency makes zero filesystem calls and exactly one network call (the OSV POST), preserving the handler's original purity contract; a `ResolutionContext` build failure degrades to "markers unresolved" rather than raising. When a marker is resolved, the result entry keeps the marker's own `groupId`/`artifactId`/`version` identity and gains an additional `resolvedImplementation: {groupId, artifactId, version}` field. Resolution failure (POM fetch failure, missing/incomplete `<dependency>` block, unresolved `${...}` property, missing version) degrades gracefully to no resolution — the coordinate is queried against OSV as-is, which simply yields no CVEs for a marker GA that OSV never indexed; this path never raises.

## `verify_coordinates`

A write-time **anti-slopsquatting** primitive: batch existence check plus a fuzzy did-you-mean for the #283 write-time guard hook. LLMs invent coordinates that do not exist (~19.6%, often recurring → predictable slopsquatting); Gradle/Maven never validate a coordinate at edit time. This tool answers "does this `groupId:artifactId` exist, and if not, what is the closest real name".

**CRITICAL — what this tool does NOT do.** It detects **non-existent** coordinates and **one-edit-from-real** names (the slopsquat *shape*). It is **not** a malware/typosquat detector for coordinates that DO exist: a malicious package actually published to Maven Central reports `existenceStatus: "exists"` and is **never** flagged. The output therefore **never means "safe"** — `likelyHallucination: false` means "not a known-fake name", not "verified clean". Active typosquat-of-existing detection is a separate follow-up (#322) that the #283 hook layers on top.

**Params:**

- `dependencies: [{groupId, artifactId, version?}]` — required; capped at **100 items, ENFORCED in the handler** before any network I/O (an MCP `inputSchema` `maxItems` is advisory client metadata the server never validates, so the bound on outbound fan-out — each dep is an up-to-N-repo probe plus a search — lives in code; an over-long batch is truncated).
- `suggestLimit` — default `3`, clamped to `[0, 10]`.
- `projectPath` — optional; project-aware repository resolution (see *Repository resolution*).

**Per-coordinate output:**

- `existenceStatus` — tri-state: `"exists"` (any probed repo answered HTTP 200) / `"absent"` (EVERY probed repo returned a definitive 404) / `"unknown"` (verification unavailable — see below).
- `gaExists: bool` — back-compat alias for `existenceStatus == "exists"`.
- `gavExists?: bool` — only when `version` was given; membership of `version` in the UNION of versions across all 200-answering repos.
- `stability?` — `classify_version(latest)`, omitted when no non-empty latest exists (a 200 with an empty `<versions>` list never calls `classify_version` on `None`).
- `likelyHallucination: bool` — true only when `absent` AND some candidate's raw similarity ≥ `HALLUCINATION_THRESHOLD` (0.8), computed over the full pre-truncation candidate set. **Never** true on `unknown` or `exists`.
- `suggestions?: [{groupId, artifactId, score, versionCount}]` — only on `absent`. `score` is the raw similarity; ranking down-weights very-low-`versionCount` candidates (sort order only — never folded into the emitted `score` or the flag) so an attacker's brand-new single-version near-miss cannot outrank a popular real coordinate. Framed as **candidates to verify, not endorsements**.
- `repository?` — first answering repository name.
- `error?` — per-item isolation: an unexpected failure on one coordinate degrades that entry to `unknown` + `error`; sibling coordinates still resolve.

**`unknown` = degraded verification, NOT clean.** Any non-200/non-404 status (401/403 auth, 429 throttle, any 5xx), a raised transport failure (offline / DNS / read timeout), or a mix (e.g. 404 + 503) yields `unknown` — the protected/throttled repo might hold the artifact, so absence cannot be asserted. The tool **never** asserts hallucination on `unknown`. The #283 hook **must treat `unknown` as degraded, NOT as clean.** This is why the handler runs its OWN per-repo probe rather than reusing `fetch_metadata` (whose raise conflates absent vs unreachable and drops which repo answered).

**Suggestion source = Maven Central Solr only** → a recall limit for androidx / Google-Maven / Gradle-plugin-marker coordinates (no suggestion backend for those scopes; documented, relates to #295). Existence checking still reuses the project-first resolution layer (declared repos are honored); only the did-you-mean fallback is Central-only.

## Hooks

### `pre-edit-deps.sh` (PreToolUse write-time guard)

Fires before `Edit`/`Write`/`MultiEdit` on build files; extracts coordinates from new content and runs `verify_coordinates` + `get_dependency_vulnerabilities` via JSON-RPC 2.0 over stdin/stdout.

**Structural fail-open contract — non-negotiable.** `set -euo pipefail` + `trap 'exit 0' EXIT` are at the top. Every external command is guarded so failure produces an empty result and the script continues to exit 0. The script can never reach `exit 2` (hard-block). Any malfunction (jq absent, no `timeout`/`gtimeout`, server crash, network failure) silently allows the edit through.

**Decision policy:**
- `absent + (likelyHallucination==true OR non-empty suggestions)` → `deny` with candidates framed as "verify before use"
- `absent + no signal` (bare absent) → `allow`; covers private/non-Central/androidx coords with no similar Central name — **never tighten to deny-on-bare-absent**
- `unknown` (401/403/429/5xx/network error from verify_coordinates) → `allow`; unknown ≠ clean but cannot assert absence
- `exists` → `allow`
- CRITICAL/HIGH CVE on versioned coord → `ask` (advisory prompt)
- `deny` wins over `ask` when both fire

**Security constraints:**
- `GITHUB_TOKEN` is scrubbed from the environment before spawning `python3` (`env -u GITHUB_TOKEN`)
- Reason strings are built entirely from known structured fields via `jq -n --arg`; file content is never interpolated into reason text
- Suggestion coordinates are charset-filtered `[A-Za-z0-9._:-]` before embedding; suggestions are phrased as candidates to verify, not as drop-in replacements

**Bash 3.2 compatibility (macOS `/bin/bash` is 3.2):**
- No `declare -A`, no `${var,,}`, no `mapfile`/`readarray`
- Guard every array expansion as `"${arr[@]:-}"`
- Use `[[:space:]]` instead of `\s` in grep ERE patterns
- Use a variable `_Q="'"` to embed single-quote in grep patterns (avoids SC2016 and broken `\x27` in single-quoted strings)

**Extraction patterns:** double-quoted `"g:a[:v]"` and single-quoted `'g:a[:v]'` Gradle notation; `<groupId>`/`<artifactId>`/`<version>` blocks for pom.xml; `module = "g:a"` and `"g:a:v"` triples for TOML. Version part uses `[^"]+`/`[^']+`/`[^<]+` (any-except-closing-delimiter) — the sanitize step drops non-literal versions containing `$`.

**Tests:** `tests/test_pre_edit_hook.py` — subprocess-based with a stub server; decorated with `@_require_jq_and_timeout()` (skipUnless both jq and timeout/gtimeout present). Stub exercises extraction, allow/deny/ask decisions, fail-open paths (server crash, timeout, garbage output, empty output), security constraints (`GITHUB_TOKEN` not forwarded), and the MAX_COORDS=8 cap. Tests skip gracefully on macOS (no `timeout`); run fully on CI (ubuntu-latest has `timeout`).

## Environment

- `GITHUB_TOKEN` — optional, enables higher GitHub API rate limits (5000 req/h vs 60) for `get_dependency_changes` and `get_dependency_health` (the health tool also uses the rate-limited Search API for issue stats).
- `MAVEN_MCP_PUBLIC_FALLBACK` — optional toggle (default OFF; accepts `1`/`true`/`on`/`yes`). When ON, public well-known repos are appended even for a scope that declares its own repositories. Read once at the handler boundary into the `ResolutionContext`, never sniffed in leaf resolvers. See *Repository resolution*.
- **Persistent file cache** (`FileCache` in `server.py`): Maven metadata, POM, and Solr-search responses are cached on disk at `${XDG_CACHE_HOME}/maven-central-mcp` (default `~/.cache/maven-central-mcp`). TTLs: metadata 1 h, POM 7 days, search 1 h. What is cached: `fetch_metadata` (metadata GET), `check_version_in_repos` (metadata GET), `fetch_pom` (POM GET), `search_maven_central` via `handle_search_artifacts` (Solr search). What is NOT cached (security and correctness non-negotiables): OSV vulnerability queries (`query_osv_batch` — POST, never cached); GitHub API calls (`_gh_get` / `gh_repo_exists` — stay raw `http_get`); the entire `verify_coordinates` path — the per-repo existence probe uses raw `http_get` directly, and the did-you-mean suggestion search calls `search_maven_central(use_cache=False)` — both are live on every invocation. `check_version_exists` inherits a ≤1 h staleness window via the metadata TTL. Set `MAVEN_MCP_CACHE_DISABLE=1` (case-insensitive `1`/`true`/`yes`/`on`; read per-operation, not memoized) to disable all caching. In-process per-call memoization (e.g. `metadata_cache` inside `audit_project_dependencies`) is separate and unaffected.

## Conventions

- No XML parser dependency — all XML parsing is regex-based.
- Network seam is `urllib.request.urlopen`; tests mock it with `unittest.mock.patch("urllib.request.urlopen", ...)`.
- Tests live dev-only at `plugins/maven-mcp/tests/` (outside `plugin/`, so they are not shipped). They import `server` via a `__file__`-resolved `sys.path` shim in `tests/_helpers.py`; filesystem-touching parsers are exercised against real files written into a `TemporaryDirectory`.
- Version constants (`SERVER_VERSION`, `USER_AGENT`) in `server.py` are part of the 3 version locations that must stay in sync on a release; `scripts/validate.sh --check-tag` enforces this.
- `import server` is side-effect-free (the `if __name__ == "__main__": main()` guard at the tail).

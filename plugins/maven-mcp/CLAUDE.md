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

**Maven parent-POM and profile repository inheritance (#319).** The Maven branch of `discover_repositories` no longer reads only the local `pom.xml`'s own `<repositories>`/`<pluginRepositories>` — it also merges repos inherited from the local parent-POM chain and from active-by-default profiles, since real multi-module Maven builds routinely declare shared repos only at the parent or in a profile:
  - **Parent chain** — `_parse_maven_parent(pom_xml)` extracts the child's `<parent>` groupId/artifactId/version/`relativePath` (defaulting to Maven's own `../pom.xml` when the tag is absent; an explicit empty/self-closed `<relativePath/>` disables local lookup, matching Maven's own convention). `_resolve_parent_chain_repos(pom_path)` then walks child → parent → grandparent purely on the **local filesystem** (no network — the common reactor-build case needs none), verifying at each hop that the resolved file's own coordinate (`_parse_maven_project_coords`, which strips `<parent>`/`<dependencies>`/`<dependencyManagement>`/`<build>`/`<profiles>` first so it isn't fooled by a nested dependency/plugin `<groupId>`/`<artifactId>`/`<version>`) actually matches the `<parent>` reference before trusting its `<repositories>`/`<pluginRepositories>`. Depth-capped at 5 hops and cycle-guarded via `realpath`, so a malformed/cyclic `<parent>` reference cannot loop forever. A parent that isn't locally resolvable (external published artifact not in this checkout, or an empty `relativePath`) degrades gracefully — no crash, no network fetch attempted — falling back to whatever else was discovered.
  - **Active profiles** — `_parse_maven_active_profile_repos(pom_xml)` merges `<repositories>`/`<pluginRepositories>` from `<profiles><profile>` blocks where `<activation><activeByDefault>true</activeByDefault></activation>` is present. Only `activeByDefault` is evaluated; a profile with no `<activation>` or `activeByDefault` absent/false contributes nothing. The plain local-pom repo parse excludes anything nested inside `<profiles>` (profiles are stripped from the content before that regex search) so a profile's repos are picked up exactly once, through this path, never leaked into or duplicated by the base parse.
  - Merge order: local pom's own repos, then active-profile repos, then parent-chain repos, deduped by URL (first-seen wins).
  - **Deferred** (documented, not built here): `settings.xml`-level active-profile repositories (`~/.m2/settings.xml` profile activation for repos); non-`activeByDefault` activation conditions (property/JDK/OS matching); network-fetching an externally-published parent POM when it isn't locally resolvable. `settings.xml` MIRROR handling remains out of scope entirely (#294), unrelated to profiles.

**Repository content / group filtering (#320).** Gradle repository declarations can scope a repo to specific groups via content filtering, so it is never consulted for coordinates outside that scope (JitPack scoped to `com.github.*` is the canonical example). `_parse_gradle_repos` recognises both syntaxes and normalises them into the same RepoEntry shape — a repo dict with an optional `group_filters` list — so downstream resolution logic never needs to know which syntax was used:
  - **`maven { ... content { includeGroup("g") } }`** — a `content { }` block nested inside a `maven { }` body. `includeGroup("exact.group")` and `includeGroupByRegex("regex")` calls are both recognised; multiple calls in one `content { }` block are all captured (a repo can allow more than one group) and OR-matched.
  - **`exclusiveContent { forRepository { maven { ... } }; filter { includeGroup("g") } }`** shorthand — same net effect, different shape. The `maven { }` nested inside `forRepository { }` is parsed for its URL exactly like the plain form, and the `filter { }` body is parsed with the same `includeGroup`/`includeGroupByRegex` extraction as `content { }`. `exclusiveContent { }` blocks are located and their spans excised from the container body *before* the bare `maven { ... }` scan runs, so the nested `maven { }` is never ALSO picked up there as a second, unfiltered, duplicate entry.
  - **Matching (`_repo_matches_group`)**: a repo with no `group_filters` is queried for every group, exactly as before #320 (the filter is opt-in per repo, not a new default restriction). A repo WITH filters is only included in `_repos_for(group_id, artifact_id, ctx)`'s result for a coordinate whose `group_id` matches at least one filter — exact string equality for `includeGroup`, full-string regex match for `includeGroupByRegex` (mirrors Gradle's own `Pattern.matches`, not a partial/search match). An invalid regex is treated as non-matching, never raises.
  - **Interaction with the declared-vs-fallback contract**: if content filtering excludes every repo in a scope that DOES declare >=1 queryable repo, `_repos_for` still treats that scope as "declared" — it returns the (now empty) filtered list rather than unconditionally reverting to the public fallback, so a project whose only declared repo is JitPack-scoped-to-`com.github.*` does not silently resolve an unrelated group via Maven Central. The `ctx.public_fallback` (`MAVEN_MCP_PUBLIC_FALLBACK`) opt-in append still applies on top of that empty list, same as the unfiltered case.
  - **Regex literal caveat**: the pattern passed to `includeGroupByRegex(...)` is captured verbatim from the quoted source text — no Kotlin/Groovy string-escape decoding is performed (consistent with how every other quoted literal in this parser, e.g. repo URLs, is captured). A pattern written with Kotlin/Groovy double-backslash escaping (`"com\\.github\\..*"`) is used as-is and will NOT behave as the equivalent single-backslash Java/Kotlin regex; write the pattern with literal single backslashes (or a raw/triple-quoted Kotlin string) to avoid the mismatch.

**`repositoriesMode` awareness (#318).** `discover_repositories` parses `repositoriesMode` from a settings-file `dependencyResolutionManagement { }` body (`repositoriesMode.set(RepositoriesMode.X)` or the Kotlin DSL `repositoriesMode = RepositoriesMode.X` assignment form, both with or without the `RepositoriesMode.` qualifier) via `_parse_repositories_mode`, and uses it to decide which side of the dependency-scope repo set is actually queryable, instead of always unioning settings-level (`dependencyResolutionManagement { repositories {} }`) and root-build-level (bare top-level `repositories {}`) repos:
  - **`PREFER_PROJECT`** (Gradle's own default, applied when unset): if the root build file declares its own dependency-scope `repositories {}`, those project repos are used **exclusively** — settings repos are consulted only as the fallback when the project declares none (unchanged from pre-#318 behavior in that no-project-repos case).
  - **`FAIL_ON_PROJECT_REPOS`**: only settings-level repos are ever used, even when the root build file ALSO declares its own `repositories {}` — a real Gradle build would error in that case, so those project repos are dropped rather than treated as queryable.
  Plugin-scope repos (`pluginManagement {}` / `buildscript {}`) are entirely unaffected by `repositoriesMode` — that property only governs `dependencyResolutionManagement`, and plugin-scope repos keep unioning across settings and build files exactly as before.

**Cross-repo merge.** `fetch_metadata(group_id, artifact_id, ctx)` queries **every** repo in the resolved set and **merges** the results from those answering HTTP 200: version sets are unioned, deduped, and sorted, so a private repo's extra versions are not lost to a first-hit short-circuit; `lastUpdated` carries the most-recent value across answering repos. If no repo answers, it raises `ValueError` with the legacy message so unwrapped callers keep working. A single-repo result is identical to the legacy path (union/sort of one set = itself). This intentionally diverges from the retired TS `resolveAll`: no proxy-target dedup.

**`MAVEN_MCP_PUBLIC_FALLBACK`** (default OFF — see *Environment*): when ON, the public repos are appended even when the project declares its own repositories in that scope (escape hatch for implicit/inherited-repo builds), deduped by URL.

**Optional `projectPath`.** Every resolution tool accepts an optional `projectPath` arg; it defaults to the current working directory. `build_resolution_context(args)` builds the `ResolutionContext` once at the handler boundary (project path + discovered repos + the toggle, read once) and threads it down to every leaf resolver.

**Provenance reporting (`resolvedFrom`, #317).** `fetch_metadata(group_id, artifact_id, ctx)` additionally tracks the **first** repo (in `_repos_for` order — declared repos before any public-fallback append) that answers HTTP 200, and returns it as `resolvedFrom: {url, scope, viaPublicFallback}`. `viaPublicFallback` is `true` only when every declared repo in scope 404'd/failed and a fallback-routed entry (declared-scope-empty fallback, or a `MAVEN_MCP_PUBLIC_FALLBACK=on` append) is what actually answered — this is the #299 false-negative signal: a coordinate that exists on public Central but is absent from the project's declared internal repo is now distinguishable from genuine absence. Every handler that consumes `fetch_metadata` exposes `resolvedFrom` on its success path: `get_latest_version`, `check_multiple_dependencies`, `compare_dependency_versions`, `get_dependency_changes`, `get_dependency_health`, `audit_project_dependencies`. `check_version_exists` gets the equivalent from `check_version_in_repos` (now returning the full matching repo entry instead of just its name). `resolvedFrom` is omitted only when `fetch_metadata` itself cannot get any answer (every repo in scope fails/404s and the call raises) — there genuinely is no provenance to report. This is uniform across every `fetch_metadata`-consuming handler: when `fetch_metadata` succeeds but a *downstream* step then fails (e.g. `_get_dependency_changes_impl`'s no-versions-in-range or repositoryNotFound, `handle_get_dependency_health`'s GitHub-lookup errors, `handle_check_multiple_dependencies`'s "No version found", `handle_compare_dependency_versions`'s "No matching version found", `handle_audit_project_dependencies`'s defensive catch-all around version selection), `resolvedFrom` IS still present alongside that error — a repo did answer, so the provenance is known even though the overall result is an error/not-found. `verify_coordinates` is explicitly out of scope here — it runs its own per-repo probe with its own `repository` field (separate tri-state contract, see below).

**Userinfo redaction.** Repo URLs are captured verbatim from build files (see *Documented limitations*), so a discouraged hardcoded `url = "https://user:pass@host/repo"` would otherwise echo the literal credential into MCP tool-facing JSON. `_strip_userinfo(url)` redacts `user:pass@` to `***@` at the output boundary only (it never touches the raw URL used for the actual HTTP fetch) and is applied to every field that can carry a repo URL or repo name: `resolvedFrom.url` (via `_to_resolved_from`), `check_version_exists`'s `repository` field, `verify_coordinates`'s `repository` field, and both branches of `fetch_metadata`'s `last_err` message (non-200 status and transport exception — see below) — `maven("url")` / `maven { url = ... }` declarations set the repo's `name` equal to its `url` (see `discover_repositories`), so any field carrying a repo name carries the same exposure as `resolvedFrom.url`. A malformed-host URL (e.g. an unterminated bracketed IPv6 literal) that fails `urllib.parse.urlsplit` no longer fails open: `_strip_userinfo` falls back to locating the `scheme://` prefix and dropping everything up to and including the LAST `@` in the authority — not just the first — so userinfo containing an unescaped `@` (e.g. `user:pa@ss@host`) is still fully redacted rather than leaving a trailing password fragment.

**`fetch_metadata`'s `last_err` never interpolates raw exception text.** A userinfo URL makes `urlopen` raise `http.client.InvalidURL` (not `urllib.error.URLError`) during request construction — every time, before any network I/O — and `str(e)` on that exception embeds the literal password (e.g. `"nonnumeric port: 'pass@host'"`), a shape `_strip_userinfo` cannot redact since it isn't a bare URL. Because this fires for every query against a hardcoded-credential repo, this was the actual exposure (the `resolvedFrom`/`repository` fields above only redact repos that successfully answer 200, which a credentialed URL never does). Both `last_err` branches therefore build the message from known-safe components instead of trusting exception text: the non-200 branch uses `f"HTTP {status} from {_strip_userinfo(entry['name'])}"`; the transport-exception branch uses `f"{type(e).__name__} from {_strip_userinfo(entry['name'])}"` — never `str(e)`.

### Documented limitations

- **Root-only discovery** — only the project-root build files are read; per-submodule `build.gradle*` / `pom.xml` repositories are not discovered.
- **`mavenLocal()`** is recorded (as a `file://` marker) but never HTTP-queried, so it does not count as a queryable repo for fallback decisions.
- **Variable-interpolated repo URLs are unsupported** — a `url = "…/${repoPath}"` is captured verbatim (the `${...}` is not expanded), so such a URL will not resolve.
- **Resolved plugin impl-GAV scoping** — only the `.gradle.plugin` marker suffix classifies as plugin scope for repo routing; a resolved plugin implementation GAV (see `resolve_plugin_marker_implementation`, used by the vulnerability-checking path) is never re-resolved through `_repos_for` itself — it is passed straight to OSV. This is intentional, not a defect.
- **`resolvedFrom` names the first-answering repo, not necessarily the source of the reported version** — `fetch_metadata` merges `versions` across every repo in scope that answers 200, but `resolvedFrom` is captured once, from the first repo to answer. When more than one repo answers with differing version sets (e.g. a declared repo and the public fallback both respond), `latest`/`release` can be drawn from a later-answering repo's contribution while `resolvedFrom` still names only the first responder. Unaffected for the #317 AC scenario (the declared repo 404s, so the fallback is the sole answerer); only a gap when multiple repos genuinely co-answer.
- **#299 follow-up sequence complete** — provenance reporting (#317), `repositoriesMode` awareness (#318), Maven parent-POM/profile inheritance (#319), and content/group filtering (#320) are all resolved; see the corresponding subsections above. Each still carries its own narrower residual gap, tracked individually rather than deferred wholesale: #319's residuals — `settings.xml` profile activation, non-`activeByDefault` activation conditions, network-fetching an unresolvable-locally parent — remain open (see *Maven parent-POM and profile repository inheritance* above); #320's residual — `exclusiveContent { forRepository { ... } }` only recognises a nested `maven { }` as the wrapped repo declaration, not the shorthand accessors (`google()`, `mavenCentral()`, etc.) — a shorthand wrapped in `exclusiveContent` falls through to the plain unfiltered shorthand scan instead of picking up the `filter { }` group scoping; #318's residual is covered separately below.
- **`repositoriesMode` is settings-file-scoped, not per-submodule** (#318 resolved the core semantics — see *`repositoriesMode` awareness* above; this is the narrower residual gap). Because discovery is root-only, "the project declares its own repositories" is read as "the root build file declares dependency-scope repositories" — a multi-module build where `PREFER_PROJECT` lets a **submodule** override with its own repos (while the root build file declares none, or different ones) is not modeled; only the root build file's declaration is ever consulted.

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

**`unknown` = degraded verification, NOT clean.** Any non-200/non-404 status (401/403 auth, 429 throttle, any 5xx), a raised transport failure (offline / DNS / read timeout, including `http.client.InvalidURL` from a userinfo repo URL — see *Userinfo redaction* above; `_verify_one`'s probe loop catches it as an ordinary unverifiable-repo outcome, the same credential-leak class fixed in `fetch_metadata`), or a mix (e.g. 404 + 503) yields `unknown` — the protected/throttled repo might hold the artifact, so absence cannot be asserted. The tool **never** asserts hallucination on `unknown`. The #283 hook **must treat `unknown` as degraded, NOT as clean.** This is why the handler runs its OWN per-repo probe rather than reusing `fetch_metadata` (whose raise conflates absent vs unreachable and drops which repo answered).

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

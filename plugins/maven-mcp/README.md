# maven-mcp

Claude Code plugin that provides Maven dependency intelligence via an MCP server — query artifact versions, scan projects for outdated dependencies, check for vulnerabilities, and fetch changelogs.

## How it works

The plugin bundles a single-file Python 3 MCP server (`plugin/server/server.py`) that speaks MCP over stdio (JSON-RPC 2.0 on stdin/stdout). It uses the Python standard library only — zero pip dependencies. The plugin manifest registers it with `command: python3`, so it runs the same way in Claude cloud and local environments with no extra runtime setup.

The server registers tools that Claude can call during a conversation. It queries Maven Central, Google Maven, Gradle Plugin Portal, and routes each artifact to the appropriate repository by group-prefix.

### Tools

| Tool | Description |
|------|-------------|
| `get_latest_version` | Find latest version of an artifact with stability-aware selection |
| `check_version_exists` | Verify if a specific version exists and classify its stability |
| `check_multiple_dependencies` | Bulk lookup of latest versions for multiple dependencies |
| `compare_dependency_versions` | Compare current versions against latest (major/minor/patch) |
| `get_dependency_changes` | Show changes between versions (AndroidX/AGP docs or GitHub releases) |
| `scan_project_dependencies` | Scan Gradle/Maven build files and Gradle version catalogs (`gradle/libs.versions.toml`) for dependencies |
| `expand_bom` | Expand a Maven BOM into managed dependency versions |
| `get_transitive_graph` | Resolved transitive dependency graph for a GAV via deps.dev |
| `get_vulnerability_paths` | Shortest dependency path from a project root GAV to each transitively vulnerable node (deps.dev graph + OSV.dev) |
| `detect_dependency_conflicts` | Flag GAs resolved at multiple versions (Gradle: from resolved scan usages; Maven: deps.dev per-root graphs with nearest-wins) |
| `check_version_compatibility` | Check Spring Boot / AGP / Kotlin / javax→jakarta compatibility |
| `get_dependency_vulnerabilities` | Check for known CVEs via OSV.dev |
| `get_dependency_health` | Assess adoption-worthiness: version/stability, GitHub activity, issue dynamics, license, owner — raw signals for a verdict |
| `get_dependency_license` | SPDX / category license intelligence for direct dependencies |
| `check_license_compliance` | Aggregate transitive licenses via deps.dev; flag copyleft/risky vs project policy |
| `search_artifacts` | Search artifacts (Maven Central Solr; Nexus/Artifactory in closed mode) |
| `audit_project_dependencies` | Full audit: scan + version compare + vulnerability check |
| `catalog_entry` | Generate/validate Gradle version-catalog entries (`libs.versions.toml`) with rule-correct aliases and minimal diffs |
| `verify_coordinates` | Tri-state existence check + did-you-mean for hallucinated coordinates |
| `get_eol_status` | End-of-life / support status for JDK (vendor-specific), Kotlin, Gradle, and Spring Boot via endoflife.date |

### Skills

| Skill | Description |
|-------|-------------|
| `/latest-version <groupId:artifactId>` | Find latest version of a Maven artifact |
| `/check-version-exists` | Confirm whether one specific, already-known version exists |
| `/check-multiple-versions` | Batch latest-version lookup for several artifacts being evaluated |
| `/compare-dependency-versions` | Compare specific current versions against latest and classify the upgrade type |
| `/check-deps` | Scan project for outdated dependencies and update them |
| `/scan-project-dependencies` | Raw inventory of a project's declared dependencies (no freshness/CVE check) |
| `/expand-bom` | Expand a Maven BOM/platform into its managed dependency versions |
| `/transitive-graph` | Resolved transitive dependency graph for a single GAV |
| `/vulnerability-paths` | Trace each transitively vulnerable dependency back to the project root |
| `/dependency-conflicts` | Flag GAs resolved at multiple versions across a project |
| `/check-version-compatibility` | Validate AGP/Gradle/JDK/Kotlin and Spring Boot BOM/javax→jakarta compatibility |
| `/check-deps-vulnerabilities` | Scan project dependencies for known CVEs/GHSA via OSV (includes Gradle/Maven submodules) |
| `/dependency-vulnerabilities` | Check specific named coordinates for known CVEs/GHSA, outside a project scan |
| `/dependency-changes` | Show release notes/changelog between two versions of a Maven/Gradle dependency |
| `/dependency-health` | Assess whether a Maven dependency is worth adopting (maintenance, activity, license, owner) |
| `/dependency-license` | SPDX/category license intelligence for specific dependencies |
| `/license-compliance` | Aggregate transitive licenses vs a project license policy; flag copyleft/violations |
| `/search-artifacts` | Search Maven Central (or Nexus/Artifactory in closed mode) by keyword |
| `/audit-project-dependencies` | One combined report: updates + vulnerabilities + optional license posture |
| `/catalog-entry` | Generate or validate a Gradle version-catalog (`libs.versions.toml`) entry |
| `/eol-status` | Check end-of-life / support status for JDK, Kotlin, Gradle, or Spring Boot |

### Supported build systems

- **Gradle** — `build.gradle`, `build.gradle.kts`, `settings.gradle`, `settings.gradle.kts`
- **Maven** — `pom.xml`
- **Version catalogs** — `gradle/libs.versions.toml`

Repositories are selected by static group-prefix routing (Gradle Plugin Portal for plugin markers, Google Maven for AndroidX/Google groups, Maven Central as fallback). **Gradle scanning** invokes the project's Gradle wrapper to resolve production runtime classpaths (`*RuntimeClasspath`) and merges declared provenance from build files and version catalogs (`gradle/libs.versions.toml`). **Maven scanning** parses `pom.xml` locally. Build-file parsers also collect catalog aliases, plugin DSL declarations, and dead-repository hints (`jcenter()`). The server also reads project-declared repositories for version lookups (see plugin docs); custom/private repos require credentials via `MAVEN_REPO_*` env vars.

## Requirements

- **Python 3.9+** — the server uses the standard library only; no pip dependencies.

## Optional

- **jq** — used by both hooks (`plugin/hooks/pre-edit-deps.sh`, `plugin/hooks/post-edit-deps.sh`) to parse JSON input. Both hooks are no-ops when `jq` is not installed; the MCP server itself does not need it.
- **timeout / gtimeout** — used by the PreToolUse guard hook (`pre-edit-deps.sh`) to cap the server call at 8 s. On macOS, `timeout` is not available by default; install GNU coreutils via `brew install coreutils` to get `gtimeout`. When neither is present the hook exits immediately (fail-open) — the MCP server is never called and every edit proceeds.
- **GITHUB_TOKEN** — set this environment variable to raise GitHub API rate limits from 60 to 5000 requests/hour. Used by the `get_dependency_changes` and `get_dependency_health` tools to fetch release notes, repository metadata, and issue statistics. The PreToolUse hook scrubs this variable from the environment it passes to the server (least-privilege).
- **MAVEN_MCP_PUBLIC_FALLBACK** — optional toggle (default OFF). When ON, public well-known repos are appended even for projects that declare their own repositories. Affects the coordinate existence check in the PreToolUse guard hook.
- **Closed / offline mode & mirrors** (`MAVEN_MCP_OFFLINE`, `MAVEN_MCP_REPOSITORY_BASE`, `MAVEN_MCP_SETTINGS`) — for closed-perimeter / air-gapped builds. `MAVEN_MCP_OFFLINE=1` disables contact with public Maven Central / Google Maven / Gradle Plugin Portal. `MAVEN_MCP_REPOSITORY_BASE` replaces those well-known URLs with an internal Nexus/Artifactory base. Maven `settings.xml` `<mirror><mirrorOf>` (from `MAVEN_MCP_SETTINGS`, else `~/.m2/settings.xml`, else `$M2_HOME/conf/settings.xml`) rewrites matched repo URLs; `mirrorOf` supports `*`, `external:*`, id lists, and `!exclusions`. When no settings mirrors exist, a single-URL Gradle init-script redirect is honored as a catch-all. Public-repo behavior is unchanged when none of these are set.
- **Repo-manager search** (`search_artifacts` + optional `repositoryType` / `MAVEN_MCP_REPOSITORY_TYPE`) — in closed mode, keyword/coordinate search uses Nexus 3 `GET /service/rest/v1/search` or Artifactory GAVC/AQL against the repository base (auto-detected from URL/headers, overridable with `nexus` / `artifactory` / `central`). Unsupported managers return empty results with `searchBackendUnavailable` (non-fatal). Public Solr is unchanged outside closed mode.
- **External enrichment air-gap degradation** (`MAVEN_MCP_OFFLINE` + optional `MAVEN_MCP_OSV_BASE` / `MAVEN_MCP_GITHUB_BASE` / `MAVEN_MCP_DEPSDEV_BASE` / `MAVEN_MCP_ANDROID_DOCS_BASE` / `MAVEN_MCP_ENDOFLIFE_BASE`) — vulnerability, vulnerability-path, health, changelog, transitive-graph, license-compliance, and EOL-status tools short-circuit public OSV / GitHub / deps.dev / developer.android.com / endoflife.date calls in offline mode and return `capabilityUnavailable: "offline"` (or `"unreachable"` on transport failure with a short timeout) so empty results are not misread as clean. Point the `*_BASE` vars at internal mirrors / GitHub Enterprise to keep those capabilities online inside a closed contour.
- **TLS + HTTP(S) proxy** (`MAVEN_MCP_CA_CERT`, `HTTP(S)_PROXY` / `NO_PROXY`, optional `MAVEN_MCP_INSECURE_TLS`) — trust an internal CA bundle and route through an enterprise proxy. TLS verification stays on by default; `MAVEN_MCP_INSECURE_TLS=1` is an explicit, warned escape hatch. `SSL_CERT_FILE` / `NODE_EXTRA_CA_CERTS` are also accepted as CA sources.
- **Private Maven repository credentials** (`MAVEN_REPO_<ID>_…`) — optional. When a project declares a private/corporate repo (Artifactory, Nexus, GitHub Packages, …), the server attaches Basic or Bearer auth on HTTP queries. Credentials are never read from build files. Resolution order (first match wins), evaluated per identifier candidate — the repo's Maven `<id>` / Gradle `name` (if declared), then its hostname:
  1. Environment: `MAVEN_REPO_<ID>_USER` + `MAVEN_REPO_<ID>_PASSWORD` (Basic), or `MAVEN_REPO_<ID>_TOKEN` alone (Bearer), or `USER` + `TOKEN` (Basic with the token as the password — GitHub Packages / Artifactory PAT style).
  2. `~/.m2/settings.xml` `<servers><server><id>…</id>` matching the identifier.
  3. `~/.gradle/gradle.properties` keys `{id}Username`/`{id}Password` or `{id}Token`.

  `<ID>` is the matched identifier, uppercased with non-alnum → `_` (e.g. `nexus.example.com` → `NEXUS_EXAMPLE_COM`).

  **Host-keyed credentials** (`<ID>` = the repo's hostname) apply unconditionally — the hostname is always derived from the same URL a request is sent to, so it can't be misdirected. **Name/id-keyed credentials** (`<ID>` = the build file's own Maven `<id>` / Gradle `name`) are untrusted on their own: that string comes from the scanned project's build file, and a malicious build file could otherwise set it to any id a *different*, trusted host's secret happens to be keyed under, redirecting that secret to an attacker-controlled URL (GHSA-m2hv-xh72-cccw). A name/id-keyed credential is therefore only used when the user has additionally pinned it to its real destination host via `MAVEN_REPO_<ID>_HOST=<hostname>`; without a matching pin it is skipped (logged once, secret-free) and resolution falls back to the host-keyed candidate — **except** when the repo was rewritten by a matched `settings.xml` mirror (`<mirrors><mirror>`, see below): the mirror's own `<id>` becomes `name`, sourced from the SAME trusted `settings.xml` as the mirror URL itself (never from the scanned project), so it is trusted like a hostname and needs no `_HOST` pin.

  Missing credentials against an auth-gated repo yield a clear `auth required for <repo>` error (no crash). Secrets are never logged or echoed in tool output. Public-repo behavior is unchanged when no credentials are configured.

## Installation

```bash
claude plugin add /path/to/maven-mcp/plugin
```

The plugin manifest registers the bundled server automatically; no separate install or build step is required.

## Hooks

### PreToolUse write-time guard (`pre-edit-deps.sh`)

Fires before `Edit`, `Write`, or `MultiEdit` on build files (`build.gradle[.kts]`, `settings.gradle[.kts]`, `pom.xml`, `libs.versions.toml`). It extracts Maven coordinates from the new content and runs two checks:

1. **Existence check** via `verify_coordinates` — flags coordinates that are absent from all resolved repositories AND are likely hallucinated (high similarity to a real name) or have did-you-mean candidates on Maven Central. The decision is `deny` with suggested candidates when actionable, `allow` otherwise. Bare absence with no signal (e.g. private or non-Central coordinates with no similar names) is always allowed.
2. **Vulnerability check** via `get_dependency_vulnerabilities` — for versioned coordinates only, flags CRITICAL or HIGH CVEs as `ask` (advisory prompt).

`deny` takes priority over `ask`. The guard is **advisory, not enforcement**: a `deny` decision displays a reason and candidates, but the user can override by confirming the edit in Claude Code.

The guard is **structurally fail-open**: any failure — jq absent, no `timeout`/`gtimeout`, server error, network error, rate limit, private/auth-gated repository — results in silent allow with no output. The server process is capped at 8 s (`timeout 8`) inside the hook's 12 s outer timeout; `GITHUB_TOKEN` is scrubbed from the spawned environment.

**Scope limitation:** the existence check is Maven-Central-scoped for the did-you-mean suggestions (the Solr suggest backend covers Central only). Existence is checked against project-declared repositories (with public fallback), so private-repo coords receive a best-effort check; only the suggestion backend is Central-only.

### PostToolUse reminder (`post-edit-deps.sh`)

Fires after `Edit`, `Write`, or `MultiEdit` on build files when the changed content contains dependency-coordinate shapes, and reminds you to run `/check-deps` to verify dependency updates. Structurally fail-open (same convention as the PreToolUse guard): malformed input or a `jq` failure exits silently with no reminder. Requires `jq`; silently does nothing if `jq` is not installed.

## Caching

The server keeps no persistent on-disk cache. Lookups are memoized in memory per call only (for example, `audit_project_dependencies` dedupes metadata lookups within a single audit run); nothing is written to disk between runs.

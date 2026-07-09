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
| `detect_dependency_conflicts` | Flag GAs resolved at multiple versions (Maven nearest-wins / Gradle highest-wins) |
| `check_version_compatibility` | Check Spring Boot / AGP / Kotlin / javax→jakarta compatibility |
| `get_dependency_vulnerabilities` | Check for known CVEs via OSV.dev |
| `get_dependency_health` | Assess adoption-worthiness: version/stability, GitHub activity, issue dynamics, license, owner — raw signals for a verdict |
| `search_artifacts` | Search Maven Central |
| `audit_project_dependencies` | Full audit: scan + version compare + vulnerability check |
| `verify_coordinates` | Tri-state existence check + did-you-mean for hallucinated coordinates |

### Skills

| Skill | Description |
|-------|-------------|
| `/latest-version <groupId:artifactId>` | Find latest version of a Maven artifact |
| `/check-deps` | Scan project for outdated dependencies and update them |
| `/check-deps-vulnerabilities` | Scan project dependencies for known CVEs/GHSA via OSV (includes Gradle/Maven submodules) |
| `/dependency-changes` | Show release notes/changelog between two versions of a Maven/Gradle dependency |
| `/dependency-health` | Assess whether a Maven dependency is worth adopting (maintenance, activity, license, owner) |

### Supported build systems

- **Gradle** — `build.gradle`, `build.gradle.kts`, `settings.gradle`, `settings.gradle.kts`
- **Maven** — `pom.xml`
- **Version catalogs** — `gradle/libs.versions.toml`

Repositories are selected by static group-prefix routing (Gradle Plugin Portal for plugin markers, Google Maven for AndroidX/Google groups, Maven Central as fallback). Dependency scanning reads `gradle/libs.versions.toml` for declared dependencies. The server does not parse build files for custom/private repositories, so version answers for projects relying on custom repos can be incomplete.

## Requirements

- **Python 3.9+** — the server uses the standard library only; no pip dependencies.

## Optional

- **jq** — used by both hooks (`plugin/hooks/pre-edit-deps.sh`, `plugin/hooks/post-edit-deps.sh`) to parse JSON input. Both hooks are no-ops when `jq` is not installed; the MCP server itself does not need it.
- **timeout / gtimeout** — used by the PreToolUse guard hook (`pre-edit-deps.sh`) to cap the server call at 8 s. On macOS, `timeout` is not available by default; install GNU coreutils via `brew install coreutils` to get `gtimeout`. When neither is present the hook exits immediately (fail-open) — the MCP server is never called and every edit proceeds.
- **GITHUB_TOKEN** — set this environment variable to raise GitHub API rate limits from 60 to 5000 requests/hour. Used by the `get_dependency_changes` and `get_dependency_health` tools to fetch release notes, repository metadata, and issue statistics. The PreToolUse hook scrubs this variable from the environment it passes to the server (least-privilege).
- **MAVEN_MCP_PUBLIC_FALLBACK** — optional toggle (default OFF). When ON, public well-known repos are appended even for projects that declare their own repositories. Affects the coordinate existence check in the PreToolUse guard hook.
- **Closed / offline mode & mirrors** (`MAVEN_MCP_OFFLINE`, `MAVEN_MCP_REPOSITORY_BASE`, `MAVEN_MCP_SETTINGS`) — for closed-perimeter / air-gapped builds. `MAVEN_MCP_OFFLINE=1` disables contact with public Maven Central / Google Maven / Gradle Plugin Portal. `MAVEN_MCP_REPOSITORY_BASE` replaces those well-known URLs with an internal Nexus/Artifactory base. Maven `settings.xml` `<mirror><mirrorOf>` (from `MAVEN_MCP_SETTINGS`, else `~/.m2/settings.xml`, else `$M2_HOME/conf/settings.xml`) rewrites matched repo URLs; `mirrorOf` supports `*`, `external:*`, id lists, and `!exclusions`. When no settings mirrors exist, a single-URL Gradle init-script redirect is honored as a catch-all. Public-repo behavior is unchanged when none of these are set.
- **Private Maven repository credentials** (`MAVEN_REPO_<ID>_…`) — optional. When a project declares a private/corporate repo (Artifactory, Nexus, GitHub Packages, …), the server attaches Basic or Bearer auth on HTTP queries. Credentials are never read from build files. Resolution order (first match wins):
  1. Environment: `MAVEN_REPO_<ID>_USER` + `MAVEN_REPO_<ID>_PASSWORD` (Basic), or `MAVEN_REPO_<ID>_TOKEN` alone (Bearer), or `USER` + `TOKEN` (Basic with the token as the password — GitHub Packages / Artifactory PAT style). `<ID>` is the Maven `<id>` / Gradle `name`, else the repo hostname, uppercased with non-alnum → `_` (e.g. `nexus.example.com` → `NEXUS_EXAMPLE_COM`).
  2. `~/.m2/settings.xml` `<servers><server><id>…</id>` matching the repo id.
  3. `~/.gradle/gradle.properties` keys `{id}Username`/`{id}Password` or `{id}Token`.
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

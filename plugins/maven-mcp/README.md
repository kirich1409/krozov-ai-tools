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
| `get_dependency_changes` | Show changes between versions from GitHub releases |
| `scan_project_dependencies` | Scan Gradle/Maven build files and Gradle version catalogs (`gradle/libs.versions.toml`) for dependencies |
| `get_dependency_vulnerabilities` | Check for known CVEs via OSV.dev |
| `get_dependency_health` | Assess adoption-worthiness: version/stability, GitHub activity, issue dynamics, license, owner — raw signals for a verdict |
| `search_artifacts` | Search Maven Central |
| `audit_project_dependencies` | Full audit: scan + version compare + vulnerability check |

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

- **jq** — used by the PostToolUse hook (`plugin/hooks/post-edit-deps.sh`) to parse JSON input. The hook is a no-op when `jq` is not installed; the MCP server itself does not need it.
- **GITHUB_TOKEN** — set this environment variable to raise GitHub API rate limits from 60 to 5000 requests/hour. Used by the `get_dependency_changes` and `get_dependency_health` tools to fetch release notes, repository metadata, and issue statistics.

## Installation

```bash
claude plugin add /path/to/maven-mcp/plugin
```

The plugin manifest registers the bundled server automatically; no separate install or build step is required.

## Hooks

The plugin includes a PostToolUse hook that triggers when build files (`build.gradle`, `pom.xml`, `libs.versions.toml`, etc.) are edited. It reminds you to run `/check-deps` to verify dependency updates. The hook requires `jq` and silently does nothing if `jq` is not installed.

## Caching

The server keeps no persistent on-disk cache. Lookups are memoized in memory per call only (for example, `audit_project_dependencies` dedupes metadata lookups within a single audit run); nothing is written to disk between runs.

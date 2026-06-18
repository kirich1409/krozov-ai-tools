# maven-mcp

Claude Code plugin that provides Maven dependency intelligence via an MCP server — query artifact versions, scan projects for outdated dependencies, check for vulnerabilities, and fetch changelogs.

## How it works

An MCP server registers tools that Claude can call during a conversation. The server queries Maven Central, Google Maven, Gradle Plugin Portal, and any custom repositories discovered from your project's build files.

### Tools

| Tool | Description |
|------|-------------|
| `get_latest_version` | Find latest version of an artifact with stability-aware selection |
| `check_version_exists` | Verify if a specific version exists and classify its stability |
| `check_multiple_dependencies` | Bulk lookup of latest versions for multiple dependencies |
| `compare_dependency_versions` | Compare current versions against latest (major/minor/patch) |
| `get_dependency_changes` | Show changes between versions from GitHub changelogs |
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

### Supported build systems

- **Gradle** — `build.gradle`, `build.gradle.kts`, `settings.gradle`, `settings.gradle.kts`
- **Maven** — `pom.xml`
- **Version catalogs** — `gradle/libs.versions.toml`

Custom repositories are auto-discovered from Gradle `settings.gradle(.kts)`/`build.gradle(.kts)` and Maven `pom.xml`, and the server queries these alongside Maven Central. Dependency scanning additionally reads `gradle/libs.versions.toml` for declared dependencies, but version catalogs are not used for repository discovery.

## HTTP (Streamable HTTP) mode

Claude Cloud (claude.ai/code web container) requires HTTP transport — stdio servers do not work there. Start the server in HTTP mode with `--port`:

```bash
npx @krozov/maven-central-mcp --port 3001
```

Then configure it in `.mcp.json`:

```json
{
  "mcpServers": {
    "maven-mcp": {
      "type": "http",
      "url": "http://127.0.0.1:3001/mcp"
    }
  }
}
```

In stdio mode (default), start with no arguments: `npx @krozov/maven-central-mcp`.

## Prerequisites

- **Node.js** 18+ (required)
- **jq** (required when hooks are enabled) — used by the PostToolUse hook script (`plugin/hooks/post-edit-deps.sh`) to parse JSON input
- **GITHUB_TOKEN** (optional) — set this environment variable to raise GitHub API rate limits from 60 to 5000 requests/hour, used by the `get_dependency_changes` and `get_dependency_health` tools to fetch changelogs, release notes, repository metadata, and issue statistics

## Installation

```bash
claude plugin add /path/to/maven-mcp/plugin
```

Or use the published npm package directly as an MCP server:

```bash
npx @krozov/maven-central-mcp
```

## Hooks

The plugin includes a PostToolUse hook that triggers when build files (`build.gradle`, `pom.xml`, `libs.versions.toml`, etc.) are edited. It reminds you to run `/check-deps` to verify dependency updates.

## Caching

Persistent cache stored at `~/.cache/maven-central-mcp/`:
- **SCM mappings** (artifact → GitHub repo) — cached permanently
- **Releases and changelogs** — cached with 24-hour TTL

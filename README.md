# maven-central-mcp

MCP server for Maven dependency intelligence. Provides AI assistants with structured, live dependency data from Maven repositories (Maven Central, Google Maven, custom repos).

Works with any JVM build tool that uses Maven coordinates (Maven, Gradle, SBT, etc). Auto-discovers repositories from project build files.

## Quick Start

```bash
npx maven-central-mcp
```

### Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "maven-central": {
      "command": "npx",
      "args": ["maven-central-mcp"]
    }
  }
}
```

### VS Code

Create `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "maven-central": {
      "type": "stdio",
      "command": "npx",
      "args": ["maven-central-mcp"]
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `get_latest_version` | Find the latest version with stability-aware selection (STABLE_ONLY / PREFER_STABLE / ALL) |
| `check_version_exists` | Verify a specific version exists and classify its stability |
| `check_multiple_dependencies` | Bulk lookup of latest versions for a list of dependencies |
| `compare_dependency_versions` | Compare current versions against latest, with upgrade type (major/minor/patch) |
| `get_dependency_changes` | Show what changed between two versions — fetches GitHub release notes and changelogs |
| `scan_project_dependencies` | Scan project build files (Gradle, Maven, version catalogs) and extract all declared dependencies |
| `search_artifacts` | Search Maven Central for artifacts by keyword |
| `get_dependency_vulnerabilities` | Check dependencies for known vulnerabilities (CVEs) via OSV database |
| `audit_project_dependencies` | Full project dependency audit: scan build files, compare versions, check vulnerabilities |

## Features

- **Version intelligence** — stability-aware version selection, upgrade type classification (major/minor/patch)
- **Project scanning** — parse Gradle (`build.gradle.kts`, `build.gradle`), Maven (`pom.xml`), and version catalogs (`libs.versions.toml`)
- **Repository auto-discovery** — detects custom Maven repositories declared in build files
- **Vulnerability checking** — batch CVE lookup via [OSV.dev](https://osv.dev/) database
- **Change tracking** — fetches GitHub release notes and changelogs between versions
- **Artifact search** — keyword search across Maven Central

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Optional | Enables higher GitHub API rate limits (5000 req/h vs 60) for `get_dependency_changes` |

## License

MIT

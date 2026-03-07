# Design: maven-central-mcp

## Overview

TypeScript MCP server for Maven Central dependency intelligence.
Distribution via `npx maven-central-mcp`. Transport: stdio. No Docker dependency.

**Repository:** https://github.com/kirich1409/maven-central-mcp

## Stack

- TypeScript, Node.js
- `@modelcontextprotocol/sdk` — official MCP SDK
- Maven Central REST API

## Tools (MVP — 4 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_latest_version` | `groupId`, `artifactId`, `stabilityFilter?` | Latest version with stability filter (STABLE_ONLY / PREFER_STABLE / ALL) |
| `check_version_exists` | `groupId`, `artifactId`, `version` | Check version existence + classify stability (stable/rc/beta/alpha/snapshot) |
| `check_multiple_dependencies` | `dependencies[]` ({groupId, artifactId}) | Bulk lookup of latest versions |
| `compare_dependency_versions` | `dependencies[]` ({groupId, artifactId, currentVersion}) | Compare current vs available, upgrade type (major/minor/patch) |

## Version Stability Classification

Parse version string by patterns:
- `SNAPSHOT` -> snapshot
- `alpha`, `a` -> alpha
- `beta`, `b` -> beta
- `M`, `milestone` -> milestone
- `RC`, `CR` -> rc
- Everything else -> stable

## Architecture

```
src/
  index.ts           — entry point, MCP server setup
  tools/             — tool implementations
  maven/             — Maven Central API client
  version/           — version parsing and classification
```

## Maven Central API

- **Search API**: `https://search.maven.org/solrsearch/select?q=g:{groupId}+AND+a:{artifactId}&rows=N&wt=json`
- **Metadata XML**: `https://repo1.maven.org/maven2/{group/path}/{artifactId}/maven-metadata.xml` — full version list

## Distribution

- npm package: `maven-central-mcp`
- Run: `npx maven-central-mcp`
- Client config: `{"command": "npx", "args": ["maven-central-mcp"]}`

## Future Enhancements (post-MVP)

- OSV.dev CVE scanning
- `analyze_dependency_age` tool
- `analyze_release_patterns` tool
- `get_version_timeline` tool
- `analyze_project_health` tool
- HTTP/SSE transport

# krozov-ai-tools

[![CI](https://github.com/kirich1409/krozov-ai-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/kirich1409/krozov-ai-tools/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/@krozov/maven-central-mcp)](https://www.npmjs.com/package/@krozov/maven-central-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)

Claude Code plugin marketplace by Kirill Rozov.

## Installation

Add the marketplace to Claude Code:

```
/plugin marketplace add kirich1409/krozov-ai-tools
```

Install a plugin:

```
/plugin install maven-mcp@krozov-ai-tools
```

## Plugins

### maven-mcp

Maven dependency intelligence for JVM projects. Auto-registers an MCP server that provides tools for version lookup, dependency auditing, vulnerability checking, and changelog tracking across Maven Central, Google Maven, and custom repositories.

**Features:**
- Version intelligence — stability-aware selection, upgrade type classification
- Project scanning — Gradle, Maven, version catalogs
- Repository auto-discovery from build files
- Vulnerability checking via [OSV.dev](https://osv.dev/)
- Changelog tracking — GitHub releases, AndroidX, AGP, Firebase release notes
- Artifact search across Maven Central

**Skills:** `/check-deps`, `/latest-version`, `/dependency-changes`

See [`plugins/maven-mcp/`](plugins/maven-mcp/) for full documentation.

## License

MIT

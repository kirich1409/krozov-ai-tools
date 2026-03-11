# krozov-ai-tools

Claude Code plugin marketplace by Kirill Rozov.

## Installation

Add the marketplace to Claude Code:

```
/plugin marketplace add kirich1409/krozov-ai-tools
```

Install a plugin:

```
/plugin install maven-mcp@krozov-ai-tools
/plugin install sensitive-guard@krozov-ai-tools
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

**Skills:** `/check-deps`, `/latest-version`

See [`plugins/maven-mcp/`](plugins/maven-mcp/) for full documentation.

### sensitive-guard

Prevents sensitive data (secrets, PII) from reaching AI servers. Scans files via a PreToolUse hook before they are read into conversation.

**Features:**
- Secret detection via [gitleaks](https://github.com/gitleaks/gitleaks) (700+ rules)
- PII detection — email, SSN, credit cards, IBAN (custom regex)
- Interactive allow/block prompt per finding
- Project and global allowlists (SHA-256 hashed)
- Configurable patterns and tools

See [`plugins/sensitive-guard/`](plugins/sensitive-guard/) for full documentation.

## License

MIT

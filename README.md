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
/plugin install sensitive-guard@krozov-ai-tools
/plugin install developer-workflow@krozov-ai-tools
/plugin install extend@krozov-ai-tools
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

### sensitive-guard

Prevents sensitive data (secrets, PII) from reaching AI servers. Scans files via a PreToolUse hook before they are read into conversation.

**Features:**
- Secret detection via [gitleaks](https://github.com/gitleaks/gitleaks) (700+ rules)
- PII detection — email, SSN, credit cards, IBAN (custom regex)
- Interactive allow/block prompt per finding
- Project and global allowlists (SHA-256 hashed)
- Configurable patterns and tools

See [`plugins/sensitive-guard/`](plugins/sensitive-guard/) for full documentation.

### developer-workflow

Developer workflow skills and expert agents for the full development cycle — from task implementation to QA testing to PR merge.

**Skills:**
- `/prepare-for-pr` — quality loop (build → simplify → self-review → lint/tests) before creating a PR
- `/create-pr` — create a draft or ready PR with auto-generated title, description, labels, and reviewer suggestions
- `/address-review-feedback` — analyze PR review comments, categorize by priority, plan and coordinate fixes, respond to reviewers
- `/code-migration` — safe in-place or parallel migration of any technology in Gradle/Android/Kotlin projects
- `/kmp-migration` — full Kotlin Multiplatform migration for Android modules
- `/migrate-to-compose` — migrate View-based Android UI (Activity, Fragment, custom View) to Jetpack Compose
- `/generate-test-plan` — generate structured, prioritized test plan from spec or code
- `/test-feature` — verify a feature against its specification on a live app
- `/exploratory-test` — undirected bug hunting and QA exploration on a running app
- `/plan-review` — multi-agent review of implementation plans using PoLL consensus protocol
- `/implement-task` — full development cycle: worktree → TDD → implementation → quality loop → draft PR (explicit invocation only)

**Agents (10):** architecture-expert, build-engineer, business-analyst, compose-developer, devops-expert, kotlin-engineer, manual-tester, performance-expert, security-expert, ux-expert

See [`plugins/developer-workflow/`](plugins/developer-workflow/) for full documentation.

### extend

Extend Claude Code built-in features with review and optimization tools.

**Skills:**
- `/agent-reviewer` — audit and improve Claude Code agent files: frontmatter, system prompt quality, tool selection, trigger accuracy

See [`plugins/extend/`](plugins/extend/) for full documentation.

## License

MIT

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
/plugin install developer-workflow-experts@krozov-ai-tools
/plugin install developer-workflow-kotlin@krozov-ai-tools
/plugin install developer-workflow-swift@krozov-ai-tools
```

Installing any of `developer-workflow`, `developer-workflow-kotlin`, or `developer-workflow-swift` automatically pulls in their dependencies (`developer-workflow-experts` and — for the platform plugins — `developer-workflow` core).

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

### developer-workflow family

Four plugins that split the dev-workflow pipeline along coherent lines. `developer-workflow` is the lifecycle core; `-experts` holds reusable review/consult agents; `-kotlin` and `-swift` hold platform specialists.

#### developer-workflow (core)

Toolbox of on-demand skills — research, spec authoring, plan-as-document planning, multiexpert review, mechanical checks, code-quality finalize, retroactive tests, QA, and PR lifecycle. No forced sequencing; the model reaches for the right skill.

**Skills (12):** `/research`, `/write-spec`, `/plan`, `/multiexpert-review`, `/evaluate-dependency`, `/check`, `/finalize`, `/write-tests`, `/generate-test-plan`, `/acceptance`, `/create-pr`, `/drive-to-merge`

**Agent:** `manual-tester` (covers exploratory QA without a spec — call directly via the Task tool; heuristics live in the agent file)

**Depends on:** `developer-workflow-experts`

See [`plugins/developer-workflow/`](plugins/developer-workflow/).

#### developer-workflow-experts

Reusable review/consult agents. Safe to install standalone in any project — no skills, no hooks, no MCP servers.

**Agents (9):** `code-reviewer`, `architecture-expert`, `security-expert`, `performance-expert`, `ux-expert`, `build-engineer`, `devops-expert`, `business-analyst`, `debugging-expert`

See [`plugins/developer-workflow-experts/`](plugins/developer-workflow-experts/).

#### developer-workflow-kotlin

Kotlin, Android, and KMP specialization.

**Agents:** `kotlin-engineer`, `compose-developer`

**Depends on:** `developer-workflow`, `developer-workflow-experts`

See [`plugins/developer-workflow-kotlin/`](plugins/developer-workflow-kotlin/).

#### developer-workflow-swift

Swift, iOS, and macOS specialization.

**Agents:** `swift-engineer`, `swiftui-developer`

**References:** Swift concurrency, testing, SwiftUI patterns/state/performance.

**Depends on:** `developer-workflow`, `developer-workflow-experts`

See [`plugins/developer-workflow-swift/`](plugins/developer-workflow-swift/).

## License

MIT

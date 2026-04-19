# developer-workflow-experts

Reusable expert agents extracted from `developer-workflow` for standalone consumption. Install this plugin alone to get the expert agents without the full workflow pipeline.

## Agents

| Agent | Purpose | Invocation |
|---|---|---|
| `code-reviewer` | Independent semantic review of diffs against task description and plan | Quality Loop gate 4; manual review |
| `architecture-expert` | Module structure, dependency direction, API design between modules | Architecture review, consortium research |
| `security-expert` | Auth flows, token storage, network security, CI/CD secrets, OWASP | Quality Loop expert review trigger: auth/crypto changes |
| `performance-expert` | Runtime, memory, I/O, database queries, hot loops, UI jank | Quality Loop expert review trigger: performance-sensitive changes |
| `ux-expert` | UI/UX flows, accessibility, platform conventions, information architecture | UX review of plans and screens |
| `build-engineer` | Gradle configuration, multi-module projects, AGP, KMP source sets, version catalogs | Build system issues |
| `devops-expert` | CI/CD pipelines, deployment automation, dependency scanning, release workflows | CI/CD work |
| `business-analyst` | Product and business value evaluation — requirements, scope, MVP, trade-offs | Research review, scope analysis |
| `debugging-expert` | Read-only root cause analysis before any fix is attempted | Bug investigation |

## Standalone use

This plugin has no skills and no hooks. It only publishes agents. Install it in any project where you want access to these review roles via the Task tool:

```
/plugin install developer-workflow-experts@krozov-ai-tools
```

Then invoke an expert with the Task tool, e.g. `subagent_type: "code-reviewer"`.

## Recommended complementary plugins

Not installed as dependencies — install yourself if useful.

| Tool | Kind | Complements | What it adds |
|---|---|---|---|
| `security-guidance` | Plugin (from `claude-plugins-official`) | `security-expert` agent | Runtime security hook layer — warns on dangerous bash patterns and file edits (rm -rf, command injection, XSS). Complements agent's design-time code review with live-prevention. |

## Part of developer-workflow family

- [`developer-workflow`](../developer-workflow/) — lifecycle pipeline (depends on this plugin)
- [`developer-workflow-kotlin`](../developer-workflow-kotlin/) — Kotlin/Android/KMP specialists
- [`developer-workflow-swift`](../developer-workflow-swift/) — Swift/iOS/macOS specialists

Each of those declares this plugin as a dependency — installing any of them installs `developer-workflow-experts` automatically.

## License

See the [root README](../../README.md) of the monorepo.

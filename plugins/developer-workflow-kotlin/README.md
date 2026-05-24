# developer-workflow-kotlin

Kotlin, Android, and KMP specialization layer for `developer-workflow`. Contains engineer agents and migration skills specific to the Kotlin ecosystem.

## Agents

| Agent | Purpose |
|---|---|
| `kotlin-engineer` | Kotlin business logic, data layer, ViewModels, use cases, repositories, DI, unit tests. Does NOT write Compose UI. |
| `compose-developer` | Jetpack Compose and Compose Multiplatform UI — screens, themes, navigation, animations, previews, accessibility. |

Shared reference material in `agents/references/`:
- `coroutines.md` — coroutines, Flow, dispatchers, test patterns (used by both Kotlin engineer and — in KMP-awareness mode — Swift engineer).

## Skills

| Skill | Purpose |
|---|---|
| `migration` | Guided 8-phase migration between technologies (DI, async, UI idiom, build plugin, View→Compose, Android→KMP) with behavioral parity and old-stack cleanup |
| `snapshot` | Capture current behavior of code targets (logic / ui / api) as `behavior-spec.md` before any migration or refactor |

## Dependencies

- [`developer-workflow`](../developer-workflow/) — toolbox skills (`write-tests`, `check`, `finalize`, etc.) used during platform work
- [`developer-workflow-experts`](../developer-workflow-experts/) — expert agents used by skills in this plugin

Both dependencies are installed automatically when this plugin is installed:

```
/plugin install developer-workflow-kotlin@krozov-ai-tools
```

## Recommended external tooling

Not installed as dependencies — install yourself if useful. Agents detect and use these when available; they fall back to web search / training knowledge when absent.

| Tool | Kind | Used for | Value |
|---|---|---|---|
| `kotlin-lsp` | Plugin (from `claude-plugins-official`) | `kotlin-engineer`, `compose-developer` | Kotlin language server (JetBrains LSP) — code intelligence, refactoring, analysis |
| `context7` | MCP server (from `claude-plugins-official`) | all agents | Version-specific documentation for Kotlin, Android SDK, Compose, KMP libraries — pulled directly from source repos |
| `ksrc` | CLI tool (env-level, external) | `kotlin-engineer`, `compose-developer` | Read source code of JVM/Kotlin dependencies directly — avoids guessing at library internals. Run `ksrc --help` for usage. |

## License

See the [root README](../../README.md) of the monorepo.

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
| `code-migration` | Safe, verifiable migrations — library swaps, async rewrites, Java→Kotlin, Gradle upgrades |
| `kmp-migration` | Android module → Kotlin Multiplatform — source set restructuring, iOS exposure |
| `migrate-to-compose` | View-based UI → Jetpack Compose, one screen at a time, with visual baseline |

## Dependencies

- [`developer-workflow`](../developer-workflow/) — lifecycle orchestration (`implement`, `write-tests`, etc. call into this plugin's engineers)
- [`developer-workflow-experts`](../developer-workflow-experts/) — expert agents used by skills in this plugin and by the lifecycle pipeline

Both dependencies are installed automatically when this plugin is installed:

```
/plugin install developer-workflow-kotlin@krozov-ai-tools
```

## License

See the [root README](../../README.md) of the monorepo.

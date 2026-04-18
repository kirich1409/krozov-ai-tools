# developer-workflow-swift

Swift, iOS, and macOS specialization layer for `developer-workflow`. Contains engineer agents and SwiftUI-specific reference material.

## Agents

| Agent | Purpose |
|---|---|
| `swift-engineer` | Swift business logic, data layer, services, actors, tests — iOS/macOS. Does NOT write SwiftUI views. |
| `swiftui-developer` | SwiftUI screens, components, themes, navigation, animations, previews, accessibility. |

Shared reference material in `agents/references/`:
- `swift-concurrency.md` — async/await, actors, Sendable, Task, TaskGroup, AsyncSequence
- `swift-testing.md` — Swift Testing, XCTest, fakes, async tests
- `swiftui-patterns.md` — view patterns, navigation, sheets, ForEach, `.task`, conditionals, previews
- `swiftui-state.md` — `@State`, `@Binding`, `@Observable`, `@Environment`, property wrappers
- `swiftui-performance.md` — body purity, `@Observable` granularity, images, animations

## Dependencies

- [`developer-workflow`](../developer-workflow/) — lifecycle orchestration (`implement`, `write-tests`, etc. call into this plugin's engineers)
- [`developer-workflow-experts`](../developer-workflow-experts/) — expert agents used by the lifecycle pipeline

Both dependencies are installed automatically when this plugin is installed:

```
/plugin install developer-workflow-swift@krozov-ai-tools
```

## License

See the [root README](../../README.md) of the monorepo.

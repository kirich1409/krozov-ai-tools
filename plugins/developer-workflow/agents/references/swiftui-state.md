# SwiftUI State Management — DO / DON'T Reference

Rules for correct state management in SwiftUI. Based on Apple documentation, WWDC sessions, and common production pitfalls.

---

## Property Wrapper Selection

| Wrapper | Owner | Scope | Use when |
|---------|-------|-------|----------|
| `@State` | View (private) | Local UI state | Toggle, text field value, scroll offset, animation flag |
| `@Binding` | Parent view | Child needs to mutate parent's state | Child toggle, text field in a form row |
| `@Observable` (class) | External model | Shared model data | Domain model, app state, screen-level model |
| `@Bindable` | `@Observable` class | Two-way binding from `@Observable` property | `TextField($model.name)` |
| `@Environment` | SwiftUI system | Dependency injection, system values | Color scheme, locale, dismiss action, custom dependencies |
| `@AppStorage` | UserDefaults | Small persistent preferences | Theme preference, onboarding flag |

---

## Decision Flowchart

```
Is it UI-only state (animation, focus, scroll, toggle)?
  YES → @State (private)
  NO ↓
Does a child view need to write it?
  YES → pass as @Binding from parent's @State or @Bindable
  NO ↓
Is it shared data / model?
  YES → @Observable class, passed as parameter or via @Environment
  NO ↓
Is it a system value (colorScheme, locale, dismiss)?
  YES → @Environment(\.keyPath)
  NO ↓
Is it a small persistent preference?
  YES → @AppStorage("key")
  NO → rethink the design
```

---

## @State Rules

**DO:**
- Always declare `@State` as `private` — it is owned by the view, never exposed
- Initialize `@State` at declaration site with a default value
- Use `@State` only for value types (`Bool`, `String`, `Int`, `enum`, small structs)

**DON'T:**
- Never pass a value from outside and store it as `@State` — the view ignores updates after init:

```swift
// DON'T — item changes from parent are ignored after first render
struct ItemRow: View {
    @State private var item: Item  // BUG: frozen after init

    init(item: Item) {
        _item = State(initialValue: item)
    }
}

// DO — passed value, view updates when parent changes
struct ItemRow: View {
    let item: Item
}
```

- Never use `@State` for reference types (`class`) — use `@Observable` or `@State` with `@Observable`
- Never declare `@State` without `private`

---

## @Binding Rules

**DO:**
- Use `@Binding` only when the child view needs to **mutate** the parent's state
- Create bindings from `@State` with `$property` or from `@Bindable` properties

**DON'T:**
- Don't use `@Binding` for read-only data — pass the value directly as `let`:

```swift
// DON'T — child only reads, never mutates
struct Label: View {
    @Binding var text: String  // unnecessary
}

// DO — plain parameter
struct Label: View {
    let text: String
}
```

- Don't create `Binding` manually with `Binding(get:set:)` unless absolutely necessary — prefer `$` syntax

---

## @Observable (iOS 17+)

**DO:**
- Use `@Observable` macro on model classes — automatic granular tracking, no `@Published` needed
- Pass `@Observable` objects as plain parameters — SwiftUI tracks property access automatically
- Use `@Bindable` when you need two-way binding to an `@Observable` property:

```swift
@Observable
class ProfileModel {
    var name: String = ""
    var email: String = ""
}

struct ProfileEditor: View {
    @Bindable var model: ProfileModel

    var body: some View {
        TextField("Name", text: $model.name)
        TextField("Email", text: $model.email)
    }
}
```

- Use `@ObservationIgnored` for properties that should not trigger view updates (caches, loggers, internal counters)
- Use `@ObservationIgnored` when storing property wrappers inside `@Observable` classes (e.g., `@AppStorage`):

```swift
@Observable
class Settings {
    @ObservationIgnored
    @AppStorage("theme") var theme: String = "light"
}
```

**DON'T:**
- Don't use `@ObservableObject` / `@Published` / `@StateObject` / `@ObservedObject` in new code — these are legacy (pre-iOS 17). Use `@Observable` instead
- Don't wrap `@Observable` in `@StateObject` or `@ObservedObject` — just pass it as a parameter or via `@Environment`
- Don't read properties you don't need in `body` — every read property becomes a dependency that triggers redraws

---

## @Environment for Dependency Injection

**DO:**
- Use `@Environment` for injecting shared dependencies (services, models):

```swift
// Define the key
struct OrderServiceKey: EnvironmentKey {
    static let defaultValue: OrderService = DefaultOrderService()
}

extension EnvironmentValues {
    var orderService: OrderService {
        get { self[OrderServiceKey.self] }
        set { self[OrderServiceKey.self] = newValue }
    }
}

// Inject
ContentView()
    .environment(\.orderService, liveOrderService)

// Consume
struct OrderList: View {
    @Environment(\.orderService) private var orderService
}
```

- For `@Observable` classes, prefer the simpler `.environment(model)` + `@Environment(ModelType.self)`:

```swift
@Observable class AuthModel { var isLoggedIn = false }

// Inject
ContentView()
    .environment(authModel)

// Consume
struct ProfileView: View {
    @Environment(AuthModel.self) private var auth
}
```

**DON'T:**
- Don't overuse `@Environment` for local state — it's for cross-cutting concerns and DI
- Don't forget to provide environment values — missing values crash at runtime with `@Environment(Type.self)` (no default)

---

## @State with @Observable (View-Owned Model)

When the view should **own** the lifecycle of an `@Observable` object:

```swift
struct OrderListScreen: View {
    @State private var model = OrderListModel()

    var body: some View {
        OrderListContent(model: model)
    }
}
```

**DO:**
- Use `@State` with `@Observable` class when the view creates and owns the model
- SwiftUI manages the lifetime — the model survives re-renders but is destroyed with the view

**DON'T:**
- Don't confuse with `@StateObject` (legacy) — `@State` works correctly with `@Observable` classes on iOS 17+

---

## Common Anti-Patterns

| Anti-pattern | Problem | Fix |
|---|---|---|
| `@State var item: Item` initialized from init param | Parent updates ignored after first render | Use `let item: Item` or `@Binding` |
| `@Binding` for read-only data | Unnecessary complexity, misleading API | Use `let` parameter |
| `@Published` + `@ObservableObject` in new code | Verbose, coarse-grained updates | Use `@Observable` macro |
| Reading unused properties in `body` | Unnecessary re-renders | Read only what you display |
| `@State` without `private` | External mutation bypasses SwiftUI lifecycle | Always `@State private var` |
| Manual `objectWillChange.send()` | Fragile, easy to forget | Use `@Observable` — automatic |
| `@EnvironmentObject` in new code | Legacy, requires exact type match | Use `@Environment(Type.self)` |

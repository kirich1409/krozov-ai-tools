# SwiftUI State — Non-Obvious Rules

This file lists only the state-management rules a modern Claude model omits or gets wrong without a reminder. Generic property-wrapper choice (`@State` for view-local UI state, `@Binding` for child-mutates-parent, `@Observable` for shared models, `@Environment` for system values, `@AppStorage` for small prefs), `private` on `@State`, and "use `$` not `Binding(get:set:)`" are **not** documented here; trust the model and Apple's SwiftUI docs.

---

## `@State` Initialized From `init` Param Freezes

The single most expensive property-wrapper bug in SwiftUI: storing an outside value as `@State` makes parent updates invisible after the first render.

```swift
// BUG: parent updates are ignored after init — @State is owner-only
struct ItemRow: View {
    @State private var item: Item
    init(item: Item) { _item = State(initialValue: item) }
}

// Fix: pass through, or @Binding if mutation is needed
struct ItemRow: View {
    let item: Item
}
```

The model writes the buggy form when the view "needs to track local state derived from a passed-in value". It almost never genuinely needs to.

## `@Observable` Tracks Per-Property Reads in `body`

`@Observable` is **not** like the old `@Published` / coarse `objectWillChange` — every property read inside `body` becomes a dependency. Two consequences the model misses:

1. **Read only what you display.** Touching `model.totalCount` in a debug log "just to see it" makes the view re-render whenever `totalCount` changes.
2. **Computed properties on the model that read N stored properties create N dependencies in any caller.** A "simple" computed `var summary: String { "\(name) — \(count) items" }` makes every caller depend on both `name` and `count`.

Destructuring at the top of `body` (`let (a, b) = (model.a, model.b)`) doesn't bypass tracking — both reads still register.

## Property Wrappers Inside `@Observable` Need `@ObservationIgnored`

Storing `@AppStorage`, `@FocusState`, or any other property wrapper inside an `@Observable` class without `@ObservationIgnored` breaks observation — the wrapper's storage shape is incompatible with the observation macro's tracking.

```swift
@Observable
class Settings {
    @ObservationIgnored
    @AppStorage("theme") var theme: String = "light"
}
```

Same applies to lazy/cached properties you don't want tracked (loggers, formatters, internal counters).

## `@Environment(Type.self)` Without Default Crashes

`@Environment(SomeType.self)` (no `defaultValue` key) silently fails at runtime when the value isn't injected — the view crashes on first read. Either:

- Provide it on every Scene root that hosts the view, or
- Use the `EnvironmentKey` form with a `defaultValue` (typically an Unimplemented stub that fails loudly in tests/previews)

The model often produces views that read `@Environment(...)` without ensuring injection — works in the simulator until the view appears in a `Settings` window or a new `WindowGroup`.

## `@State private var model = ObservableModel()` — Not `@StateObject`

For view-owned `@Observable` models on iOS 17+, the correct lifetime wrapper is `@State`. `@StateObject` is the legacy pattern for `ObservableObject`. The model still emits `@StateObject` from older training data — replace it.

```swift
struct OrderListScreen: View {
    @State private var model = OrderListModel()  // ✓ owns lifetime, survives recompositions
    var body: some View { /* ... */ }
}
```

# SwiftUI Patterns — Non-Obvious Rules

This file lists only the structural-pattern rules a modern Claude model omits or gets wrong without a reminder. Generic guidance — when to extract a sub-view, `@ViewBuilder` for composable containers, "use enum routes", "previews use realistic data", basic `#Preview` setup, sheet/alert basics — is **not** documented here; trust the model and Apple's SwiftUI docs.

---

## `AnyView` Breaks Diffing — Use Generics + `@ViewBuilder`

The model occasionally reaches for `AnyView` when generics get awkward (heterogeneous sub-trees, "any view" stored in a property). It's a correctness bug, not just a perf hit — `AnyView` erases the static type SwiftUI uses for identity and diffing.

```swift
// DON'T — type erasure breaks diffing
var content: AnyView { AnyView(makeView()) }

// DO — generics + @ViewBuilder; let the compiler track concrete types
struct Card<Content: View>: View {
    @ViewBuilder let content: () -> Content
    var body: some View { /* ... */ }
}
```

If you cannot avoid type erasure, prefer `Group { ... }` or a refactor that returns `some View`.

## Custom Modifier — Provide an Extension, Not `.modifier(X())`

Stateful modifier? Use `ViewModifier`. Stateless chain? Use a plain `View` extension. **Always** wrap call sites with an extension method (`.shimmer()`, `.cardStyle()`); never expose `.modifier(SomeModifier())` at the call site — it leaks the implementation type and reads worse.

## NavigationStack Routing — `.navigationDestination` at the Root

Type-safe enum routes are the modern pattern. The non-obvious rule: **`navigationDestination(for:)` must live at the `NavigationStack` root**, not on child views — child placement silently misroutes after the first push.

```swift
NavigationStack(path: $path) {
    HomeScreen()
        .navigationDestination(for: Route.self) { route in
            // resolve every Route case here
        }
}
```

`NavigationLink(destination:)` (eager API) is deprecated for new code — use `NavigationLink(value:)` paired with `.navigationDestination`.

## Sheets — One Modifier, Item-Based, Enum

Two gotchas:

1. **Multiple `.sheet` modifiers on the same view → only the last one fires.** Always consolidate to a single modifier driven by an `Identifiable` enum:

```swift
enum SheetType: Identifiable {
    case editProfile
    case addItem(category: String)
    var id: String { /* unique per case */ }
}

@State private var activeSheet: SheetType?
// ...
.sheet(item: $activeSheet) { sheet in
    switch sheet { /* ... */ }
}
```

2. **Don't drive sheets with multiple booleans** — use the enum. The same applies to alerts and confirmation dialogs.

## `ForEach` Identity — `id: \.self` Is a Trap on Mutable Data

`id: \.self` only works for immutable collections of simple values (`[String]`, `[Int]`, enums). For any model with mutating fields, identity changes when the content changes — animations break, `@State` resets, focus jumps.

Use `Identifiable` conformance or an explicit `\.id` keypath. **Never use array index** (`enumerated()` + `id: \.offset`) — insertions/deletions mis-associate animations and view-local state.

## `.task` Cancels on Disappear — `Task` in `onAppear` Doesn't

```swift
// DO — cancelled automatically when the view disappears
.task { orders = await fetchOrders() }

// DO — restarts when dep changes
.task(id: selectedCategory) { orders = await fetchOrders(in: selectedCategory) }
```

```swift
// DON'T — Task continues after the view is gone, leaks the work and may write to dead state
.onAppear {
    Task { orders = await fetchOrders() }
}
```

The model still emits `onAppear + Task { }` from older training data. Replace it.

## View Identity — `if` Destroys State, `.opacity` Preserves It

`if cond { TextField(...) }` is a different view in the tree depending on `cond` — toggling it destroys the previous instance, including focus, scroll offset, and any `@State`. To toggle visibility while preserving state, switch to `.opacity` (and zero out `.frame`/`.allowsHitTesting` if you need real hide-and-disable):

```swift
TextField("Search", text: $query)
    .opacity(showSearch ? 1 : 0)
    .frame(height: showSearch ? nil : 0)
    .allowsHitTesting(showSearch)
```

For genuinely different hierarchies (logged-in vs logged-out, list vs error) — `if` is correct. The trap is using `if` for visibility toggles.

## Conditional Modifier `.if {}` Is an Anti-Pattern

```swift
// Widely-recommended, widely-wrong
extension View {
    @ViewBuilder
    func `if`<Content: View>(_ cond: Bool, transform: (Self) -> Content) -> some View {
        if cond { transform(self) } else { self }
    }
}
```

The return type changes with `cond`, which confuses SwiftUI's diffing algorithm — same identity issue as the `if` block above. Apply modifiers conditionally inline using a ternary on the modifier value, not on the modifier presence:

```swift
Text("Status")
    .foregroundStyle(isActive ? .green : .secondary)
    .fontWeight(isActive ? .bold : .regular)
```

## Previews — Static Samples on the Model

Add a `static let samples` (or `static func sample(...)`) extension on the domain type rather than constructing test data inline in every `#Preview`. Hardcoded data only — no live network, no real model that does I/O. Match the project's preview convention (`#Preview("name", traits:)`, dark/light variants, multi-device).

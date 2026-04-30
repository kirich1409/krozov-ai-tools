# SwiftUI Performance — Non-Obvious Rules

This file lists only the SwiftUI performance rules a modern Claude model omits or gets wrong without a reminder. Generic guidance — `body` is pure, no object allocation in `body`, no side effects in `body`, basic `withAnimation`, `matchedGeometryEffect` — is **not** documented here; trust the model.

For view-identity rules (`if` vs `.opacity`, `id: \.self` traps), see `swiftui-patterns.md`. The performance impact is the same as the correctness impact — chosen deliberately is the rule.

---

## `@Observable` Tracks Per-Property Reads — Granularity Matters

`@Observable` is **not** like `@Published` / `objectWillChange`. Each property read in `body` becomes a tracked dependency. Two consequences the model misses:

1. **Read only what you display.** Touching `model.totalCount` in a hidden modifier or a debug `Text` makes the view re-render whenever `totalCount` changes — even if it's not visible.

2. **Computed properties on the model that read N stored properties create N dependencies in any caller.** A "convenient" `var summary: String { "\(name) — \(count) items" }` makes every caller re-render on changes to `name` OR `count`.

Destructuring at the top of `body` doesn't bypass tracking — both reads still register:

```swift
// DON'T — tracks all of name, status, items
var body: some View {
    let title = model.name
    let badge = model.status
    let total = model.items.count
    /* ... */
}
```

(This is also covered in `swiftui-state.md`. Same rule, performance-critical.)

## Hoist Allocations Out of `body`

The model emits `let formatter = DateFormatter()` inside `body` from generic Swift habit. SwiftUI re-evaluates `body` constantly — every render allocates a new formatter, configures it, and throws it away. On a `List` with hundreds of rows this is real cost.

```swift
// DO — created once
private static let priceFormatter: NumberFormatter = {
    let f = NumberFormatter(); f.numberStyle = .currency; return f
}()
```

Same applies to sort/filter/map of large collections. Compute in the model or in a cached computed property — never inline in `body`.

## `id: \.offset` From `enumerated()` Mis-Associates State

For `ForEach` over a collection that changes shape (insertions, deletions, reorder), array index as identity is wrong:

```swift
// DON'T — insert at top: every row's animations and @State move to the wrong row
ForEach(Array(items.enumerated()), id: \.offset) { index, item in /* ... */ }
```

Use `Identifiable` conformance or an explicit `\.id` keypath. `id: \.self` is acceptable only for immutable collections of simple values.

## `.animation(_:value:)` Requires `value`

`.animation(.default)` without a `value:` parameter is **deprecated** and animates every state change in the subtree, including unrelated ones. The model still emits the value-less form from older training data. Always specify `value:`:

```swift
Text("Count: \(count)")
    .animation(.spring, value: count)
```

## Image Memory — `.frame()` Doesn't Downsample

`.frame(width:height:)` only sets the **display** size. The image is still decoded at full resolution and stored in memory at full resolution. On a list with 100 large remote images, this blows up memory even if each thumbnail is 80×80.

To actually reduce decode cost: use `preparingThumbnail(of:)` (or downsample at the data layer for known thumbnail sizes). The model writes `AsyncImage(url:).frame(80, 80)` and considers the job done — it isn't.

## `List` Over `ScrollView + LazyVStack`

For typical scrolling content, `List` has built-in cell reuse, prefetching, and platform-correct selection / swipe affordances. `ScrollView { LazyVStack { ForEach { } } }` looks similar but lacks the optimizations and platform behaviors. The model picks `LazyVStack` when it should default to `List` — only choose `LazyVStack` when you genuinely need custom layout that `List` cannot express.

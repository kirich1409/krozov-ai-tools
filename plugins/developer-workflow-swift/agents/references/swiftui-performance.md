# SwiftUI Performance — DO / DON'T Reference

Rules for avoiding common SwiftUI performance pitfalls. Focus on preventing unnecessary view re-evaluation and work in `body`.

---

## @Observable Granularity

**DO:**
- Read only the properties you need in `body` — each read property becomes a tracked dependency:

```swift
// DO — only reads `title` and `status`, ignores other properties
struct OrderHeader: View {
    let model: OrderModel  // @Observable

    var body: some View {
        HStack {
            Text(model.title)       // tracks `title`
            StatusBadge(model.status) // tracks `status`
        }
        // Changes to model.items, model.notes, etc. do NOT trigger re-render
    }
}
```

**DON'T:**
- Don't pass the entire model to a helper function that reads many properties — it creates broad tracking:

```swift
// DON'T — reads all properties, re-renders on any change
var body: some View {
    Text(model.description) // `description` is a computed property reading 5 fields
}
```

- Don't destructure an `@Observable` into local variables at the top of `body` — you've now tracked everything:

```swift
// DON'T — all properties tracked
var body: some View {
    let title = model.title
    let status = model.status
    let count = model.items.count  // tracks `items` — re-renders on any item mutation
    // ...
}
```

---

## body Must Be Pure

**DO:**
- Keep `body` as a pure function — it should only describe UI based on current state
- Move async work, data fetching, and side effects to `.task {}`, `.onChange`, or action handlers

**DON'T:**
- Never perform side effects in `body` — no logging, no analytics, no mutations:

```swift
// DON'T
var body: some View {
    print("body called")  // side effect
    logger.log("rendering")  // side effect
    counter += 1  // mutation — causes infinite loop

    return Text("Hello")
}
```

- Never create objects in `body` — they're re-created on every evaluation:

```swift
// DON'T — new formatter on every body call
var body: some View {
    let formatter = DateFormatter()  // expensive allocation per render
    formatter.dateStyle = .medium
    Text(formatter.string(from: date))
}
```

---

## Expensive Work in body

**DO:**
- Cache formatters and computed values outside `body`:

```swift
struct OrderRow: View {
    let order: Order

    // DO — static formatter, created once
    private static let priceFormatter: NumberFormatter = {
        let f = NumberFormatter()
        f.numberStyle = .currency
        return f
    }()

    // DO — computed property, not in body
    private var formattedPrice: String {
        Self.priceFormatter.string(from: order.price as NSNumber) ?? ""
    }

    var body: some View {
        Text(formattedPrice)
    }
}
```

- For expensive computations that depend on state, use a cached approach or pre-compute in the model

**DON'T:**
- Don't sort, filter, or transform collections inside `body`:

```swift
// DON'T — sorts on every render
var body: some View {
    ForEach(items.sorted(by: { $0.date > $1.date })) { item in
        ItemRow(item: item)
    }
}

// DO — pre-sort in model or use computed property
private var sortedItems: [Item] {
    items.sorted(by: { $0.date > $1.date })
}
```

---

## ForEach with Stable Identity

**DO:**
- Always provide stable, unique identifiers — enables correct animations and state preservation:

```swift
ForEach(items, id: \.id) { item in
    ItemRow(item: item)
}
```

**DON'T:**
- Don't use `id: \.self` with mutable data — identity changes when content changes
- Don't use array index as identity — insertions/deletions cause items to be associated with wrong state

```swift
// DON'T
ForEach(Array(items.enumerated()), id: \.offset) { index, item in
    ItemRow(item: item)  // wrong item gets animations on insert/delete
}
```

---

## Image Optimization

**DO:**
- Use `AsyncImage` with proper placeholder and caching for remote images:

```swift
AsyncImage(url: imageURL) { phase in
    switch phase {
    case .success(let image):
        image
            .resizable()
            .aspectRatio(contentMode: .fill)
    case .failure:
        Image(systemName: "photo")
    case .empty:
        ProgressView()
    @unknown default:
        EmptyView()
    }
}
.frame(width: 80, height: 80)
.clipShape(RoundedRectangle(cornerRadius: 8))
```

- Apply `.frame()` before expensive modifiers — constrains the rendering surface
- Use `preparingThumbnail(of:)` for downsampling large images

**DON'T:**
- Don't load full-resolution images when displaying thumbnails — downsample first
- Don't create `UIImage`/`NSImage` in `body` — load asynchronously with `.task` or `AsyncImage`
- Don't apply `.resizable()` without `.frame()` or `.aspectRatio()` — image fills all available space

---

## View Identity and Conditional Switching

**DO:**
- Prefer modifier-based toggling when preserving view state matters:

```swift
// DO — preserves the view identity and internal state
TextField("Search", text: $query)
    .opacity(isSearching ? 1 : 0)
    .allowsHitTesting(isSearching)
```

**DON'T:**
- Don't use `if/else` to toggle views that have internal state — it destroys and recreates them:

```swift
// DON'T — TextField loses text and focus on every toggle
if isSearching {
    TextField("Search", text: $query)
}
```

---

## List Performance

**DO:**
- Use `List` with `id` parameter or `Identifiable` conformance for stable row identity
- Use `.listRowBackground()` and `.listRowSeparator()` for customization
- Use `@Observable` with granular properties — List rows re-render only when their specific data changes

**DON'T:**
- Don't use `ScrollView` + `LazyVStack` as a replacement for `List` unless you need custom layout — `List` has built-in optimizations (cell reuse, prefetching)
- Don't nest `List` inside `ScrollView` — `List` scrolls on its own

---

## Animation Performance

**DO:**
- Use `withAnimation(.easeInOut) { }` for state-driven animations
- Always specify `value:` parameter in `.animation(_:value:)` modifier:

```swift
// DO
Text("Count: \(count)")
    .animation(.spring, value: count)
```

- Use `.matchedGeometryEffect` for shared element transitions
- Use `.contentTransition(.numericText())` for number change animations

**DON'T:**
- Never use `.animation(.default)` without `value:` — it animates everything, including unrelated changes:

```swift
// DON'T — animates ALL state changes in this view
Text("Count: \(count)")
    .animation(.default)  // deprecated, unpredictable
```

- Don't animate `body` evaluation — animate state changes that trigger re-evaluation

---

## Summary: Performance Checklist

| Rule | Impact |
|------|--------|
| `body` is pure — no side effects | Prevents infinite loops and unexpected behavior |
| No object allocation in `body` | Prevents per-render allocation overhead |
| Formatters are `static let` or cached | Prevents expensive re-creation |
| Collections sorted/filtered outside `body` | Prevents per-render O(n log n) work |
| `ForEach` uses stable ID (not `\.self` for mutable data) | Correct animations, preserved state |
| `@Observable` reads are granular | Minimizes unnecessary view re-evaluation |
| `.animation(_:value:)` always has `value` | Predictable, scoped animations |
| Images downsampled before display | Prevents memory spikes |
| `if/else` vs `.opacity` — chosen deliberately | Preserves or resets state as intended |

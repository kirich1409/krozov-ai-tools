# SwiftUI Patterns — DO / DON'T Reference

Common patterns for structuring SwiftUI views, navigation, and composition. Based on Apple guidelines and production best practices.

---

## View Extraction

**DO:**
- Extract sub-views into dedicated `struct` types when they have distinct identity, state, or are reused
- Use computed properties for simple, stateless UI fragments within the same view:

```swift
// DO — dedicated struct for reusable or stateful component
struct OrderHeader: View {
    let order: Order

    var body: some View {
        HStack {
            Text(order.title)
            Spacer()
            StatusBadge(status: order.status)
        }
    }
}

// DO — computed property for simple, non-reusable fragment
struct OrderDetailScreen: View {
    let order: Order

    var body: some View {
        VStack {
            headerSection
            itemsList
        }
    }

    private var headerSection: some View {
        Text(order.title).font(.title)
    }
}
```

**DON'T:**
- Don't extract every 3-line block into a separate struct — extraction has a cost (a new type, parameter passing). Extract when it improves clarity or enables reuse
- Don't use `AnyView` for type erasure — it breaks SwiftUI diffing. Use `@ViewBuilder` or `Group` instead

---

## Container View Pattern

**DO:**
- Use `@ViewBuilder` for composable containers that accept arbitrary child content:

```swift
struct Card<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            content()
        }
        .padding()
        .background(.background, in: RoundedRectangle(cornerRadius: 12))
        .shadow(radius: 2)
    }
}

// Usage
Card {
    Text("Title")
    Text("Subtitle")
}
```

**DON'T:**
- Don't accept `AnyView` as a parameter — use generics with `@ViewBuilder`
- Don't force callers to wrap content in `Group` or `VStack` — your container should handle layout

---

## ViewModifier vs View Extension

**DO:**
- Use `ViewModifier` when the modifier has its own state, lifecycle, or complex logic:

```swift
struct ShimmerModifier: ViewModifier {
    @State private var phase: CGFloat = 0

    func body(content: Content) -> some View {
        content
            .overlay(shimmerGradient)
            .onAppear {
                withAnimation(.linear(duration: 1.5).repeatForever(autoreverses: false)) {
                    phase = 1
                }
            }
    }
}

extension View {
    func shimmer() -> some View {
        modifier(ShimmerModifier())
    }
}
```

- Use plain `View` extension for simple modifier chaining without state:

```swift
extension View {
    func cardStyle() -> some View {
        self
            .padding()
            .background(.background)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .shadow(radius: 2)
    }
}
```

**DON'T:**
- Don't use `ViewModifier` for simple chains — a `View` extension is simpler and reads better
- Don't use `.modifier(SomeModifier())` at call site — always provide an extension method

---

## NavigationStack + Enum Routing

**DO:**
- Use enum-driven navigation with `NavigationStack(path:)`:

```swift
enum Route: Hashable {
    case orderDetail(id: String)
    case profile
    case settings
}

struct AppNavigationStack: View {
    @State private var path = NavigationPath()

    var body: some View {
        NavigationStack(path: $path) {
            HomeScreen(path: $path)
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .orderDetail(let id):
                        OrderDetailScreen(orderId: id)
                    case .profile:
                        ProfileScreen()
                    case .settings:
                        SettingsScreen()
                    }
                }
        }
    }
}
```

- Keep `navigationDestination` at the root of `NavigationStack` — not nested inside child views
- Use typed `NavigationPath` for heterogeneous stacks, or `[Route]` for homogeneous stacks

**DON'T:**
- Don't use `NavigationLink(destination:)` (the old eager-loading API) — use `NavigationLink(value:)` + `.navigationDestination`
- Don't scatter `.navigationDestination` across multiple child views — centralize routing

---

## Sheets, Alerts, and Confirmation Dialogs

**DO:**
- Use `item`-based presentation for sheets tied to specific data:

```swift
enum SheetType: Identifiable {
    case editProfile
    case addItem(category: String)

    var id: String {
        switch self {
        case .editProfile: "editProfile"
        case .addItem(let cat): "addItem-\(cat)"
        }
    }
}

struct ContentView: View {
    @State private var activeSheet: SheetType?

    var body: some View {
        Button("Edit") { activeSheet = .editProfile }
            .sheet(item: $activeSheet) { sheet in
                switch sheet {
                case .editProfile:
                    EditProfileSheet()
                case .addItem(let category):
                    AddItemSheet(category: category)
                }
            }
    }
}
```

- Use `.alert(title:isPresented:actions:message:)` with a dedicated state enum for complex alerts
- Use `.confirmationDialog` for destructive actions with multiple choices

**DON'T:**
- Don't use multiple boolean `@State` for different sheets — use an enum
- Don't present multiple `.sheet` modifiers on the same view — only the last one works

---

## List / ForEach Identity

**DO:**
- Always use a stable, unique identifier for `ForEach`:

```swift
// DO — stable ID from data model
ForEach(orders, id: \.id) { order in
    OrderRow(order: order)
}

// DO — Identifiable conformance (preferred)
struct Order: Identifiable {
    let id: String
    var title: String
}

ForEach(orders) { order in  // uses \.id automatically
    OrderRow(order: order)
}
```

**DON'T:**
- Never use `id: \.self` with mutable data — identity changes when content changes, breaking animations and state:

```swift
// DON'T — if order.title changes, SwiftUI treats it as a new item
ForEach(orders, id: \.self) { order in  // BUG with mutable data
    OrderRow(order: order)
}
```

- `id: \.self` is acceptable ONLY for immutable collections of simple values (`[String]`, `[Int]`, enums)
- Don't use array index as identity — insertions and deletions cause wrong items to animate

---

## .task {} for Async Work

**DO:**
- Use `.task { }` for async work tied to a view's lifecycle — automatically cancelled when view disappears:

```swift
struct OrderListScreen: View {
    @State private var orders: [Order] = []

    var body: some View {
        List(orders) { order in
            OrderRow(order: order)
        }
        .task {
            orders = await fetchOrders()
        }
    }
}
```

- Use `.task(id:)` to restart work when a dependency changes:

```swift
.task(id: selectedCategory) {
    orders = await fetchOrders(category: selectedCategory)
}
```

**DON'T:**
- Don't use `onAppear` + `Task { }` — `.task` handles lifecycle correctly (cancellation on disappear):

```swift
// DON'T — Task is not cancelled when view disappears
.onAppear {
    Task {
        orders = await fetchOrders()  // may complete after view is gone
    }
}
```

- Don't use `.task { }` for synchronous work — it's for `async` operations only

---

## Conditional Views

**DO:**
- Use `if`/`else` when showing completely different view hierarchies:

```swift
if isLoggedIn {
    DashboardView()
} else {
    LoginView()
}
```

- Use `.opacity()` or `.hidden()` when toggling visibility but preserving state and identity:

```swift
Text("Error: \(message)")
    .opacity(showError ? 1 : 0)
```

**DON'T:**
- Don't use `if` just to toggle visibility — it destroys and recreates the view, losing state:

```swift
// DON'T — TextField state lost on each toggle
if showSearch {
    TextField("Search", text: $query)
}

// DO — preserves TextField state
TextField("Search", text: $query)
    .opacity(showSearch ? 1 : 0)
    .frame(height: showSearch ? nil : 0)
```

---

## Conditional Modifiers

**DO:**
- Apply modifiers conditionally using ternary operator inside the modifier:

```swift
Text("Status")
    .foregroundStyle(isActive ? .green : .secondary)
    .fontWeight(isActive ? .bold : .regular)
```

**DON'T:**
- Don't create `if`-based modifier extensions — they change the view type and break identity:

```swift
// DON'T — common anti-pattern
extension View {
    @ViewBuilder
    func `if`<Content: View>(_ condition: Bool, transform: (Self) -> Content) -> some View {
        if condition { transform(self) } else { self }
    }
}
// This changes the return type depending on the condition,
// which confuses SwiftUI's diffing algorithm
```

---

## Preview Best Practices

**DO:**
- Add `#Preview` for each meaningful visual state:

```swift
#Preview("Loading") {
    OrderListScreen(state: .loading)
}

#Preview("Populated") {
    OrderListScreen(state: .loaded(orders: Order.samples))
}

#Preview("Empty") {
    OrderListScreen(state: .loaded(orders: []))
}

#Preview("Error") {
    OrderListScreen(state: .error("Connection failed"))
}
```

- Use realistic sample data — real names, plausible numbers, not `"test"` or `"lorem ipsum"`
- Provide static sample data on model types for previews:

```swift
extension Order {
    static let samples: [Order] = [
        Order(id: "1", title: "MacBook Pro 16\"", amount: 2499.00),
        Order(id: "2", title: "AirPods Pro", amount: 249.00),
    ]
}
```

**DON'T:**
- Don't use live data sources or network calls in previews — hardcode everything
- Don't skip previews for non-trivial components — they are living documentation

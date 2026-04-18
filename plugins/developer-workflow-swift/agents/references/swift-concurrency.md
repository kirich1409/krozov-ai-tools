# Swift Concurrency — DO / DON'T Reference

Rules for writing correct, testable, and production-safe concurrent Swift code in iOS and macOS projects. Based on Swift 5.10+ / Swift 6 concurrency model.

---

## async/await Basics

**DO:**
- Mark functions `async` when they perform I/O, wait for results, or call other async functions
- Use `try await` for async throwing functions — handle errors at the appropriate layer
- Prefer async/await over completion handlers for all new code

**DON'T:**
- Never mix async/await with completion handlers in the same function — pick one
- Never call `Task.value` from synchronous code to "wait" for a result — restructure to be async
- Never wrap a simple synchronous operation in `async` just to make it awaitable

```swift
// DO — clean async chain
func fetchOrders() async throws -> [Order] {
    let data = try await urlSession.data(from: ordersURL).0
    return try decoder.decode([OrderDTO].self, from: data).map { $0.toOrder() }
}

// DON'T — pointless async wrapper
func getCount() async -> Int {
    return items.count // This doesn't need to be async
}
```

---

## Structured Concurrency

**DO:**
- Use `async let` for fixed number of concurrent operations:

```swift
async let profile = fetchProfile(id: userID)
async let orders = fetchOrders(userID: userID)
let result = try await (profile, orders)
```

- Use `TaskGroup` / `ThrowingTaskGroup` for dynamic number of concurrent operations:

```swift
try await withThrowingTaskGroup(of: Order.self) { group in
    for id in orderIDs {
        group.addTask { try await fetchOrder(id: id) }
    }
    var results: [Order] = []
    for try await order in group {
        results.append(order)
    }
    return results
}
```

- Use `withTaskCancellationHandler` when you need to cancel underlying non-async work (e.g. URLSession task)

**DON'T:**
- Never fire-and-forget with `Task { }` inside structured concurrency — use `async let` or `TaskGroup`
- Never nest `TaskGroup` inside another `TaskGroup` without a clear reason — flatten when possible

---

## Actors

**DO:**
- Use `actor` when a type has mutable state accessed from multiple concurrency domains
- Keep actor methods focused — minimize time spent holding the actor's isolation
- Use `nonisolated` for methods/properties that don't access mutable state:

```swift
actor OrderCache {
    private var cache: [OrderID: Order] = [:]

    func get(_ id: OrderID) -> Order? { cache[id] }
    func store(_ order: Order) { cache[order.id] = order }

    // This doesn't access mutable state — no need for isolation
    nonisolated var description: String { "OrderCache" }
}
```

**DON'T:**
- Never access actor properties from outside without `await` — the compiler enforces this
- Never use `class` with manual locks (NSLock, DispatchQueue) when an `actor` would suffice
- Never make everything an actor — use `struct` for immutable data, `actor` only for shared mutable state

---

## @MainActor

**DO:**
- Use `@MainActor` on @Observable model classes that update UI-bound state:

```swift
@MainActor
@Observable
final class OrderListModel {
    private(set) var orders: [Order] = []
    private(set) var isLoading = false
    // ...
}
```

- Use `@MainActor` on individual methods when only that method needs main thread:

```swift
@MainActor
func updateUI(with orders: [Order]) { ... }
```

**DON'T:**
- Never annotate the entire service/repository layer with `@MainActor` — data fetching belongs off the main thread
- Never use `DispatchQueue.main.async { }` in async code — use `@MainActor` or `MainActor.run { }`
- Never assume `@MainActor` methods are called on the main thread from synchronous context — only async calls guarantee it

---

## Sendable

**DO:**
- Make all types that cross concurrency domains `Sendable`
- Value types (`struct`, `enum`) with only `Sendable` stored properties automatically conform
- Use `final class` with only `let` stored properties of `Sendable` types for reference-type Sendable
- Actors are implicitly `Sendable`

```swift
// Automatically Sendable — struct with Sendable properties
struct Order: Sendable {
    let id: OrderID
    let status: OrderStatus
}

// Explicitly Sendable — final class with immutable state
final class Configuration: Sendable {
    let apiBaseURL: URL
    let timeout: TimeInterval
}
```

**DON'T:**
- Never use `@unchecked Sendable` unless you can prove thread safety — it bypasses the compiler:

```swift
// ACCEPTABLE — proven thread-safe (e.g., internally synchronized)
final class AtomicCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var _value = 0
    // All access goes through the lock
}

// UNACCEPTABLE — lying to the compiler
class MutableThing: @unchecked Sendable {
    var data: [String] = [] // Data race waiting to happen
}
```

- Never pass non-Sendable types across actor boundaries — compiler will flag this in strict mode

---

## Task

**DO:**
- Use `Task { }` for bridging from synchronous to async context (e.g., SwiftUI `.task` modifier, button actions)
- Use `Task.detached { }` only when you explicitly need to escape the current actor context
- Check `Task.isCancelled` or call `try Task.checkCancellation()` in long-running loops
- Store `Task` handles when you need to cancel them later:

```swift
private var loadTask: Task<Void, Never>?

func startLoading() {
    loadTask?.cancel()
    loadTask = Task {
        // work
    }
}
```

**DON'T:**
- Never ignore the `Task` handle when the work should be cancelled on dealloc/navigation
- Never use `Task.detached` just because you "don't want @MainActor" — use `nonisolated` methods instead
- Never use `Task.sleep` as a polling mechanism — use `AsyncStream` or notifications

---

## Task Cancellation

**DO:**
- Check cancellation cooperatively in long-running work:

```swift
for item in largeCollection {
    try Task.checkCancellation() // Throws CancellationError
    await process(item)
}
```

- Use `withTaskCancellationHandler` to propagate cancellation to non-async APIs:

```swift
func download(url: URL) async throws -> Data {
    let task = URLSession.shared.dataTask(with: url)
    return try await withTaskCancellationHandler {
        try await withCheckedThrowingContinuation { continuation in
            task.completionHandler = { data, _, error in
                if let error { continuation.resume(throwing: error) }
                else { continuation.resume(returning: data ?? Data()) }
            }
            task.resume()
        }
    } onCancel: {
        task.cancel()
    }
}
```

**DON'T:**
- Never swallow `CancellationError` — let it propagate
- Never continue expensive work after detecting cancellation — clean up and exit

---

## AsyncSequence and AsyncStream

**DO:**
- Use `AsyncStream` to bridge callback/delegate patterns to structured concurrency:

```swift
func observeNotifications(named name: Notification.Name) -> AsyncStream<Notification> {
    AsyncStream { continuation in
        let observer = NotificationCenter.default.addObserver(
            forName: name, object: nil, queue: nil
        ) { notification in
            continuation.yield(notification)
        }
        continuation.onTermination = { _ in
            NotificationCenter.default.removeObserver(observer)
        }
    }
}
```

- Use `AsyncThrowingStream` when errors can occur
- Always set `onTermination` to clean up resources (observers, connections, file handles)
- Use `for await` to consume sequences — respects cancellation automatically

**DON'T:**
- Never forget `continuation.finish()` when the source is done — the consumer will hang forever
- Never call `yield` after `finish` — it's a no-op but signals a logic error
- Never create an `AsyncStream` when a simple `async` function returning an array would suffice

---

## Swift 6 Strict Concurrency

**DO:**
- Enable strict concurrency checking: `SwiftSetting.strictConcurrency(.complete)` in Package.swift or `-strict-concurrency=complete` build setting
- Fix all `Sendable` warnings — they become errors in Swift 6
- Annotate closures that cross isolation boundaries with `@Sendable`:

```swift
Task { @Sendable in
    await processData()
}
```

- Use `sending` parameter modifier (Swift 6) for transferred ownership:

```swift
func process(data: sending [Order]) async { ... }
```

**DON'T:**
- Never suppress concurrency warnings with `@preconcurrency` on your own types — fix the conformance
- `@preconcurrency import` is acceptable for third-party modules not yet updated for Sendable
- Never use `nonisolated(unsafe)` as a general escape hatch — it's for specific interop scenarios only

### Migration Path

1. Enable warnings first: `-strict-concurrency=targeted` or `.enableUpcomingFeature("StrictConcurrency")`
2. Fix Sendable conformances on your types
3. Add actor isolation where needed
4. Mark callbacks as `@Sendable`
5. Move to `.complete` / Swift 6 language mode
6. Address remaining warnings one module at a time

---

## Testing Async Code

**DO:**
- Mark test functions as `async` — Swift Testing and XCTest both support it:

```swift
@Test("Fetches orders successfully")
func fetchOrders() async throws {
    let repository = FakeOrderRepository()
    repository.stubbedOrders = [.sample()]
    let service = OrderService(repository: repository)

    let orders = try await service.activeOrders()

    #expect(orders.count == 1)
}
```

- Test actor behavior by awaiting methods:

```swift
@Test("Cache stores and retrieves orders")
func cacheRoundtrip() async {
    let cache = OrderCache()
    let order = Order.sample()

    await cache.store(order)
    let retrieved = await cache.get(order.id)

    #expect(retrieved == order)
}
```

- Test cancellation explicitly:

```swift
@Test("Cancellation stops processing")
func cancellation() async {
    let task = Task {
        try await longRunningOperation()
    }
    task.cancel()

    await #expect(throws: CancellationError.self) {
        try await task.value
    }
}
```

**DON'T:**
- Never use `Thread.sleep` or `usleep` in async tests — use `Task.sleep` or `Clock.sleep` if a delay is genuinely needed
- Never test timing-dependent behavior without a controllable clock

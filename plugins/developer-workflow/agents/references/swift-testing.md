# Swift Testing — DO / DON'T Reference

Rules for writing correct, readable, and maintainable tests using Swift Testing framework and XCTest. Prefer Swift Testing for all new test code.

---

## Swift Testing vs XCTest

**When to use Swift Testing (`@Test`):**
- All new test code (Swift 5.10+, Xcode 16+)
- Parameterized tests — first-class support
- Better diagnostics — `#expect` shows actual vs expected inline
- Async tests — cleaner syntax
- Parallel by default — faster test suites

**When to use XCTest (`XCTestCase`):**
- Project targets < Swift 5.10
- UI tests (XCUITest) — Swift Testing does not support UI testing
- Performance tests (`measure { }`) — XCTest-only feature
- Existing test suites — don't migrate unless there's a reason

**Mixing:** Swift Testing and XCTest can coexist in the same target. Don't mix in the same file.

---

## @Test and @Suite

**DO:**
- Use `@Test("descriptive name")` with human-readable descriptions:

```swift
@Test("Empty cart shows zero total")
func emptyCartTotal() {
    let cart = Cart()
    #expect(cart.total == 0)
}
```

- Use `@Suite` to group related tests:

```swift
@Suite("Order cancellation")
struct OrderCancellationTests {
    let repository = FakeOrderRepository()
    let service: OrderService

    init() {
        service = OrderService(repository: repository)
    }

    @Test("Pending order can be cancelled")
    func cancelPending() async throws {
        repository.stubbedOrders = [.sample(status: .pending)]
        try await service.cancel(orderID: .sample)
        #expect(repository.cancelledOrderIDs.contains(.sample))
    }

    @Test("Shipped order cannot be cancelled")
    func cancelShipped() async throws {
        repository.stubbedOrders = [.sample(status: .shipped(trackingNumber: "123"))]
        await #expect(throws: OrderError.self) {
            try await service.cancel(orderID: .sample)
        }
    }
}
```

- Use `init()` for shared setup — each `@Test` gets a fresh instance (no shared mutable state)

**DON'T:**
- Never use `setUp` / `tearDown` — those are XCTest concepts. Use `init` and `deinit`
- Never share mutable state between tests — each test method gets its own `@Suite` instance
- Never use empty test names: `@Test func test1()` — always describe the behavior

---

## #expect and #require

**DO:**
- Use `#expect` for assertions that should continue on failure:

```swift
#expect(order.status == .pending)
#expect(orders.count == 3)
#expect(name.contains("Swift"))
#expect(items.isEmpty)
```

- Use `#require` when subsequent code depends on the assertion (like `guard`):

```swift
let order = try #require(orders.first) // Fails test if nil, unwraps if non-nil
#expect(order.status == .pending)
```

- Use `#expect(throws:)` for error assertions:

```swift
// Assert specific error type
await #expect(throws: OrderError.self) {
    try await service.cancel(orderID: .invalid)
}

// Assert specific error value (if Equatable)
#expect(throws: OrderError.notFound(.sample)) {
    try service.find(id: .sample)
}

// Assert no error thrown
#expect(throws: Never.self) {
    try service.validate(order: .sample())
}
```

**DON'T:**
- Never use XCTest assertions (`XCTAssertEqual`, `XCTAssertNil`) in Swift Testing — use `#expect`
- Never use `try!` or force-unwrap in tests — use `try #require` to safely unwrap with a clear failure

---

## Parameterized Tests

**DO:**
- Use parameterized tests to avoid copy-paste test methods:

```swift
@Test("Order status display name", arguments: [
    (OrderStatus.pending, "Pending"),
    (OrderStatus.confirmed, "Confirmed"),
    (OrderStatus.shipped(trackingNumber: "ABC"), "Shipped"),
    (OrderStatus.delivered, "Delivered"),
    (OrderStatus.cancelled, "Cancelled"),
])
func statusDisplayName(status: OrderStatus, expected: String) {
    #expect(status.displayName == expected)
}
```

- Use `zip` for paired arguments:

```swift
@Test("Parsing", arguments: zip(
    ["1", "2", "3"],
    [1, 2, 3]
))
func parsing(input: String, expected: Int) throws {
    #expect(Int(input) == expected)
}
```

**DON'T:**
- Never use parameterized tests with huge argument lists (>20) — split into focused test suites
- Never use parameterized tests when different arguments need different assertions — write separate tests

---

## Traits

**DO:**
- Use `.disabled` for temporarily skipped tests (with a reason):

```swift
@Test("Feature X integration", .disabled("Waiting for API v2 deployment"))
func featureXIntegration() async throws { ... }
```

- Use `.timeLimit` for tests that must complete quickly:

```swift
@Test("Cache lookup is fast", .timeLimit(.minutes(1)))
func cacheLookup() async { ... }
```

- Use `.tags` to categorize tests:

```swift
extension Tag {
    @Tag static var networking: Self
    @Tag static var persistence: Self
}

@Test("Fetch orders from API", .tags(.networking))
func fetchOrders() async throws { ... }
```

- Use `.enabled(if:)` for conditional tests:

```swift
@Test("Keychain storage", .enabled(if: ProcessInfo.processInfo.environment["CI"] == nil))
func keychainStorage() { ... }
```

**DON'T:**
- Never leave `.disabled` tests without a reason — stale disabled tests accumulate
- Never use `.enabled(if:)` to skip flaky tests — fix the flakiness

---

## Fakes vs Mocks

**DO — prefer fakes:**

```swift
// Fake — explicit behavior, no framework, readable
final class FakeAPIClient: APIClient, @unchecked Sendable {
    var responses: [String: Any] = [:]
    private(set) var requestedPaths: [String] = []

    func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        requestedPaths.append(path)
        guard let response = responses[path] as? T else {
            throw APIError.notFound
        }
        return response
    }
}
```

**Why fakes over mocks:**
- No framework dependency — works everywhere
- Readable — the behavior is right there in the code
- Flexible — easy to add custom behavior for edge cases
- Compile-time safe — protocol changes break fakes at compile time

**When mocks are acceptable:**
- Protocol has many methods and the test only cares about one interaction
- Verifying exact call count or call order is the test's purpose
- But prefer restructuring code to not need call verification

**DON'T:**
- Never use mocking frameworks as the default — reach for them only when fakes become impractical
- Never verify implementation details (method call order, exact arguments) unless that IS the contract

---

## Async Test Patterns

**DO:**
- Async tests are first-class in Swift Testing:

```swift
@Test("Orders load from repository")
func ordersLoad() async throws {
    let repository = FakeOrderRepository()
    repository.stubbedOrders = [.sample()]
    let model = OrderListModel(service: OrderService(repository: repository))

    await model.loadOrders()

    #expect(model.orders.count == 1)
    #expect(!model.isLoading)
}
```

- Test AsyncSequence consumption:

```swift
@Test("Observe orders emits updates")
func observeOrders() async {
    let repository = FakeOrderRepository()
    repository.stubbedOrders = [.sample()]

    var received: [[Order]] = []
    for await orders in repository.observeOrders() {
        received.append(orders)
        if received.count >= 1 { break } // Don't hang
    }

    #expect(received.count == 1)
}
```

- Test error cases:

```swift
@Test("Cancelled order throws when not pending")
func cancelNonPending() async {
    let repository = FakeOrderRepository()
    repository.stubbedOrders = [.sample(status: .delivered)]
    let service = OrderService(repository: repository)

    await #expect(throws: OrderError.self) {
        try await service.cancel(orderID: .sample)
    }
}
```

**DON'T:**
- Never use `Thread.sleep` to wait for async operations — the test should `await` directly
- Never use `Task.sleep` as a synchronization mechanism in tests — restructure the code
- Never leave tests that can hang indefinitely — use `.timeLimit` trait or bounded loops

---

## Test Organization

**DO:**
- One test file per production type: `OrderService.swift` -> `OrderServiceTests.swift`
- Use `@Suite` to group by behavior, not by method name
- Create test helpers as extensions on domain types:

```swift
extension Order {
    static func sample(
        id: OrderID = .sample,
        status: OrderStatus = .pending,
        items: [OrderItem] = []
    ) -> Order {
        Order(id: id, items: items, status: status, createdAt: .now)
    }
}

extension OrderID {
    static let sample = OrderID(rawValue: "test-order-1")
}
```

- Keep test helpers in a shared file (`TestHelpers.swift` or `Fixtures.swift`)

**DON'T:**
- Never put business logic in test helpers — they should only create test data
- Never share mutable state between test files — each test must be independent

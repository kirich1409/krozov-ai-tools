# Swift Testing — Non-Obvious Rules

This file lists only the testing rules a modern Claude model omits or gets wrong without a reminder. Generic syntax — `@Test`, `#expect`, `@Suite`, basic async tests, `#expect(throws:)`, `XCTAssertEqual` for XCTest, parameterized tests with `arguments:` — is **not** documented here; trust the model and [Apple's Testing docs](https://developer.apple.com/documentation/testing).

For project-config decisions: prefer Swift Testing for new code. UI tests stay XCUITest. Performance `measure {}` stays XCTest. Don't mix Swift Testing and XCTest in the same file.

---

## `@Suite` Test Isolation

Each `@Test` in a `@Suite struct` gets a **fresh instance**. `init` and `deinit` replace XCTest's `setUp` / `tearDown`. There is **no shared mutable state between tests by design** — store dependencies as `let` properties on the suite and each test sees them re-initialized.

The model occasionally tries to share state via `static var` for "performance" — that breaks parallel execution and creates flaky tests.

```swift
@Suite("Order cancellation")
struct OrderCancellationTests {
    let repository = FakeOrderRepository()  // re-created per @Test
    let service: OrderService
    init() { service = OrderService(repository: repository) }
}
```

## `#require` vs `#expect`

- `#expect(condition)` → assertion that continues on failure (records and proceeds).
- `try #require(condition)` → guard-equivalent: fails the test AND unwraps. Use it when subsequent code depends on the result.

The model defaults to `#expect` everywhere and writes manual `guard` clauses with `Issue.record`. Use `#require` to compress that:

```swift
let order = try #require(orders.first)  // fails if nil, unwraps if non-nil
#expect(order.status == .pending)
```

Never `try!` in tests — `try #require` is the correct unwrap.

## Parallel-by-Default Isolation

**Swift Testing runs tests in parallel by default.** Anything touching shared global state — Keychain, file system, `UserDefaults`, environment variables, singletons, network — will race.

For tests that genuinely cannot parallelize: apply `.serialized` trait at the suite or test level.

```swift
@Suite("Keychain integration", .serialized)
struct KeychainTests { /* ... */ }
```

This is the most common gotcha when migrating from XCTest. The model is unaware unless told.

## Fakes Over Mocks

Default to hand-written fakes. The model reaches for mocking frameworks (Cuckoo, Mockingbird) by reflex; in Swift, hand-written fakes are usually clearer and don't need a framework.

```swift
final class FakeAPIClient: APIClient, @unchecked Sendable {
    var responses: [String: Any] = [:]
    private(set) var requestedPaths: [String] = []
    func get<T: Decodable>(_ path: String, as: T.Type) async throws -> T {
        requestedPaths.append(path)
        guard let r = responses[path] as? T else { throw APIError.notFound }
        return r
    }
}
```

Reach for mocks only when: (a) a protocol has many methods and the test cares about one interaction; (b) verifying exact call count or order IS the contract under test.

`@unchecked Sendable` on a fake is acceptable when the test is single-threaded; under Swift 6 strict concurrency consider an actor-backed fake or proper synchronization.

## AsyncSequence Test Bounds

Consuming an `AsyncSequence` in a test must be **bounded** — break after N items or apply `.timeLimit`. Without a bound, an unfinished sequence makes the test hang forever, not fail. The model often writes `for await x in sequence { ... }` without an exit condition.

```swift
for await orders in repository.observeOrders() {
    received.append(orders)
    if received.count >= 1 { break }  // ← required
}
```

Or use `.timeLimit(.minutes(1))` as a safety net.

## Traits — `.disabled` Needs a Reason

`.disabled` always takes a reason string — without it, disabled tests accumulate as silent dead code:

```swift
@Test("Feature X integration", .disabled("Waiting for API v2 deployment"))
func featureXIntegration() async throws { /* ... */ }
```

Never use `.enabled(if:)` to silence flaky tests. Fix the flake (controllable clock, bounded async, deterministic fakes), don't hide it.

## No `Thread.sleep` / `usleep`

Async tests must not wait via wall-clock sleep. Use `Task.sleep` only when a delay is genuinely needed; better, inject a controllable clock (`Clock` protocol or project-specific fake) so the test advances time deterministically.

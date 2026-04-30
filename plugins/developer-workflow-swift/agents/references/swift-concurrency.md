# Swift Concurrency — Non-Obvious Rules

This file lists only the Swift Concurrency rules a modern Claude model omits or gets wrong without a reminder. Generic idioms — `async`/`await`, `try await`, `async let`, `TaskGroup`, structured concurrency basics, value-type Sendable inference, choosing actor over locks, basic test async syntax — are **not** documented here; trust the model and the [Apple Concurrency book](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/).

---

## `@MainActor` Placement

The model defaults to over-applying `@MainActor` for "safety". Stop it.

- **`@Observable` model classes that update UI-bound state** → `@MainActor` (correct).
- **Service / Repository / DataSource layer** → **never** `@MainActor`. I/O, parsing, mapping must run off the main thread. Annotate the layer with `actor` for thread-safe state, leave dispatcher choice to the call site.
- **Single method needs main-thread access** → `@MainActor func updateUI(...)` rather than the whole type.
- **Inside async code** → use `@MainActor` / `MainActor.run { }`, never `DispatchQueue.main.async`.

`@MainActor` methods only guarantee main-thread execution when called from async context. Synchronous callers can still execute them off-main on the synthesized thread — assume nothing.

## `Task.detached` Is Not "Escape `@MainActor`"

`Task.detached` exists for the rare case where you genuinely need a top-level unstructured task with no inherited isolation, priority, or task-local values. The model reaches for it reflexively to "escape" `@MainActor`. Don't.

- To run a method off the main actor → mark the method `nonisolated`.
- To do CPU work in parallel → `async let` or `TaskGroup` from a non-actor context.
- `Task.detached` is correct only for: orphaned background work that survives the parent, work that explicitly must NOT inherit task-local values, or the rare interop case.

## `nonisolated` for Pure Computed Members

On an actor or `@MainActor` type, mark properties / methods that don't touch mutable state as `nonisolated`. Without it, every read forces an `await`. Model often forgets and creates pointless cross-actor hops.

```swift
actor OrderCache {
    private var cache: [OrderID: Order] = [:]
    nonisolated var description: String { "OrderCache" } // ← correct
}
```

## `Task` Cancellation Bridging

Three things the model misses:

1. **Cooperative cancellation in long loops** — `try Task.checkCancellation()` (or `Task.isCancelled`) inside the loop body. Without it, cancellation only takes effect at suspension points.
2. **Bridging cancellation to non-async APIs** — wrap `URLSessionDataTask` / `OperationQueue` / similar with `withTaskCancellationHandler { ... } onCancel: { task.cancel() }`. The model often writes a `withCheckedThrowingContinuation` without the cancel bridge, leaving the underlying request running.
3. **Store the `Task` handle** when work should be cancelled on dealloc, navigation, or new request:

```swift
private var loadTask: Task<Void, Never>?
func startLoading() {
    loadTask?.cancel()
    loadTask = Task { /* ... */ }
}
```

## `AsyncStream` / `AsyncThrowingStream` Lifecycle

Two silent footguns:

- **`continuation.finish()` is mandatory** when the producer is done. Forgetting it makes `for await` consumers hang forever — not fail, hang.
- **`continuation.onTermination` must clean up** observers, file handles, network listeners. Without it, every cancelled consumer leaks the underlying resource.

```swift
AsyncStream { continuation in
    let observer = register(...)
    continuation.onTermination = { _ in unregister(observer) } // ← required
    // and continuation.finish() once the source is exhausted
}
```

## `@unchecked Sendable` Discipline

`@unchecked Sendable` is for proven thread-safe reference types only — internally synchronized via lock, queue, or atomic primitive. Never use it to silence a Sendable warning on a type that genuinely has data races. The compiler is right; the annotation isn't a fix.

```swift
// Acceptable — internal lock guards all access
final class AtomicCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var _value = 0
}

// NOT acceptable — silencing a real race
final class MutableThing: @unchecked Sendable {
    var data: [String] = []
}
```

## Swift 6 Strict Concurrency — Migration & Escape Valves

Migration ladder (use the project's current rung; raise gradually):

1. `-strict-concurrency=targeted` — warnings on annotated APIs only
2. `-strict-concurrency=complete` — warnings everywhere
3. Swift 6 language mode — warnings become errors

Escape valves to use sparingly:

- **`@preconcurrency import ThirdParty`** — acceptable for third-party modules not yet updated for Sendable. **Never** apply `@preconcurrency` to your own types; fix the conformance.
- **`nonisolated(unsafe)`** — interop-only escape hatch (legacy globals, ObjC bridging). Never a general silencer.
- `sending` parameter modifier transfers ownership; rarely actionable in normal code.

## Tests — Controllable Clock

Async tests must not rely on wall-clock time. Use `Task.sleep` only when a delay is genuinely needed; better, use a controllable clock (`Clock` protocol, `ContinuousClock`, or a project-injected fake clock) so the test can advance time deterministically.

Never `Thread.sleep` / `usleep` in async tests.

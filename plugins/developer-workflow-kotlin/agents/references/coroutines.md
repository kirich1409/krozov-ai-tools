# Kotlin Coroutines & Flow — Non-Obvious Rules

This file lists only the coroutine and Flow rules a modern Claude model omits or gets wrong without a reminder. Generic idioms — structured concurrency basics, `viewModelScope` for ViewModels, exposing immutable `StateFlow`, `async`/`await`, `flow {}` builders, choosing `suspend` vs `Flow`, catching `IOException` instead of `Exception`, no empty `catch` blocks — are **not** documented here; trust the model and the [official kotlinx.coroutines docs](https://kotlinlang.org/docs/coroutines-guide.html).

---

## Scope Ownership by Layer

Models occasionally inject an Application-scoped `CoroutineScope` into a Repository. They shouldn't.

| Layer | Scope | Why |
|-------|-------|-----|
| ViewModel | `viewModelScope` | Tied to ViewModel lifecycle, survives config changes |
| UseCase / Repository | **No own scope — inherits caller's** | Caller controls cancellation |
| Work that must outlive a screen | Injected `CoroutineScope` (Application-scoped) | Guaranteed completion when the user navigates away mid-write |

## Dispatcher Injection — Constructor Param, Not Hardcoded

Inject `CoroutineDispatcher` as a constructor parameter. Models default to hardcoded `Dispatchers.IO` inside `withContext` blocks, which makes the class untestable.

```kotlin
class DefaultOrderRepository(
    private val api: OrderApi,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : OrderRepository {
    override suspend fun getOrders(): List<Order> =
        withContext(dispatcher) { api.getOrders().map { it.toOrder() } }
}
```

## Suspend Functions Are Main-Safe — Caller Doesn't Wrap

Every `suspend fun` in the data/domain layer must be safe to call from the main thread. The function chooses the dispatcher via internal `withContext`. The caller does **not** wrap your function in `withContext` — that breaks the contract and indicates the function did not respect main-safety.

Models sometimes push dispatcher choice up to the caller. Keep it inside the function.

## StateFlow / SharedFlow Lifecycle Pairing

`SharingStarted.WhileSubscribed(5_000)` is the right default for `stateIn` in a ViewModel — and it only works if the UI collects with **lifecycle-aware** APIs. Without lifecycle awareness, the upstream never stops:

```kotlin
val orders: StateFlow<List<Order>> = getOrders()
    .stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = emptyList(),
    )
```

UI side:
- Compose: `collectAsStateWithLifecycle()`
- Views: `flowWithLifecycle()` / `repeatOnLifecycle(Lifecycle.State.STARTED)`

`SharingStarted.Eagerly` wastes resources unless the state is genuinely always needed. `SharingStarted.Lazily` never stops once started — usually wrong for screen-scoped state.

## Flow Operator Gotchas

Two non-obvious facts the model gets wrong about ordering:

1. **`flowOn(dispatcher)` only affects upstream operators** — calling it twice or after a terminal operator silently does nothing useful. Apply once, at the producer side.
2. **`retry { }` must be placed BEFORE `catch { }`** in the chain. If `catch` runs first, it consumes the error and `retry` never sees it.

```kotlin
upstream
    .map { /* ... */ }
    .retry(3) { it is IOException }   // first — gets a chance to retry
    .catch { /* fallback emission */ } // last — handles unrecoverable errors
    .collect { /* ... */ }
```

## Avoiding Indefinite Suspension

Terminal operators like `first()`, `single()`, `Channel.receive()` suspend until data arrives. If the source never emits, the coroutine hangs forever — a common production bug with event-driven flows.

| Source | `first()` risk | Mitigation |
|---|---|---|
| `StateFlow` | Safe — always has a value | None |
| `SharedFlow(replay > 0)` | Low — replays last N values | `withTimeout` for rare events |
| `SharedFlow(replay = 0)` | **High** — waits for next emit | Always use `withTimeout` |
| `Channel` | **High** — waits for `send()` | `tryReceive()` or `withTimeout` |
| Cold `flow { }` | Depends on producer | `withTimeout` if producer may not emit |

Use `firstOrNull()` when absence of data is a valid outcome rather than an error.

## Cancellation — `CancellationException` Must Propagate

Every `catch` that catches `Exception` or `Throwable` must re-throw `CancellationException` first. Models forget this constantly:

```kotlin
try {
    api.fetchData()
} catch (e: CancellationException) {
    throw e
} catch (e: Exception) {
    handleError(e)
}
```

`runCatching { }` swallows `CancellationException` — never use bare `runCatching` in suspend code. Either re-throw inside `onFailure`, or use explicit `try/catch`:

```kotlin
runCatching { api.fetchData() }
    .onFailure { e ->
        if (e is CancellationException) throw e
        handleError(e)
    }
```

## `withContext(NonCancellable)` — Only in `finally`

`NonCancellable` disables cancellation for everything inside. Use it **only in cleanup that must complete after a coroutine is being cancelled**:

```kotlin
try {
    work()
} finally {
    withContext(NonCancellable) { releaseResources() } // valid
}
```

Anywhere else it's a bug — disables cooperative cancellation in the calling chain.

## Error Mapping at Layer Boundaries

Don't leak `HttpException`, `SQLiteException`, or other implementation exceptions to the domain or presentation layer. Map them at the data → domain boundary into a project-specific error type or `Result<T>`.

## Testing

Three rules the model misses:

1. **All `TestDispatchers` in a single test must share the same scheduler** — otherwise `advanceUntilIdle()` doesn't propagate. Pass the same `TestCoroutineScheduler` to each dispatcher.
2. **Replace the `Main` dispatcher** before testing anything that uses `viewModelScope`: `Dispatchers.setMain(testDispatcher)` in `@Before`, `Dispatchers.resetMain()` in `@After`.
3. **`UnconfinedTestDispatcher` vs `StandardTestDispatcher`** — `Unconfined` runs eagerly (simpler for most tests; assertions see latest state after each suspending call). `Standard` queues; advance via `advanceUntilIdle()` or `runCurrent()` — use when you need explicit control over scheduling order.

Use Turbine for Flow assertions:

```kotlin
viewModel.state.test {
    assertTrue(awaitItem().isLoading)
    val loaded = awaitItem()
    assertFalse(loaded.isLoading)
    cancelAndIgnoreRemainingEvents()
}
```

Do not use `delay()` or `Thread.sleep()` to wait for coroutines in tests.

# Kotlin Coroutines & Flow — DO / DON'T Reference

Rules for writing correct, testable, and production-safe coroutine code in Android and KMP projects. Based on official Android best practices and common production pitfalls.

---

## Structured Concurrency

**DO:**
- Use a lifecycle-bound scope (`viewModelScope`, `lifecycleScope`, or an injected `CoroutineScope`)
- Use `coroutineScope` when all children must succeed — one failure cancels siblings
- Use `supervisorScope` when children are independent — one failure doesn't affect others

**DON'T:**
- Never use `GlobalScope` — it bypasses structured concurrency, makes testing hard, and leaks coroutines. If work must outlive the current screen, inject an external `CoroutineScope` scoped to the Application or navigation graph
- Never use `runBlocking` in production code — it blocks the calling thread and defeats the purpose of coroutines. Acceptable only in `main()` functions and test bridges

**Scope ownership by layer:**

| Layer | Scope | Why |
|-------|-------|-----|
| ViewModel | `viewModelScope` | Tied to ViewModel lifecycle, survives config changes |
| UseCase / Repository | No own scope — inherits caller's | Caller controls cancellation |
| Work that must outlive screen | Injected `CoroutineScope` (Application-scoped) | Guaranteed completion even if user navigates away |

---

## Dispatcher Injection

**DO:**
- Accept `CoroutineDispatcher` as a constructor parameter — makes the class testable with `TestDispatcher`
- Use `Dispatchers.Default` for CPU-intensive work (sorting, parsing, computation)
- Use `Dispatchers.IO` for I/O operations (network, disk, database)
- Use `Dispatchers.Main` for UI updates (ViewModel layer on Android)

**DON'T:**
- Never hardcode `Dispatchers.IO` or `Dispatchers.Default` inside a class — inject them

```kotlin
// DO — testable, configurable
class DefaultOrderRepository(
    private val api: OrderApi,
    private val dispatcher: CoroutineDispatcher,
) : OrderRepository {
    override suspend fun getOrders(): List<Order> =
        withContext(dispatcher) { api.getOrders().map { it.toOrder() } }
}

// DON'T — hardcoded, untestable
class DefaultOrderRepository(
    private val api: OrderApi,
) : OrderRepository {
    override suspend fun getOrders(): List<Order> =
        withContext(Dispatchers.IO) { api.getOrders().map { it.toOrder() } }
}
```

---

## Suspend Functions Must Be Main-Safe

**DO:**
- Every `suspend fun` in the data/domain layer must be safe to call from the main thread
- Move blocking work off the main thread using `withContext(dispatcher)` inside the function
- The function is responsible for choosing the right dispatcher — not the caller

**DON'T:**
- Don't force callers to wrap your function in `withContext` — that's the function's job
- Don't do blocking I/O on the calling dispatcher

**Why:** Makes the app scalable. Callers don't need to worry about which `Dispatcher` to use.

---

## ViewModel Creates Coroutines

**DO:**
- Launch coroutines in ViewModel using `viewModelScope.launch { }`
- Expose state as `StateFlow` — not as `suspend fun` for the UI to call

**DON'T:**
- Don't expose `suspend fun` from ViewModel for business logic — the View shouldn't manage coroutine lifecycle
- Don't launch business-logic coroutines from the View/Activity/Fragment — delegate to ViewModel

**Exception:** Views can launch coroutines for UI-only work (fetching images, formatting strings).

---

## suspend vs Flow

**DO:**
- Use `suspend fun` for one-shot operations: fetch, save, delete — returns a single value
- Use `Flow` for multiple values over time: observe database, real-time updates, paginated streams
- Data and business layer should expose `suspend` functions and `Flow` — callers control execution and lifecycle

**DON'T:**
- Don't return `Flow` from a function that only emits once — use `suspend` instead
- Don't use `Flow` for fire-and-forget operations — use `suspend`

---

## StateFlow and SharedFlow

**DO:**
- Use `StateFlow` for UI state — always has a current value, replays the latest to new collectors
- Use `SharedFlow` for one-shot events (navigation, snackbar) — no replay by default
- Expose immutable `StateFlow` / `SharedFlow` — keep `MutableStateFlow` / `MutableSharedFlow` private
- Convert cold `Flow` to hot with `stateIn` / `shareIn`:

```kotlin
val orders: StateFlow<List<Order>> = getOrders()
    .stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = emptyList(),
    )
```

`WhileSubscribed(5_000)` keeps the upstream active for 5 seconds after the last subscriber disconnects — survives configuration changes without restarting the Flow.

**Android lifecycle awareness:**
- Use `SharingStarted.WhileSubscribed(stopTimeoutMillis)` when converting cold Flow to StateFlow in ViewModel. The timeout keeps the upstream alive during configuration changes (Activity recreation) so the Flow doesn't restart:

```kotlin
val orders: StateFlow<List<Order>> = getOrders()
    .stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = emptyList(),
    )
```

- `5_000` ms is the common default — long enough to survive a rotation, short enough to stop upstream when the user leaves the screen
- Collect in the UI layer with `collectAsStateWithLifecycle()` (Compose) or `flowWithLifecycle()` / `repeatOnLifecycle(Lifecycle.State.STARTED)` (Views) — these automatically unsubscribe when the UI goes to the background, and the `WhileSubscribed` timeout starts counting from that moment
- `SharingStarted.Eagerly` — starts immediately, never stops. Use only for app-wide state that is always needed
- `SharingStarted.Lazily` — starts on first collector, never stops. Use when you want caching without restart

**DON'T:**
- Don't expose `MutableStateFlow` directly — callers could mutate state from outside the ViewModel
- Don't use `SharingStarted.Eagerly` by default — it wastes resources when no one is collecting
- Don't collect StateFlow with plain `collect { }` in Activities/Fragments — it keeps collecting when the app is in the background. Always use lifecycle-aware collection

---

## Flow Operators

**DO:**
- `flowOn(dispatcher)` to switch the upstream dispatcher — apply once, at the producer side
- `catch { }` to handle upstream errors — place before terminal operators
- `retry(n) { cause -> cause is IOException }` for retriable operations — place before `catch`
- `map`, `filter`, `flatMapLatest`, `debounce`, `distinctUntilChanged` for transformations
- Prefer terminal operators (`first()`, `single()`, `toList()`) over collecting when only one value is needed

**DON'T:**
- Don't call `flowOn` multiple times in a chain — it only affects upstream operators
- Don't use `collect` when a terminal operator would suffice

---

## Avoiding Indefinite Suspension

Terminal operators like `first()`, `single()`, and `Channel.receive()` suspend until data arrives. If the source never emits, the coroutine hangs forever. This is a common production bug with event-driven flows where events may never occur.

**DO:**
- Bound waiting with `withTimeout` when the source may not emit: `withTimeout(5_000) { events.first() }`
- Use `firstOrNull()` when absence of data is a valid outcome, not an error
- Use `Channel.tryReceive()` for non-suspending checks when you can handle "nothing available" immediately
- Prefer `StateFlow` over `SharedFlow` when a current value is meaningful — `StateFlow.first()` returns immediately

**DON'T:**
- Don't call `first()` on a `SharedFlow(replay = 0)` without a timeout — new collectors see nothing until the next emission
- Don't assume an emission will arrive "soon" — always set explicit bounds in production code
- Don't use bare `Channel.receive()` on event channels where events are infrequent or optional

**Risk levels:**

| Source | `first()` risk | Mitigation |
|--------|---------------|------------|
| `StateFlow` | Safe — always has value | None needed |
| `SharedFlow(replay > 0)` | Low — replays last N values | Usually safe, but `withTimeout` for rare events |
| `SharedFlow(replay = 0)` | High — waits for next emit | Always use `withTimeout` |
| `Channel` | High — waits for `send()` | Use `tryReceive()` or `withTimeout` |
| Cold `flow { }` | Depends on producer | `withTimeout` if producer may not emit |

---

## Cancellation

**DO:**
- Always re-throw `CancellationException` — it signals structured cancellation:

```kotlin
try {
    api.fetchData()
} catch (e: CancellationException) {
    throw e
} catch (e: Exception) {
    handleError(e)
}
```

When using `runCatching`, check in `onFailure`:

```kotlin
runCatching { api.fetchData() }
    .onFailure { e ->
        if (e is CancellationException) throw e
        handleError(e)
    }
```

- Use `ensureActive()` or `yield()` in long-running loops for cooperative cancellation
- Use `withTimeout(millis)` for time-bounded operations
- Use `withContext(NonCancellable)` only in `finally` blocks for cleanup that must complete
- Parallel processing: `coroutineScope { items.map { async { process(it) } }.awaitAll() }`

**DON'T:**
- Never swallow `CancellationException` — it breaks structured concurrency
- Never catch generic `Exception` or `Throwable` without re-throwing `CancellationException` first
- Don't use `withContext(NonCancellable)` outside of cleanup — it prevents cancellation

---

## Error Handling in Coroutines

**DO:**
- Catch specific exception types (`IOException`, `HttpException`) rather than generic `Exception`
- Use `Result<T>` or a project-specific sealed type for expected failures at layer boundaries
- Map errors as they cross layer boundaries — don't leak `HttpException` to the domain layer
- In ViewModel: catch exceptions from `viewModelScope.launch` and update UI state

**DON'T:**
- Never have an empty `catch (e: Exception) {}` — every catch must handle or re-throw
- Never catch `CancellationException` (see Cancellation section)
- Don't let implementation exceptions (Retrofit, Room) propagate to the presentation layer

---

## Testing Coroutines

**DO:**
- Use `runTest` for all coroutine tests — it provides a `TestCoroutineScheduler`
- Inject `TestDispatcher` instead of real dispatchers — enables deterministic tests
- `UnconfinedTestDispatcher` — dispatches eagerly, simpler for most tests
- `StandardTestDispatcher` — queues dispatches, gives explicit control via `advanceUntilIdle()`
- All `TestDispatchers` in a test must share the same scheduler
- Use Turbine for testing Flow emissions:

```kotlin
@Test
fun `state emits loading then data`() = runTest {
    val viewModel = createViewModel()

    viewModel.state.test {
        val loading = awaitItem()
        assertTrue(loading.isLoading)

        val loaded = awaitItem()
        assertFalse(loaded.isLoading)
        assertEquals(2, loaded.orders.size)

        cancelAndIgnoreRemainingEvents()
    }
}
```

- Replace `viewModelScope` dispatcher in tests using `Dispatchers.setMain(testDispatcher)`

**DON'T:**
- Don't use `delay()` or `Thread.sleep()` in tests to wait for coroutines — use `advanceUntilIdle()` or Turbine
- Don't hardcode dispatchers — it makes `TestDispatcher` injection impossible

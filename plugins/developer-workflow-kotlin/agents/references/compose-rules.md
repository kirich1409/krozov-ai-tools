# Compose Rules

Project-specific Compose conventions and non-obvious gotchas that go beyond what a modern model writes by default. Generic Compose idioms — `remember` for cached values, `rememberSaveable` for config changes, `LazyColumn` `key` for dynamic items, `derivedStateOf` for derived state, state hoisting, UDF, PascalCase, `on*` callbacks — are **not** documented here; trust the model and Compose Lint.

This file lists only:
- Genuinely non-obvious rules the model omits without a reminder
- Project-config-dependent behavior (stability under strong skipping)
- Strong opinions where the model's default differs

For coroutines inside composables (`LaunchedEffect`, `rememberCoroutineScope`, Flow collection), see `coroutines.md`. For Kotlin language style, see `kotlin-style.md`.

---

## Screen Pattern

The screen composable must be **stateless**:

```kotlin
@Composable
internal fun FooScreen(
    state: FooState,
    onAction: (FooAction) -> Unit,
    modifier: Modifier = Modifier,
)
```

- `viewModel()` / `hiltViewModel()` / `koinViewModel()` is resolved **once at the navigation entry point** (`FooRoute`), never inside `FooScreen` and never inside reusable shared components.
- Never pass a `ViewModel` as a composable parameter — the model sometimes does this for convenience; it breaks reusability and previewability.

## Forbidden Parameter Types

Never accept these as composable parameters:

- `MutableState<T>` — hoist as `value: T` + `onValueChange: (T) -> Unit`
- `State<T>` — pass the value directly
- `ViewModel` — see Screen Pattern above

The model occasionally takes a `MutableState` shortcut. Don't.

## Custom Modifiers — Modifier.Node, never `composed {}`

`Modifier.composed {}` is deprecated and ~80% slower (allocates per-composition, defeats modifier sharing). The model still emits `composed {}` from older training data — explicitly choose `Modifier.Node`:

| Scenario | Approach |
|---|---|
| Combination of existing modifiers | Plain extension chain |
| Needs animation or `CompositionLocal` | `@Composable` Modifier factory |
| Drawing, layout, input, semantics | `Modifier.Node` + `ModifierNodeElement` |

```kotlin
private class FooNode(...) : Modifier.Node(), DrawModifierNode {
    override fun ContentDrawScope.draw() { /* ... */ }
}
private data class FooElement(...) : ModifierNodeElement<FooNode>() {
    override fun create() = FooNode(...)
    override fun update(node: FooNode) { /* update fields */ }
}
fun Modifier.foo(...): Modifier = this then FooElement(...)
```

## Stability — Project-Config-Dependent

Whether `@Stable` / `@Immutable` matter depends on Compose Compiler config:

- **Strong skipping mode** (default in Compose Compiler 2.0+ / Kotlin 2.0+) → annotations are **less critical**; the compiler skips even unstable parameters. Plain `List` / `Map` work for skipping. Annotations remain useful as documentation of intent.
- **Strong skipping disabled** (`composeCompiler { enableStrongSkippingMode.set(false) }` or older compiler) → annotations are important. Collections are unstable; use `kotlinx.collections.immutable` (`ImmutableList`) if the project does.

**Always match the project's existing convention.** If existing state classes use `@Immutable`, add it to new ones for consistency. Check `stability_config.conf` for cross-module rules if it exists.

## Performance — Phase Deferral via Lambda Modifiers

Compose runs in three phases: **Composition → Layout → Drawing**. Lambda-based modifier overloads let the runtime skip earlier phases when only later phases need to update. The model often picks the value-based overload by reflex.

```kotlin
// Good — skips composition, runs only in layout
Box(Modifier.offset { IntOffset(offsetX().roundToInt(), 0) })

// Bad — full recomposition every frame
Box(Modifier.offset(x = offsetX.dp, y = 0.dp))

// Good — skips composition + layout, runs only in draw
Box(Modifier.fillMaxSize().drawBehind { drawRect(animatedColor) })

// Bad — recomposes every frame
Box(Modifier.fillMaxSize().background(animatedColor))
```

When passing a frequently-changing `State` into a modifier, prefer the lambda overload (`offset { }`, `drawBehind { }`, `graphicsLayer { }`).

Also: pass `() -> T` instead of `T` to defer reads in custom composables when the value updates often.

## Side Effects — `rememberUpdatedState` for long-lived effects

Inside `LaunchedEffect(Unit)` or `DisposableEffect`, lambda parameters captured directly will be the value from when the effect *started* — not the latest. Use `rememberUpdatedState` to keep the captured callback fresh without restarting the effect:

```kotlin
@Composable
fun FooScreen(onTimeout: () -> Unit) {
    val currentOnTimeout by rememberUpdatedState(onTimeout)
    LaunchedEffect(Unit) {
        delay(5_000)
        currentOnTimeout() // always the latest lambda
    }
}
```

The model sometimes captures the original lambda directly and ships a stale callback bug.

## Exhaustive `when` Without `else`

`when` over a sealed state / action type **must be exhaustive without an `else` branch**. The compiler must catch missing cases when a new subtype is added. The model occasionally writes `else -> {}` to silence the compiler — that silently swallows new subtypes.

```kotlin
when (action) {
    is FooAction.ItemClicked -> handle(action.id)
    FooAction.Refresh -> refresh()
    // No else — adding a new FooAction subtype must be a compile error.
}
```

## Theme Tokens — No Raw `dp` / Hex

If the project has a token system (`AppDimens.spacingM`, `AppColors.primary`, `AppTypography.titleMedium`) — never emit raw `dp` literals or hex color values in screen code. Use the tokens.

If the project does not have tokens and uses `MaterialTheme.colorScheme.x` directly — match that. Discovered in Step 1 of compose-developer.

## Accessibility — Beyond `contentDescription`

The model writes `contentDescription` by default. Often missed:

- **`Modifier.semantics { role = Role.Button }`** on custom interactive composables (custom click handling without using `Button`/`IconButton`)
- **`mergeDescendants = true`** on compound rows where the screen reader should read title + subtitle as a single unit
- **`Modifier.minimumInteractiveComponentSize()`** when the visual element is smaller than 48×48 dp but is interactive

```kotlin
Icon(
    imageVector = Icons.Default.Close,
    contentDescription = stringResource(R.string.close),
    modifier = Modifier
        .clickable(role = Role.Button) { onAction(FooAction.Dismiss) }
        .minimumInteractiveComponentSize(),
)
```

## KMP / Compose Multiplatform

- No `android.*` / `java.*` / `javax.*` / `dalvik.*` in `commonMain`
- Resources via `org.jetbrains.compose.resources` API — **the API has changed multiple times across CMP versions**. Read project's existing resource usage; do not assume.
- `expect`/`actual` only for platform-specific implementation; UI logic in `commonMain`
- Verify every dep has KMP artifacts before using in common code
- Platform-specific UI (iOS touch handling, SwiftUI / UIKit interop, desktop) — verify against current docs, do not assume API shapes

## Previews — Never the ViewModel

A preview receives **hardcoded state**, never `viewModel()` / a repository / real data. The model occasionally wires VMs into previews "for realism" — that breaks tooling and often makes previews uncompilable.

Previews are always `private`, always wrapped in the project's theme composable. Multi-state coverage (loading / error / empty / populated) is the screen-preview convention.

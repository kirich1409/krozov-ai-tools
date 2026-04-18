# Compose Rules

Rules for writing Jetpack Compose / Compose Multiplatform UI code.

## Stateless vs Stateful

- Reusable and shared components must be **stateless**: accept data and lambda callbacks as parameters, own no state
- `remember` is for **UI element state only** (animations, focus, scroll position) — never for business data
- `rememberSaveable` when UI state must survive configuration changes
- Screen-level composables (`FooScreen`) may be stateful via ViewModel, but still pass state down as a plain object

## State Hoisting — Three Rules (Android Developers)

1. Hoist state to the **lowest common ancestor** of all composables that read it
2. Hoist no lower than the **highest level where it is written**
3. Two states that change together in response to the same event → hoist together

State goes **down**, events go **up** (Unidirectional Data Flow).

## Screen Pattern (MVI)

```kotlin
@Composable
fun FooScreen(
    state: FooState,
    onAction: (FooAction) -> Unit,
)
```

- Never pass a ViewModel as a parameter to a composable
- Never call `viewModel()` inside a reusable component — only at the screen root
- ViewModel is resolved once at the navigation/screen entry point and converted to `state: FooState`

## Splitting Composables

- Split a composable into sub-components when parts are logically independent or reusable — not by line count
- Private helper composables live in the same file as the public composable they serve

## Preview

- Add `@Preview` where the component is visually non-trivial or reused across screens
- Provide separate `@Preview` functions for distinct states: loading, error, empty, populated
- Previews always use a hardcoded `FooState(...)` — never a ViewModel or real data source

## Side Effects

- `LaunchedEffect(key)` — for one-shot events triggered by state changes (navigation, snackbar)
- `SideEffect` — for syncing Compose state with non-Compose APIs
- Never launch coroutines directly in composable body; use `LaunchedEffect` or `rememberCoroutineScope`
- Never write to state after reading it in the same composition (backwards write causes infinite recomposition)

## Performance

- Wrap expensive calculations in `remember(key) { }` or move them to ViewModel
- When a composable only needs to read a frequently-changing state value for layout/drawing, pass it as `() -> T` to defer the read and narrow the recomposition scope

## Naming

- Composable functions → `PascalCase` (treated as a UI noun, not a verb)
- Callback parameters → `on` + verb: `onClick`, `onValueChange`, `onDismiss`, `onRetry`

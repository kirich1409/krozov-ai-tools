# View → Compose Component Mapping

## Common Migrations

**RecyclerView with adapter** → `LazyColumn`/`LazyRow`. The adapter logic (diffing, item types, binding) maps to composable item functions and `key` parameters. Don't forget the click handlers from `onBindViewHolder`.

**Custom View (no drawing)** → A composable function placed in the shared UI module. Map `attrs.xml` attributes to function parameters. Replace `setListener`/`setXxx` setters with lambda parameters. Replace saved instance state with `rememberSaveable`.

**Wrapping a View in `AndroidView {}`** → This is **not a migration to Compose** — it is interop. Acceptable only when there is genuinely no Compose equivalent. Before using `AndroidView`, explicitly tell the user: "I'm proposing to wrap `FooView` in `AndroidView` rather than rewriting it — this keeps the old View running inside Compose." Wait for agreement. Never use `AndroidView` silently as a migration shortcut.

**Custom ViewGroup (layout logic in `onMeasure`/`onLayout`)** → A `Layout` composable or a combination of built-in layout composables. Custom measure/layout logic maps to `MeasurePolicy`. Non-trivial — flag and budget extra time.

**Custom View with `onDraw`** → **STOP and flag this explicitly to the user.** This is the **highest-risk migration type**. Tell the user what makes it complex (paths, clipping, layer operations), that it deserves its own isolated PR, and that screenshot comparison on a real device is strongly recommended. Implementation uses `Canvas { }` with `DrawScope`. Never wrap in `AndroidView` as a shortcut.

**Data binding / two-way binding** → Compose has no two-way binding. Model all mutations as explicit callbacks (`onValueChange`, `onCheckedChange`). ViewModel holds the source of truth.

**Fragment with back stack** → In Compose Navigation, back stack is handled by the nav graph. `onBackPressed` maps to `BackHandler` composable.

## Animation Mapping

Never drop animations silently. Every animation inventoried in Phase 1 must have a Compose equivalent or a documented user-approved deferral.

| View animation | Compose equivalent | Notes |
|---|---|---|
| `view.animate().alpha(0f)` / fade | `AnimatedVisibility` with `fadeIn`/`fadeOut` | Use `animateFloatAsState` for direct alpha control |
| `view.animate().translationY(...)` | `animateFloatAsState` + `Modifier.offset` or `AnimatedVisibility` with `slideIn`/`slideOut` | |
| `view.animate().scaleX/Y(...)` | `animateFloatAsState` + `Modifier.scale` | |
| `ObjectAnimator` / `ValueAnimator` | `Animatable` + `LaunchedEffect` | Drive from a coroutine |
| `AnimatorSet` (chained/parallel) | Multiple `Animatable` coordinated in coroutine | `launch` for parallel, sequential `await` for chained |
| `LayoutTransition` | `AnimatedVisibility` per child + `animateContentSize()` | `animateItem()` in `LazyColumn` for list items |
| `RecyclerView` item animation | `LazyColumn` + `animateItem()` (Compose 1.7+) | Older: `AnimatedVisibility` per item |
| Fragment enter/exit transition | `AnimatedContent` or NavHost `enterTransition`/`exitTransition` | |
| Fragment shared element | `SharedTransitionLayout` + `SharedTransitionScope` (1.7+) | High effort — consider deferring |
| Activity `overridePendingTransition` | Compose Navigation `enterTransition`/`exitTransition` | |
| `MotionLayout` | No direct equivalent — **must be decomposed** | See below |

**MotionLayout** is the highest-risk animation migration. In Compose, the equivalent is typically a combination of `AnimatedContent`, `animateFloatAsState`, custom `Animatable` coroutines, and possibly `InfiniteTransition`. Almost always deserves its own PR.

**Material component built-in animations** (FAB morph, BottomSheet, NavigationDrawer slide) are handled automatically by Material3 Compose components — verify visually during device testing.

## WindowInsets and Edge-to-Edge

One of the most common silent regressions in Activity migrations.

*Activity migration:*
- Call `enableEdgeToEdge()` in `onCreate()` before `setContent {}`
- Use `Scaffold` — it handles system bar insets automatically
- Remove manual status bar padding if present

*Keyboard / IME:*
- Text input screens **must** have `Modifier.imePadding()` on the outermost scrollable container
- `windowSoftInputMode="adjustResize"` → `Modifier.imePadding()` + scrollable container

*Mapping:*

| Old (View / XML / Manifest) | Compose equivalent |
|---|---|
| `android:fitsSystemWindows="true"` | `Scaffold` or `Modifier.systemBarsPadding()` |
| `windowSoftInputMode="adjustResize"` | `Modifier.imePadding()` on scrollable container |
| `windowSoftInputMode="adjustPan"` | `Modifier.imePadding()` + scrollable content |
| `setPadding(0, statusBarHeight, 0, 0)` | `Modifier.statusBarsPadding()` |
| `setPadding(0, 0, 0, navBarHeight)` | `Modifier.navigationBarsPadding()` |
| Hardcoded status bar height | `WindowInsets.statusBars.asPaddingValues()` |
| Content avoiding all bars + IME | `Modifier.safeContentPadding()` |

*Fragment migration:* Fragments inherit insets from the host. In Compose, pass `WindowInsets` down explicitly or let `Scaffold` consume them.

## Specific Component Mappings

**ViewPager2 + TabLayout** → `HorizontalPager` + `TabRow`. `pagerState.currentPage` drives tab selection; tab clicks call `pagerState.animateScrollToPage(index)`. Fragment-based `FragmentStateAdapter` moves into composable pages.

**CoordinatorLayout + AppBarLayout + CollapsingToolbarLayout** → `Scaffold` + `TopAppBar` (Large or Medium variant) + `TopAppBarScrollBehavior` + `Modifier.nestedScroll(scrollBehavior.nestedScrollConnection)`. Title transition maps to built-in collapse behavior.

**Toolbar / ActionBar with menus** → `TopAppBar` with `actions = { ... }` slot. Menu items become `IconButton` or `DropdownMenu` entries. Navigation icon maps to `navigationIcon` slot.

**BottomSheetDialogFragment** → `ModalBottomSheet`. Fragment's `onCreateView` becomes the content lambda. State (`BottomSheetBehavior.STATE_*`) maps to `SheetValue` in `rememberModalBottomSheetState`.

**ItemTouchHelper (swipe/drag)** → `SwipeToDismissBox` for swipe-to-dismiss. Drag-to-reorder: `Modifier.draggable` or `Modifier.pointerInput`. Both are meaningfully more code — flag and budget extra time.

**ActivityResultLauncher / permissions** → `rememberLauncherForActivityResult` (results) and `rememberPermissionState` / `rememberMultiplePermissionsState` (Accompanist Permissions). Launchers must be remembered at composition time.

**Focus management in forms** → `FocusRequester` + `SoftwareKeyboardController`. Replace `editText.requestFocus()` with `focusRequester.requestFocus()` inside `LaunchedEffect`. Tab-order: chain `FocusRequester` instances via `KeyboardOptions(imeAction = ImeAction.Next)`.

**Toast** → No `Toast.makeText` equivalent in Compose. Replace with `SnackbarHost` + `SnackbarHostState`, or temporary `SideEffect { Toast.makeText(...).show() }`.

**`View.post { }` / `Handler.postDelayed { }`** → `LaunchedEffect` for one-shot operations, `SideEffect` for every-recomposition sync. `Handler.postDelayed` → `LaunchedEffect { delay(ms); doSomething() }`.

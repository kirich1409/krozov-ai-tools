# Discovery, Patterns & Gap Analysis — Detailed Reference

## Source Type Table

| Source type | Composes into | Key things to capture |
|---|---|---|
| **Activity** | Screen composable + nav entry point | `onCreate` setup, intent extras, window flags, `onBackPressed`, result contracts |
| **Fragment** | Screen composable + nav destination | `onViewCreated`, arguments/nav args, `FragmentManager` interactions, shared element transitions |
| **Custom View / ViewGroup** | Reusable composable (goes into shared UI module, not a screen) | Constructor attrs, `onMeasure`/`onLayout` if overridden, `onDraw`, public API (properties, listeners), saved state via `onSaveInstanceState` |

## What to Read in Discovery

- The XML layout file(s) — view hierarchy, constraints, IDs, hardcoded styles, `tools:` attributes
- The host class (Activity / Fragment / View subclass) — lifecycle hooks, binding setup, click listeners, observers, any direct `canvas` usage
- The ViewModel (if present) — state it exposes, actions it accepts, and **what stream type it uses** (StateFlow, LiveData, RxJava Observable, etc.)
- Any nested custom Views — each is a potential gap item; note their public API
- Any adapters (RecyclerView, ViewPager) — these need full replacement in Compose
- Resource files referenced: drawables, styles, attrs, dimens, colors

## Animation Inventory

While reading the code, explicitly inventory all animations:
- `view.animate()` / `ViewPropertyAnimator` calls (fade, translate, scale, rotation)
- `ObjectAnimator` / `ValueAnimator` / `AnimatorSet`
- `LayoutTransition` on a `ViewGroup` (automatic animate children add/remove)
- `RecyclerView` item animations (default `DefaultItemAnimator` or custom)
- Fragment transitions (`setEnterTransition`, `setExitTransition`, shared element transitions)
- Activity transitions (`overridePendingTransition`, window transitions)
- `MotionLayout` scenes
- XML `<animation>` / `<animator>` resources referenced from code
- Material component built-in animations (FAB expand, BottomSheet slide-up, etc.)

Note each one in the behavior-scenarios document under a dedicated **Animations** section.

## Behavior Scenarios Template

As part of discovery, produce a `behavior-scenarios.md` for the target screen. This document captures everything the screen does and becomes the verification checklist used after migration.

Structure it as a flat list of scenarios, grouped by area:

**Visual states** — every distinct appearance the screen can have:
- Initial / loading state
- Populated state (what data looks like when present)
- Empty state (what shows when there's nothing to display)
- Error state (what shows when something failed)
- Any partial states (e.g. list with a loading footer, refreshing over existing content)

**Interactions** — every tap, swipe, or input the user can perform:
- Each button: what it does, whether it shows feedback (ripple, disable while loading, etc.)
- Each list item: tap behavior, swipe behavior, long press if any
- Each input field: keyboard type, IME action, validation trigger
- Pull-to-refresh, scroll behavior, infinite scroll if present

**Side effects** — things triggered by interactions or state changes:
- Navigation events (which destination, what data is passed)
- Snackbars, toasts, dialogs
- Animations and transitions (item appear/disappear, shared element, content size change)

**Edge cases visible from the code:**
- Behavior when the back button is pressed
- Behavior on configuration change (rotation)
- Behavior when the screen is entered with specific arguments/extras

Example entry:
```
## Cancel order button
- Visible only for orders with status PENDING or IN_PROGRESS
- Tap: calls ViewModel.onCancelOrder(order), shows loading state on that item
- On success: item disappears from list
- On error: snackbar shown with error message
```

## Phase 2: Analyze Existing Compose Patterns

**This step is mandatory.** Find all existing Compose screens in the project and understand how they're built.

Launch the `compose-developer` agent to discover project patterns. Brief it to analyze existing Compose screens and produce a **Pattern Summary** covering: architecture patterns (screen structure, state/action model shape, ViewModel resolution, parameterless action convention, string type in state), theme and design system (color tokens, typography, spacing/dimension tokens, Material version), shared UI components (what exists and where), code style conventions (visibility, stability annotations, composable body length, preview style), and navigation (library, route definition, screen registration).

The agent's Step 1 is designed for exactly this — it will read 2–3 representative screens end-to-end and extract all pattern findings into a structured summary.

### Migration-specific discovery

In addition to the agent's Pattern Summary, determine these migration-specific items yourself:

**State stream conventions**
- What stream type do existing ViewModels expose — `StateFlow`, `LiveData`, `RxJava`? Note the dominant pattern.
- If the ViewModel being migrated uses a legacy stream type (LiveData, RxJava), note it and propose migrating to `StateFlow` as part of this work — unless the user explicitly defers it.

**Event transport compatibility** — verify that the project's parameterless action convention (from the Pattern Summary) is compatible with the event transport mechanism. Singleton objects (`object`/`data object`) are equal to themselves, so they will be deduplicated by `StateFlow`/`LiveData`/`distinctUntilChanged`. `Channel` and `SharedFlow` emit every event regardless of instance identity, so singletons are safe there. If there's a mismatch, note it.

## Phase 3: Gap Analysis

For each UI element in the target screen that has no direct shared Compose equivalent, resolve it using this priority order:

**1. Existing UI Kit / design system** — check the project's shared UI module (often named `uikit`, `designsystem`, `ui-components`, or similar). This is always the first place to look.

**2. Already-imported libraries** — check the project's Gradle dependency declarations. Libraries like Material 3, Accompanist, Coil, or any component library already on the classpath may already provide what's needed.

**3. Suggest adding a library** — if a well-established library would solve the gap cleanly and the project doesn't have it yet, propose it to the user. Wait for approval before adding it.

**4. Write a custom component** — if none of the above applies, implement a new shared composable. Place it in the appropriate shared UI module so it's available to other screens too.

For each gap, document which option you're proposing and why.

**For any gap that requires adding a new library or replacing an existing one:**
- Well-known and obviously the right fit → propose with brief rationale
- Less obvious or requires evaluating alternatives → present options with trade-offs and wait
- Never add a dependency to `build.gradle.kts` without user approval

**Special case — Custom View migration:**

Custom Views used on the migrated screen **must be migrated to Compose equivalents** as part of this migration. Wrapping a project-owned custom View in `AndroidView` is not acceptable — it defeats the purpose of the migration and will be caught by the View API Audit (Phase 8). `AndroidView` wrapping is allowed **only** for third-party Views with no Compose equivalent (e.g. `MapView`, `WebView`, `PlayerView`).

See `references/custom-view-migration.md` for the full decision tree: classify the View → search for existing replacements (Material3 → project UI kit → imported libraries → new library) → assess custom implementation feasibility → choose a migration strategy (inline / pre-migration component / dedicated sub-task).

State the result of each search step explicitly, even when the answer is "no existing equivalent found".

## Phase 4: Confirm

Before writing any Compose code, present a migration plan:

**0. Behavior scenarios review** — share `behavior-scenarios.md` with the user for confirmation

**1. What you found** — screen structure summary, ViewModel contract, key interactions, risky areas

**2. Patterns you'll follow** — from Phase 2

**3. Gaps and decisions** — from Phase 3 with proposed resolutions

**4. Migration strategy** — based on complexity:
- **Simple screen**: migrate in a single pass
- **Moderately complex**: migrate in one PR but keep old code intact until QA
- **Complex screen**: split into sub-tasks (shared components → screen → animation/effects)

**Screenshot testing — propose for moderately complex and complex screens:**
Screenshot tests (Paparazzi or Roborazzi) run on the JVM without a device. Propose when the screen has multiple distinct visual states, custom drawing, or is high-risk. If the project already uses Paparazzi or Roborazzi, use that; otherwise propose adding (Roborazzi for KMP, Paparazzi for Android-only).

**5. Scope** — what's in this migration and what's explicitly deferred

Wait for explicit user approval before continuing.

## Phase 5: Implement Gaps First

Resolve missing components **before** writing the screen:
- **UI Kit match found** → confirm import path, move on
- **Already-imported library** → confirm API, move on
- **New library approved** → add dependency, sync, verify
- **Custom View migration** → migrate each project-owned custom View to a Compose composable using the `compose-developer` agent. This is mandatory — `AndroidView` wrapping of project-owned Views is not acceptable. Place the new composable in the shared UI module.
- **Custom component needed** (not a View migration) → implement in shared UI module using `compose-developer` agent; each new component gets at least one `@Preview`. **Name the target module explicitly.**

Do not implement the screen migration and new shared components at the same time. Migrate custom Views first, then proceed to the screen.

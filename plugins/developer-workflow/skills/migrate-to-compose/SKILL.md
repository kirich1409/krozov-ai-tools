---
name: migrate-to-compose
description: Use when migrating any Android View-based UI to Jetpack Compose — whether the source is an Activity, a Fragment, or a standalone custom View/ViewGroup. Invoke proactively whenever the user says "migrate to Compose", "convert this screen to Compose", "rewrite in Compose", "move to Compose", "this screen needs Compose", "replace XML layout", "drop this fragment", "convert this Activity", "replace this custom view", "rewrite this ViewGroup", or asks how to approach a View→Compose migration for a specific screen or component. Covers: analyzing the existing View-based implementation regardless of its host (Activity/Fragment/custom View), discovering patterns from screens already written in Compose, identifying shared components that need to be built first, capturing a visual baseline via screenshot, implementing the Compose equivalent, and verifying both visual fidelity and structural consistency. Do NOT use for: migrating entire apps at once (do it screen-by-screen), KMP migrations (use kmp-migration instead), or non-UI code rewrites.
---

# Migrate to Compose

## Overview

**Core principle:** Understand the screen deeply before touching it → discover how the rest of the app uses Compose → identify what's missing → capture a visual baseline → migrate → verify appearance and structure match.

A Compose migration is not just a syntax swap. The goal is a screen that behaves identically, looks identical (or better), and fits naturally into the codebase — using the same patterns, the same theme tokens, the same shared components that every other Compose screen uses.

Never write a single line of Compose until the pattern analysis and gap analysis are done. A screen that works but looks nothing like the rest of the app is a failed migration.

### Scope discipline — what this migration is NOT

**Do not do any of the following without explicit user approval:**
- Fix existing bugs in the original screen — if the old screen had a bug, the new screen should have the same bug. Note it and ask.
- Add features that didn't exist — no tablet layouts, no landscape support, no new states, no new interactions unless explicitly requested.
- Improve UX, spacing, or visual design beyond what's needed to make Compose look identical to the original.
- Refactor business logic, naming, or architecture outside the UI layer.

**When you encounter a bug or missing feature during migration:**
Do not fix it silently. Add it to a dedicated **"Issues found"** section in the migration report, describe the problem clearly, and ask the user: "This bug exists in the original — do you want to fix it as part of this migration, or track it separately?" Then follow their decision.

**Special case — unavoidable behavior differences:** Some View behaviors have no exact Compose equivalent (e.g. a bug in `ItemTouchHelper` that doesn't exist in `SwipeToDismissBox`, or a `MotionLayout` animation that can't be replicated identically). In these cases: document the difference, propose the closest Compose behavior, and ask the user to confirm the acceptable deviation before proceeding.

## Workflow

```
DISCOVER → ANALYZE PATTERNS → GAP ANALYSIS → CONFIRM → IMPLEMENT GAPS → MIGRATE → STATIC VERIFY → [device: manual-tester agent (QA)]
```

---

## Phase 1: Discover

First, identify what kind of View-based source you're dealing with — this shapes the migration strategy:

| Source type | Composes into | Key things to capture |
|---|---|---|
| **Activity** | Screen composable + nav entry point | `onCreate` setup, intent extras, window flags, `onBackPressed`, result contracts |
| **Fragment** | Screen composable + nav destination | `onViewCreated`, arguments/nav args, `FragmentManager` interactions, shared element transitions |
| **Custom View / ViewGroup** | Reusable composable (goes into shared UI module, not a screen) | Constructor attrs, `onMeasure`/`onLayout` if overridden, `onDraw`, public API (properties, listeners), saved state via `onSaveInstanceState` |

Then read every file that makes up the target:

- The XML layout file(s) — view hierarchy, constraints, IDs, hardcoded styles, `tools:` attributes
- The host class (Activity / Fragment / View subclass) — lifecycle hooks, binding setup, click listeners, observers, any direct `canvas` usage
- The ViewModel (if present) — state it exposes, actions it accepts, and **what stream type it uses** (StateFlow, LiveData, RxJava Observable, etc.). Note this explicitly — it determines how state is collected in the Compose layer and whether a migration to StateFlow should be proposed.
- Any nested custom Views — each is a potential gap item; note their public API
- Any adapters (RecyclerView, ViewPager) — these need full replacement in Compose
- Resource files referenced: drawables, styles, attrs, dimens, colors — especially anything declared in `attrs.xml` for custom Views

Build a mental model of:
1. What data is displayed and where it comes from
2. What user interactions exist and what they trigger
3. Which parts are complex or risky (custom drawing, animations, accessibility, saved instance state)

While reading the code, explicitly inventory all animations — they are easy to miss and silently drop during migration:
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

### Behavior scenarios document

As part of discovery, produce a `behavior-scenarios.md` for the target screen. This document captures everything the screen does and becomes the verification checklist used after migration. The source of truth is the code you just read — supplement it with any existing spec, test plan, or QA document if found in the project.

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

**Side effects** — things triggered by interactions or state changes that happen outside the screen:
- Navigation events (which destination, what data is passed)
- Snackbars, toasts, dialogs
- Animations and transitions (item appear/disappear, shared element, content size change)

**Edge cases visible from the code** — anything that stands out:
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

This document is reviewed and confirmed with the user in Phase 4. After migration it becomes the verification checklist — both for Phase 7 code review and for the `manual-tester` device agent.

---

## Phase 2: Analyze Existing Compose Patterns

**This step is mandatory.** Find all existing Compose screens in the project and understand how they're built. You're looking for the conventions this specific codebase has already established.

Launch the `compose-ui-architect` agent to discover project patterns. Brief it to analyze existing Compose screens and produce a **Pattern Summary** covering: architecture patterns (screen structure, state/action model shape, ViewModel resolution, parameterless action convention, string type in state), theme and design system (color tokens, typography, spacing/dimension tokens, Material version), shared UI components (what exists and where), code style conventions (visibility, stability annotations, composable body length, preview style), and navigation (library, route definition, screen registration).

The agent's Step 1 is designed for exactly this — it will read 2–3 representative screens end-to-end and extract all pattern findings into a structured summary.

### Migration-specific discovery

In addition to the agent's Pattern Summary, determine these migration-specific items yourself:

**State stream conventions**
- What stream type do existing ViewModels expose — `StateFlow`, `LiveData`, `RxJava`? Note the dominant pattern.
- If the ViewModel being migrated uses a legacy stream type (LiveData, RxJava), note it and propose migrating to `StateFlow` as part of this work — unless the user explicitly defers it.

**Event transport compatibility** — verify that the project's parameterless action convention (from the Pattern Summary) is compatible with the event transport mechanism. Singleton objects (`object`/`data object`) are equal to themselves, so they will be deduplicated by `StateFlow`/`LiveData`/`distinctUntilChanged`. `Channel` and `SharedFlow` emit every event regardless of instance identity, so singletons are safe there. If there's a mismatch, note it.

Document all findings — they become the constraint set for Phase 6.

---

## Phase 3: Gap Analysis

Based on what the target screen needs and what already exists in the Compose layer, identify what's missing.

For each UI element in the target screen that has no direct shared Compose equivalent, resolve it using this priority order:

**1. Existing UI Kit / design system** — check the project's shared UI module (often named `uikit`, `designsystem`, `ui-components`, or similar). Search for composables that match the needed behavior or appearance. This is always the first place to look.

**2. Already-imported libraries** — check the project's Gradle dependency declarations. Libraries like Material 3, Accompanist, Coil, or any component library already on the classpath may already provide what's needed. Prefer using what's already there — no new dependency, no approval needed.

**3. Suggest adding a library** — if a well-established library would solve the gap cleanly and the project doesn't have it yet, propose it to the user. Explain what it provides and why it fits. Wait for approval before adding it. Example: "The screen needs an image cropper — `ucrop` has a Compose wrapper; would you like to add it?"

**4. Write a custom component** — if none of the above applies, implement a new shared composable. Place it in the appropriate shared UI module (not inside the screen file) so it's available to other screens too. Follow the patterns from Phase 2.

For each gap, document which option you're proposing and why. Example:
- "Loading skeleton — no existing component; `shimmer` library is not yet imported; proposing to write a custom `ShimmerBox` composable in the UI kit"
- "Bottom sheet — Material 3 `ModalBottomSheet` covers this; already on classpath"
- "Star rating widget — a `RatingBar` composable exists in `uikit` module; will use that"

**For any gap that requires adding a new library or replacing an existing one:**
- If the library is well-known and obviously the right fit (e.g. adding `material3` pull-to-refresh on a project already using Material3), propose it with a brief rationale
- If the library is less obvious, requires evaluating alternatives, or has a non-trivial API surface, do not decide alone — present the options with trade-offs and wait for the user's choice
- Never add a dependency to `build.gradle.kts` without the user explicitly approving it

**Special case — Custom View migration:** When the source is a Custom View (not a screen), the gap analysis must include an explicit prior-art check before deciding to write custom code. Specifically:
1. Name-check Material3 components — does it already have an equivalent? (e.g. `Slider` for a custom seek bar, `LinearProgressIndicator` for a custom progress view, `RatingBar`-style input — check if Material3 provides anything close)
2. Check the project's UI kit module — does it already have a composable equivalent?
3. Check already-imported libraries on the classpath — any component library that might cover it?

State the result of each check explicitly in the migration plan, even when the answer is "no existing equivalent found" — this shows the decision wasn't made blindly.

**Present this list to the user and confirm before proceeding.**

---

## Phase 4: Confirm

Before writing any Compose code, present a migration plan and agree on strategy with the user.

**0. Behavior scenarios review** — share the `behavior-scenarios.md` from Phase 1 with the user. Ask them to confirm: are all scenarios captured correctly? Are there any edge cases, documented QA scenarios, or known quirks not visible from the code? Incorporate their additions before proceeding. This document is the ground truth for all verification steps that follow.

**1. What you found** — screen structure summary, ViewModel contract, key interactions, any risky areas identified in Phase 1

**2. Patterns you'll follow** — from Phase 2: state/action model shape, theme tokens, nav approach, string resource conventions

**3. Gaps and decisions** — the list from Phase 3 with proposed resolutions, including any dependency additions that need approval

**4. Migration strategy** — propose how to approach this migration given its complexity:
- Check whether the project has a pre-defined migration guide or established migration conventions. If it does, base the strategy on that.
- For a **simple screen** (static layout, few interactions, no custom views): migrate in a single pass, replace Fragment/Activity directly
- For a **moderately complex screen** (RecyclerView, multiple states, adapters): migrate in one PR but keep old code intact until QA pass
- For a **complex screen** (custom drawing, animations, deep Fragment back-stack logic, significant business logic): consider splitting into sub-tasks — shared components first, then screen migration, then animation/effects
- Propose whether any parts of the migrated screen should be covered by new UI tests (especially if the original had tests, or if the component has non-trivial interaction logic)

**Screenshot testing — propose this for moderately complex and complex screens:**
Screenshot tests (Paparazzi or Roborazzi) run on the JVM without a device and render Compose composables to a bitmap for visual comparison. They are especially useful during migration because they let you verify rendering quality before ever launching the app — no need to navigate through auth flows or reach deep screens manually.

Propose adding screenshot tests when:
- The screen has multiple distinct visual states (loading, error, empty, populated)
- The screen contains custom drawing or complex layout
- The migration is high-risk and you want a fast feedback loop before device testing

Ask the user whether to:
1. **Add screenshot tests as part of the migration** — write them alongside the Compose code; they can be kept permanently as regression guards or removed after the migration is confirmed
2. **Skip** — if the screen is simple enough that `@Preview` and manual device testing are sufficient

If the project already uses Paparazzi or Roborazzi, default to using whichever is already set up. If neither is present, propose adding the dependency (Roborazzi is preferred for KMP projects; Paparazzi for Android-only) and wait for approval before adding it.

**5. Scope** — what's in this migration and what's explicitly deferred (with a reason)

Wait for explicit user approval before continuing.

---

## Phase 5: Implement Gaps First

If Phase 3 identified components that need to be added or created, resolve them **before** writing the screen itself — in the same priority order:

- **UI Kit match found** → nothing to implement; just confirm the import path and move on
- **Already-imported library covers it** → nothing to implement; confirm the API and move on
- **New library approved** → add the dependency to the relevant `build.gradle.kts` first, sync, verify it resolves
- **Custom component needed** → implement it in the shared UI module using the `compose-ui-architect` agent, following patterns from Phase 2; each new component gets at least one `@Preview`. **Name the target module explicitly** — state the module name (e.g. `uikit`, `designsystem`, `ui-components`) and the file path in the migration plan. "Reusable composable" is not sufficient — the module must be named so it's clear where to find the component later.

Do not implement the screen migration and the new shared components at the same time. If the new components are significant (non-trivial custom drawing, complex state, reusable across many screens), flag them to the user and suggest a separate review before wiring them into the screen migration.

---

## Phase 6: Migrate the Screen

Use the `compose-ui-architect` agent to write the Compose implementation.

Brief the agent with:
- The full content of all files from Phase 1 (the old implementation)
- The pattern constraints from Phase 2 (state model shape, action shape, theme usage, nav approach)
- The existing shared components to use (from Phase 2 + Phase 5)

The migration produces:
- A new `FooScreen.kt` (or equivalent) with the screen composable and all sub-composables
- A minimal update to `FooViewModel.kt` only if strictly required by the new state/action model
- Wiring into the nav graph (if applicable)
- The old Activity/Fragment **kept intact** until verification passes — do not delete it yet

Key constraints to enforce on the agent:

**Business logic preservation — critical**
The migration must not become a refactoring of the non-UI layers. Changes outside the UI layer must be minimal, each one explicitly justified, and limited strictly to what the Compose integration requires. Specifically:
- **Do not touch** repositories, use cases, domain models, data layer, or any class not directly involved in rendering or user interaction
- **ViewModel changes are allowed only when necessary**: adapting the state type, adding an `onAction` dispatcher if one didn't exist, or switching a legacy stream type (e.g. `LiveData` → `StateFlow`) if agreed with the user in Phase 4. Nothing else.
- If you find yourself wanting to refactor something outside the UI layer "while you're in there" — don't. Note it as a separate suggestion to the user instead.

**Architecture**
- The new screen must be stateless at the composable level: `FooScreen(state: FooState, onAction: (FooAction) -> Unit)`
- `viewModel()` is called only at the navigation entry point
- No business logic inside composables — it belongs in the ViewModel
- State classes **must** have `@Stable` or `@Immutable` if the project uses explicit stability annotations (from Phase 2). Do not skip this — it directly affects recomposition performance and the project's consistency.
- `when` expressions over sealed state or sealed actions must be **exhaustive — no `else` branch**. The entire point of a sealed hierarchy is that the compiler tells you when you've missed a case. An `else` branch silently swallows future states.
- Error/message strings in state must use the same type as the rest of the project's state classes (`String`, `@StringRes Int`, `UiText`, etc.). If Phase 2 couldn't determine this, ask the user before writing state.
- Parameterless actions: follow the project convention discovered in Phase 2. If no convention was found, prefer plain `class` or `data class` with no fields — not `object` or `data object` — so each invocation is a distinct instance and won't be deduplicated by `Channel` or `SharedFlow`.

**Code quality**
- Inline composable lambdas longer than ~8 lines (e.g. `trailingIcon`, `leadingIcon`, complex item content) must be extracted to private composable functions — large inline blocks hurt readability and make previews impossible
- Composable function bodies over ~50 non-empty lines should be split into clearly-named private sub-composables; each sub-composable should represent one coherent UI concept
- Visibility: `internal` by default for all composables and classes not needed outside the module; `private` for helpers within a file; `public` only for the screen-level entry point if it crosses a module boundary

**Theming and resources**
- Sizes and dimensions: use the project's theme tokens or named constants (from Phase 2). Never emit raw `dp` literals unless the project consistently uses them — and even then, prefer named constants
- String resources: if the project uses `stringResource()` for user-visible strings, all strings in the migration must go through resources, not hardcoded literals
- Colors: `MaterialTheme.colorScheme.X` or the project's token system — never raw hex values

**Previews and comments**
- Every significant composable gets a `@Preview`
- Multiple `@Preview` functions for distinct states (loading, error, empty, populated)
- Add inline comments for non-obvious decisions — e.g. why a particular `LaunchedEffect` key was chosen, why a side effect is placed where it is, why `imePadding()` is needed. Comments explaining *why* are valuable; comments restating *what* the code does are not.

**Screenshot tests (if agreed in Phase 4)**
Write screenshot tests alongside the Compose implementation — one test per visual state (loading, error, empty, populated, and any other distinct states from the original screen). Each test renders the stateless composable in isolation with a hardcoded `FooState(...)` — no ViewModel, no real data. Use the same tool the project already has (Paparazzi or Roborazzi); if adding from scratch, follow the dependency approved in Phase 4. Record initial snapshots as the baseline — they will be used for visual regression after device testing confirms the output is correct.

---

## Phase 7: Static Verification

Verify everything that can be checked without a running device. Code style is not checked here — that is the responsibility of a separate code review step configured at the project level. Focus solely on: does the code build, does it pass the project's linter, and did the migration faithfully transfer all the UI structure and behavior from the original.

### Step 1: Build, lint, and screenshot tests

Run the project's standard checks:
- Compile: `./gradlew :<module>:compileDebugKotlin` (or the project's equivalent) — zero errors
- Lint: `./gradlew :<module>:lintDebug` — no new errors or warnings introduced by this migration
- Screenshot tests (if written in Phase 6): `./gradlew :<module>:recordPaparazziDebug` or `./gradlew :<module>:recordRoborazziDebug` to record initial snapshots, then `verifyPaparazzi` / `verifyRoborazzi` on subsequent runs. Any rendering failure here is a concrete visual regression — fix it before proceeding to device testing.

Fix any failures before proceeding.

### Step 2: Migration fidelity review

Go through the confirmed `behavior-scenarios.md` from Phase 1 and the original XML layout element by element. The goal is to verify that nothing silently went missing — every scenario has a corresponding implementation in the new Compose code.

**Layout structure and spacing**
- Every View in the XML has a corresponding Compose element
- Margins and paddings from XML constraints (`layout_margin*`, `padding*`) are reflected as `Modifier.padding` values — none silently dropped
- Element order (z-order, draw order, stacking) is preserved
- `ConstraintLayout` relationships (bias, chains, barriers) are correctly expressed in Compose layout

**Visual properties**
- Text styles match: `textAppearance`, `textSize`, `textColor`, `fontFamily`, `textStyle` → correct `MaterialTheme.typography` or local token
- Backgrounds, shapes, corner radii, elevation transferred
- Drawables / icons mapped to correct Compose equivalents
- Tint colors preserved

**Behavioral details that are easy to miss**
- Any `Fragment`-level setup in `onViewCreated` (toolbar attachment, menu inflation, shared element transitions) — each must have a Compose equivalent or a documented deferral
- Any `Activity`-level setup in `onCreate` (window flags, `adjustResize`/`adjustPan`, result contracts, intent extras) — each must be accounted for. For Activity migrations: if the original already uses `enableEdgeToEdge()` or opts into edge-to-edge, preserve it and call `enableEdgeToEdge()` before `setContent {}`. If the original does not use edge-to-edge, do not add it — document it as an optional modernization step and let the user decide whether to adopt it
- Any `tools:` attributes that hinted at runtime behavior (sample data, visibility overrides) — check whether they revealed actual runtime states that need handling
- Any `<include>` or `<merge>` layouts — the included content must be fully represented
- Accessibility: `contentDescription`, `importantForAccessibility`, `labelFor` — these must be preserved

**Architecture**
- Screen composable is stateless — no ViewModel reference inside
- `when` over sealed types is exhaustive — no `else` branch
- Old Activity / Fragment / View is kept intact, not deleted

**Window insets**
- Activity migration: if the original used edge-to-edge, `enableEdgeToEdge()` is called in `onCreate()` before `setContent {}`
- Any screen with text input fields has `Modifier.imePadding()` on its scrollable container
- Any `android:fitsSystemWindows="true"` from the original XML has a Compose equivalent (`Scaffold` or explicit `systemBarsPadding()`)
- Bottom navigation bars / gesture navigation area do not overlap interactive content
- No hardcoded status bar or navigation bar heights remain in the migrated code

### Migration report

Produce a `migration-report.md` file and save it alongside the migrated code. This document serves as the PR description template and the visual evidence for the team that the migration is correct.

```markdown
# Migration report: [ScreenName]
_Generated by migrate-to-compose skill — [date]_

---

## Source
- Type: Fragment / Activity / Custom View _(pick one)_
- Class: `ClassName`
- Layout: `layout_file_name.xml`

---

## What changed

### Replacements (old → new)
_Every View element and its Compose equivalent. Be specific — include class names._

| Old (View) | New (Compose) | Notes |
|---|---|---|
| `OrderListFragment` | `OrderListScreen` composable + `OrderListRoute` entry point | |
| `RecyclerView` + `OrderAdapter` | `LazyColumn` + `OrderItem` composable | DiffUtil replaced by `key` param |
| `SwipeRefreshLayout` | `PullToRefreshBox` (Material3 1.3+) | New Gradle dep added |
| `TextView` (empty state) | `OrderListEmptyState` composable | |
| `TextView` (error) | `OrderListErrorState` composable | |
| ... | ... | |

### New components created
_Shared composables or UI kit components that didn't exist before and were created as part of this migration._

| Component | Location | Purpose |
|---|---|---|
| `OrderItem` | `ui/orders/OrderItem.kt` | Reusable order row; candidate for UI kit extraction |
| `OrderListEmptyState` | `ui/orders/OrderListScreen.kt` | Private to this screen |
| ... | ... | |

### New dependencies added
_Only if approved by user in Phase 4._

| Dependency | Version management | Reason |
|---|---|---|
| `androidx.compose.material3:material3` | Compose BOM / version catalog | `PullToRefreshBox` |
| ... | ... | ... |

### ViewModel changes
_Should be minimal. List every change made outside the UI layer._

| Change | Reason |
|---|---|
| Added `@Stable` to `OrderListState` | Compose stability requirement |
| Added `fun onAction(action: OrderListAction)` dispatcher | Compose event model |
| ... | ... | |

---

## Behavior scenarios verified
_From behavior-scenarios.md — status after static verification._

| Scenario | Static ✅/⏳ | Device ✅/⏳ |
|---|---|---|
| Loading state shown on initial load | ✅ | ⏳ |
| Order list renders with title/status/amount | ✅ | ⏳ |
| Empty state shown when orders = [] | ✅ | ⏳ |
| Error message shown on failure | ✅ | ⏳ |
| Pull-to-refresh triggers reload | ✅ | ⏳ |
| Tapping order navigates to detail | ✅ | ⏳ |
| Cancel button visible only for PENDING/IN_PROGRESS | ✅ | ⏳ |
| ... | | |

---

## Visual comparison
_Populated by manual-tester agent after device testing._

| State | Before | After |
|---|---|---|
| Populated | ![](screenshots/before_populated.png) | ![](screenshots/after_populated.png) |
| Loading | ![](screenshots/before_loading.png) | ![](screenshots/after_loading.png) |
| Empty | ![](screenshots/before_empty.png) | ![](screenshots/after_empty.png) |
| Error | ![](screenshots/before_error.png) | ![](screenshots/after_error.png) |

---

## Deviations from original
_Intentional or unavoidable differences, approved by user._

| Element | Old behavior | New behavior | Reason / approval |
|---|---|---|---|
| Email field clear icon | Material `endIconMode="clear_text"` | Omitted | No M3 built-in equivalent; approved by [user] |
| ... | | | |

---

## Issues found (not fixed in this migration)
_Bugs or gaps discovered during migration. Out of scope — track separately._

| # | Description | Severity | Suggested action |
|---|---|---|---|
| 1 | Error state shows raw exception message to user | Medium | Replace with user-facing string in a follow-up |
| 2 | Cancel button has no loading state while request is in flight | Low | Follow-up ticket |
| ... | | | |

---

## Pending before old code can be deleted
- [ ] Device visual verification passes (manual-tester agent)
- [ ] QA sign-off on staging
- [ ] Navigation graph updated to use Compose destination
- [ ] Old files deleted: `OrderListFragment.kt`, `fragment_order_list.xml`, `OrderAdapter.kt`
```

Save screenshots to a `screenshots/` subdirectory next to the report. When device testing runs, the `manual-tester` agent populates the screenshot table. Even before device testing, the report should be filled with `@Preview` renders if screenshots are not yet available — they help reviewers understand the visual result.

After the report is ready: **"Static checks passed. Invoke the `manual-tester` agent on a connected device to complete visual verification and populate the screenshot table."**

---

## Device Testing (separate agent)

Visual and functional verification on a real device is handled by the `manual-tester` agent. Invoke it after Phase 7 passes.

Brief the `manual-tester` agent with:
- The `behavior-scenarios.md` document from Phase 1 as the spec / acceptance criteria
- The migration report's visual comparison table — the agent should capture before/after screenshots for each visual state
- The list of interactions to verify (buttons, scroll, navigation, edge cases)

The `manual-tester` agent will:
- Connect to a device/emulator and install the app
- Capture screenshots of the old implementation first (the "before" baseline)
- Switch to the new Compose implementation and capture "after" screenshots
- Execute all test cases from the behavior scenarios — every interaction, every visual state
- Compare layout, typography, colors, spacing between before and after
- Report bugs with severity, reproduction steps, and screenshot evidence
- Populate the screenshot table in the migration report

---

## Post-migration Cleanup (after device verification passes)

Once both Phase 7 (static) and device verification are complete and the user is satisfied with the result, **offer to clean up the old View-based code**. Do not do this automatically — propose it explicitly and wait for approval.

Files to propose deleting (confirm each with the user before removing):
- The old Activity / Fragment class
- The XML layout file(s) for the migrated screen
- Any `RecyclerView` adapters that are now fully replaced by Compose item composables
- Any `ViewHolder` classes
- Any `DataBinding` or `ViewBinding` generated classes (the bindings themselves disappear when the XML is removed)
- Any `DiffUtil.Callback` implementations that were adapter-specific
- `attrs.xml` entries for any migrated custom Views (after confirming no other View still uses them)

Also review:
- Navigation graph: remove the Fragment destination and replace with the Compose equivalent if not already done
- DI / Hilt modules: remove any Fragment-scoped bindings that no longer exist

**Do not delete anything that is still referenced elsewhere.** Run a project-wide usage search before proposing deletion of any class or resource.

---

## Handling Common Complexity

**RecyclerView with adapter** → `LazyColumn`/`LazyRow`. The adapter logic (diffing, item types, binding) maps to composable item functions and `key` parameters. Don't forget the click handlers from `onBindViewHolder`.

**Custom View (no drawing)** → A composable function placed in the shared UI module. Map `attrs.xml` attributes to function parameters. Replace `setListener`/`setXxx` setters with lambda parameters. Replace saved instance state with `rememberSaveable`.

**Wrapping a View in `AndroidView {}`** → This is **not a migration to Compose** — it is interop. It is acceptable only when there is genuinely no Compose equivalent and the View's behavior cannot be reasonably replicated. Before using `AndroidView`, explicitly tell the user: "I'm proposing to wrap `FooView` in `AndroidView` rather than rewriting it — this keeps the old View running inside Compose. This is a pragmatic shortcut, not a full migration." Wait for the user to agree. Never use `AndroidView` silently as a migration shortcut.

**Custom ViewGroup (layout logic in `onMeasure`/`onLayout`)** → A `Layout` composable or a combination of built-in layout composables. Custom measure/layout logic maps to `MeasurePolicy`. This is non-trivial — flag it and budget extra time.

**Custom View with `onDraw`** → **STOP and flag this explicitly to the user before writing any code.** This is the **highest-risk migration type**. You must use that exact label in the migration plan — not "moderately complex", not "non-trivial" — so the user understands the level of care required. Custom drawing involves pixel-level logic that is easy to get subtly wrong and hard to verify without a running device. Tell the user:
- What specifically makes this view complex (paths, clipping, layer operations, etc.)
- That this migration deserves its own isolated PR, separate from any screen migration that uses this view
- That a screenshot comparison on a real device is strongly recommended before and after
- That a careful code review is recommended before merging
Only proceed once the user acknowledges the risk. The implementation uses `Canvas { }` with `DrawScope` — a direct port of the `onDraw` + `canvas.clipRect` / `canvas.drawPath` logic into Compose drawing primitives. Never wrap the old View in `AndroidView` as a migration shortcut — that defeats the purpose.

**Data binding / two-way binding** → Compose has no two-way binding. Model all mutations as explicit callbacks (`onValueChange`, `onCheckedChange`). The ViewModel holds the source of truth.

**Fragment with back stack** → In Compose Navigation, back stack is handled by the nav graph. The Fragment's `onBackPressed` override maps to a `BackHandler` composable.

**Animations** — never drop silently. Every animation inventoried in Phase 1 must either have a Compose equivalent implemented or a documented user-approved deferral. Use the table below to map each one:

| View animation | Compose equivalent | Notes |
|---|---|---|
| `view.animate().alpha(0f)` / fade in/out | `AnimatedVisibility` with `fadeIn`/`fadeOut` | Prefer `AnimatedVisibility` for show/hide; use `animateFloatAsState` if you need direct alpha control |
| `view.animate().translationY(...)` | `animateFloatAsState` + `Modifier.offset` or `AnimatedVisibility` with `slideIn`/`slideOut` | |
| `view.animate().scaleX/Y(...)` | `animateFloatAsState` + `Modifier.scale` | |
| `ObjectAnimator` / `ValueAnimator` | `Animatable` + `LaunchedEffect` | Drive the animation from a coroutine; `Animatable` is the low-level equivalent |
| `AnimatorSet` (chained/parallel) | Multiple `Animatable` instances coordinated in a coroutine | Use `launch` for parallel, sequential `await` for chained |
| `LayoutTransition` (auto-animate children) | `AnimatedVisibility` per child + `animateContentSize()` on the container | `animateItemPlacement()` / `animateItem()` in `LazyColumn` for list items |
| `RecyclerView` item add/remove animation | `LazyColumn` + `animateItem()` modifier on each item (Compose 1.7+) | Older: `AnimatedVisibility` wrapped per item |
| Fragment enter/exit transition | `AnimatedContent` or `NavHost` `enterTransition`/`exitTransition` in Compose Navigation | |
| Fragment shared element transition | `SharedTransitionLayout` + `SharedTransitionScope` (Compose 1.7+) | High effort — flag to user and consider deferring |
| Activity `overridePendingTransition` | Compose Navigation `enterTransition` / `exitTransition` at the nav graph level | |
| `MotionLayout` | No direct equivalent — **must be decomposed** | See note below |

**MotionLayout** is the highest-risk animation migration. It encodes a complex multi-step transition as a scene graph. In Compose, the equivalent is typically a combination of `AnimatedContent`, `animateFloatAsState`, custom `Animatable` coroutines, and possibly `InfiniteTransition`. This almost always deserves its own PR. Flag it explicitly to the user, describe what the animation does, and propose a decomposition plan before attempting it.

**Material component built-in animations** (FAB morph, BottomSheet, NavigationDrawer slide) are handled automatically by Material3 Compose components — no manual implementation needed. Verify they behave the same visually during device testing.

**WindowInsets and edge-to-edge** → This is one of the most common silent regressions in Activity migrations. Modern Android enforces edge-to-edge by default (Android 15+), and `enableEdgeToEdge()` must be called explicitly in older targets. Without proper inset handling, system bars will overlap content or the keyboard will cover input fields.

*Activity migration:*
- Call `enableEdgeToEdge()` in `onCreate()` before `setContent {}`
- Use `Scaffold` — it handles top/bottom system bar insets automatically via `contentWindowInsets`
- If the original Activity set padding for the status bar manually (common before edge-to-edge), remove it — `Scaffold` handles this now

*Keyboard / IME:*
- Any screen with text input fields **must** have `Modifier.imePadding()` on the outermost scrollable container (e.g. `Column` inside `verticalScroll` or `LazyColumn`). Without this, the software keyboard will cover the submit button — a silent regression that only appears on device.
- If the original had `windowSoftInputMode="adjustResize"`, the Compose equivalent is `Modifier.imePadding()` + a scrollable container

*Mapping from View/XML:*

| Old (View / XML / Manifest) | Compose equivalent |
|---|---|
| `android:fitsSystemWindows="true"` | `Scaffold` defaults or `Modifier.systemBarsPadding()` |
| `windowSoftInputMode="adjustResize"` | `Modifier.imePadding()` on the scrollable container |
| `windowSoftInputMode="adjustPan"` | `Modifier.imePadding()` + ensure content is scrollable |
| `setPadding(0, statusBarHeight, 0, 0)` (manual) | `Modifier.statusBarsPadding()` |
| `setPadding(0, 0, 0, navBarHeight)` (manual) | `Modifier.navigationBarsPadding()` |
| Hardcoded status bar height via `getResourceId` | `WindowInsets.statusBars.asPaddingValues()` |
| Content that avoids both system bars and IME | `Modifier.safeContentPadding()` (WindowInsets.safeContent) |

*Fragment migration:* Fragments inside a `WindowInsets`-aware Activity inherit the insets from the host. In Compose, pass `WindowInsets` down explicitly or let `Scaffold` consume them at the screen level.

**ViewPager2 + TabLayout** → `HorizontalPager` + `TabRow`. The key: `pagerState.currentPage` drives tab selection, and tab clicks call `coroutineScope.launch { pagerState.animateScrollToPage(index) }`. Fragment-based `FragmentStateAdapter` logic moves into composable pages. Verify swipe and tab-tap both stay in sync.

**CoordinatorLayout + AppBarLayout + CollapsingToolbarLayout** → `Scaffold` + `TopAppBar` (Large or Medium variant) + `TopAppBarScrollBehavior` + `Modifier.nestedScroll(scrollBehavior.nestedScrollConnection)` on the scrollable content. The `CollapsingToolbarLayout` title transition maps to the built-in Large/Medium `TopAppBar` collapse behavior. Custom pinned views inside the toolbar need explicit implementation as `TopAppBar` content slots.

**Toolbar / ActionBar with menus** → `TopAppBar` with `actions = { ... }` slot. Menu items from `onCreateOptionsMenu` become `IconButton` or `DropdownMenu` entries in the actions slot. The navigation icon (`setNavigationOnClickListener`) maps to the `navigationIcon` slot with a lambda. If the screen used `setSupportActionBar`, the Activity's ActionBar must be disabled (`requestWindowFeature(Window.FEATURE_NO_TITLE)` or theme) to avoid conflicts with the Compose toolbar.

**BottomSheetDialogFragment** → `ModalBottomSheet`. The Fragment's `onCreateView` content becomes the `ModalBottomSheet` content lambda. Dismiss handling: `sheetState.hide()` + `onDismissRequest` callback. State (`BottomSheetBehavior.STATE_*`) maps to `SheetValue` in `rememberModalBottomSheetState`. If the bottom sheet was shown from a Fragment via `FragmentManager`, the trigger moves to a boolean state variable in the host composable.

**ItemTouchHelper (swipe-to-dismiss, drag-to-reorder)** → `SwipeToDismissBox` for swipe-to-dismiss. Drag-to-reorder has no built-in equivalent — implement with `Modifier.draggable` or `Modifier.pointerInput` with position tracking and a mutable list in state. Both are meaningfully more code than `ItemTouchHelper`. Flag this to the user and budget extra time.

**ActivityResultLauncher / permission requests** → `rememberLauncherForActivityResult` (for results) and `rememberPermissionState` / `rememberMultiplePermissionsState` from Accompanist Permissions (or the equivalent if the project uses a different permissions library). Each `registerForActivityResult` call in the Fragment/Activity maps to one `rememberLauncherForActivityResult` in the composable. Launchers must be remembered at composition time — they cannot be created inside a callback or LaunchedEffect.

**Focus management in forms** → `FocusRequester` + `SoftwareKeyboardController`. Replace `editText.requestFocus()` with `focusRequester.requestFocus()` inside a `LaunchedEffect`. Replace `hideSoftInputFromWindow` with `keyboardController.hide()`. Tab-order (next field on IME action) is achieved by chaining `FocusRequester` instances: the first field's `KeyboardOptions(imeAction = ImeAction.Next)` + `onAction { nextFocusRequester.requestFocus() }`.

**Toast** → There is no `Toast.makeText` equivalent in Compose. Replace with `SnackbarHost` + `SnackbarHostState`. If the project uses Toasts in many places, confirm with the user whether to switch to Snackbars or keep Toasts via a `SideEffect { Toast.makeText(...).show() }` as a temporary measure.

**`View.post { }` / `Handler.postDelayed { }`** → `LaunchedEffect` for one-shot post-layout operations, `SideEffect` for synchronizing with non-Compose code every recomposition. `Handler.postDelayed` maps to `LaunchedEffect { delay(ms); doSomething() }`. Never use `Handler` directly inside a composable.

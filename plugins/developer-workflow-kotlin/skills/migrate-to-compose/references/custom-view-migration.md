# Custom View Migration Strategies

## When this applies

Any project-owned custom View or ViewGroup used on the screen being migrated. Third-party Views (MapView, WebView, PlayerView, ExoPlayer) are exempt — wrap them in `AndroidView`.

## Decision tree

For each custom View, walk through these steps **in order**. Stop at the first match.

### Step 1: Classify the View

Before searching for replacements, understand what the View actually does:

| Type | How to recognize | Complexity |
|---|---|---|
| **Composite** — assembles standard widgets | Extends `FrameLayout`/`LinearLayout`/`ConstraintLayout`, inflates XML, no `onDraw` | Low |
| **Behavioral** — adds behavior to children | Extends `ViewGroup`, overrides `onInterceptTouchEvent`/`onTouchEvent`, custom `onMeasure`/`onLayout` | Medium |
| **Drawing** — custom rendering | Overrides `onDraw`/`dispatchDraw`, uses `Canvas`/`Paint`/`Path` | High |
| **Hybrid** — combines layout + drawing | Has both custom layout logic and `onDraw` | High |

Document the type and its public API: constructor attrs, public properties/setters, listener interfaces, saved state.

### Step 2: Search for existing replacements

**Priority order — always prefer what's already available:**

**2a. Material3 / Compose Foundation**
Check if a standard Compose component already does what the custom View does. Common matches:

| Custom View pattern | Compose equivalent |
|---|---|
| Custom progress/loading indicator | `CircularProgressIndicator`, `LinearProgressIndicator` |
| Custom toggle/switch | `Switch`, `Checkbox`, `RadioButton` |
| Custom chip/tag | `AssistChip`, `FilterChip`, `InputChip`, `SuggestionChip` |
| Custom badge/count | `Badge`, `BadgedBox` |
| Custom bottom bar | `NavigationBar`, `NavigationBarItem` |
| Custom segmented control | `SegmentedButton`, `SingleChoiceSegmentedButtonRow` |
| Custom slider | `Slider`, `RangeSlider` |
| Custom tooltip | `PlainTooltip`, `RichTooltip` |
| Flow/wrap layout | `FlowRow`, `FlowColumn` |
| Custom card | `Card`, `ElevatedCard`, `OutlinedCard` |
| Custom divider | `HorizontalDivider`, `VerticalDivider` |

If you find a match: verify it covers the full feature set of the custom View. A 90% match is usually good enough — document the differences.

**2b. Project's UI kit / design system module**
Search the project's shared UI module (`uikit`, `designsystem`, `ui-components`, or similar) for an existing Compose version of this View. Projects often migrate widgets incrementally — there may already be a Compose version that another screen uses.

**2c. Already-imported Compose libraries**
Check `build.gradle.kts` / version catalog for libraries already on the classpath that might provide the component. Common ones:

- `accompanist-*` — permissions, system UI controller, web view, placeholder
- `coil-compose` / `glide-compose` — image loading
- `lottie-compose` — Lottie animations
- `compose-richtext` — rich text rendering
- `compose-shimmer` — shimmer/skeleton loading
- `compose-charts` / `vico` — charting
- `telephoto` — zoomable images
- `compose-calendar` — date pickers / calendars

**2d. Search for a well-known Compose library**
If nothing on the classpath fits, search for established Compose libraries that provide this component. Criteria for "established":
- 500+ GitHub stars or part of a known suite
- Active maintenance (commits in the last 6 months)
- Compose Multiplatform support is a bonus if the project uses KMP

**Propose to the user with rationale. Do not add without approval.**

### Step 3: Assess if custom implementation is feasible

If no existing replacement found — you need to write a Compose composable. Assess feasibility based on the View type from Step 1:

**Composite View (low complexity)**
- Straightforward: replace the inflated XML with a composable function
- Map XML attrs → function parameters
- Map setters/listeners → lambda parameters
- Map `addView`/`removeView` patterns → conditional composition or `AnimatedVisibility`
- Estimated effort: small, do inline with the migration

**Behavioral View (medium complexity)**
- Map `onMeasure`/`onLayout` → custom `Layout` composable with `MeasurePolicy`
- Map `onInterceptTouchEvent`/`onTouchEvent` → `Modifier.pointerInput` with gesture detectors
- Map scroll behavior → `Modifier.nestedScroll` with `NestedScrollConnection`
- Estimated effort: moderate, may need its own sub-task in Phase 4

**Drawing View (high complexity)**
- Map `onDraw` → `Canvas { }` composable or `Modifier.drawBehind`/`Modifier.drawWithContent`
- Map `Paint` → `DrawScope` methods and `Paint` in Compose graphics
- Map `Path` → `androidx.compose.ui.graphics.Path`
- Map `clipPath`/`saveLayer` → `clipPath`/`drawWithLayer` in `DrawScope`
- Map `Bitmap` operations → `ImageBitmap`
- Map invalidate-driven animation → `Animatable` + `LaunchedEffect`
- **Flag explicitly to the user**: this is high risk, recommend screenshot testing, may deserve its own PR
- Estimated effort: significant, always a separate sub-task

**Hybrid View (high complexity)**
- Decompose into layout part and drawing part
- Layout → custom `Layout` composable
- Drawing → `Canvas` or draw modifiers applied to the layout
- Same risk level as Drawing View — flag and budget accordingly

### Step 4: Plan the migration

Based on the assessment, propose one of these strategies to the user in Phase 4:

| Strategy | When to use | Approach |
|---|---|---|
| **Inline replacement** | Composite View with clear Compose equivalent or trivial custom impl | Migrate as part of the screen migration in Phase 6 |
| **Pre-migration component** | Any View that will be reused across screens, or medium-complexity behavioral View | Build the Compose composable in Phase 5 (Implement Gaps), then use it in Phase 6 |
| **Dedicated sub-task** | Drawing View, Hybrid View, or any View with complex touch/animation | Separate sub-task with its own `@Preview`, screenshot tests, and verification. Complete before Phase 6 |

### Step 5: Verify completeness

After migration, every custom View must satisfy ALL of these:
- [ ] No `AndroidView` wrapping of project-owned code
- [ ] Full public API preserved (all attrs/properties/listeners have Compose parameter equivalents)
- [ ] Visual appearance matches (verified via `@Preview` at minimum, screenshot test for complex cases)
- [ ] Behavioral parity (touch handling, animations, state saving)
- [ ] Placed in shared UI module (not inlined in the screen) if the View was shared or could be reused
- [ ] Old View class kept intact until device verification passes (same as screen migration rule)

## Example walkthrough

```
Custom View: RatingBar (extends LinearLayout, inflates 5 star ImageViews, 
             supports half-stars, has setRating/setOnRatingChanged)

Step 1: Composite View — inflates XML, no onDraw → Low complexity
Step 2a: No Material3 RatingBar in Compose
Step 2b: Project UI kit has no Compose version
Step 2c: No rating library on classpath
Step 2d: Found compose-ratingbar (800+ stars, maintained) — option A
         Custom implementation with Row + Icon — option B (simple enough)
Step 3: Composite, low complexity → feasible to write custom
Step 4: Recommend option B (no new dependency, simple component)
        → Pre-migration component in Phase 5
Step 5: Checklist passes
```

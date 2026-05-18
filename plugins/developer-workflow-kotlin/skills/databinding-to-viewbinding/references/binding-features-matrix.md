# Binding Features Matrix

This matrix is the master classifier for every DataBinding feature encountered during Discovery.
Every binding row in `<slug>-property-map.md` gets its `bucket` value by looking up its feature
here. Per-expression overrides come from `expression-resolution.md`; per-adapter overrides come
from `adapter-resolution.md`. When signals from different sources conflict, the worst bucket wins
(see Consensus Rule below).

## Bucket definitions

**mechanical** — deterministic conversion: the skill writes the replacement with no human
judgment required. The output is a bit-for-bit behavioural equivalent of the original binding
expression. The result is verified by `/check` (build + lint). No review caveat is added to
the property map `notes` column. Examples: replacing `executePendingBindings()` with nothing,
replacing `DataBindingUtil.setContentView(…)` with the typed `XxxBinding.inflate(…)` call,
removing `lifecycleOwner = …` from the binding object.

**partial** — the skill writes a default replacement but flags it for human (or follow-up agent)
confirmation. DataBinding's runtime behaviour may differ subtly from the literal Kotlin
equivalent. The `notes` column carries the specific caveat text so the reviewer knows exactly
what to verify. The property map row is committed but the screen is not marked clean until the
user acknowledges the caveat. Examples: a `LiveData` variable whose lifecycle attachment point
moves from the binding object to an explicit `observe` call; a `bind:` variable on an `<include>`
that must now be wired by the host explicitly.

**escalate** — the skill stops on this binding and records the case in the property map without
emitting a replacement fragment. No host-code write happens for this row. The user or
`kotlin-engineer` agent selects a recipe from `escalation-patterns.md` and the conversion of
the screen cannot proceed until all its escalations are resolved. Examples: any `@={…}` two-way
binding, any `Observable*`-typed variable, a `<ViewStub>`, a `<merge>` root layout.

## Feature → bucket matrix

| Feature | Bucket | Replacement strategy | Cross-ref |
|---|---|---|---|
| One-way `@{…}` — supported expression (arithmetic, logic, ternary depth ≤ 2, string template, null-coalescing, safe-unbox) | mechanical | Direct Kotlin equivalent per grammar rules | expression-resolution.md |
| One-way `@{…}` — resource reference (`@string/`, `@dimen/`, `@color/`, `@drawable/`, `@integer/`, `@bool/`) | mechanical | Wrap in `context.getString(…)` / `getDimensionPixelSize` / `ContextCompat.getColor` / `ContextCompat.getDrawable` / `getInteger` / `getBoolean` | expression-resolution.md §resource_ref |
| One-way `@{…}` — `safeUnbox(…)` / `default=` / `??` (null-coalescing with matching types) | mechanical | `expr ?: zeroPrimitive` / `expr ?: defaultVal` / Kotlin Elvis chain | expression-resolution.md §safe_unbox |
| One-way `@{…}` — `@BindingAdapter` resolved to project-local sources | mechanical | Direct function call with resolved args; disposal options apply after migration | adapter-resolution.md, escalation-patterns.md §adapter-cleanup |
| One-way `@{…}` — `@BindingAdapter` resolved to binary library (`androidx.databinding:databinding-adapters`, AppCompat, Material, etc.) | mechanical | Direct call with FQN import; add explicit dependency if AGP no longer pulls it transitively after `dataBinding = false` | adapter-resolution.md §binary |
| One-way `@{…}` — `@BindingAdapter` in a different monorepo module, module already on classpath | partial | Direct call if dependency exists; user confirms placement; duplication or extraction if not | adapter-resolution.md §monorepo |
| One-way `@{…}` — `@BindingAdapter` unresolved (no match in any source tier) | escalate | No template generated; record adapter attribute and failing lookup in notes | adapter-resolution.md §unresolved, escalation-patterns.md |
| Two-way `@={…}` on standard widgets (`EditText.text`, `Switch.isChecked`, `RadioGroup.checkedButtonId`, etc.) | escalate | TextWatcher + setter pair or OnCheckedChangeListener pair | escalation-patterns.md §two-way |
| Two-way `@={…}` on custom widget with project-local `@InverseBindingAdapter` | escalate | Decompose into `@BindingAdapter` call + `@InverseBindingAdapter` listener wiring | escalation-patterns.md §two-way-inverse |
| Listener attribute — inline lambda `android:onClick="@{() -> vm.onClick()}"` | mechanical | `setOnClickListener { vm.onClick() }` with translated lambda body | expression-resolution.md §lambda |
| Listener attribute — method reference `android:onClick="@{vm::onClick}"` | mechanical | `setOnClickListener { vm.onClick(it) }` | expression-resolution.md §lambda |
| Listener attribute — multi-listener or custom listener binding (`app:onTextChanged`, `app:onItemSelected`) | partial | DataBinding's listener method picker is non-trivial; skill writes the most likely overload but flags for review | adapter-resolution.md §overload-selection |
| `Observable*` / `ObservableField<T>` / `ObservableArrayList<T>` as variable type | escalate | Property-holder type must be replaced with `StateFlow` or `LiveData`; project-wide decision required | escalation-patterns.md §observable-decommission |
| `LiveData<T>` / `StateFlow<T>` / `Flow<T>` as variable type with `lifecycleOwner = …` on binding | partial | Skill writes subscription scaffold (`viewLifecycleOwner.lifecycleScope.collect` or `LiveData.observe`); user reviews lifecycle attachment point | escalation-patterns.md §livedata-wiring |
| `<include>` referencing a sub-layout (no `bind:` variables) | mechanical | `binding.includedLayoutId.<viewId>` — ViewBinding generates the nested binding field automatically | mechanical-transforms.md §include |
| `<include>` with `bind:variable="@{vm}"` — passes variables to sub-layout | partial | Sub-binding variables now require explicit host-side passing; skill generates the call site but user confirms correct scope | mechanical-transforms.md §include, escalation-patterns.md |
| `<merge>` as layout root | escalate | ViewBinding inflate for `<merge>` requires the two-arg `inflate(inflater, parent)` form; placement of inflate call must change in host | escalation-patterns.md §merge |
| `<ViewStub>` | escalate | DataBinding's `OnInflateListener` integration has no ViewBinding equivalent; manual `setOnInflateListener` + typed binding access required | escalation-patterns.md §viewstub |
| `<import>` declarations | mechanical | Consumed during expression resolution; no emission into host code | expression-resolution.md §static_ref |
| `<variable>` declarations | — | Not a property-map row; feeds `<slug>-variables-map.md` and informs lifecycle and escalation strategy | property-map-spec.md §variables-map |
| `@BindingMethods` / `@BindingConversion` | partial | Bucket confirmed during Discovery based on adapter chain result: if resolved adapter and conversion are both mechanical → mechanical; if conversion chain is ambiguous or type mismatch → escalate | adapter-resolution.md §BindingConversion |
| `BR` class references in host code (`binding.setVariable(BR.user, user)`, `notifyPropertyChanged(BR.x)`) | partial | `BR` disappears with DataBinding; see `escalation-patterns.md §BR references` for the decision recipe | escalation-patterns.md §BR references |
| `executePendingBindings()` calls | mechanical | Remove the call; ViewBinding has no pending-binding queue | mechanical-transforms.md §pending-bindings |
| `lifecycleOwner = viewLifecycleOwner` on the binding object | mechanical | Remove the line; if a `LiveData` row on the same screen is `partial`, lifecycle wiring is owned by that row | mechanical-transforms.md §lifecycle-owner |
| `DataBindingUtil.setContentView` / `DataBindingUtil.inflate` / `DataBindingUtil.bind` | mechanical | Replace with `XxxBinding.inflate(layoutInflater)` + `setContentView(binding.root)` for Activity; Fragment / ViewHolder variants per `mechanical-transforms.md` | mechanical-transforms.md §inflate |
| Project-local `@BindingAdapter` with all its callsites migrated — post-migration cleanup | partial | Bucket confirmed during Discovery based on disposal option chosen (keep / delete / extract to util / convert to extension / move to separate module); see adapter disposal matrix | escalation-patterns.md §Adapter cleanup |

## Reading the table during Discovery

At Discovery time the skill walks every binding expression in the scope, matches it against the
rows above (top to bottom; first match wins for single-feature expressions), and writes the
bucket and a one-line `notes` entry into the property map. When multiple rows match a single
expression, apply each and take the worst bucket (see Consensus Rule). The `Cross-ref` column
points to the reference that supplies the concrete conversion recipe or escalation detail.

At Conversion time the skill re-reads the approved property map, groups rows by bucket, and
processes `mechanical` rows first. `partial` rows are processed next and the caveat from `notes`
is surfaced to the user before writing. `escalate` rows are skipped — they wait for the user's
recipe selection via `escalation-patterns.md`.

## Consensus rule

When a single binding row touches multiple features in this matrix — for example, a one-way
expression using a project-local `@BindingAdapter` whose result passes through a
`@BindingConversion` — apply each matching row independently and take the worst bucket:
`mechanical` < `partial` < `escalate`. This matches the bucket resolution rule in
`property-map-spec.md` and ensures no conversion proceeds silently when any component of it
requires human attention. Apply the rule per binding row, not per feature class across the whole
screen: a screen with both mechanical and escalate rows is not itself escalated; only the specific
rows with `escalate` bucket are blocked.

## Cross-references

- `expression-resolution.md` — per-expression grammar, bucket labels, and escalation triggers
- `adapter-resolution.md` — adapter source taxonomy, overload selection, replacement-template builder
- `property-map-spec.md` — row schema, bucket column definition, consensus rule, USER GATE handoff
- `mechanical-transforms.md` — concrete code patterns for all mechanical rows
- `escalation-patterns.md` — recipes for two-way binding, Observable decommission, ViewStub, `<merge>`, BR refs, adapter cleanup

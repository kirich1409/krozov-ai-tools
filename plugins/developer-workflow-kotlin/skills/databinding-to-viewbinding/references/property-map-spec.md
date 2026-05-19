# Property Map Spec

These artifacts are the single source of truth that crosses the USER GATE between the Discovery
and Conversion phases. Once the user approves them, they are immutable and drive every mechanical
and escalated step of the conversion.

---

## Files in scope

All three files live in `./swarm-report/`. Replace `<slug>` with the kebab-case migration
identifier used throughout the session (e.g. `databinding-to-viewbinding`).

| File | Created when | Purpose |
|---|---|---|
| `<slug>-property-map.md` | Always | One row per `@{…}` / `@={…}` binding occurrence across every layout in scope. Primary artifact. |
| `<slug>-variables-map.md` | Always | One row per layout × `<variable>` declaration — drives host-Kotlin wiring replacements. |
| `<slug>-adapter-sources.md` | When adapter resolution ran and found non-trivial entries | One row per resolved `@BindingAdapter` symbol; cross-referenced by the property map. |

---

## `<slug>-property-map.md` — row schema

| Column | Type | Description |
|---|---|---|
| `layout` | path | Layout XML file path relative to module root |
| `view_id` | string | `android:id="@+id/..."` of the host view; `__synthesized_N__` when the layout omits the id |
| `view_type` | class name | Simple class name of the host view (`TextView`, `ImageView`); full FQN when not in `android.widget` |
| `attribute` | string | XML attribute name including namespace (`android:text`, `app:imageUrl`, `bind:onClick`) |
| `binding_kind` | enum | `one_way` / `two_way` / `listener_lambda` / `event_callback` |
| `expression_raw` | string | The literal `@{…}` or `@={…}` text from the layout |
| `expression_type` | Kotlin type | Resolved Kotlin type from `expression-resolution.md` step 4; nullability marked with `?` |
| `adapter_origin` | enum | `project-local` / `monorepo:<gradle-path>` / `binary:<group>:<artifact>:<version>` / `implicit-setter` / `unresolved` |
| `adapter_symbol` | FQN | FQN of the resolved `@BindingAdapter` method or implicit setter |
| `replacement_fragment` | Kotlin snippet | Host-Kotlin call built by the replacement-template builder in `adapter-resolution.md` |
| `bucket` | enum | `mechanical` / `partial` / `escalate` |
| `notes` | free text | Engineer or reviewer annotations; escalation recipe references; footnote indices |

**Conventions:**

- Empty cells use `—`.
- Multi-line values are forbidden in cells. If a value cannot fit on one line, write a footnote
  index `[N]` in the cell and place the full text in a numbered list after the table.
- `expression_type` records nullability with `?` (e.g. `String?`, `Uri?`).
- Rows are sorted by layout path, then by line number of the binding within the layout — engineers
  can walk the file top-to-bottom and see each layout's bindings together.

**Bucket resolution rule.** `bucket` is the consensus of the expression-resolution result and the
adapter-resolution result: any `escalate` from either side wins; `partial` from either side wins
over `mechanical`; otherwise `mechanical`. When a single XML attribute resolves to multiple
`@BindingAdapter` candidates with no specificity winner after tie-breaking, write
`adapter_symbol = <ambiguous>` and force `bucket = escalate`.

---

## `<slug>-variables-map.md` — row schema

| Column | Type | Description |
|---|---|---|
| `layout` | path | Layout XML path relative to module root |
| `variable_name` | string | `name` attribute from `<variable name="X" type="Y"/>` |
| `declared_type` | FQN | The `type` attribute value verbatim |
| `host_class` | FQN | Activity / Fragment / ViewHolder / Custom-View Kotlin class that inflates this layout, resolved during scope discovery |
| `binding_call_site` | location | File path and line where `binding.setX(…)` is called; `n/a` when the variable is only set from XML |
| `replacement_strategy` | enum | `field` / `constructor_param` / `direct_property_access` / `escalate` |
| `notes` | free text | Free-form; escalation reasons, cross-references |

---

## `<slug>-adapter-sources.md` — row schema (optional)

Created only when adapter resolution actually ran and indexed entries from `ksrc`. Cross-referenced
by `adapter_origin` in the property map.

| Column | Type | Description |
|---|---|---|
| `origin` | enum | `project-local` / `monorepo:<gradle-path>` / `binary:<group>:<artifact>:<version>` |
| `symbol` | FQN | FQN of the `@BindingAdapter`-annotated method |
| `attributes` | string list | Comma-separated XML attribute strings the adapter handles |
| `parameter_signature` | string | Kotlin parameter list, e.g. `(View, String, Drawable?)` |
| `require_all` | bool | `true` / `false` |
| `overload_group` | label | Short label grouping overloads on the same attribute set for deterministic cross-overload selection |
| `references_in_scope` | integer | Count of property-map rows that reference this adapter |
| `cleanup_status` | enum | `keep-as-regular-dep` / `duplicate-from-sources` / `convert-to-extension` / `static-call` / `escalate`; empty during Discovery, filled during Cleanup |

---

## Worked example — `<slug>-property-map.md`

Three rows from a hypothetical `feature/profile/res/layout/fragment_profile.xml`.

| layout | view_id | view_type | attribute | binding_kind | expression_raw | expression_type | adapter_origin | adapter_symbol | replacement_fragment | bucket | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| feature/profile/res/layout/fragment_profile.xml | name_label | TextView | android:text | one_way | `@{viewModel.user.name}` | `String` | implicit-setter | `android.widget.TextView#setText` | `binding.nameLabel.text = viewModel.user.name` | mechanical | — |
| feature/profile/res/layout/fragment_profile.xml | avatar | ImageView | app:imageUrl | one_way | `@{viewModel.user.avatarUri ?? "default"}` | `String` | binary:androidx.databinding:databinding-adapters:8.3.2 | `androidx.databinding.adapters.ImageViewBindingAdapter#setImageUrl` | `ImageViewBindingAdapter.setImageUrl(binding.avatar, viewModel.user.avatarUri ?: "default")` [1] | mechanical | — |
| feature/profile/res/layout/fragment_profile.xml | notifications_switch | SwitchMaterial | android:onCheckedChanged | two_way | `@={viewModel.notificationsEnabled}` | `Boolean` | — | — | — | escalate | Two-way binding — apply `escalation-patterns.md §Two-way` |

**Footnotes:**

1. `databinding-adapters` is pulled transitively by AGP when `dataBinding = true`. After setting
   `dataBinding = false`, declare `implementation("androidx.databinding:databinding-adapters:8.3.2")`
   explicitly in the module's `build.gradle.kts` if this call site survives the migration; otherwise
   replace with a Coil / Glide / Picasso load call per the project's image-loading library.

---

## USER GATE handoff

When Discovery is complete, the property map is presented to the user showing the count of rows in
each bucket (`mechanical: N`, `partial: M`, `escalate: K`) alongside the full tables. The user
reviews the distribution, inspects any `partial` or `escalate` rows, and either approves the plan
or requests re-discovery on a narrower scope. After approval, the following footer is appended to
`<slug>-property-map.md` and the file is treated as immutable for the remainder of the migration:

```
---
Approved on YYYY-MM-DD by USER
```

No row may be modified after approval. If a discrepancy surfaces during Conversion, a new
discovery pass creates a separate corrected artifact — it does not edit the approved one.

---

---

## `<slug>-reused-helpers.md`

Created during Phase 4 (Conversion), before Phase 5 cleanup. Populated when the engineer
identifies a multi-line code shape that is either repeated across ≥ 2 distinct host classes
(auto-aggregate) or flagged for extraction even at a single occurrence (engineer-flagged). One
row per candidate group.

| Column | Type | Description |
|---|---|---|
| `pattern_id` | string | Short generated ID for the candidate group (e.g. `h-two-way-edittext`, `h-stateflow-collect`) |
| `description` | string | One-line gloss of the pattern (e.g. "two-way EditText with TextWatcher suppress guard") |
| `occurrences` | int | Count of property-map rows where this shape appears |
| `host_classes` | string list | Distinct host class names the pattern appears in |
| `surfaced_via` | enum | `auto-aggregate` (occurrences ≥ 2 across distinct host classes) or `engineer-flag` (occurrences = 1 with a specific reason) |
| `proposed_signature` | Kotlin snippet | Function signature the extracted helper would have (e.g. `fun EditText.bindTwoWayText(state: MutableStateFlow<String>)`) |
| `placement_decision` | string | Filled after the user prompt; records the chosen path (e.g. `helper-extraction → :core:ui`) or `keep-inline` |
| `notes` | string | Any relevant context; when `surfaced_via = engineer-flag`, records the specific reason (e.g. "TextWatcher + lifecycleScope > 6 lines", "matches project's :core:ui helper convention") |

The `placement_decision` column is filled via the prompt template in
`gradle-and-lint-gate.md "Placement options"`. The file is created only when at least one
candidate group exists (auto-aggregate or engineer-flagged); it is omitted when no candidates
are identified.

---

## Cross-references

- `expression-resolution.md` — produces `expression_raw`, `expression_type`, and `replacement_fragment`
- `adapter-resolution.md` — produces `adapter_origin`, `adapter_symbol`, and finalizes `replacement_fragment`
- `binding-features-matrix.md` — defines the bucket taxonomy and per-feature escalation thresholds
- `mechanical-transforms.md` — consumes `replacement_fragment` to weave Kotlin into the host file; defines the helper-extraction step
- `escalation-patterns.md` — recipes for each `escalate` bucket entry, including two-way bindings

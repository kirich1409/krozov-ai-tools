# Gradle and Lint Gate

This reference is consulted at three moments: at scope intake (verify coexistence flags are
correctly set), at the end of each module's conversion (residual scan before cleanup), and at
the per-module cleanup attempt (flag removal, KAPT pruning, adapter disposal).

## Coexistence configuration

During mid-migration both flags may be active simultaneously so modules that have not yet been
converted continue to build.

```kotlin
android {
    buildFeatures {
        dataBinding = true   // still enabled while any <layout> binding remains
        viewBinding = true   // generates *Binding for non-<layout> XML
    }
}
```

Notes:

- ViewBinding does **not** process layouts wrapped in `<layout>` — DataBinding still owns those
  until the `<layout>` wrapper is stripped. Coexistence is real, not transitional boilerplate.
- The skill never modifies these flags during conversion. They are touched only at cleanup time.
- On AGP < 7.0, the legacy `dataBinding { enabled = true }` block is equivalent. The skill
  recognizes both forms when scanning for residuals and generating cleanup diffs.

## Forward gate via lint baseline

Once a layout is converted, new `@{…}` expressions or new `<layout>` roots must not be
introduced in that module. Strategy:

- Add a project-local Lint rule (or a Konsist layout-XML inspection for Kotlin-only projects)
  that fails the build on:
  - `<layout>` root element in any XML inside an in-scope module.
  - `@{` or `@=` in any XML attribute value.
  - `<data>` element in any XML inside an in-scope module.
- The skill does **not** author this rule. It records a `follow-up: add lint rule` item in
  `<slug>-cleanup-status.md` and points the user to any existing custom Lint examples in the
  project. If the project already uses Konsist, an equivalent layout-XML inspection in tests
  satisfies the same gate.

## Residual scan per module

After all bindings in a module are converted, the skill runs a residual scan before attempting
cleanup. The scan checks three surfaces:

**XML layouts.** All `*.xml` files under the module's resource directories must have no:
- `<layout>` root element
- `<data>` child element
- `@{` or `@=` in any attribute value
- `bind:` namespace declaration

**Kotlin/Java host code.** All source files must have no:
- Imports of `androidx.databinding.*`
- References to `DataBindingUtil.*` or `ViewDataBinding`
- Uses of `BaseObservable`, `ObservableField`, `ObservableBoolean`, or similar Observable
  subtypes when they were introduced for DataBinding purposes
- References to the generated `BR` class (`BR.user`, `notifyPropertyChanged(BR.x)`, etc.)
- `@BindingAdapter`, `@InverseBindingAdapter`, `@BindingConversion`, or `@BindingMethods`
  annotations

Note: DataBinding-generated and ViewBinding-generated classes share the `<pkg>.databinding.*`
FQN root. Distinguish them by `DataBindingUtil` / `Observable*` / `BR.*` references —
ViewBinding imports alone do not count as residuals.

**Build files.** `build.gradle*` files must have no:
- `dataBinding = true` in `buildFeatures` (or legacy `dataBinding { enabled = true }`)
- `kapt("androidx.databinding:databinding-compiler:…")` or equivalent annotation processor

**Scan tooling.** Small modules: `Glob` + `Bash` grep. Large modules: delegate to `Explore`
(haiku). Residuals are written to `<slug>-cleanup-status.md`; cleanup is blocked until empty.

## Cleanup package per module

When the residual scan is empty, the skill proposes the cleanup package via `AskUserQuestion`;
on approval, `developer-workflow-kotlin:kotlin-engineer` (sonnet) applies the edits:

1. **Disable DataBinding flag.** Set `dataBinding = false` in `buildFeatures`, or remove the
   line entirely if AGP's default is already `false`. Keep `viewBinding = true`.

2. **Remove KAPT if DataBinding was its sole reason.** Scan `build.gradle*` for other
   `kapt(…)` declarations (Dagger/Hilt, Room, Moshi codegen, etc.). If any remain, leave KAPT
   untouched. If no other processors use KAPT, remove `kotlin("kapt")` from the plugins block;
   note an optional follow-up to migrate remaining processors to KSP.

3. **Explicit dependency for `keep-as-regular-dep`.** Add an explicit `implementation` entry
   to `libs.versions.toml` and `build.gradle*` for any adapter library the user chose to keep.
   AGP no longer pulls it transitively after `dataBinding = false` — omitting the declaration
   causes a compile-time class-not-found failure.

## Five disposal options for `@BindingAdapter` sources

The table below maps adapter origin (from `adapter-resolution.md`) to applicable options.

| Origin | Applicable options |
|---|---|
| project-local (in scope) | `convert-to-extension`, `static-call`, `duplicate-from-sources`, `escalate` |
| project-local (out of scope) | leave file as-is (function stays callable without annotation), `static-call`, `escalate` |
| monorepo (other Gradle module) | `keep-as-regular-dep`, `duplicate-from-sources`, `escalate` |
| binary library | `keep-as-regular-dep`, `duplicate-from-sources`, `escalate` |
| implicit-setter | n/a — no adapter to dispose of |
| unresolved | `escalate` only |

**`keep-as-regular-dep`** — declare the library as a normal `implementation` dependency; call
its adapter functions as plain Kotlin. Requires an explicit entry when the artifact was
previously pulled transitively by AGP and will disappear after `dataBinding = false`.

**`duplicate-from-sources`** — copy the used adapter functions into a project-local file under
a new package; the original library dependency may then be dropped. Only after explicit user
approval with licence confirmation; undetermined licence falls through to `escalate`.

**`convert-to-extension`** — project-local sources only. Rewrite the `@BindingAdapter` method
as a Kotlin extension function on the target `View` subtype; drop the annotation, keep the body.

**`static-call`** — project-local sources only. Keep the function as a top-level function or
`object` member; drop the annotation. Callers invoke it directly rather than as an extension.

**`escalate`** — see `escalation-patterns.md`. Always used when the source is unresolved, the
licence blocks duplication, or the adapter requires DataBinding runtime infrastructure.

---

## Placement options for `convert-to-extension` and `duplicate-from-sources`

For every adapter going through `convert-to-extension` or `duplicate-from-sources`, the skill
stops and presents placement choices to the user before any file is written or rewritten. There
is no silent default.

**Candidate-discovery procedure.** The skill builds the candidate list by:
- Counting in-scope modules that use the adapter (from the property map's `adapter_origin` and
  the layout → host-class map from scope-discovery).
- For each potential shared parent module: verifying reachability from every consumer via
  `ast-index dependents`. A module is a viable candidate only if all consumers can already see
  it through existing module dependencies. The skill does NOT add new dependency edges silently;
  if a candidate would require a new edge, that is a follow-up the user must approve separately.
- The "new module" option is shown only if the user explicitly chose `--allow-new-module` (or
  equivalent) at scope intake; otherwise it is omitted entirely.

**Per-adapter prompt template:**

```
Adapter: <FQN of original method>
Disposal: convert-to-extension | duplicate-from-sources
Used by: <count> in-scope screens across <list of module paths>

Placement options:
1. In-module: <single module path>       (used only by this module)
2. Shared module (existing): <path>      (already on every consumer's classpath)
3. Shared module (existing): <path>      (alternative — reachable from N consumers)
4. New module: <suggested name>          (only if --allow-new-module was set)
5. Custom path                           (you provide)
```

**Ranking.** In-module wins when the adapter is used by exactly one in-scope module. A shared
module wins when two or more in-scope modules use the adapter and one shared parent is already
reachable from all of them. A new module is offered only as the last option and never as a
default.

**After the user picks.** The decision is recorded in `<slug>-adapter-sources.md` under the
`cleanup_status` column as the chosen placement path (e.g., `convert-to-extension → :core:ui`,
`duplicate-from-sources → :feature:profile`). The engineer agent writes the file at that
location.

**Batch prompting.** When multiple adapters share an identical candidate analysis (same consumer
set, same reachable shared modules), the skill MAY group them: "Adapters A, B, C share the same
placement candidates; pick one placement for all, or expand to per-adapter choice." This is an
optional usability optimization and must not be applied silently if the user prefers per-adapter
prompting.

---

## Cleanup status file

`./swarm-report/<slug>-cleanup-status.md` — one row per in-scope module, updated on every
cleanup pass:

| Column | Content |
|---|---|
| `module` | Gradle module path (`:app`, `:feature:login`, …) |
| `residuals_count` | Number of residual artefacts found in the last scan |
| `databinding_flag` | `removed` or `kept-due-to-residuals` |
| `kapt_status` | `removed`, `kept-due-to-<processor>`, or `n/a` |
| `disposal_decisions` | Count per option applied (e.g. `convert-to-extension: 2, keep-as-regular-dep: 1`) |
| `notes` | Blocked items, escalation reasons, follow-up lint rule status |

---

## Cross-references

- `adapter-resolution.md` — origin taxonomy and the five adapter buckets
- `escalation-patterns.md` — recipes for `escalate` outcomes
- `mechanical-transforms.md` — host-code residual definitions and replacement templates
- `property-map-spec.md` — schema for `<slug>-adapter-sources.md` and the `cleanup_status` column

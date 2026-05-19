# Scope Discovery

Discovery is the front-end for the entire `databinding-to-viewbinding` skill. Its output —
the seeded property map, variables map, and adapter inventory — is the contract that the skill
presents to the user at the USER GATE before any code changes begin.

---

## Scope intake

The skill accepts three intake shapes. Before running discovery, confirm the resolved scope
back to the user (modules list + estimated layout count). This confirmation is informational —
it is not the USER GATE. The gate fires after the property map is fully built.

**Module list.** The user names one or more Gradle modules: `":feature:profile"`,
`":feature:cart"`. For each named module verify that its `build.gradle*` contains
`dataBinding = true` (or the legacy form; see Module discovery below). Modules that do not
declare the flag are dropped from scope with a one-line note in `<slug>-discover-modules.md`.

**Layout list.** The user names specific XML layouts: `fragment_profile.xml`. The skill maps
each layout to its owning module, then includes that module in the cleanup scope. Layouts that
do not carry a `<layout>` root or any binding expression are dropped with a note.

**All in-tree.** The user says "everything" or "the whole project". The skill enumerates all
Gradle modules where `dataBinding = true` is enabled and runs discovery across all of them.
For large monorepos (more than ~50 modules), delegate enumeration to `Explore` (haiku).

---

## Module discovery

1. Locate all `build.gradle*` files via `Glob` (`**/build.gradle`, `**/build.gradle.kts`).
   Exclude `buildSrc/` and composite-build subprojects unless they appear in the user's
   explicit scope.

2. For each file, check for `android { buildFeatures { dataBinding = true } }` (current form) or
   `android { dataBinding { enabled = true } }` (legacy form). A module with neither is not a
   DataBinding module and is excluded from scope.

3. Record each in-scope module's Gradle path (`:feature:profile`) and filesystem root
   directory. Write the result to `./swarm-report/<slug>-discover-modules.md` with columns:
   gradle_path / root_dir / flag_form / layout_count (filled in after Layout discovery).

4. For monorepo-wide discovery (hundreds of modules), delegate to `Explore` (haiku) rather
   than running `Glob` and multiple `Read` calls in the main session.

---

## Layout discovery

For each in-scope module, walk `src/*/res/layout*/*.xml`. This glob covers `layout/`,
`layout-night/`, `layout-w600dp/`, `layout-land/`, and any other configuration qualifier
directories.

A layout is in scope only when both conditions hold:

- The root element is `<layout>` (or the outermost non-comment node is `<layout>`).
- At least one of the following is present: a `<data>` block, an `@{…}` or `@={…}` attribute
  anywhere in the file, or a `bind:` namespace attribute.

Layouts that have a `<layout>` root but carry no binding expressions are recorded as
candidates for a trivial wrapper-strip and flagged `no_bindings` — they may still need the
`<layout>` removed, but they are not enumerated in the property map.

Write `./swarm-report/<slug>-discover-layouts.md` with columns: module / layout_path /
has_data_block / binding_count / variable_count / include_refs.

For modules with many layouts (more than ~50 XML files), delegate the walk to `Explore`
(haiku).

---

## Host code discovery

For each in-scope layout, find every class that inflates it: Activities, Fragments, custom
Views, ViewHolders, and Adapters.

**Step 1 — Generated binding name lookup.** DataBinding's naming convention maps
`fragment_profile.xml` to `FragmentProfileBinding`. Run `ast-index usages FragmentProfileBinding`
to find all direct references to the generated class. Each reference site is a candidate host.

**Step 2 — Legacy inflation API.** Search for `DataBindingUtil.setContentView(this, R.layout.fragment_profile)`
and `DataBindingUtil.inflate(…, R.layout.fragment_profile, …)` to catch hosts that use the
utility class rather than the generated class directly.

**Step 3 — Nested include references.** Search for `<include layout="@layout/fragment_profile"/>`
in other in-scope layouts. Layouts that include this layout are themselves hosts and must be
tracked in the property map.

For each resolved host record: host class FQN, inflation call site (file path + line number),
and the binding-variable assignment pattern (`val binding`, `private lateinit var binding`,
field injection, factory parameter, etc.).

Flag the following for review rather than blocking discovery:

- **Zero-host layouts** — orphan layouts that are not inflated anywhere in the project. They
  may be unused or inflated dynamically via reflection or a third-party framework.
- **Multi-host layouts** — layouts inflated from more than one host class. Each host gets its
  own row in `<slug>-variables-map.md` for the `host_class` / `binding_call_site` columns.

---

## Custom `@BindingAdapter` discovery

Beyond the runtime classpath adapters (covered by `adapter-resolution.md`), the project may
declare its own `@BindingAdapter`, `@InverseBindingAdapter`, `@BindingConversion`, or
`@BindingMethods` annotations.

**Project-local sources.** For each in-scope module run
`ast-index search '@BindingAdapter'`. This covers Kotlin `object` and companion object
methods, top-level functions, and Java static methods within the module.

**Monorepo sources (out-of-scope modules).** Delegate a single `Explore` (haiku) agent to
scan the rest of the build. The Explore agent runs `ast-index search '@BindingAdapter'` across
all modules not already covered.

Collect results into `./swarm-report/<slug>-custom-adapters.md` (draft at this stage; the
`<slug>-adapter-sources.md` file is created and enriched by the adapter-resolution sub-phase
during Discovery — before the USER GATE. At the USER GATE, the user's per-adapter disposal
decisions fill in the `cleanup_status` and `placement_target` columns of existing rows — no
new rows are added post-gate). Columns:
origin_module / method_fqn / attribute_strings / signature / in_scope_usage_count.

Scope-discovery seeds the property map with `layout`/`view_id`/`view_type`/`attribute`/
`binding_kind`/`expression_raw`/`adapter_origin` placeholder. The remaining columns
(`expression_type`, `expression_fragment`, `adapter_symbol`, `replacement_fragment`, `bucket`)
are filled in by expression-resolution and adapter-resolution, which run as the next two
sub-phases of Discovery (still before the USER GATE). Do not invoke `ksrc` during the
`@BindingAdapter` discovery step — `ksrc` is invoked in the adapter-resolution sub-phase.

---

## `<variable>` and `<import>` discovery

Parse the `<data>` block of every in-scope layout. For each `<variable>` declaration emit one
row into `./swarm-report/<slug>-variables-map.md` (schema from `property-map-spec.md`). Fill
`layout`, `variable_name`, `declared_type`, `host_class`, and `binding_call_site` from the
data gathered in the previous two phases. Leave `replacement_strategy` and `notes` empty.

`<import>` declarations are noted in `<slug>-discover-layouts.md` but are not emitted as
separate rows. They are consumed by `expression-resolution.md` during the resolution pass.

---

## Binding enumeration and property-map seeding

For each in-scope layout, walk every attribute in every view element and collect all `@{…}` and
`@={…}` occurrences. For each occurrence, emit one partially-filled row into
`./swarm-report/<slug>-property-map.md` using the schema from `property-map-spec.md`.
Fill `layout`, `view_id`, `view_type`, `attribute`, `binding_kind`, and `expression_raw`.
Leave `expression_type`, `adapter_origin`, `adapter_symbol`, `replacement_fragment`, `bucket`,
and `notes` empty — they are filled during the expression-resolution and adapter-resolution
passes. Rows are sorted by layout path, then by source-line order within the layout.

---

## Tool routing

Use `Glob` + direct `Read` for small file counts (a few dozen layouts or build files). Delegate
to `Explore` (haiku) for any cross-module scan, monorepo-wide adapter search, or when more
than ~50 files need to be read in a single pass. Use `ast-index` for symbol-level lookups
(class/method/field discovery, reference walks — host class usages, legacy inflation calls, and
`@BindingAdapter` search). When `ast-index` is not initialized for the project, fall back to
`Grep` with explicit notes that precision is reduced — e.g., a bare `@BindingAdapter` regex may
catch occurrences inside comments or string literals. The Discovery output should flag rows where
the adapter resolution was Grep-based with `notes = "grep-resolved"` so the USER GATE can warn
the user. Use targeted `Grep` without fallback notes only for `<include>` layout references,
which are string patterns rather than symbol lookups.

`ksrc` is not used during the scope-discovery sub-phase — it enters during the adapter-resolution
sub-phase that follows (still within Discovery, before the USER GATE). `developer-workflow-kotlin:kotlin-engineer` is not used
at this phase — discovery is read-only and produces no code changes.

---

## Output artifacts

- `./swarm-report/<slug>-discover-modules.md` — module inventory (gradle path, root dir,
  flag form, layout count).
- `./swarm-report/<slug>-discover-layouts.md` — layout inventory (per-layout: has data block,
  binding count, variable count, include refs).
- `./swarm-report/<slug>-custom-adapters.md` — custom adapter inventory (draft; the
  adapter-resolution sub-phase enriches and finalizes it as `<slug>-adapter-sources.md`,
  all before the USER GATE).
- `./swarm-report/<slug>-property-map.md` — seeded by scope-discovery (with `expression_type`,
  `expression_fragment`, `adapter_origin`, `adapter_symbol`, `replacement_fragment`, and `bucket`
  columns empty at seed time); fully resolved by expression-resolution and adapter-resolution
  sub-phases before the USER GATE.
- `./swarm-report/<slug>-variables-map.md` — variable declarations; `replacement_strategy`
  column empty.

---

## Cross-references

- `property-map-spec.md` — full column schemas for all output files.
- `expression-resolution.md` — fills `expression_type` in the property map after Discovery.
- `adapter-resolution.md` — fills adapter columns and `bucket`; uses `ksrc` for runtime
  adapter pulling.
- `gradle-and-lint-gate.md` — covers the `dataBinding = true` / `viewBinding = true`
  coexistence flag and the per-module cleanup after the USER GATE.

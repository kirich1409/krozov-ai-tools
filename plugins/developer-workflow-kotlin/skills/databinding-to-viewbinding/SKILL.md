---
name: databinding-to-viewbinding
description: "Migrates Android DataBinding to ViewBinding screen-by-screen within a user-provided scope. Discovery phase builds a property map of all bindings and resolves adapters at runtime via ksrc. Single USER GATE before conversion. Per-module cleanup attempts to disable the dataBinding flag and remove kapt databinding-compiler when residual-scan is empty. Manual invocation only."
---

# DataBinding to ViewBinding

## Overview

This skill migrates Android DataBinding to ViewBinding screen-by-screen within a user-defined
scope. The workflow follows a strict ordering: discover all bindings and resolve their adapters
first, present the full picture to the user via a single USER GATE, then execute mechanical
conversions through an engineer agent while surfacing every escalation case explicitly.
Behavioural parity is the contract for everything in the `mechanical` bucket. The `escalate`
bucket requires explicit user or engineer decisions before any code is written for that row.

The skill is intentionally narrow. It does not perform unrelated refactors, does not switch MVVM
patterns wholesale, and does not decommission `Observable*` property holders by default —
Observable decommission is treated as an escalation recipe that the user opts into per row. It
does not convert layouts to Jetpack Compose. For those paths, use
`developer-workflow-kotlin:migrate-to-compose`, `developer-workflow-kotlin:kmp-migration`, or
the general `developer-workflow-kotlin:migration` skill.

Silent guessing is prohibited. Every unresolved expression, every unmatched adapter, and every
binary-only library that fails `ksrc` lookup lands in the `escalate` bucket with an explicit
note. The `mechanical` bucket is the only zone where the engineer agent writes code without
human confirmation.

## Workflow

```
1. Scope intake  →  2. Discovery  →  3. USER GATE
                                           ↓
6. Optional next-steps ← 5. Per-module cleanup ← 4. Conversion (per screen)
```

Step 3 (USER GATE) is the only mandatory blocking gate. Every other phase is a checklist for
the user, not a forced pipeline transition. The skill produces material; the user drives the
flow. If you find yourself enforcing phase completion order or calling other skills from inside
a phase, stop — that is the orchestrator anti-pattern.

## Phase 1 — Scope intake

Three intake shapes are accepted, per `references/scope-discovery.md` §2:

- **Module list.** The user names one or more Gradle module paths (`:app`, `:feature:login`).
  All `dataBinding = true` modules within that list are in scope.
- **Layout list.** The user names specific layout files or a directory. Only those layouts and
  their host classes are in scope.
- **All in-tree.** No explicit scope. The skill discovers every module with `dataBinding = true`
  in the project tree. For repositories with many DataBinding modules, prefer module-by-module
  scope over a single all-in-tree migration to keep the USER GATE summary tractable.

Before discovery begins, the skill echoes the resolved scope back to the user (module paths,
layout count estimate, and any excluded modules). This is informational — not the USER GATE.
The user may correct the scope at this point. Output: the scope is recorded implicitly in the
discovery artifacts; no separate artifact is produced for intake alone.

Cross-reference: `references/scope-discovery.md`.

## Phase 2 — Discovery

Discovery builds the complete picture of every DataBinding usage in scope. It runs once per
scope, before any code is touched. Five subactivities:

**Module discovery.** Enumerate every Gradle module in scope; verify `dataBinding = true`
(or legacy `dataBinding { enabled = true }`) in its `buildFeatures` block; note the AGP
version and whether `viewBinding = true` is already present. Output:
`./swarm-report/<slug>-discover-modules.md`. Cross-reference: `references/scope-discovery.md` §3.

**Layout discovery.** For each in-scope module, find all XML layouts with a `<layout>` root
and a non-empty `<data>` block. Record presence of `@{`, `@=`, `bind:`, `<variable>`, and
`<include>` elements. Output: `./swarm-report/<slug>-discover-layouts.md`.
Cross-reference: `references/scope-discovery.md` §4.

**Host code discovery.** For each in-scope layout, find every class that inflates it —
Activities, Fragments, custom Views, ViewHolders, and Adapters. Use `ast-index usages
<GeneratedBindingName>` as the primary lookup; supplement with `DataBindingUtil.setContentView`
and `DataBindingUtil.inflate` search for hosts using the utility class. Flag zero-host layouts
and multi-host layouts. Cross-reference: `references/scope-discovery.md` §5.

**Custom `@BindingAdapter` discovery.** Use `ast-index` to find all `@BindingAdapter`,
`@InverseBindingAdapter`, `@BindingConversion`, and `@BindingMethods` annotations declared
in the project source tree and across monorepo modules. Record FQN, attribute name, parameter
types, and source file. Output: `./swarm-report/<slug>-custom-adapters.md` (draft; upgraded to
`<slug>-adapter-sources.md` after the gate). For adapters in binary dependencies — including
`androidx.databinding:databinding-adapters` — use `ksrc` against the version pinned in the
project to pull the actual source signatures at runtime. Cross-references:
`references/scope-discovery.md` §6, `references/adapter-resolution.md` §3.

**Per-binding resolution pass.** For each binding expression row seeded into the property map,
run expression resolution followed by adapter resolution:
- Expression resolution (`references/expression-resolution.md`) classifies the expression,
  determines `expression_type`, and detects grammar-level escalations (deep ternaries, dynamic
  types, multi-method listeners).
- Adapter resolution (`references/adapter-resolution.md`) matches the attribute + `expression_type`
  against the adapter source tiers in priority order, selects the correct overload, and builds
  the `replacement_fragment`. It also consults `references/binding-features-matrix.md` to
  assign every row a `bucket` (`mechanical`, `partial`, or `escalate`) and applies the consensus
  rule when a row matches multiple features.

**Tool routing.** Delegate cross-module scans and any pass over more than ~50 files to
`Explore` (haiku). Use `ast-index` for all symbol-level lookups within the project. Use `ksrc`
as the runtime adapter discovery channel for binary dependencies. Targeted `Grep` is permitted
only for `<include>` layout references (string patterns, not symbols).

**Output artifacts** (all in `./swarm-report/`):
- `<slug>-discover-modules.md` — module inventory (mandatory)
- `<slug>-discover-layouts.md` — layout inventory (mandatory)
- `<slug>-custom-adapters.md` — custom adapter draft (mandatory)
- `<slug>-property-map.md` — seeded and fully resolved property map (mandatory)
- `<slug>-variables-map.md` — `<variable>` declarations with `replacement_strategy` empty (mandatory)
- `<slug>-adapter-sources.md` — resolved adapter sources with `ksrc` provenance (optional; emitted
  when binary adapters are present)

Cross-references: `references/property-map-spec.md` (full column schemas),
`references/scope-discovery.md` §8–§9.

## Phase 3 — USER GATE

The single mandatory blocking step. The skill presents the following summary to the user:

- Total binding count and layout count in scope.
- Count per bucket: `mechanical` / `partial` / `escalate`.
- Count per `adapter_origin` (project-local, monorepo, binary-library, implicit-setter, unresolved).
- Full list of every `escalate` row — layout, attribute, and a one-line recipe pointer
  referencing `references/escalation-patterns.md` (e.g., `two-way §EditText.text`,
  `observable-decommission §ObservableField<T>`, `unresolved-adapter §my:customAttr`).
- All `partial` rows with their caveats.

The user may:

1. **Approve and proceed.** The property map is appended with an
   "Approved on YYYY-MM-DD by USER" footer and treated as immutable for the remainder of the
   migration. Confirmation in any language; matched by intent.
2. **Narrow the scope.** Remove specific layouts or modules and re-run Phase 2 on the subset.
3. **Resolve a row manually.** The user provides a replacement strategy for an `escalate` or
   unresolved row; update the property map and optionally re-run the resolution pass for that
   row only.

This gate is presented once. No re-prompting. Returning to Phase 2 after approval requires
passing through this gate again. The immutable approved property map is the source of truth
for Phases 4 and 5.

Cross-reference: `references/property-map-spec.md` §USER-GATE-handoff.

## Phase 4 — Conversion (per screen)

For each in-scope layout, in order. Steps 2–4 describe per-row bucket handling; steps 5–6 describe layout-wide and host-class transforms; they execute concurrently per screen, not sequentially.

**Resuming after a pause.** The approved `<slug>-property-map.md` is the durable state — no phase re-runs are needed as long as it has not changed. Conversion is per-screen and idempotent: re-running the engineer brief on an already-converted screen is a no-op because the layout transforms (`<layout>` removal, `<data>` removal) will simply be absent and the engineer will reject them as already done. To resume, re-read the property map, identify the next layout whose host code still imports DataBinding APIs or whose XML still contains `<layout>`, and continue from that screen.

1. The `developer-workflow-kotlin:kotlin-engineer` agent (sonnet) receives a brief naming the
   layout file, the relevant rows from `<slug>-property-map.md` and `<slug>-variables-map.md`,
   and must-read references: `references/mechanical-transforms.md` and
   `references/escalation-patterns.md`. The brief instructs the engineer per bucket:
   `mechanical` rows — write the replacement immediately; `partial` rows — write the default
   replacement AND attach a one-line `// review: <caveat>` comment beside the host-code change;
   `escalate` rows — do NOT write code, emit one question block per row in the per-screen status
   output referencing the recipe from `references/escalation-patterns.md`.

2. **`mechanical` rows.** The engineer applies every transform defined in
   `references/mechanical-transforms.md`: remove the `<layout>` wrapper and `<data>` block
   from XML, replace or remove one-way `@{…}` attribute values, update namespace declarations,
   update the host-class inflate call to the ViewBinding pattern, replace per-binding access
   calls with direct field access, and insert the `_binding = null` lifecycle cleanup for
   Fragments. No human review is needed before the screen is submitted to `/check`.

3. **`partial` rows.** The engineer applies the default transform and leaves a structured note
   in the property map row (`notes` column) surfacing the caveat. The user sees the note when
   `/check` runs or when the screen brief is reviewed.

4. **`escalate` rows.** The engineer stops on that row and emits the recipe context per
   `references/escalation-patterns.md` (recipe name, options, trade-offs). The user picks the
   recipe — or asks Claude to pick based on visible project convention — before any code is
   written for that row. Escalation recipes include: `two-way`, `two-way-inverse`,
   `Observable decommission`, `ViewStub`, `<merge>`, `BR references`, `ambiguous overload`,
   `unresolved adapter`, `multi-method listener`, `adapter cleanup`. (`LiveData wiring` is
   `partial`, not escalate — `escalation-patterns.md §LiveData wiring` carries the replacement
   scaffold and is not blocked.)

5. **XML transforms.** Per `references/mechanical-transforms.md` §XML. Applied in a single
   ordered pass: remove `<layout>`, delete `<data>`, replace or remove `@{…}` attribute values,
   handle `<include>` elements, clean up `bind:` namespace prefixes.

6. **Host-class transforms.** Per `references/mechanical-transforms.md` §3–§5. Activity,
   Fragment, and ViewHolder inflate patterns; `_binding = null` rule; DataBinding-only call
   removal; per-binding replacement assembly using the approved `replacement_fragment`.

7. **Inline-first for repeated patterns.** When a mechanical or escalation pattern (e.g., the
   two-way TextWatcher shape, the `repeatOnLifecycle` collector block) recurs across multiple
   screens, the engineer writes it inline each time during per-screen conversion.

8. After the screen completes, the user runs `/check` if desired. A `/check` failure on a
   specific row loops back to step 2 for that row. This skill does not invoke `/check`.

## Phase 5 — Per-module cleanup

Once every in-scope screen in a module has been converted and any desired `/check` runs pass:

**Residual scan.** Run the residual scan defined in `references/gradle-and-lint-gate.md "Residual scan per module"` against XML layouts, Kotlin/Java host code, and build files. Any hit blocks cleanup for that module. Results are written to `./swarm-report/<slug>-cleanup-status.md`.

**Cleanup package** (applied only when residual count is zero). The
`developer-workflow-kotlin:kotlin-engineer` agent applies per `references/gradle-and-lint-gate.md` "Cleanup package per module":
- Toggle `dataBinding = false` (or remove the flag) in `buildFeatures`.
- Remove `kapt("androidx.databinding:databinding-compiler:…")` if DataBinding was its sole
  annotation processor; keep `kapt` if other processors remain.
- When the user chose `keep-as-regular-dep` for any adapter disposal option, declare the
  `androidx.databinding:databinding-adapters` dependency explicitly so it is not lost when
  `dataBinding = false` removes the implicit transitive pull.

**Adapter disposal.** Five options per `references/gradle-and-lint-gate.md` "Five disposal options for @BindingAdapter sources":
`keep-as-regular-dep`, `duplicate-from-sources`, `convert-to-extension`, `static-call`,
`escalate`. The user selects per adapter or per batch. For adapters going through
`convert-to-extension` or `duplicate-from-sources`, the skill presents an explicit per-adapter
placement prompt (candidate list with rationale, ranked in-module → shared module → new module)
before the engineer writes any file — no placement is applied silently. See
`references/gradle-and-lint-gate.md "Placement options"` for the prompt template and ranking
criteria.

Output: `./swarm-report/<slug>-cleanup-status.md` (updated after every cleanup attempt).
Cross-reference: `references/gradle-and-lint-gate.md`.

## Phase 6 — Optional next-steps

These are suggestions for the user after this skill's work is complete. None are invoked from
inside this skill.

- `/check` — run the full quality gate over the converted scope before committing. The user
  invokes this directly.
- `developer-workflow-kotlin:snapshot` — characterize visual behaviour before/after if
  additional UI regression gates are desired. The user runs it manually.
- `developer-workflow:write-tests` — add regression coverage for `partial`-bucket rows where
  the caveat warrants an automated check. The user invokes it manually.
- `developer-workflow:manual-tester` agent — exploratory QA against the running app.
  The user invokes it directly.
- `developer-workflow-kotlin:migrate-to-compose` — natural follow-up when the user wants to
  move further. This skill leaves screens in pure-ViewBinding state, which is a valid
  Compose-migration starting point. Note: screens that replaced `Observable*` with `LiveData`
  (per `references/escalation-patterns.md §Observable decommission`) may require a follow-up
  `LiveData → StateFlow` migration before or during Compose conversion; this is normal
  Compose-migration scope, not regression.

## Artifacts checklist

All artifacts live in `./swarm-report/`. Mandatory artifacts are marked **(M)**.

**Phase 2 — Discovery**
- `<slug>-discover-modules.md` — module inventory **(M)**
- `<slug>-discover-layouts.md` — layout inventory **(M)**
- `<slug>-custom-adapters.md` — custom adapter draft **(M)**
- `<slug>-property-map.md` — resolved property map **(M)**
- `<slug>-variables-map.md` — variable declarations **(M)**
- `<slug>-adapter-sources.md` — binary adapter provenance (optional; when binary adapters present)

**Phase 3 — USER GATE**
- `<slug>-property-map.md` appended with approval footer **(M)**

**Phase 5 — Cleanup**
- `<slug>-cleanup-status.md` — residual scan and disposal decisions per module **(M)**

## Delegation routing

| Phase | Primary agent | Model |
|---|---|---|
| 1–2 Module/layout/adapter scan | `Explore` for cross-module passes | haiku |
| 2 Symbol lookups | `ast-index` via main session | — |
| 2 Binary adapter resolution | `ksrc` via main session | — |
| 3 USER GATE | main session synthesis | — |
| 4 Conversion | `developer-workflow-kotlin:kotlin-engineer` | sonnet |
| 5 Residual scan (large modules) | `Explore` | haiku |
| 5 Cleanup edits | `developer-workflow-kotlin:kotlin-engineer` | sonnet |

For the full orchestration matrix and the rules under which the main session delegates, see
`~/.claude/rules/orchestration.md`.

## Anti-patterns / red flags

- This skill calling `/check`, `/finalize`, or `/create-pr` from inside its own phases. The
  skill produces material; the user runs the surrounding flow.
- A screen's `escalate` rows exceeding half of its total bindings. This usually means the scope
  was defined too broadly or the screen is a better candidate for a different migration target
  (Compose rather than ViewBinding).
- The `dataBinding` flag toggled off before the residual scan is empty. Cleanup must wait;
  partial flag removal leaves the build in an inconsistent state.
- The property map modified after the USER GATE approval without running the gate again. The
  approved map is immutable; any change invalidates the approval footer.
- Invocation triggered by a phrase match rather than an explicit user request. This skill is
  manual-only; no automatic activation is permitted.

## Cross-references

- `references/scope-discovery.md` — three intake shapes, module/layout/host discovery algorithms,
  tool routing rules, and output artifact schemas for the discovery phase.
- `references/property-map-spec.md` — full column schemas for `<slug>-property-map.md`,
  `<slug>-variables-map.md`, and `<slug>-adapter-sources.md`; USER GATE handoff contract.
- `references/expression-resolution.md` — `@{…}` and `@={…}` mini-grammar, identifier
  resolution algorithm, escalation rules, and `expression_type` handoff to adapter resolution.
- `references/adapter-resolution.md` — adapter source taxonomy (five tiers), runtime adapter
  discovery via `ksrc`, overload selection algorithm, `@BindingConversion` handling, and
  replacement-template builder.
- `references/binding-features-matrix.md` — feature-to-bucket classification table (mechanical /
  partial / escalate), consensus rule for multi-feature rows, and per-feature cross-references.
- `references/mechanical-transforms.md` — concrete code patterns for XML layout transforms,
  `<include>` transforms, host-class inflate patterns, `_binding = null` rule, DataBinding-only
  call removal, and per-binding replacement assembly.
- `references/escalation-patterns.md` — recipes for every `escalate` bucket outcome: two-way
  binding, Observable decommission, ViewStub, `<merge>`, BR references, adapter cleanup,
  unresolved adapter, multi-method listener, and ambiguous overload.
- `references/gradle-and-lint-gate.md` — coexistence configuration for `dataBinding` +
  `viewBinding` flags, lint baseline forward gate, residual scan criteria, cleanup package
  steps, five adapter disposal options with placement choices, and cleanup status file schema.

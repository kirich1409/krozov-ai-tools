# Migration Approaches

Four approaches to migrating from one technology to another, with the criteria that select between them and the mechanics of each. Consult this document during Phase 4 (Strategy) — the choice of approach is the most consequential decision of the entire migration.

## Decision tree

Use this order of questions to pick an approach. Stop at the first match.

1. **Does the technology have a global contract that cuts across the whole module graph?** (DI registry, async runtime, build plugin, logging framework, serialization framework.) → **Branch by Abstraction**. Copies cannot coexist; you need a single contract and two implementations behind it.

2. **Is the migration scoped to a self-contained vertical (one screen, one feature module, one bounded set of files) with no global contract?** → **Strangler Fig**. Migrate the slice end-to-end on the new stack; the rest of the system continues on the old stack via interop (`ComposeView`/`AndroidView`, Dagger/Metro interop, RxJava-Coroutines bridges).

3. **Inside a vertical slice, is introducing a common abstraction artificial?** (For example: an XML screen and a Compose screen do not share a meaningful API contract — they are different paradigms.) → **Duplicate-then-delete**. Copy the file/class/module, freeze the original, migrate the copy, switch routing, then delete the original.

4. **Is the migration an idiom swap where the compiler enforces parity?** (Databinding → ViewBinding, KAPT → KSP for one processor, `kotlin-android-extensions` → ViewBinding, Java → Kotlin file-by-file.) → **Utility refactor**. Enable both side-by-side, convert in batches, remove the old flag.

Edge cases:
- **Cross-cutting concern over a vertical slice** (e.g., migrating logging on one screen): treat as Utility refactor — the contract is local.
- **DB schema migration**: this is a different category. Use proper migration tooling (Room/SQLDelight migrations, Flyway, Liquibase). The four approaches here do not apply directly.
- **`expect/actual` contract change in KMP**: the migration is horizontal across platforms — use Branch by Abstraction, but the `expect` declaration *is* the abstraction.

---

## Approach 1: Branch by Abstraction

**Source.** Fowler, https://martinfowler.com/bliki/BranchByAbstraction.html.

**When.** Horizontal migrations: DI framework (Hilt → Metro, Dagger → Hilt), async runtime (RxJava → Coroutines), serialization (Gson → kotlinx.serialization), logging framework, threading model, build plugin replacement (KAPT → KSP for projects with many processors). Anywhere the technology has a global contract that touches the whole module graph.

**Mechanics.**

1. **Identify.** Find every use-site of the FROM technology. Output of Phase 2 (Discover).
2. **Introduce abstraction.** Define an interface or abstract type that captures the contract. The existing `OldImpl` implements it; nothing else changes. Convert every use-site to depend on the abstraction. The system still runs on `OldImpl` — behavior is unchanged.
3. **Build new implementation.** Write `NewImpl` against the abstraction. Wire it up but do not switch yet. Run all contract tests against both implementations in a `@ParameterizedTest impl: [OldImpl, NewImpl]` matrix.
4. **Switch incrementally.** Feature flag, per-module switch, per-environment toggle. One line of code chooses `OldImpl` or `NewImpl`. Rollback is the inverse.
5. **Remove old.** After full cutover and a soak period, delete `OldImpl`. If the abstraction was introduced only for the migration and has no other reason to exist, consider removing it as well.

**Trade-offs.**

- (+) System works on every step. No long-lived divergent branches.
- (+) Rollback is one line.
- (+) Parallel `OldImpl`/`NewImpl` under one contract enables shadow run and A/B testing.
- (−) Up-front investment in characterization tests is non-trivial.
- (−) The abstraction can fossilize and remain after the migration is "done", carrying maintenance cost.

**Phase 3 (Behavior-Fix) emphasis.** Plane A (code tests) is dominant — characterization tests on `OldImpl` become contract tests on the abstraction.

---

## Approach 2: Strangler Fig (vertical slice)

**Source.** Fowler, https://martinfowler.com/bliki/StranglerFigApplication.html.

**When.** Vertical migrations where the unit of migration is a self-contained slice: one screen, one feature module, one bounded set of files. The migration progresses slice by slice; the rest of the system runs on the old stack until its own slice is migrated.

**Mechanics.**

1. **Slice inventory.** List every slice that needs to migrate (Phase 2 output). Order by complexity ascending — simplest first to build team experience.
2. **Coexistence layer.** Establish how old and new stacks coexist. UI: `ComposeView` and `AndroidView` from Google's official interop (https://developer.android.com/develop/ui/compose/migrate/interoperability-apis). DI: Dagger/Metro interop modules. Async: `rxSingle { }`, `await()`, `asFlow()`, `asObservable()`.
3. **Migrate one slice.** Pick the first slice. Replace its implementation entirely on the new stack. Wire it back into the system via the coexistence layer. Capture behavior tests against the slice before and after.
4. **Verify and ship.** Phase 6 on the slice. Ship it (behind a feature flag for the first slice; subsequent slices once the team is confident).
5. **Repeat.** Move to the next slice.
6. **Remove coexistence layer.** When the last slice migrates, the bridge is no longer needed. Delete it.

**Trade-offs.**

- (+) Risk is bounded to one slice at a time.
- (+) Production feedback per slice — issues surface early.
- (+) Compatible with Duplicate-then-delete inside a slice (combine approaches).
- (−) Coexistence layer is fragile and must be policed; long-lived hybrid screens are anti-pattern (Getir, Reddit case studies).
- (−) Some slices are not actually self-contained; what looks like a slice may share state with the rest of the system.

**Phase 3 (Behavior-Fix) emphasis.** Plane B (test cases) and Plane C (manual scenarios) carry most of the weight per slice. Plane A is useful but slice-scoped.

---

## Approach 3: Duplicate-then-delete

**When.** Vertical migrations where introducing a common abstraction (Branch by Abstraction) would be artificial. The classic case: migrating an XML screen to a Compose screen — there is no meaningful API contract shared by `LoginActivity` and `LoginScreen` composable. They are different paradigms.

Also applies to: self-contained utility classes, mappers, pure functions, entire feature modules.

**Mechanics.**

1. **Copy.** Duplicate the file/class/module under a new name or in a new package. Examples: `LoginScreenLegacy.kt` next to `LoginScreen.kt`; `:feature:checkout-legacy` next to `:feature:checkout`; `OldMapper.kt` frozen, `NewMapper.kt` mutable.
2. **Freeze the original.** Do not modify the original after the copy is made. If a bug surfaces in the original during the migration, decide explicitly: fix in original (and re-copy), fix only in new, or leave both (defer).
3. **Route.** Build the switch mechanism. Options: feature flag (`if (flag.useNewLogin) NewLoginScreen() else LegacyLoginScreen()`); build variant (`mainDebug` vs `mainRelease`); navigation entry (`composable("login_new")` vs `Fragment("LoginLegacy")`); `productFlavors` for fully separated builds.
4. **Migrate the copy.** Rewrite the copy on the new stack while the original keeps serving production. Phase 6 device verification runs on the copy.
5. **Switch routing.** Route all traffic to the new copy. Monitor.
6. **Delete the original.** After a soak period, delete the original and simplify the routing to single-target.

**Trade-offs.**

- (+) Rollback is trivial: switch routing back, delete the copy.
- (+) No abstraction overhead; no forcing of artificial contracts.
- (+) Side-by-side code makes review easier — reviewers see both versions.
- (−) Code drift: the original may get bugfixes that miss the copy (or vice versa). Mitigation: explicit freeze policy.
- (−) Double build cost during the transition.
- (−) Naming and package conflicts: requires explicit naming convention (`*Legacy` suffix, `legacy/` subpackage) or separate modules.
- (−) Does not work for horizontal migrations (DI, async) — global graphs do not duplicate.

**Phase 3 (Behavior-Fix) emphasis.** Plane B (test cases) and golden snapshots (Plane A subset). Test cases are walked against both copies during Phase 6.

---

## Approach 4: Utility refactor

**When.** The migration is an idiom swap where the compiler and lint enforce parity:

- Databinding → ViewBinding (replaces XML expression evaluation with direct field access; compiler catches type mismatches).
- KAPT → KSP for a specific annotation processor (Room, Dagger, Hilt — all ship KSP variants with the same generated API).
- `kotlin-android-extensions` (synthetic properties) → ViewBinding.
- Java → Kotlin file-by-file (Kotlin compiler enforces null safety, type checks).
- Gradle Groovy DSL → Kotlin DSL.
- Older API → newer API on the same library, where the change is mechanical.

**Mechanics.**

1. **Enable side-by-side.** Turn on the new technology while leaving the old enabled. Example: `buildFeatures { viewBinding = true; dataBinding = true }`. Both can coexist during transition.
2. **Convert in batches.** Use IntelliJ refactoring, an existing plugin (`Flamedek/viewbinding-migration-plugin` for Databinding → ViewBinding), or a scripted codemod. Convert per module or per batch of files. Run the build after each batch.
3. **Handle non-mechanical leftovers.** Each idiom has corner cases the compiler cannot rewrite for you. For Databinding → ViewBinding: `@BindingAdapter` definitions, two-way binding (`@={}`), `BindingConversion`, `@={ ...}` observable polling. Extract these into extension functions or imperative listener code.
4. **Snapshot UI sanity check (optional but recommended).** Run Paparazzi/Roborazzi on the screens that used the old idiom — catches null-handling and visibility regressions.
5. **Remove the old flag.** Once no use-sites remain, drop `dataBinding = true` (or whatever the activation flag was). Delete generated files. Update `libs.versions.toml` if the dependency is no longer needed.

**Trade-offs.**

- (+) Cheapest class of migrations.
- (+) Compiler is the safety net; runtime regressions are rare.
- (+) Can be done incrementally on a large codebase without a flag day.
- (−) The "trivial" idiom swap often hides a non-trivial corner: `@BindingAdapter` removal can be substantial work in itself.
- (−) Easy to forget the cleanup step — `dataBinding = true` stays in build files even after the last `<layout>` tag is gone, KAPT plugin stays when no processors need it.

**Phase 3 (Behavior-Fix) emphasis.** Plane B (test cases) for sanity; Plane A only on parts the compiler does not catch (custom binding adapters, null handling, two-way binding logic).

---

## Side-by-side comparison

| Dimension | 1. BBA | 2. Strangler | 3. Duplicate-then-delete | 4. Utility refactor |
|---|---|---|---|---|
| Effort | L | M per slice | M | S |
| Blast radius | Whole graph behind one contract | One slice | One file/class | Imports + generated |
| Rollback | One line (switch impl) | Per-slice route | Delete copy + switch | Revert commit |
| Behavioral guarantee | Contract tests, optional shadow run | Golden snapshots + behavior-scenarios | Side-by-side QA + golden snapshots | Compiler + lint + snapshot sanity |
| Cleanup signal | Delete `OldImpl` + interface | Delete coexistence layer | Delete original file/module | Drop old flag, delete generated |
| Boundary location | Module / Gradle dependency | Composable / Fragment / Screen / Module | File / class / package | Import / package |
| Horizontal contract (DI, async, build) | Yes | No (slice has no global contract) | No (cannot duplicate global graph) | Yes (compiler enforces) |
| Vertical slice (UI, screen) | Possible but artificial | Yes | Yes | Possible |

---

## Common FROM/TO pairs and where to find authoritative docs

When studying FROM and TO in Phase 1, prefer authoritative sources. Training-data memory is unreliable for build-time behavior.

| Migration | Approach | Where to verify |
|---|---|---|
| Databinding → ViewBinding | Utility refactor | https://developer.android.com/topic/libraries/view-binding/migration |
| `kotlin-android-extensions` → ViewBinding | Utility refactor | https://developer.android.com/topic/libraries/view-binding/migration |
| Dagger → Hilt | BBA + Utility (mechanical parts) | https://dagger.dev/hilt/migration-guide.html |
| Hilt / Dagger → Metro DI | BBA | https://github.com/ZacSweers/metro, https://www.zacsweers.dev/metro-is-stable/ |
| Anvil → Metro DI | BBA | https://github.com/ZacSweers/metro, square/metro-extensions for compiler-plugin scenarios |
| RxJava → Coroutines/Flow | BBA | kotlinx-coroutines-rx interop module README on GitHub |
| Gson/Moshi → kotlinx.serialization | BBA | https://kotlinlang.org/docs/serialization.html |
| KAPT → KSP (specific processor) | Utility refactor | https://kotlinlang.org/docs/ksp-overview.html, processor's own KSP guide |
| Java → Kotlin (per file) | Utility refactor | https://kotlinlang.org/docs/mixing-java-kotlin-intellij.html |
| XML View → Compose (a screen) | Duplicate-then-delete | Use the `migrate-to-compose` skill (this skill defers to it) |
| Fragment navigation → Compose navigation | Strangler Fig per screen | https://developer.android.com/develop/ui/compose/navigation |
| Groovy Gradle → Kotlin Gradle | Utility refactor (file by file) | https://docs.gradle.org/current/userguide/migrating_from_groovy_to_kotlin_dsl.html |
| AGP major bump with breaking changes | Utility refactor + targeted BBA for breakages | https://developer.android.com/build/agp-upgrade-assistant, release notes for the AGP version |

For each migration, also check:
- The library's own GitHub release notes for the FROM and TO versions, focusing on breaking changes between them.
- A dependency-changelog lookup capability, if one is installed, can summarize the diff between two versions automatically; otherwise read the release notes manually.
- A vulnerability scan on the FROM dependency in the current project — a known CVE in FROM is a separate decision input. If a vulnerability is also publicly known to be fixed in TO, that strengthens the case for the migration. Use whatever dependency-vulnerability scanner is installed (or the ecosystem default: `npm audit`, `pip-audit`, `cargo audit`, the OSV CLI).

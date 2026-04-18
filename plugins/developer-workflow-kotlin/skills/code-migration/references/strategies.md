# Migration Strategies — Detailed Reference

## Strategy Reference Table

| Strategy | Core mechanism | Fits when |
|----------|---------------|-----------|
| **In-place** | Replace directly in existing files; build stays green after each file | ≤5 files, few external callers, good test coverage, internals-only change |
| **Parallel (Expand-Contract)** | **Expand:** add new impl alongside old. **Migrate:** swap callers one-by-one (each step independently rollbackable). **Contract:** delete old when all callers switched. Layer-by-layer for large scope (data → domain → UI) | Many callers, breaking interface change, uncertain behavior, large scope |
| **Branch by Abstraction** | Introduce interface → implement new behind it → swap DI binding → delete old. Callers never change | Public API must stay stable; new technology fits behind the same interface |
| **Big Bang** | Full rewrite on a branch; switch at merge. **Requires:** explicit rollback plan agreed with user before starting — what condition triggers rollback, who decides, and is the rollback path tested? | Coupling makes incremental impractical. Last resort — flag the risk explicitly |
| **Feature-flagged Parallel** | New impl behind a feature flag; old path stays live. Flag enables gradual rollout or instant rollback without redeployment | Large UI migrations (e.g., Compose rollout screen-by-screen); risky behavioral changes where production validation is needed before full switch |

## Strategy Option Format

Format each option like this:

> **Option A — [Strategy name]** ⭐ recommended
> Preparation: [what to do before migrating — e.g., extract module, add tests, introduce interface — or "none"]
> Migration: [how the actual migration proceeds]
> PRs: [how the work splits into PRs — e.g., "PR 1: module isolation + tests, PR 2: data layer, PR 3: UI layer, PR 4: cleanup"]
> Effort: low / medium / high
> Risk: low / medium / high
> Why: [1–2 sentences tied to what you found in discovery]

Non-recommended options may still be offered if they are genuinely viable (different trade-offs, not wrong). But strategies that don't fit should be explicitly dismissed — name them and explain why based on what you found:

> **Not offered:** Big Bang — 6 callers across 4 modules with no tests means a regression has no safety net and is expensive to debug. In-place — breaking interface change means all 6 ViewModels must be updated simultaneously, too broad for a single step.

Dismissing a strategy clearly is more useful than listing it as an option.

## Module Isolation as Preparation

Propose extracting to a dedicated Gradle module when it reduces risk or effort more than it adds:
- Target is mixed into a large module and the migration changes its public API — isolation limits blast radius to dependents of that module, and `./gradlew :new-module:assemble` gives fast feedback
- Build is slow and targeted module builds would meaningfully speed up iteration
- Skip when the target is already isolated, or when it's a small in-place change with few callers

Isolation sequence (when included as preparation): extract → `./gradlew :new-module:assemble` green → migrate inside the module.

## In-place Strategy

- Single file: migrate in one step
- Multiple files: file-by-file; build must stay green after each file
- **Commit cadence:** commit after each file is migrated and tests are green

## Extension Function Bridge (Parallel Variant)

When the migration involves an API shape change (e.g., RxJava → coroutines), extension functions can serve as a temporary bridge layer — keeping both old and new callers happy simultaneously without duplicating the implementation. Two directions:

**Direction A — Implementation-first (rewrite core, keep old surface for callers)**
1. Rewrite the implementation to the new technology (e.g., `suspend fun`/`Flow`)
2. Add a `*Compat.kt` file with extension functions that re-expose the old API style:
   ```kotlin
   // UserRepositoryCompat.kt — temporary bridge, deleted after migration
   fun UserRepository.getUserRx(id: String): Single<User> =
       rxSingle { getUser(id) }  // wraps suspend fun in RxJava
   ```
3. Callers compile unchanged. Migrate them one-by-one from `getUserRx()` → `getUser()` (suspend)
4. When all callers switched, delete `*Compat.kt` and remove RxJava dependency

**Direction B — Caller-first (callers adopt new style early, implementation migrates later)**
1. Keep the original implementation unchanged (RxJava)
2. Add extension functions that expose a coroutines surface over the existing RxJava API:
   ```kotlin
   // UserRepositoryExt.kt — temporary bridge, deleted after rewrite
   suspend fun UserRepository.getUserSuspend(id: String): User =
       getUser(id).await()  // wraps RxJava Single in coroutine
   ```
3. Migrate callers one-by-one from `getUser()` (RxJava) → `getUserSuspend()` (coroutine)
4. Once all callers use the suspend form, rewrite the implementation to native `suspend fun`
5. Rename `getUserSuspend` → `getUser`, delete extension file, remove RxJava dependency

**Choosing a direction:**
- Use **A** when the implementation is straightforward to rewrite and you want callers to migrate gradually afterward
- Use **B** when callers are numerous or spread across teams and you want to migrate them independently of the implementation rewrite — callers can move at their own pace without waiting for the implementation
- Both are temporary — the extension file is scaffolding, not permanent code. Name it clearly (`*Compat.kt`, `*Ext.kt`, or `*Bridge.kt`) and add a comment marking it for deletion

## Parallel Strategy

1. **Place the new implementation** alongside the old:
   - Same package: use a `New` or `V2` suffix (e.g., `UserRepositoryImpl` → `UserRepositoryImplNew`) until callers are switched, then rename
   - New module: use a `new` or `next` suffix on the module name (`:feature-auth` → `:feature-auth-new`)
2. Add new Gradle dependencies required by the new technology
3. **Verify both old and new compile together** before touching callers:
   ```bash
   ./gradlew compileDebugKotlin          # Android module
   # or simply: ./gradlew :module:assemble
   ```
4. **Mark the old implementation as deprecated** before touching callers — this turns the IDE into a migration guide:
   ```kotlin
   @Deprecated(
       message = "Migrating to [NewTechnology]. Use NewImpl instead.",
       replaceWith = ReplaceWith("NewImpl(param)", "com.example.NewImpl"),
       level = DeprecationLevel.WARNING
   )
   fun oldFunction(param: String) = NewImpl(param)
   ```
   With `ReplaceWith` set, IntelliJ / Android Studio shows a **"Replace with..."** quick fix at every call site. To migrate all callers at once: **Analyze → Run Inspection by Name → "Usage of API marked for removal"** (or the Deprecated API usage inspection) → Apply fix to all. This is faster and safer than manual find-and-replace because the IDE resolves imports and handles overloads correctly.

   Use `DeprecationLevel.WARNING` while migrating (callers still compile), switch to `DeprecationLevel.ERROR` once you want to enforce the cutover, then delete after all callers are switched.

5. Swap callers one-by-one from old → new; build must stay green after each swap
6. **Commit cadence:** commit after new implementation compiles; commit again after each major batch of caller swaps
7. When all callers switched → proceed to Verify + Cleanup
   - Before proceeding: confirm via codebase search that no callers of the old implementation remain

## Branch by Abstraction Strategy

Use when callers must not change — e.g., a heavily-used service class that many layers depend on. The key idea: introduce an interface that both old and new implementations satisfy, so the swap happens at the DI binding level without touching callers.

1. **Introduce an interface** that captures the current public API:
   ```kotlin
   interface AnalyticsTracker {
       fun track(event: String, properties: Map<String, Any> = emptyMap())
   }
   ```
2. **Make the old implementation implement it** — minimal change, callers still compile:
   ```kotlin
   class LegacyAnalyticsTracker : AnalyticsTracker { ... }
   ```
3. **Write the new implementation** behind the same interface:
   ```kotlin
   class NewAnalyticsTracker : AnalyticsTracker { ... }
   ```
4. **Swap the DI binding** from old to new (e.g., in a Hilt module or manual factory):
   ```kotlin
   @Provides fun provideTracker(): AnalyticsTracker = NewAnalyticsTracker()
   ```
5. **Delete the old implementation** once the new one is stable
6. Callers never touch the interface — they see no change

## Feature-flagged Parallel Strategy

Use for large UI migrations (e.g., Compose rollout screen-by-screen) or any migration where production validation before full cutover matters.

1. **Add a feature flag** that selects old vs new path at runtime
2. **Build the new implementation** behind the flag — old path stays live:
   ```kotlin
   if (featureFlags.isEnabled("compose_feed")) {
       FeedScreenCompose()
   } else {
       FeedFragment()  // old path, untouched
   }
   ```
3. **Migrate screens/modules one at a time** — each gets its own flag or shares one per feature area
4. **Enable in production gradually** (internal → beta → full rollout) to catch regressions before they affect everyone
5. **Remove the flag and old path** once the new implementation is stable at 100% rollout
6. Flag the feature flag itself for cleanup — don't leave dead flag checks in the codebase

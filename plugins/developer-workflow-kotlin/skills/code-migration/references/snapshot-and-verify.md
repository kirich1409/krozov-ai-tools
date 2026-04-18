# Snapshot & Verify — Detailed Reference

## Behavior Specification Template

Before writing tests or taking screenshots, produce a `behavior-spec.md` for the target. This is the source of truth for what the migration must preserve — readable by the user, checkable in Phase 4, and independent of any particular test framework.

```markdown
# Behavior Specification: [TargetName]
FROM: [technology] → TO: [technology]

## Public Interface
| Method / Property | Inputs | Output / Side Effect | Notes |
|---|---|---|---|
| `methodName(x)` | type, constraints | return type + value | e.g. "returns null for id ≤ 0" |

## Normal Behaviors
- [description of each significant behavior]

## Edge Cases
- [inputs at boundaries, empty collections, zero, max values]

## Quirks (preserve exactly unless user decides otherwise)
- [unexpected nullability, swallowed exceptions, hardcoded values, implicit assumptions]
- [parsing/formatting library defaults that differ from intuition — e.g., `SimpleDateFormat.isLenient() == true` means invalid dates like month 13 silently overflow rather than throwing; `DateTimeFormatter` is strict by default — these semantics differ and callers may rely on the lenient behavior]
- [thread-safety assumptions — e.g., `SimpleDateFormat` is not thread-safe; its Kotlin equivalent is; callers that share a single instance across threads have hidden race conditions that must be preserved or explicitly fixed]
- [timezone implicit dependencies — methods that use `TimeZone.getDefault()` silently; behavior differs across JVM configurations]

## Out of Scope
- [behaviors that will intentionally change after migration]
```

**Present the completed spec to the user and wait for explicit confirmation before Phase 3.** Do not proceed to Phase 3 (migration) until the user has acknowledged the spec. Use this prompt:

> "Here is the behavior spec for [TargetName]. Please review it before I begin the migration:
> - Are the public interface signatures correct?
> - Are there any quirks you want to mark as bugs to fix (rather than preserve)?
> - Are there behaviors that should intentionally change after migration?
>
> Reply 'confirmed' to proceed, or point out anything to correct."

They may correct misunderstandings, mark quirks as bugs to fix, or explicitly list what should change. This confirmation is the shared contract for the migration.

## Snapshot: `logic` — Characterization Tests

Write **characterization tests** — tests that capture what the code *actually does*, not what it ideally should do. This distinction matters: legacy code often encodes years of production bug fixes and edge-case handling that aren't documented anywhere. The goal is a behavioral safety net, not a correctness audit.

1. Read the code carefully and write tests that pin down actual inputs/outputs, including edge cases, nullability behavior, error paths, and any quirks you notice
2. If existing tests already cover the target: run them, confirm green — but also check if they're comprehensive enough to catch behavioral regressions in the parts you'll change
3. **Async/callback-heavy code** (RxJava, coroutines, listeners, callbacks): write synchronous characterization tests that still exercise the async paths — use `blockingGet()` / `TestObserver` for RxJava, `runBlocking { }` for coroutines, or a `CountDownLatch`/`CompletableFuture` for callbacks. Don't skip async behaviors — they're often the most important to capture, and they expose timing/threading assumptions that the migration must preserve.
4. Run all tests — all must pass before proceeding
5. Note any surprising behaviors you discover (e.g., silent null returns, unexpected exception swallowing) — these are not bugs to fix now, but they must be preserved through the migration unless the user explicitly decides otherwise
6. **If tests cannot compile or pass:** stop → describe problem to user → decide together: fix first OR switch to manual checklist

## Snapshot: `ui`

1. **Existing screenshot tests** → run them, save outputs as baseline
2. **No screenshot tests** → use `mcp__mobile__screenshot` to capture affected screens manually
3. **Mobile MCP unavailable** → create manual checklist: each screen's visible state (layout, colors, text, key interactions)
4. **No infrastructure at all** → document limitation to user; proceed with manual checklist fallback

## Snapshot: `api`

1. List every public surface: classes, functions, extension points, Gradle configs
2. List every known caller (search the codebase)
3. Record as behavioral checklist in `migration-checklist.md`

## Verify: Regression Diagnosis

**If tests fail after migration (regression):**
1. Do NOT proceed to other verify steps
2. Identify which test failed and why — this is a regression, not a pre-existing issue
3. Diagnose systematically:
   - Read the failing test — what behavior does it assert?
   - Read the new code that replaced the old — what did you change that affects this behavior?
   - Compare old vs new: did the semantics change (nullability, exception handling, edge cases, ordering)?
   - If not obvious: temporarily revert the single file and re-run to confirm the test was green before — then narrow down which change broke it
4. Fix the regression in the migrated code (never by weakening or deleting the test)
5. Re-run until all pass before continuing

## Verify: UI Visual Diff

- Take new screenshots of all affected screens
- **Present before/after diff to user — wait for approval**
- User confirms: "expected change" (proceed) or "regression" (fix and re-verify)
- If user cannot respond: re-prompt once; if still no response, park migration as incomplete

## Verify: Behavior Spec Review

Walk through `behavior-spec.md` line by line against the new implementation:
- Every row in **Public Interface**: does the new code have the same signature or a documented intentional change?
- Every item in **Normal Behaviors** and **Edge Cases**: is it covered by a passing test, or manually verified?
- Every item in **Quirks**: is it preserved — or, if the user marked it for removal, confirm it's gone?
- Every item in **Out of Scope**: confirm the change is present and correct
- **Present the completed review to the user** — they confirm: "all behaviors accounted for" or point to gaps

## Verify: API Compilation Check

- Per public surface: run the appropriate compile task for the module type — must compile
- Per known caller: confirm it compiles; run any relevant tests

## Cleanup

1. Find: old-tech Gradle deps, imports, plugin declarations no longer referenced anywhere — include any library adapters/artifacts identified in the Phase 1 dependency compatibility audit that are now obsolete
2. Find: dead code — old implementations, utility classes, adapter layers; for **parallel**: the old implementation class/module itself
3. **Present full removal list to user — wait for acknowledgment**
4. After user acknowledges: remove everything on the list
5. Rebuild to confirm nothing breaks

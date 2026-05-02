---
name: snapshot
description: "Captures current behavior of code targets as a shared contract before any migration or refactoring begins. Produces behavior-spec.md using characterization tests (logic), screenshots or manual checklist (ui), and public surface listing (api). Standalone triggers: \"snapshot\", \"зафиксируй поведение\", \"сними базлайн\", \"задокументируй как работает\", \"capture behavior\", \"baseline before migration\", \"record current behavior\". In orchestrator mode: called by code-migration after Plan — reads targets from migration-plan.md, writes behavior-spec.md, gates until user confirms. GATE: does not hand control back until user confirms the spec is accurate. Do NOT use for: post-migration verification (see verify.md in code-migration references), writing tests beyond characterization (use write-tests), or codebase discovery (use research)."
---

# Snapshot

Captures what code *currently does* — not what it should do — before any migration or refactoring
begins. Produces a `behavior-spec.md` that becomes the shared contract for the migration and the
acceptance criteria for the `code-migration` acceptance phase.

**GATE: Does not return control until the user has explicitly confirmed the behavior spec.**

---

## Input Contract

**Orchestrator mode** (called from `developer-workflow-kotlin:code-migration`):
- Reads targets and categories from `swarm-report/<slug>-migration-plan.md`
- Writes a single `swarm-report/<slug>-behavior-spec.md` containing all targets (one `##` section
  per target); the slug comes from the orchestrator's migration slug. Multiple targets in one file
  prevents slug collision and keeps the acceptance contract as a single reviewable artifact.

**Standalone mode** (user invokes directly):
- If the user has not specified what to snapshot, ask ONE question:
  > "What should I snapshot? Please list the files or classes and their categories: `logic` (pure
  > data/business logic), `ui` (views, screens, layouts), or `api` (public interfaces, module
  > boundaries, Gradle configs)."
- Wait for the answer before proceeding.
- Writes `swarm-report/<slug>-behavior-spec.md`. Slug rules when none is provided:
  - Single target → derive from the class/file name in kebab-case (e.g., `UserRepository` →
    `user-repository`); confirm the slug with the user in one line before writing
  - Multiple targets → ask the user for a slug. Composite names from file lists are rarely
    meaningful, so do not auto-generate. Suggest one (e.g., the migration topic if hinted) but
    require user confirmation

---

## Phase 1: Identify Targets

Read the migration plan or user input and build the snapshot work list:

| Unit | Category | Snapshot method |
|------|----------|-----------------|
| `path/to/File.kt` | logic | characterization tests |
| `path/to/Screen.kt` | ui | screenshots / manual checklist |
| `path/to/Repository.kt` | api | public surface listing |

A single unit may have multiple categories — apply all matching methods, in order: `logic` → `ui` → `api`.

---

## Phase 2: Snapshot by Category

### `logic` — Characterization Tests

Write **characterization tests** — tests that capture what the code *actually does*, not what it
ideally should do. Legacy code often encodes years of production fixes and undocumented edge-case
handling. The goal is a behavioral safety net, not a correctness audit.

1. Read the code carefully and write tests that pin actual inputs/outputs, including edge cases,
   nullability behavior, error paths, and any quirks discovered
2. If existing tests already cover the target: run them, confirm green — then check whether
   they're comprehensive enough to catch behavioral regressions in the areas that will change
3. **Async/callback-heavy code** (RxJava, coroutines, listeners, callbacks): write synchronous
   characterization tests that still exercise the async paths — use `blockingGet()` / `TestObserver`
   for RxJava, `runBlocking { }` for coroutines, or a `CountDownLatch`/`CompletableFuture` for
   callbacks. Async behaviors are often the most important to capture; they expose
   timing/threading assumptions the migration must preserve.
4. Run all tests — all must pass before recording as complete
5. Note surprising behaviors (silent null returns, exception swallowing, etc.) — preserve them
   through migration unless the user explicitly decides otherwise
6. **If tests cannot compile or pass:** stop → describe the problem to the user → decide together:
   fix first OR switch to manual checklist (document the limitation clearly)

### `ui` — Screenshots / Manual Checklist

1. **Existing screenshot tests** → run them, save outputs as baseline
2. **No screenshot tests** → use `mcp__mobile__screen` to capture affected screens manually
3. **Mobile MCP unavailable** → create manual checklist: each screen's visible state
   (layout, colors, text, key interactions)
4. **No infrastructure at all** → document limitation to user; proceed with manual checklist fallback

### `api` — Public Surface Listing

1. List every public surface: classes, functions, extension points, Gradle configs
2. List every known caller (search the codebase)
3. Record as behavioral checklist in the behavior spec

---

## Phase 3: Produce behavior-spec.md

After completing all applicable snapshot methods, write `swarm-report/<slug>-behavior-spec.md`.

**Single target** — use this template:

```markdown
# Behavior Specification: [TargetName]
FROM: [technology] → TO: [technology]   <!-- omit TO: in standalone mode when TO is unknown -->

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
- [parsing/formatting library defaults that differ from intuition — e.g., `SimpleDateFormat.isLenient() == true`
  means invalid dates silently overflow; `DateTimeFormatter` is strict by default — callers may rely on
  the lenient behavior]
- [thread-safety assumptions — e.g., `SimpleDateFormat` is not thread-safe; callers sharing a
  single instance across threads have hidden race conditions that must be preserved or fixed]
- [timezone implicit dependencies — methods using `TimeZone.getDefault()` silently]

## Out of Scope
- [behaviors that will intentionally change after migration]
```

**Multiple targets** (orchestrator mode or standalone with several files) — use H1 for the overall
spec, H2 for each target, H3 for subsections. `FROM: → TO:` appears inside each target's `##`
section (not at file level) when targets have different source/target technologies:

```markdown
# Behavior Specification: [migration-slug]

## [TargetA — e.g., UserRepository]
FROM: RxJava → TO: coroutines/Flow

### Public Interface
| Method / Property | Inputs | Output / Side Effect | Notes |
|---|---|---|---|
| `getUser(id)` | String | suspend User | throws on network error |

### Normal Behaviors
- ...

### Edge Cases
- ...

### Quirks
- ...

### Out of Scope
- ...

## [TargetB — e.g., DateUtils]
FROM: SimpleDateFormat → TO: DateTimeFormatter

### Public Interface
...
```

If all targets share the same FROM/TO pair, a single `FROM: → TO:` line at the top of the file
(directly after the H1) is acceptable in place of repeating it in each section.

---

## GATE: Confirmation

Present the completed spec to the user using this prompt:

> "Here is the behavior spec for [TargetName / N targets: A, B, C]. Please review it before
> the migration begins:
> - Are the public interface signatures correct?
> - Are there any quirks you want to mark as bugs to fix (rather than preserve)?
> - Are there behaviors that should intentionally change after migration?
>
> Confirm when ready to proceed, or point out anything to correct."
>
> *(One GATE per file, not one per target — confirm or correct the whole file at once.)*

**Do not return control until the user gives a clear affirmative.** Examples (non-exhaustive):
"confirmed", "yes", "ok", "looks good", "go", "ship it", "подтверждаю", "хорошо", "готово",
"погнали" — or any equivalent in the language they are communicating in. Match by intent, not by
exact phrase. If the response is ambiguous (e.g., "hmm", "maybe", a question, or a comment without
a clear go/no-go), ask ONE clarifying question: "Confirm to proceed, or point out what to fix?".
A correction ("fix X" or "add Y") is not an affirmative — update the spec and re-present it.

If the user provides corrections: update the spec and re-present it. Repeat until confirmed.

The confirmation is the shared contract for the migration. After confirmation, the spec is final —
any further changes require an explicit new snapshot invocation or user override. In orchestrator
mode, the skill signals readiness by returning with the confirmed `behavior-spec.md` written to
disk; the orchestrator treats file presence + return as the completion signal.

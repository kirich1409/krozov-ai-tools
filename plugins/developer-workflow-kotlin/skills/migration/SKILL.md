---
name: migration
description: "Use for migrating one technology to another in Android/Kotlin/KMP/JVM projects with behavioral parity — Databinding to ViewBinding, Dagger/Hilt to Metro DI, RxJava to Coroutines, KAPT to KSP, Java to Kotlin, Gson to kotlinx.serialization, and similar tech swaps. Triggers: \"migrate X to Y\", \"replace X with Y\", \"swap X for Y\", \"drop X in favor of Y\", \"move off X\", \"decommission X\". Covers studying FROM/TO technologies and their build artifacts, mapping use-sites, fixing current behavior across three planes (code tests + test cases + manual scenarios), agreeing strategy with the user, implementing via one of four approaches (Branch by Abstraction, Strangler Fig, Duplicate-then-delete, Utility refactor), verifying on a real device, and cleaning up the old stack fully. Do NOT use for: bug fixes (use plan mode), or pure library version bumps without API changes."
---

# Migration

## Overview

**Core principle:** Understand both technologies before touching code → fix current behavior across three independent planes → agree the strategy with the user → execute with the chosen approach → verify on device → remove the old stack fully.

Behavioral parity is the contract. Anything that changes intentionally must be agreed in Phase 4 (Strategy gate) and listed in the migration report. Anything else must remain identical FROM and TO.

### Scope discipline — what migration is NOT

Do not do any of the following without explicit user approval:
- **Fix unrelated bugs** — a bug in the old stack stays as a bug in the new stack until the user asks otherwise. Bugs are tracked separately in the migration report's "Issues found" section.
- **Refactor adjacent code** — if a class works but is ugly, leave it. Migration is not a cleanup tour.
- **Modernize patterns** — replace only the technology in scope. Do not add coroutines while migrating DI. Do not introduce DI while migrating UI.
- **Add features or new states** — no new screens, no new options, no new edge cases.
- **Migrate multiple technologies in one pass** — UI, DI, and async are three different migrations, even if they look related. If the work expands beyond the agreed scope, stop and renegotiate Phase 4.

When a bug, missing feature, or adjacent improvement surfaces during the work — add it to the migration report and ask. Never silently extend scope.

## Workflow

```
1. Tech-Study  →  2. Discover  →  3. Behavior-Fix  →  4. Strategy + USER GATE
                                                              ↓
8. Final Audit ← 7. Cleanup  ←  6. Device Verify  ←  5. Implement
```

Phase 4 is the only mandatory gate. Every other phase is a checklist for the user, not a blocking state transition. The skill produces material; the user drives progress. Plan mode is the real orchestrator — this skill only supplies the structure.

If you find yourself building a state machine, requiring strict completion of one phase before starting the next, or invoking other skills from inside this one, stop. That is the failure mode of the deleted `code-migration` orchestrator (v0.14.0) and the reason it was removed. See `references/anti-orchestrator.md` for the five concrete criteria that separate this skill from a forced pipeline.

---

## Phase 1: Tech-Study (FROM and TO)

Before touching the project, understand both technologies as a class. The most common cause of incomplete migrations is treating the technology as a black box and missing what it generates, scans, or hooks into at build time.

Produce `./swarm-report/<slug>-tech-snapshot.md` covering both FROM and TO:

- **Generated artifacts** — what code does it emit (KAPT, KSP, FIR/IR compiler plugin), into which directories (`build/generated/...`), under what classpath. Example: Databinding generates `*Binding.java` via KAPT; ViewBinding generates via AGP directly; Hilt generates per-module Dagger components via KAPT/KSP; Metro generates via Kotlin compiler plugin with no separate processing stage.
- **Build hooks** — Gradle plugin id, flags that activate it (`dataBinding = true`, `viewBinding = true`, `kotlin("kapt")`), tasks it registers.
- **Classpath / scanning behavior** — does it scan annotations across modules (Hilt does; ViewBinding does not), does it require `@AndroidEntryPoint` markers, does it inject at runtime or compile time.
- **Side effects** — build time impact, generated R-classes, lint integration, IDE plugin requirements, KSP1 vs KSP2 compatibility, AGP version requirements.
- **Interop facilities** — does the TO technology offer an explicit interop layer with FROM (Metro has Dagger interop; Coroutines have RxJava bridges; Compose has `AndroidView`/`ComposeView`)? This is the foundation for any incremental approach.

Verify each fact against authoritative sources — official documentation, the library's own GitHub README, the source code of installed dependencies. Do not rely on training-data memory — APIs and build behavior change.

If the project ships JVM/Kotlin dependencies in a Gradle cache, a source-reading tool (such as `ksrc` if installed) is preferred over web fetches because it sees the exact installed version. For Android platform migrations, an official Android docs search tool (such as the `android` CLI if installed) gives curated guidance; otherwise fall back to web search against `developer.android.com`. See `references/approaches.md` for a list of common FROM/TO pairs and where to find their docs.

---

## Phase 2: Discover (scope in the project)

Map every use-site of the FROM technology in the current codebase. Without a complete inventory, Cleanup cannot succeed — leftovers stay hidden.

Produce `./swarm-report/<slug>-discover.md`:

- **Use-site inventory** — files, classes, modules using the FROM technology. Group by horizontal (cuts across modules: DI, async, build plugins) vs vertical (single screen / module / feature).
- **Dependency graph fragment** — which modules pull in the FROM library directly vs transitively. Note any modules where FROM leaks through `api` configuration.
- **Generated-code footprint** — which `build/generated/...` directories will need cleanup; which downstream code imports from them.
- **In scope / out of scope** — explicit list of what this migration will and will not touch. Adjacent migrations that surface during discovery (UI migration uncovers state-holder issues; DI migration uncovers scoping concerns) go into out-of-scope unless the user explicitly extends the contract in Phase 4.

This phase must produce a `Risk of scope explosion` section listing any adjacent technology that *might* need migrating later. The list itself is the protection — it forces an explicit decision instead of drift.

For investigations that touch the entire codebase, delegate to the Explore subagent rather than running grep yourself in the main session. See `~/.claude/rules/orchestration.md`.

---

## Phase 3: Behavior-Fix (three planes)

Fix current behavior across three independent planes. Each plane catches what the others miss. The level of investment per plane is calibrated to the migration risk (see `references/behavior-fix.md` for the calibration matrix).

**Plane A — Code tests.** Characterization tests (Feathers, *Working Effectively with Legacy Code*, ch. 13), contract tests, integration tests, golden snapshots. These run in CI and turn red on regression.

**Plane B — Test cases (`<slug>-test-cases.md`).** Formal test scenarios written in prose — TC-1, TC-2, …, each with steps and expected outcome. This is the document the user reads during Phase 6 Device Verify; it is the source of truth for "what should still work".

**Plane C — Manual scenarios (`<slug>-manual-scenarios.md`).** Exploratory paths that are hard to automate: accessibility (TalkBack/VoiceOver), RTL, dark mode, locale switching, low memory, slow network, configuration changes.

Plane A is the strongest but most expensive. Plane B is the cheapest investment with the highest leverage — write the test cases before deciding how much of Plane A to invest in. Plane C is the safety net against unknown unknowns.

See `references/behavior-fix.md` for templates, the calibration matrix (how much of each plane per migration type), and how to balance the investment against migration risk.

If the FROM stack has zero tests and writing a full Plane A is more expensive than the migration itself — say so, propose dropping Plane A in favor of stronger Planes B and C, and capture the trade-off in Phase 4.

---

## Phase 4: Strategy + USER GATE

This is the only mandatory blocking phase. Until the user confirms the strategy, do not start implementation.

Produce `./swarm-report/<slug>-strategy.md` containing:

1. **Chosen approach** — one of: Branch by Abstraction, Strangler Fig vertical slice, Duplicate-then-delete, Utility refactor. See `references/approaches.md` for the selection matrix.
2. **Rationale** — why this approach, why not the others, in two sentences.
3. **Implementation order** — which modules/files/screens go first, second, third. For horizontal migrations: bottom-up by dependency graph. For vertical: simplest screens first to build team confidence.
4. **Intentional behavioral changes** — explicit list of "behavior X changes from A to B because Y". Anything not on this list must remain identical.
5. **Bridge / interop layers** — if any (Hilt-Metro bridge, `AndroidView`, `rxSingle { await() }` adapters), each gets a sunset date and a removal criterion.
6. **Rollback plan** — one paragraph describing how to undo the migration if Phase 6 finds blocking regressions.

Present the strategy to the user, wait for explicit approval. The wait is the gate — phrased once, no nagging. Confirmation can be in any language; match by intent ("yes", "ok", "go", "approved", "looks good", a Russian/German/Spanish equivalent), not by exact phrase.

After approval, the document becomes immutable. Any later change in scope or approach requires returning to Phase 4 explicitly.

---

## Phase 5: Implement

Execute the migration according to the strategy. The four approaches differ in mechanics but share the same hand-off pattern: this skill produces a brief; an engineer agent (`developer-workflow-kotlin:kotlin-engineer` or `developer-workflow-kotlin:compose-developer` depending on layer) writes the code; the main session reviews.

**Branch by Abstraction.** Introduce a shared interface, route all use-sites through it, build the new implementation behind it, then switch and remove the old. See `references/approaches.md` for mechanics, trade-offs, and ordering.

**Strangler Fig vertical slice.** Migrate one self-contained slice end-to-end on the new stack while the rest of the system continues on the old stack via interop. See `references/approaches.md` for mechanics, trade-offs, and ordering.

**Duplicate-then-delete.** Copy the file/class/module, freeze the original, migrate the copy, switch routing, then delete the original. See `references/approaches.md` for mechanics, trade-offs, and ordering.

**Utility refactor.** Enable the new technology alongside the old, convert use-sites in batches, then remove the old flag — the compiler is the safety net. See `references/approaches.md` for mechanics, trade-offs, and ordering.

Delegate the actual implementation work. The main session orchestrates, agents implement. See `~/.claude/rules/orchestration.md` for the routing matrix.

---

## Phase 6: Device Verify

Run the application on a device, emulator, or appropriate test harness (JVM rig for backend / library code). Walk through every TC in `<slug>-test-cases.md` and every scenario in `<slug>-manual-scenarios.md`. Compare actual behavior to FROM behavior recorded in Phase 3.

For UI migrations, ask the user to provide before/after screenshots, or delegate the capture to the `manual-tester` agent.

Produce `./swarm-report/<slug>-device-verify.md`:

- TC-N → pass / fail / N/A, with a one-line note on any deviation.
- Manual scenarios → same.
- Discrepancies — for each: is it on the "intentional changes" list from Phase 4? If yes, mark as expected. If no, it is a regression — go back to Phase 5 to fix.

The phase ends only when every TC and scenario is either passing or explicitly accepted as an intentional change.

For Android device automation, an agent-oriented Android CLI (such as Google's `android` tool if installed) covers screen capture, layout dump, and APK deploy with one interface; without it, fall back to `adb` directly (`adb shell screencap`, `adb shell uiautomator dump`, `adb install`). For exploratory QA against a running app, call the `developer-workflow:manual-tester` agent directly via the Task tool — do not invoke `/acceptance` from this skill.

---

## Phase 7: Cleanup

Remove the FROM technology fully. Until this phase completes, the migration is not done — coexistence is technical debt, not a milestone.

Walk the ten-item checklist in `references/cleanup.md` top to bottom; each item ends in done / N/A with reason / deferred with sunset date and tracker link.

Cleanup uses an engineer agent for code edits; review the deletions with `developer-workflow-experts:architecture-expert` if the migration was horizontal (DI, async, build) — these have the highest risk of leaving invisible coupling.

---

## Phase 8: Final Audit

Close the loop. The artifacts are now an audit trail; the migration is complete or has a documented partial state.

Produce `./swarm-report/<slug>-migration-report.md` aggregating:

- Strategy (from Phase 4) — what was promised.
- Implementation summary — what was done, which approach, deviations from the strategy and why.
- Behavioral parity status — TC pass rate, intentional changes list, any accepted regressions with rationale.
- Cleanup status — checklist from Phase 7 with pass/fail per item.
- Outstanding follow-ups — adjacent migrations now visible, bridge layers that survived with sunset dates, technical debt incurred.

Optionally request a `developer-workflow-experts:code-reviewer` pass on the cleanup commit and a `developer-workflow-experts:architecture-expert` pass on the strategy retrospective. These are optional — do not invoke them automatically. The user decides.

---

See `references/approaches.md` for the decision tree.

---

## Artifacts checklist

All artifacts live in `./swarm-report/`. None are mandatory beyond `<slug>-strategy.md` (the Phase 4 gate output). Skip what does not apply.

- `<slug>-tech-snapshot.md` — FROM and TO technology study.
- `<slug>-discover.md` — use-site inventory and scope.
- `<slug>-behavior-spec.md` — index pointing to the three behavior-fix planes.
- `<slug>-test-cases.md` — Plane B, formal test cases.
- `<slug>-manual-scenarios.md` — Plane C, exploratory scenarios.
- `<slug>-strategy.md` — Phase 4 output (mandatory).
- `<slug>-device-verify.md` — Phase 6 verification log.
- `<slug>-cleanup-checklist.md` — Phase 7 status per item.
- `<slug>-migration-report.md` — Phase 8 final aggregation.

Templates for each are in `references/artifacts.md`.

---

## Delegation routing

The main session orchestrates; specialists implement. See `~/.claude/rules/orchestration.md` for the full matrix. Migration-specific routing:

| Phase | Primary agent | Model |
|---|---|---|
| 1 Tech-Study | main session (light reads) + `Explore` for codebase scan | haiku for Explore |
| 2 Discover | `Explore` for multi-file scan | haiku |
| 3 Behavior-Fix code tests | `developer-workflow-kotlin:kotlin-engineer` or `compose-developer` | sonnet |
| 4 Strategy | main session synthesis + optional `developer-workflow-experts:architecture-expert` review | opus for review |
| 5 Implement | `kotlin-engineer` / `compose-developer` | sonnet |
| 6 Device Verify | `developer-workflow:manual-tester` (when UI), or main session walking through TCs | sonnet |
| 7 Cleanup | `kotlin-engineer` for deletions; `architecture-expert` for horizontal-migration review | sonnet / opus |
| 8 Final Audit | optional `code-reviewer` + `architecture-expert` | sonnet / opus |

This skill does not invoke other skills. The user decides whether to run `/check`, `/finalize`, `/create-pr`, or `/drive-to-merge` afterwards.

---

## Anti-patterns / red flags

Stop and renegotiate (return to Phase 4) when:

- The migration of one slice takes 2–3× the original estimate.
- A new dependency surfaces ("we also need to migrate X to make Y work").
- The cycle "old depends on new, new depends on old" appears anywhere in the diff. Loops block cleanup. The dependency direction must always be FROM → TO; never TO → FROM. See `references/anti-orchestrator.md` for the dependency-direction enforcement options (Konsist, Lint baseline).
- A bridge layer outlives its sunset date once already — it is becoming permanent debt.
- Phase 3 (Behavior-Fix) was skipped on a non-trivial migration. Without recorded behavior, parity is opinion, not evidence.
- The skill starts calling `/acceptance`, `/finalize`, `/create-pr`, or any other slash command from inside its own phases. The skill is supposed to produce material, not to orchestrate the whole pipeline. See `references/anti-orchestrator.md`.

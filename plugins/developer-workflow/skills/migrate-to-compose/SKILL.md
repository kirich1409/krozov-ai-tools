---
name: migrate-to-compose
description: Use when migrating any Android View-based UI to Jetpack Compose — whether the source is an Activity, a Fragment, or a standalone custom View/ViewGroup. Invoke proactively whenever the user says "migrate to Compose", "convert this screen to Compose", "rewrite in Compose", "move to Compose", "this screen needs Compose", "replace XML layout", "drop this fragment", "convert this Activity", "replace this custom view", "rewrite this ViewGroup", or asks how to approach a View→Compose migration for a specific screen or component. Covers: analyzing the existing View-based implementation regardless of its host (Activity/Fragment/custom View), discovering patterns from screens already written in Compose, identifying shared components that need to be built first, capturing a visual baseline via screenshot, implementing the Compose equivalent, and verifying both visual fidelity and structural consistency. Do NOT use for: migrating entire apps at once (do it screen-by-screen), KMP migrations (use kmp-migration instead), or non-UI code rewrites.
---

# Migrate to Compose

## Overview

**Core principle:** Understand the screen deeply before touching it → discover how the rest of the app uses Compose → identify what's missing → capture a visual baseline → migrate → verify appearance and structure match.

Never write a single line of Compose until the pattern analysis and gap analysis are done.

### Scope discipline — what this migration is NOT

**Do not do any of the following without explicit user approval:**
- Fix existing bugs in the original screen — if the old screen had a bug, the new screen should have the same bug. Note it and ask.
- Add features that didn't exist — no tablet layouts, no landscape support, no new states.
- Improve UX, spacing, or visual design beyond what's needed for identical appearance.
- Refactor business logic, naming, or architecture outside the UI layer.

**When you encounter a bug or missing feature:** Add it to an **"Issues found"** section in the migration report and ask the user.

**Unavoidable behavior differences:** Document the difference, propose the closest Compose behavior, and ask the user before proceeding.

## Workflow

```
DISCOVER → ANALYZE PATTERNS → GAP ANALYSIS → CONFIRM → IMPLEMENT GAPS → MIGRATE → STATIC VERIFY → [device: manual-tester agent (QA)]
```

---

## Phase 1: Discover

First, identify the source type (Activity/Fragment/Custom View) — this shapes the migration strategy. See `references/discovery-and-patterns.md` for the source type table and detailed inventory checklist.

Read every file that makes up the target: XML layout, host class, ViewModel, nested custom Views, adapters, and referenced resources. Build a mental model of: what data is displayed, what interactions exist, and which parts are complex or risky.

**Inventory all animations** — they are easy to miss and silently drop. See `references/discovery-and-patterns.md` for the full animation inventory checklist.

**Produce a `behavior-scenarios.md`** — captures everything the screen does. Grouped by: visual states, interactions, side effects, edge cases. See `references/discovery-and-patterns.md` for the template and examples. This document becomes the verification checklist for all subsequent phases.

---

## Phase 2: Analyze Existing Compose Patterns

**Mandatory.** Launch the `compose-developer` agent to discover project patterns and produce a Pattern Summary. Also determine state stream conventions and event transport compatibility yourself. See `references/discovery-and-patterns.md` for full details.

---

## Phase 3: Gap Analysis

For each UI element with no shared Compose equivalent, resolve using priority: existing UI Kit → already-imported libraries → suggest new library → write custom component. See `references/discovery-and-patterns.md` for the full priority order, custom View special case, and documentation format.

**Present the gap list to the user and confirm before proceeding.**

---

## Phase 4: Confirm

Present a migration plan before writing any Compose code:
1. Behavior scenarios review — share `behavior-scenarios.md` for user confirmation
2. What you found — screen structure, ViewModel contract, risky areas
3. Patterns you'll follow — from Phase 2
4. Gaps and decisions — from Phase 3
5. Migration strategy — simple / moderate / complex, with screenshot testing proposal
6. Scope — what's in and what's explicitly deferred

See `references/discovery-and-patterns.md` for screenshot testing guidance. Wait for explicit user approval.

---

## Phase 5: Implement Gaps First

Resolve missing components **before** writing the screen. See `references/discovery-and-patterns.md` for the implementation priority order.

---

## Phase 6: Migrate the Screen

Use the `compose-developer` agent. Brief it with: all files from Phase 1, pattern constraints from Phase 2, shared components from Phase 2 + Phase 5.

The migration produces:
- New `FooScreen.kt` with screen composable and sub-composables
- Minimal ViewModel update only if strictly required
- Nav graph wiring (if applicable)
- **Old Activity/Fragment kept intact** until verification passes

Key constraints — see `references/migration-and-verify.md` for full details:
- **Business logic preservation**: do not touch anything outside the UI layer
- **Architecture**: stateless screen, exhaustive `when`, stability annotations, correct string type
- **Code quality**: extract long lambdas, split large composables, `internal` by default
- **Theming**: use project tokens, never raw `dp`/hex values
- **Previews**: every significant composable, multiple states
- **Screenshot tests** (if agreed in Phase 4)

For View→Compose component mapping, see `references/view-to-compose-mapping.md` — covers RecyclerView, Custom Views, animations, WindowInsets, ViewPager, CoordinatorLayout, BottomSheet, ItemTouchHelper, permissions, focus management, and more.

---

## Phase 7: Static Verification

See `references/migration-and-verify.md` for detailed fidelity review checklist and migration report template.

1. **Build, lint, screenshot tests** — zero errors, no new warnings
2. **Migration fidelity review** — walk through `behavior-scenarios.md` and XML element by element: layout structure, visual properties, behavioral details, architecture, window insets
3. **Produce `migration-report.md`** — replacements, new components, ViewModel changes, behavior verification status, visual comparison table, deviations, issues found

After static checks pass: invoke the `manual-tester` agent for device verification.

---

## Device Testing

Brief the `manual-tester` agent with `behavior-scenarios.md`, the migration report, and interaction list. It captures before/after screenshots, executes all test cases, and populates the screenshot table. See `references/migration-and-verify.md` for briefing details.

---

## Post-migration Cleanup

Once verification passes, **offer to clean up** (never automatically). Propose deleting old files: Activity/Fragment, XML layouts, adapters, ViewHolders, binding classes, DiffUtil callbacks. Also review: nav graph, DI/Hilt modules. **Run project-wide usage search before any deletion.** See `references/migration-and-verify.md` for the full checklist.

# Artifacts — templates

All migration artifacts live in `./swarm-report/<slug>-*.md` where `<slug>` is a kebab-case short identifier for the migration (`databinding-to-viewbinding`, `hilt-to-metro`, `rxjava-to-coroutines`).

None are mandatory beyond `<slug>-strategy.md` (Phase 4 gate output). Skip what does not apply.

## Index

| Phase | Artifact | Mandatory |
|---|---|---|
| 1 | `<slug>-tech-snapshot.md` | no |
| 2 | `<slug>-discover.md` | no |
| 3 | `<slug>-behavior-spec.md` (index) | no |
| 3 | `<slug>-test-cases.md` | recommended |
| 3 | `<slug>-manual-scenarios.md` | recommended |
| 4 | `<slug>-strategy.md` | **yes** |
| 6 | `<slug>-device-verify.md` | no |
| 7 | `<slug>-cleanup-checklist.md` | recommended |
| 8 | `<slug>-migration-report.md` | recommended |

---

## `<slug>-tech-snapshot.md`

```markdown
# Tech Snapshot: <FROM> -> <TO>

## FROM: <technology name and version>

### Generated artifacts
- What it generates: ...
- Where: ...
- Via: KAPT / KSP / FIR-IR / AGP plugin / runtime

### Build hooks
- Gradle plugin id: ...
- Activation flag: ...
- Tasks registered: ...

### Classpath / scanning behavior
- Annotation scanning across modules: yes/no
- Entry-point markers required: ...
- Inject time: compile / runtime

### Side effects
- Build time impact: ...
- Generated R classes: ...
- Lint integration: ...
- IDE plugin: ...
- KSP1 vs KSP2: ...
- AGP version constraint: ...

### Known limitations
- ...

## TO: <technology name and version>

(Same structure as FROM)

## Interop facilities

Does TO offer a bridge with FROM?
- ...

## Migration-relevant differences

| Aspect | FROM | TO |
|---|---|---|
| ... | ... | ... |

## Sources

- Official doc: ...
- GitHub: ...
- Verified via: <official docs / installed dependency source / release notes / authoritative web source>
- Reference source category for this entry: <one of: official documentation, installed dependency source, GitHub release notes, library README, third-party article (rare — name and justify)>
```

---

## `<slug>-discover.md`

```markdown
# Discover: <slug>

Migration: <FROM> -> <TO>
Date: <YYYY-MM-DD>

## Use-site inventory

### Horizontal cross-cuts
- Modules affected: :core:*, :data:*, :domain, :feature:*
- Total files: N

### Vertical slices (if any)
- :feature:login (8 files)
- :feature:checkout (12 files)

## Dependency graph fragment

- :app depends on FROM (transitively via :feature:*)
- :feature:* depends on FROM directly via `implementation`
- :data:* does not depend on FROM

## Generated-code footprint

- build/generated/databinding/* in modules: :feature:login, :feature:checkout, :feature:profile
- Total generated files at last clean build: ~120

## In scope
- All modules in :feature:*
- Specifically: replace Databinding with ViewBinding; remove `<layout>` wrapping; convert `@BindingAdapter` to extension functions.

## Out of scope
- ViewModel state management (LiveData stays as LiveData; no migration to StateFlow)
- Navigation framework (stays Fragment-based)
- DI framework (stays Hilt)

## Risk of scope explosion

The following adjacent migrations might surface during work and are explicitly deferred:
- LiveData -> StateFlow (would simplify Compose adoption later, but not now)
- Fragment -> Compose Navigation (separate migration)
- KAPT -> KSP for Hilt (if Hilt eventually migrates to KSP, separate effort)
```

---

## `<slug>-behavior-spec.md`

Thin index document. See `references/behavior-fix.md` for the full template — the example there is canonical.

---

## `<slug>-test-cases.md`

```markdown
# Test Cases: <slug>

Migration: <FROM> -> <TO>
Source: <link to acceptance criteria or behavior recording>
Last updated: <YYYY-MM-DD>

## TC-1: User logs in with valid credentials
**Preconditions:** App freshly installed, no user logged in.
**Priority:** P0
**Steps:**
1. Open the app, navigate to Login.
2. Enter email "test@example.com".
3. Enter password "correctPassword123".
4. Tap "Log in".
**Expected:** Loading spinner appears for ~1s, then user lands on Home screen. Email is shown in the top bar.
**Verification source:** Plane A `LoginIntegrationTest#logsInWithValidCredentials` + manual.

## TC-2: User sees validation error for empty email
**Preconditions:** App on Login screen.
**Priority:** P1
**Steps:**
1. Leave email empty.
2. Enter any password.
3. Tap "Log in".
**Expected:** Inline error under email field: "Enter your email." Login button stays disabled until email is non-empty.
**Verification source:** manual only.

## TC-3: ...
```

Priority: follow P0–P3 from `~/.claude/rules/qa-and-testing.md § 2`.

---

## `<slug>-manual-scenarios.md`

```markdown
# Manual Scenarios: <slug>

## MS-1: Accessibility (TalkBack)
- Open Login screen.
- Enable TalkBack.
- Walk through with swipe-right navigation.
- Verify: focus order is email -> password -> login button -> forgot password link.
- Verify: each control announces its label and current state.

## MS-2: RTL
- Set device language to Arabic.
- Open Login screen.
- Verify: form fields right-aligned.
- Verify: leading/trailing icons flipped.

## MS-3: Dark mode
- Toggle system dark mode.
- Verify: backgrounds, text colors, button colors all switch correctly.
- Verify: no hard-coded #FFFFFF / #000000 leaking.

## MS-4: Configuration change
- Open Login screen.
- Type email and password (do not submit).
- Rotate device.
- Verify: typed values are preserved.

## MS-5: Process death
- Open Login screen.
- Background the app.
- adb shell am kill <pkg>.
- Reopen.
- Verify: app resumes at Login (or appropriate restoration point).
```

Adapt the scenarios to the surface being migrated. For backend / library migrations without UI, replace MS-1..MS-3 with concurrency, error handling, and resource cleanup scenarios.

---

## `<slug>-strategy.md` (Phase 4 — mandatory gate output)

```markdown
# Strategy: <slug>

Migration: <FROM> -> <TO>
Date: <YYYY-MM-DD>
Author: <Claude / user>
Status: Draft | Confirmed (with timestamp of confirmation)

## Chosen approach

<one of: Branch by Abstraction | Strangler Fig | Duplicate-then-delete | Utility refactor>

## Rationale

<one or two sentences on why this approach, why not the others>

## Implementation order

1. ...
2. ...
3. ...

Rationale for ordering: bottom-up by dependency graph / simplest first / by user-facing risk / ...

## Intentional behavioral changes

Anything that intentionally changes between FROM and TO. Anything not in this list must remain identical.

- ...

## Bridge / interop layers

If any temporary bridge is introduced during Phase 5, list it here with sunset criterion.

| Bridge | Purpose | Sunset criterion | Sunset target date |
|---|---|---|---|
| ... | ... | ... | YYYY-MM-DD |

If no bridges are needed, write "None — direct migration".

## Rollback plan

<one paragraph: how do we undo this migration if Phase 6 reveals a blocking regression?>

## User confirmation

- [ ] User has reviewed this strategy and approved.

Confirmation timestamp: <YYYY-MM-DD HH:MM>
```

---

## `<slug>-device-verify.md`

```markdown
# Device Verify: <slug>

Migration: <FROM> -> <TO>
Verification date: <YYYY-MM-DD>
Device(s): <device + OS version>
Build under test: <branch / commit / build number>

## Test cases (from <slug>-test-cases.md)

| ID | Title | Status | Notes |
|---|---|---|---|
| TC-1 | User logs in with valid credentials | pass | identical to FROM |
| TC-2 | Validation error for empty email | pass | |
| TC-3 | ... | fail | error toast color differs from FROM |
| ... | ... | ... | ... |

## Manual scenarios (from <slug>-manual-scenarios.md)

| ID | Title | Status | Notes |
|---|---|---|---|
| MS-1 | Accessibility | pass | |
| MS-2 | RTL | partial | login button reflows on long Arabic labels |
| ... | ... | ... | ... |

## Discrepancies

For each non-pass result above, classify:

- TC-3 (error toast color): **regression**, go back to Phase 5 and align color.
- MS-2 (button reflow): **intentional change** per Phase 4 strategy (longer-text accommodation was explicitly accepted).

## Sign-off

- [ ] All TCs and MSs are either passing or explicitly classified as intentional.
- [ ] Regressions, if any, are fixed and re-verified.

Verifier: <name>
Date: <YYYY-MM-DD>
```

---

## `<slug>-cleanup-checklist.md`

The cleanup checklist template is in `references/cleanup.md`. The Status column uses three states only: **done**, **N/A** (with reason in Notes), or **deferred: YYYY-MM-DD** (with tracker link in Notes). Example rows:

```markdown
| 1 | No FROM imports outside :legacy:* | done | grep clean |
| 9 | APK/AAB size reduced | N/A | library-only migration, no APK build |
| 6 | Lint baseline / Konsist updated | deferred: 2026-08-01 | lint rules shared with another active migration — JIRA-4521 |
```

---

## `<slug>-migration-report.md` (Phase 8 final aggregation)

```markdown
# Migration Report: <slug>

Migration: <FROM> -> <TO>
Started: <YYYY-MM-DD>
Completed: <YYYY-MM-DD>
Status: Done | Partial | Blocked

## Strategy (from Phase 4)

<approach + rationale + intentional changes — copy/paste from strategy.md>

## Implementation summary

- Approach used: ...
- Modules migrated: N
- Files changed: M
- Bridges introduced: K (all removed in Cleanup; or list survivors with sunset)
- Deviations from strategy: <if any, with reasoning>

## Behavioral parity status

- Plane A coverage: <test names + counts>
- Plane B (test cases): <TC count, P0/P1/P2/P3 breakdown>; pass rate: X%
- Plane C (manual scenarios): <MS count>; pass rate: X%
- Intentional changes shipped: <list from strategy>
- Accepted regressions (with rationale): <if any>

## Cleanup status

<10-item checklist from cleanup.md with per-item status>

## Outstanding follow-ups

- Adjacent migrations now visible: ...
- Bridge layers that survived with sunset dates: ...
- Technical debt incurred: ...

## Issues found (out of scope)

Things observed during the migration that were not migrated (bugs, refactor opportunities, missing tests). For each: short description + suggested follow-up tracker entry.

- ...

Sources: all `./swarm-report/<slug>-*.md` artifacts per the index above.
```

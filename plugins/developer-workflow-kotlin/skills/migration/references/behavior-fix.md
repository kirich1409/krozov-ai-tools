# Behavior-Fix — three planes

## Why three planes

A single test pyramid (Plane A) is not enough for migrations:

- Plane A misses anything that depends on the running environment (real device rendering, real network, real OS-level state).
- A pure manual checklist is not reproducible across iterations and fails as a CI gate.
- A test plan document is unreadable for a machine but indispensable for human verification.

The three planes work together: Plane A is the regression sentinel in CI, Plane B is the human-readable contract for what should still work, Plane C is the safety net for things you cannot fully automate.

---

## Plane A — Code tests

**Goal.** Reproducible, in-CI verification that catches regressions automatically.

**Sub-types.**

- **Characterization tests.** Record what the FROM implementation actually does, then assert against that recording — bugs-as-features included. See `developer-workflow-kotlin:snapshot` for the canonical characterization-test methodology; apply it here to the FROM-stack targets.
- **Contract tests.** Tests on an interface that run against both `OldImpl` and `NewImpl` (parameterized matrix). Idiomatic for Branch by Abstraction.
- **Integration tests.** Wire components and run end-to-end against the test harness (Robolectric, JVM in-memory DB, fake network). Cover DI graph assembly, serialization round-trip, repository → use-case wiring.
- **Golden snapshots.** UI screenshot tests (Paparazzi, Roborazzi) for visual parity. Stored alongside the test; CI fails on diff.
- **Property-based tests.** For pure functions and bounded inputs: generate inputs, assert an invariant holds for both implementations. Useful when an exhaustive case list is impractical.

**Investment cost.** Highest. Writing characterization tests for a legacy codebase that has none is itself a significant project.

**When to invest heavily.** Horizontal migrations (DI, async, serialization) — bugs there affect everything downstream. High-traffic critical paths — payments, authentication, data persistence. Anything where regression is hard to detect by eye.

**When to invest minimally.** Single-screen UI migrations where Plane B + manual verification is cheaper and equally effective. Idiom swaps where the compiler enforces parity.

---

## Plane B — Test cases

**Goal.** A human-readable contract for "what should still work after the migration". The source of truth that Phase 6 (Device Verify) walks against.

**Format.** Prose test cases in `<slug>-test-cases.md`, each with steps and expected outcome. Numbered: TC-1, TC-2, … . One test case per behavior, not per UI element.

**Template fields:**

```markdown
**Preconditions:** ...
**Priority:** P0 / P1 / P2 / P3
**Steps:** ...
**Expected:** ...
**Verification source:** Plane A test name (if any), or "manual only".
```

See `references/artifacts.md` for a fill-in template with worked examples.

**Priority framework:** P0–P3 as defined in `~/.claude/rules/qa-and-testing.md § 2`. Do not redefine here.

**Investment cost.** Low to medium. Writing 20–40 test cases for one migration takes a few hours; reading and running them takes much less than writing them.

**When to invest heavily.** Every non-trivial migration. Plane B is the cheapest plane with the highest leverage — it forces an explicit answer to "what does this thing actually do?".

**When to skip.** Pure utility refactors where the compiler is the verification (file-by-file Kotlin DSL conversion, IDE-driven `kotlin-android-extensions` cleanup).

---

## Plane C — Manual scenarios

**Goal.** The safety net. Covers paths that Plane A cannot reasonably automate and Plane B does not enumerate.

**Format.** Exploratory paths in `<slug>-manual-scenarios.md`, organized by concern.

**Standard concerns to cover** (mark N/A explicitly when one does not apply):

- **Accessibility** — TalkBack (Android) / VoiceOver (iOS) walk-through, focus order, contrast, content descriptions.
- **RTL** — layout in `ar-SA` or `iw-IL` locale.
- **Dark mode** — both light and dark variants of each screen.
- **Locale switching** — `en` → `de` → `ar` runtime switch; verify formatting (numbers, currencies, dates).
- **Low memory** — `adb shell am send-trim-memory <pkg> COMPLETE` and recovery.
- **Slow network** — Charles / Network Conditioner throttling; verify loading states, timeouts, retries.
- **Configuration change** — rotation, font scaling, dynamic theme, split-screen.
- **Back stack** — deep navigation, then back; verify state restoration.
- **Process death** — kill app, return — state restoration.
- **Permissions** — grant/revoke each runtime permission; verify graceful handling.

See `references/artifacts.md` for the Manual Scenarios template (MS-1..MS-5 worked examples).

**Investment cost.** Low for the document; the cost is the time spent walking through during Phase 6.

**When to invest heavily.** Any user-facing migration. UI migrations especially benefit from Plane C because Plane A (snapshot tests) is brittle and Plane B describes intent, not edge-case visual behavior.

**When to skip.** Backend/library migrations with no UI surface.

---

## Calibration matrix

| Migration class | Plane A | Plane B | Plane C |
|---|---|---|---|
| Horizontal: DI, async, serialization | Heavy (contract tests on abstraction) | Medium | Light |
| Vertical UI: single screen | Light (golden snapshots) | Heavy | Heavy |
| Vertical UI: many screens | Medium (snapshot suite) | Heavy | Medium per screen |
| Utility refactor (idiom swap, compiler-enforced) | Light (sanity snapshots) | Light | Light |
| Backend/library swap | Heavy (contract + property-based) | Medium | N/A |
| KMP `expect/actual` change | Medium (parameterized across targets) | Light | Light per platform |

The matrix is a starting point. Adjust based on:
- **Risk.** Higher cost-of-failure → invest more in Plane A.
- **Existing coverage.** If Plane A already covers FROM behavior — extend it. If FROM has zero tests — Plane B and Plane C carry the parity contract.
- **Reversibility.** If the migration uses a feature flag with fast rollback (Duplicate-then-delete, Strangler Fig with flag), Planes B and C can carry more weight.

---

## When Plane A is too expensive

If the FROM stack has no tests and writing characterization tests for it would cost more than the migration itself:

1. Be explicit. State this in the Phase 4 strategy document: "Plane A reduced to TC-mapped sanity snapshots; Planes B and C carry parity."
2. Strengthen Planes B and C. Add more TCs covering edge cases that Plane A would normally catch. Add more manual scenarios.
3. Consider shadow run for critical paths only (Branch by Abstraction supports this naturally). Send real production traffic to both `OldImpl` and `NewImpl`, compare outputs off-line.
4. Use a phased rollout with monitoring. Phase 6 then includes a canary release window with explicit metrics to watch.
5. Document the trade-off in `<slug>-strategy.md` so it is visible to the user and to future reviewers.

The trade-off is acceptable as long as it is explicit. Silent "we'll skip Plane A" is the failure mode.

---

## Behavior-spec index

`<slug>-behavior-spec.md` is a thin index that lists what was captured and where. Keep it short:

```markdown
# Behavior spec: <slug>

FROM: <technology + version>
TO: <technology + version>

## Plane A — Code tests
- Characterization: `module/src/test/.../OldImplCharacterizationTest.kt` (47 tests)
- Contract: `module/src/test/.../<Abstraction>ContractTest.kt` (matrix OldImpl × NewImpl)
- Golden snapshots: `module/src/test/snapshots/<slug>/` (12 baselines)

## Plane B — Test cases
- `swarm-report/<slug>-test-cases.md` (TC-1..TC-32; P0×4, P1×12, P2×8, P3×8)

## Plane C — Manual scenarios
- `swarm-report/<slug>-manual-scenarios.md` (MS-1..MS-8 covering a11y, RTL, dark, locale, low memory, rotation, back stack, process death)

## Calibration rationale
<one paragraph explaining why Planes were weighted this way>
```

The index makes Phase 6 (Device Verify) trivial to start — one entry point points at everything.

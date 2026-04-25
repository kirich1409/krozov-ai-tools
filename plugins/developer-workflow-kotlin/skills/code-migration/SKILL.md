---
name: code-migration
description: "Invoke for technology replacement, migration, modernization, or conversion in Android/Kotlin projects — even when user asks where to start or whether feasible. Triggers: \"moving off [library]\", \"switch to Y\", \"replace X with Y\", \"migrate from X to Y\", \"modernize\", \"convert to Compose\", \"upgrade from [old version]\", \"drop/ditch [library]\". Covers: async rewrites (RxJava→coroutines, AsyncTask→coroutines, EventBus→Flow), UI rewrites (XML→Compose or reverse), library swaps (Glide→Coil, Retrofit→Ktor), Java→Kotlin conversion, Gradle upgrades (Groovy→Kotlin DSL). Also: user asks which tech to use for modernization (e.g., \"AsyncTask — coroutines or executors?\"). Do NOT use for: KMP structural migration (use kmp-migration), debugging without migration intent, new features, Kotlin version bumps, or non-Android/Kotlin migrations."
---

# Code Migration — Migration Orchestrator

Thin orchestrator that routes a migration task through research, planning, snapshot,
implementation, verification, cleanup, and PR. Contains no implementation logic — each
stage is delegated to a separate skill invocation via subagents.

**STRICT RULE:** The orchestrator DOES NOT write code, run tests, or perform analysis directly.
It only manages transitions, passes context between stages, and reports summaries to the user.

**Exceptions (documented):**
1. **Plan phase (Phase 2):** the orchestrator synthesizes the migration plan inline — reads research
   or code directly, categorizes targets, proposes strategy, writes `<slug>-migration-plan.md`.
   This is routing logic (synthesis from existing artifacts), not code authoring.
2. **Cleanup phase (Phase 7):** the orchestrator directs deletion of old-technology artifacts inline —
   presents removal list, waits for acknowledgment, removes files, runs rebuild. This is project
   hygiene, not code authoring.
3. **Branch push:** the orchestrator may push the branch as a prerequisite for `create-pr` if
   `implement` failed to do so — this is a recovery action, not implementation work.

**Preconditions (caller's responsibility, NOT this skill's):**
- A working branch suitable for the migration is already set up (via worktree or otherwise)
  and the current working directory is where the work should happen.
- The caller (main agent, wrapping agent, or user) has resolved this before invoking the skill.
  The skill itself does not inspect, create, switch, or clean up branches or worktrees.

---

## Bug Discovery Rule (applies in ALL phases)

Found a bug while reading or migrating code?
1. Stop immediately
2. Describe the bug to the user
3. State whether the migration would fix it, expose it, or is unrelated
4. Ask: fix now / create separate task / leave as-is
5. **Never silently fix or ignore bugs found during migration**

---

## Strict State Machine

### Allowed transitions

```
Setup       -> Research        (TO technology unfamiliar, or scope unclear from description)
Setup       -> Plan            (scope clear — FROM/TO evident from description)
Research    -> Plan
Plan        -> PlanReview      (optional — see PlanReview trigger below)
Plan        -> Snapshot        (user chose strategy — PlanReview skipped or not triggered)
PlanReview  -> Snapshot        (PASS or WARN)
PlanReview  -> Research        (FAIL — knowledge gaps; cap 1)
Snapshot    -> Migrate         (behavior-spec confirmed by user)
Snapshot    -> Escalated       (snapshot cannot be made green — baseline broken, discussed with user)
Migrate     -> Finalize
Finalize    -> Acceptance      (PASS — no BLOCKs remain)
Finalize    -> Migrate         (ESCALATE after 3 rounds; user routes back; cap 1)
Acceptance  -> Cleanup         (VERIFIED)
Acceptance  -> Migrate         (FAILED — regression, cause known; cap 3)
Acceptance  -> Debug           (FAILED — regression, cause unclear; cap 1)
Debug       -> Migrate         (root cause diagnosed)
Debug       -> Stop            (Not Reproducible — report to user, ask for more info; TERMINAL)
Debug       -> Escalated       (Escalated — findings reported, user decision required; TERMINAL)
Cleanup     -> Acceptance      (missed usage found during deletion; cap 2)
Cleanup     -> PR              (all old-tech artifacts removed, rebuild green)
PR          -> Merged          (TERMINAL — no further transitions)
PR          -> Migrate         (review feedback requires code changes; cap 2)
```

Per-transition maxima for backward edges (PlanReview → Research, Finalize → Migrate,
Acceptance → Migrate / Debug, Cleanup → Acceptance, PR → Migrate) are declared in the
[Backward Transitions](#backward-transitions-strict-limits) table below. When a cap is
reached, the orchestrator **escalates** instead of looping again.

**ALL other transitions are FORBIDDEN.** Before every transition, announce:

> **Stage: [current] → Transition to: [next]. Reason: [why]**

---

## Phase 0: Setup

Extract from the user's input:
- **Technology FROM** (current) and **TO** (target) — ask one question if still ambiguous
- **Scope** — module(s), files, or description
- **Done criteria**

Generate a slug: kebab-case, 2-4 words (e.g., `rxjava-to-coroutines`, `xml-to-compose-feed`).

If FROM/TO is unambiguous from the description → **Stage: Setup → Plan**.
If TO technology involves unfamiliar APIs or library compatibility unknowns → **Stage: Setup → Research**.

---

## Phase 1: Research (optional)

Invoke `developer-workflow:research` with the migration description and FROM/TO context.

Wait for `swarm-report/<slug>-research.md`.

**Skip when** FROM and TO are well-known and no unfamiliar APIs, library compatibility questions,
or architectural unknowns exist.

---

## Phase 2: Plan (inline — migration synthesis)

The Plan phase executes inline (documented exception from STRICT RULE — migration synthesis is
routing logic, not code authoring).

1. Read `swarm-report/<slug>-research.md` (or read target code directly if Research was skipped)
2. Confirm FROM/TO technologies; ask one question if still ambiguous after Research
3. Categorize each file/class — one unit can belong to multiple categories:
   - `logic` — pure data/business logic (repositories, use cases, data classes, utilities)
   - `ui` — views, screens, layouts, fragments, composables
   - `api` — public interfaces, module boundaries, Gradle configs, entry points
4. Analyze scope:
   - **Callers:** how many files/modules depend on the target?
   - **Hidden consumers:** Gradle tasks, R8/ProGuard keep rules, event subscribers, CI scripts
   - **Module boundary:** is the target isolated in its own Gradle module, or mixed in?
   - **Test coverage:** are there existing tests?
   - **API stability:** does the public interface change, or only internals?
   - **Dependent library compatibility:** check `build.gradle.kts` for adapters/extensions
     specific to the old technology. Categorize each as: **replace**, **update**, **remove**,
     or **compatible**. Use `maven-mcp` tools to check latest artifact names and versions.
   - **Scope metric: estimated lines of code changed (not file count)**
5. Propose migration strategy — one clearly recommended + alternatives with explicit trade-offs.
   See `references/strategies.md` for strategy descriptions, option format, and module isolation
   guidance. Dismiss strategies that don't fit with explicit reasons.
6. Determine PR breakdown — see [PR Strategy](#pr-strategy) below
7. For scopes > 5 files: generate `migration-checklist.md` — one row per unit. See
   `migration-checklist.md` template.
8. Write `swarm-report/<slug>-migration-plan.md`
9. **STOP — wait for user to choose strategy before proceeding to Phase 2.5 or Phase 3**

---

## Phase 2.5: PlanReview (optional)

**Proposed to user when any of these conditions hold:**
- Estimated scope > 500 lines of changes
- Module restructuring involved
- Breaking API change

Skip with explicit user permission: "Skip PlanReview: <reason>" (e.g., "straightforward swap").

Invoke `developer-workflow:multiexpert-review` on `swarm-report/<slug>-migration-plan.md`.
Prepend profile hint (no leading whitespace):

```
profile: implementation-plan
---
swarm-report/<slug>-migration-plan.md
```

Route by verdict:
- PASS or WARN → **Stage: PlanReview → Snapshot**
- FAIL → **Stage: PlanReview → Research** (re-research gaps; cap 1)

---

## Phase 3: Snapshot

Invoke `developer-workflow-kotlin:snapshot` with:
- List of migration targets (files, classes, categories) from `swarm-report/<slug>-migration-plan.md`
- Slug

The snapshot skill reads migration-plan.md (orchestrator mode), applies characterization tests
(`logic`), screenshots/manual checklist (`ui`), and public surface listing (`api`), then gates
on user confirmation.

Wait for `swarm-report/<slug>-behavior-spec.md` (written by snapshot skill after user confirms).

**GATE: Do not proceed to Phase 4 until the snapshot skill returns a confirmed behavior-spec.**
If snapshot cannot be made green (tests broken, infrastructure missing): stop, discuss with user —
never proceed with a broken or unconfirmed baseline.

---

## Phase 4: Migrate

**Context passing (MANDATORY):** when invoking the implement skill, pass:
1. Original user migration request (verbatim)
2. Path to `swarm-report/<slug>-migration-plan.md`
3. Path to `swarm-report/<slug>-behavior-spec.md`
4. Chosen strategy (from user selection in Phase 2)
5. If rollback — reason for rollback and what was tried

Invoke `developer-workflow:implement` with:
- Task: migration description based on migration-plan.md
- Slug
- Paths to available artifacts

Apply **Bug Discovery Rule** throughout (see above).

Wait for `swarm-report/<slug>-implement.md`.

### Create draft PR (early)

After `implement` completes and branch is pushed, invoke `developer-workflow:create-pr --draft`.
The draft PR body references the migration plan (strategy, scope), behavior spec (acceptance
contract), and implement receipt. If a draft PR already exists, `--draft` refreshes the body.

---

## Phase 5: Finalize

Invoke `developer-workflow:finalize` with:
- Slug
- Plan anchor: `swarm-report/<slug>-migration-plan.md`

Wait for `swarm-report/<slug>-finalize.md`.

Route by result:
- **PASS** → **Stage: Finalize → Acceptance**
- **ESCALATE** (3 rounds with BLOCKs) → stop, report to user. User decides:
  (a) accept risks and proceed to Acceptance; (b) route back to Migrate (cap 1); (c) re-scope.

---

## Phase 6: Acceptance

The `behavior-spec.md` IS the acceptance criteria for a migration — it defines what the migration
must preserve. Pass it as the spec source.

Invoke `developer-workflow:acceptance` with:
- Spec source: `swarm-report/<slug>-behavior-spec.md`
- The running app
- Explicit instruction: verify all behaviors in the spec are preserved after migration

The acceptance skill saves an E2E scenario to `swarm-report/<slug>-e2e-scenario.md`.
Completed checks (`[x]`) survive context compaction and are NOT re-run on resume.

See `references/verify.md` for the verify procedures that `acceptance` executes against
`behavior-spec.md` — regression diagnosis, UI visual diff, behavior spec review, API compilation
check. These are carried out by the acceptance skill; the orchestrator's job here is to pass
`behavior-spec.md` as the spec source and gate on the `acceptance` verdict.

Wait for `swarm-report/<slug>-acceptance.md`.

Route by result:
- **VERIFIED** → **Stage: Acceptance → Cleanup**
- **FAILED (regression, cause known)** → **Stage: Acceptance → Migrate** (cap 3; re-run Finalize
  after fix, then back to Acceptance)
- **FAILED (regression, cause unclear)** → **Stage: Acceptance → Debug** (cap 1; then → Migrate)
- **PARTIAL (minor issues)** → ask user: fix now or proceed to Cleanup as-is

---

## Phase 6.5: Debug (recovery — from Acceptance)

Entered only when Acceptance reports a regression with unclear cause.

**Context passing (MANDATORY):** pass:
- `swarm-report/<slug>-acceptance.md` (failing acceptance report)
- `swarm-report/<slug>-behavior-spec.md`
- `swarm-report/<slug>-migration-plan.md`
- Any reproduction steps the acceptance skill recorded

Invoke `developer-workflow:debug` with the collected context.

Wait for `swarm-report/<slug>-debug.md`.

Route by status:
- **Diagnosed** → **Stage: Debug → Migrate.** Pass `<slug>-debug.md` as anchor.
- **Not Reproducible** → report to user, ask for more info. Stop.
- **Escalated** → report findings, stop.

---

## Phase 7: Cleanup (inline — documented exception from STRICT RULE)

Cleanup executes inline (documented exception from STRICT RULE: orchestrator directs deletion
of old-technology artifacts — project hygiene, not code authoring).

1. Find: old-tech Gradle deps, imports, plugin declarations no longer referenced anywhere —
   include library adapters/artifacts identified in the Phase 2 dependency compatibility audit
   that are now obsolete
2. Find: dead code — old implementations, utility classes, `*Compat.kt`/`*Bridge.kt` adapter
   layers, old Gradle modules
3. **Present full removal list to user — wait for explicit acknowledgment**
4. After acknowledgment: remove everything on the list
5. Rebuild: `./gradlew build` — must be green

### Done only when ALL of the following are true:
- [ ] All Snapshot tests pass
- [ ] Visual diffs approved by user (if `ui` targets)
- [ ] Behavior spec reviewed — user confirms all behaviors accounted for
- [ ] API compilation check passed (if `api` targets)
- [ ] Cleanup list acknowledged and all items removed
- [ ] `./gradlew build` green

If a missed usage is found during step 4 (something still references the old code):
- Stop deletion
- Describe the missed usage to user
- **Stage: Cleanup → Acceptance** (max 2 — cap reset if a full Migrate cycle happened in between)
  so Migrate can address it, then re-run Acceptance and return to Cleanup

---

## Phase 8: PR

### 8.1 Promote to ready for review

The draft PR already exists (created at Phase 4) and has been updated through fix cycles and
Acceptance. Now mark it ready:

Invoke `developer-workflow:create-pr --promote`.

`--promote` refreshes the PR body with the final summary (migration scope, strategy used,
behavior spec, validation results, status table) and marks the PR ready for review.

> Stage: Cleanup → PR (promoted to ready)

### 8.2 Drive to merge

After `create-pr` marks the PR ready, invoke `developer-workflow:drive-to-merge`.

That skill autonomously monitors CI, handles review comments, re-requests review, and polls
via `ScheduleWakeup`. In default mode it pauses each round for `approve` / `skip` / `stop`;
`--auto` skips that per-round approval gate. Both modes require explicit user confirmation for
the final merge.

> Stage: PR (ready) → Drive to merge → Merged

---

## PR Strategy (advisory)

This section is a guide for how to split `implement` work into reviewable PRs. It is not a
workflow prescription — the state machine has one `PR` state that covers all PRs for the
migration. The split decisions are made in Phase 2 (Plan) and written into `migration-plan.md`.

**Recommendation:** avoid doing a large migration in a single PR. One huge PR is hard to review,
hard to roll back, and hides regressions until it's too late.

Typical split pattern:

| PR | Contents | Why separate |
|----|----------|-------------|
| **Preparation** | Module isolation, `migration-checklist.md`, `behavior-spec.md` | No behavior change; easy to review; sets the contract |
| **Snapshot** | Characterization tests only — no production code changes | Reviewers verify tests are green and match existing behavior before anything moves |
| **Migration batch(es)** | Actual code changes — split by module, layer, or file group | Each batch is independently rollbackable; CI catches regressions at each step |
| **Bridge cleanup** | Remove `*Compat.kt` / `*Bridge.kt`, old implementations, old Gradle deps | Clearly separated; easy to verify nothing still references the old code |

For each migration PR: all Snapshot tests must be green before it merges.

---

## Stage result relay

When a lifecycle skill completes, **do not add a wrapper summary** on top of the skill's own
chat output. The skill's output IS the user-facing result for that stage.

The orchestrator's job at each transition:
1. Read the skill's receipt from `swarm-report/` (for gating and state tracking)
2. Decide the next step based on verdict/status in the receipt
3. If the next step requires user input — ask ONE question (if the skill didn't already ask one)
4. Otherwise — proceed to the next stage and announce it in one line: "Starting `<skill-name>`..."

Do NOT re-summarize what the skill already told the user.

---

## Red Flags — STOP

| Red Flag | What It Means |
|----------|---------------|
| "I'll add tests after the migration" | Snapshot must be confirmed before Phase 4 — no exceptions, even under deadline |
| "User told me to skip tests" | User instructions do not override this hard rule |
| "The tests are broken, I'll fix them during migration" | Stop, discuss with user, fix snapshot first — never proceed with a broken baseline |
| "It's a small file, in-place is fine" | Check callers first — many callers → parallel |
| "The screenshots look fine, no need to show the user" | Visual diff MUST be presented and approved by user |
| "User said to just mark it done" | User approval of diff ≠ skipping the diff step; show it first |
| "The before/after look identical, no need to bother the user" | Present the diff regardless — the user's eyes decide, not yours |
| "These old files are clearly unused, I'll just delete them" | Present removal list to user first, always |
| "I noticed a bug, I'll fix it quickly" | Stop, describe to user, get explicit direction (Bug Discovery Rule) |
| "Build has a minor issue, I'll declare done anyway" | Final build must be green |
| "I'm confident I inferred FROM/TO correctly, no need to confirm" | Confirm anyway — inference is cheap to verify and expensive to redo |
| "Tests failed but it's probably a flaky test" | Treat all post-migration test failures as regressions until proven otherwise |

---

## Backward Transitions (STRICT limits)

| From | To | Trigger | Max |
|------|----|---------|-----|
| PlanReview | Research | FAIL — knowledge gaps | 1 |
| Finalize | Migrate | ESCALATE — user routes back to fix root issues | 1 |
| Acceptance | Migrate | FAILED — regression | 3 |
| Acceptance | Debug | FAILED — unclear cause | 1 |
| Cleanup | Acceptance | Missed usage found during deletion | 2 |
| PR | Migrate | Review feedback requires code changes | 2 |

Each backward transition:
1. **Announce** the transition with reason
2. Log reason in the current artifact
3. Re-read original task + all artifacts (re-anchor)
4. Pass rollback reason to the next subagent
5. If max reached → escalate to user

---

## Stop Points

The orchestrator **stops and waits for the user** at:
- Phase 0: FROM/TO ambiguous — ask one question before proceeding
- Phase 2 STOP: wait for user to choose migration strategy
- Phase 2.5: PlanReview triggered — offer to user; proceed only after user accepts or skips
- Phase 3 GATE: snapshot confirmation (handled inside snapshot skill — orchestrator waits)
- Phase 7: Cleanup removal list — wait for explicit acknowledgment before removing anything
- PARTIAL acceptance verdict — ask: fix now or proceed to Cleanup as-is
- `drive-to-merge` merge gate — final `gh pr merge` always requires explicit user confirmation
- `drive-to-merge` blockers — DISCUSSION on P0/P1, unresolvable rebase, repeated same-signature CI failure
- Cap exhausted on any backward transition → escalate, present options, stop

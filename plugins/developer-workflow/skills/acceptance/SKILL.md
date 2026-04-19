---
name: acceptance
description: >
  Acceptance verification — confirm implementation meets spec (feature) or that a bug no longer
  reproduces (bug fix). Orchestrator: detects project type, verifies a source exists (spec AC,
  test plan, or debug.md), fans out parallel checks to `manual-tester` (UI + scenario),
  `code-reviewer` (delta), plus `business-analyst` / `ux-expert` / `security-expert` /
  `performance-expert` and a build smoke as triggered by spec frontmatter and project type,
  then aggregates via PoLL rules. Without a source, proposes `/write-spec`,
  `/generate-test-plan`, or `/debug`. Trigger on: "test this", "verify against spec",
  "QA the implementation", "run the test plan", "validate acceptance criteria",
  "verify the PR", "verify the fix", "confirm bug is gone", "acceptance", "приёмка",
  "проверь", "протестируй".
disable-model-invocation: true
---

# Acceptance

Choreographer skill. Detects project type, confirms a verification source exists, fans out
parallel checks to specialized agents, aggregates verdicts into one receipt. Acceptance
executes a pre-existing verification contract — it does not invent checks. When no contract
is available, it halts and proposes the correct upstream skill.

---

## Vocabulary

Canonical values used throughout this skill. Downstream consumers (feature-flow, bugfix-flow,
create-pr) read these from the receipt.

- **`project_type`** — one of: `android`, `ios`, `web`, `desktop`, `backend-jvm`,
  `backend-node`, `cli`, `library`, `generic`. Source of truth: ORCHESTRATION.md §Project
  type detection.
- **`has_ui_surface`** — boolean derived from `project_type`. True for `android`, `ios`,
  `web`, `desktop`. False otherwise (`generic` → ask user).
- **`ecosystem`** — build stack: `gradle`, `node`, `rust`, `go`, `python`, `xcode`. Used for
  build-smoke command selection only; orthogonal to `project_type`.
- **Per-check verdict** — each sub-check reports `PASS | WARN | FAIL | SKIPPED`, plus
  `severity` (`critical | major | minor`), `confidence` (`high | medium | low`), and
  `domain_relevance` (`high | medium | low`) for aggregation.
- **Bug severity** — `P0 | P1 | P2 | P3`. Unchanged from prior receipt schema, primary axis
  for `feature-flow`/`bugfix-flow` routing.
- **Aggregated Status** — `VERIFIED | FAILED | PARTIAL`. Derived; see §Aggregation.

---

## Step 0: Detect Project Type

Follow the canonical heuristic in `plugins/developer-workflow/docs/ORCHESTRATION.md` §Project
type detection. Output: `project_type`, `has_ui_surface`, `ecosystem`.

**Override policy.** If the spec frontmatter `platform:` list is non-empty, **spec wins** —
take the first platform value as the canonical `project_type`. If the list has more than one
entry, record the full list separately as `platforms: [...]` in the receipt; do not invent a
`multi-platform` `project_type`. Record `project_type_override: spec` in the receipt. If the
user corrects detection mid-run, record `project_type_override: user`.

Step 0 file reads and Step 1 file reads are disjoint. You MAY issue both sets in one batched
Read call set to avoid serial round-trips.

---

## Step 1: Gather Inputs

Acceptance requires at least one verification source. If none is available, Step 1.5 halts.

### 1.1 Spec Source (optional if a test plan or debug.md is provided)

Accept any combination of: Figma mockups, PRD / requirements, acceptance criteria list, PR
description, GitHub/Linear issue. Read all provided sources.

**Read the spec frontmatter.** If present, load `platform`, `surfaces`, `risk_areas`,
`non_functional`, `acceptance_criteria_ids`, `design.figma`. These drive the conditional
triggers in Step 3 plus two invariant guards on the base plan:

- `ui ∈ surfaces` forces `manual-tester` into the fan-out when a scenario source exists,
  even if Step 0 detected a non-UI project (hybrid products with both UI and non-UI
  surfaces).
- `surfaces` set and does not contain `ui` on a UI-detected project means the spec
  explicitly excludes UI — skip `manual-tester` even if `has_ui_surface` is true, and note
  this in the Check Plan section of the receipt.

If the spec has no frontmatter (pre-iteration-2 specs, external specs, or plain-text issues)
— every conditional defaults to "not triggered" and `surfaces` is treated as unspecified;
only the base checks keyed off `has_ui_surface` run. This preserves backward compatibility.

### 1.2 Probe available artifacts (parallel)

Before branching, read the following in a single batched Read call set. Each may error-as-absent
— that is expected:

- `swarm-report/<slug>-test-plan.md` (receipt)
- `docs/testplans/<slug>-test-plan.md` (permanent)
- `swarm-report/<slug>-debug.md` (bug-fix reproduction steps)

Combined with inline inputs and spec sources, one of the branches below fires. Record the
selected branch as `test_plan_source` in the receipt.

#### Branch 1 — Receipt present (`test_plan_source: receipt`)

**Condition:** `swarm-report/<slug>-test-plan.md` exists.

Read the receipt's YAML frontmatter and load `permanent_path`. Interpret `review_verdict` per
the canonical definition in `generate-test-plan/SKILL.md` §Receipt: treat `PASS` / `WARN` /
`skipped` as proceed; `FAIL` and `pending` as blockers that escalate back to the orchestrator.
Pass the **permanent file** to `manual-tester` as the primary test-plan source. If the
receipt has a `platform:` field, use it as an additional input to Step 0's override policy.

#### Branch 2 — Permanent file exists without receipt (`test_plan_source: mounted`)

**Condition:** Branch 1 did not fire **and** `docs/testplans/<slug>-test-plan.md` exists on
disk without a matching receipt.

Acceptance owns the mount-receipt when invoked outside `feature-flow`. Emit a mount-receipt
at `swarm-report/<slug>-test-plan.md` following the canonical format in
`generate-test-plan/SKILL.md` §Receipt. Apply the mount overrides: `status: Mounted`,
`review_verdict: skipped`, `source_spec: existing (pre-orchestration)`. Derive
`phase_coverage` from the permanent file's phase headings; omit the field if coverage cannot
be determined reliably. Pass the permanent file to `manual-tester`.

#### Branch 3 — Inline test plan or spec available (`test_plan_source: on-the-fly`)

**Condition:** Branches 1 and 2 did not fire **and** the invocation provides a test plan
inline, a spec source, or both.

Three modes:

- **Test plan only (no spec)** — execute as-is; verdict depends on TC pass/fail.
- **Test plan + spec** — execute the plan, cross-reference against the spec, flag obvious gaps
  to the user ("spec mentions X but the test plan doesn't cover it — add a TC?").
- **Spec only (no test plan)** — generate a test plan from the spec: identify testable flows,
  write TC-prefixed cases with tiers/steps/expected results, present for approval, adjust per
  feedback.

#### Branch 4 — Nothing available (`test_plan_source: absent`)

**Condition:** no receipt, no permanent file, no inline test plan, no spec source, no
`swarm-report/<slug>-debug.md` (bug-fix path).

Proceed to Step 1.5. Do not run any checks.

---

## Step 1.5: Source-Missing Gate

### Proposal table

| Situation | Proposal |
|---|---|
| No spec, no test plan, implement receipt exists (feature) | Run `/write-spec` (requirements doc) or `/generate-test-plan` (tests only), then re-run acceptance. |
| Spec exists without acceptance criteria, no test plan, UI project | Run `/generate-test-plan` to produce executable TCs, or add acceptance criteria to the spec. |
| Bugfix path with no `swarm-report/<slug>-debug.md` | Run `/debug` to capture reproduction steps, then re-run acceptance. |
| Only `design.figma` in spec, no test plan, UI project | Design-only review possible via ux-expert; for functional acceptance also run `/generate-test-plan`. |

### Options

1. **Create the missing source** — invoke the proposed upstream skill, then re-run acceptance.
2. **Abort acceptance** — exit without a receipt; user re-invokes when ready.

Exploratory QA without a scenario is the `bug-hunt` skill's responsibility. Do not offer it as
a fallback inside acceptance.

From `feature-flow` / `bugfix-flow` this gate rarely fires — upstream skills guarantee a
source. Standalone invocations are the main user.

---

## Step 2: Persist E2E Scenario

**Only relevant if `has_ui_surface == true` and a scenario source exists** (test plan, spec
with AC, or debug.md). Re-anchoring against this file is enforced by `manual-tester` —
acceptance writes it once here; re-reads during aggregation only.

The running-app environment (device, simulator, emulator, browser) is **owned by
`manual-tester` itself** — see its Step 0 Environment Setup. This skill does not probe
devices, run `gradlew installDebug`, or start dev servers; it delegates that responsibility
wholesale to the agent.

Save to `swarm-report/<slug>-e2e-scenario.md`:

```markdown
# E2E Scenario: <task name>
Type: Feature / Bug fix
Project type: <project_type>
Spec source: <what was used>

## Steps
- [ ] 1. <concrete user action> → Expected: <result>
- [ ] 2. <concrete user action> → Expected: <result>
```

For bug fixes, steps come from `debug.md` reproduction steps inverted:
- Original: "Step X triggers the bug" → E2E: "Step X no longer triggers the bug".

Compaction-resilience (enforced by `manual-tester`, not by this skill): checkbox marks survive
compaction; completed steps (`[x]`) are not repeated; resume from the first incomplete step.

---

## Step 2.5: Dedup Probe

Read `swarm-report/<slug>-quality.md` (produced by `implement`'s Quality Loop). Three cases:

- **`Status: PASS`, receipt is from the current branch head** — `code-reviewer` is skipped.
  Freshness is inferred from the receipt's `Date:` field vs the branch commit window; if it
  cannot be confirmed (e.g. receipt significantly older than the latest commit), do **not**
  skip — run `code-reviewer` normally. On skip, write a stub artifact at
  `swarm-report/<slug>-acceptance-code.md` with `verdict: SKIPPED`, `blocked_on: null`, and a
  one-line body referencing `<slug>-quality.md`.
- **`Status: FAIL`** — Quality Loop failed upstream; do not silently proceed. Run
  `code-reviewer` anyway, and surface `blocked_on: quality-loop failed — see <slug>-quality.md`
  in the Step 4 Summary. The aggregated Status is forced to `PARTIAL` at minimum (or
  `FAILED` if `code-reviewer` itself returns `FAIL`).
- **Receipt missing** — run `code-reviewer` normally. No skip.

Field name matches `implement`'s receipt schema. Note: `code-reviewer` skipping here is
decoupled from the Re-verification Loop's `diff_hash` policy — the dedup here is about
"implement already ran code-review on this diff", whereas `diff_hash` idempotency (§Re-verification
Loop) is about "previous acceptance run covered this same diff".

This probe is synchronous — it decides the Step 3 fan-out composition and emits the stub
before fan-out.

---

## Step 2.6: Persist Fan-out State

Before issuing the Step 3 fan-out — but **after** the full check plan has been finalized
(Step 3 intro resolves base + all conditional triggers) — save the plan and
compaction-resilient progress to `swarm-report/<slug>-acceptance-state.md`. Symmetric to
`plan-review`'s state file. This file carries the acceptance run across context compaction —
it is never a receipt, just operational state.

Step ordering: 2.5 dedup probe → Step 3 intro resolves conditional triggers → write the
state file here (Step 2.6) with the complete `Planned Checks` list → Step 3 body dispatches
the fan-out.

```markdown
# Acceptance State: <slug>

Status: planning | running | aggregating | done
Cycle: <N> of 3              # incremented on Re-verification Loop re-entry
Started: <ISO8601>
Base: <base-branch>
Diff hash: <sha256 of git diff <base>...HEAD>
Spec hash: <sha256 of spec file, or null>
Test-plan hash: <sha256 of permanent test plan, or null>

## Planned Checks
- [ ] manual (triggered by has_ui_surface + scenario)
- [ ] code (triggered by dedup miss)
- [ ] ac-coverage (triggered by spec.acceptance_criteria_ids)
- [ ] security (triggered by spec.risk_areas: [auth])
- ...

## Completed Checks
- [x] code — swarm-report/<slug>-acceptance-code.md — PASS
- [x] build — swarm-report/<slug>-acceptance-build.md — PASS
...

## Aggregated Verdict History
### Cycle 1
Verdict: FAILED
Blockers: <copy from aggregated receipt>
```

**Rules:**
1. Create and populate the file only after the full check plan is finalized — base
   fan-out plus all conditional triggers (spec-driven and diff-driven) — and before any
   agent batch is spawned. The initial `Planned Checks` list must reflect that complete
   plan.
2. Before each major action (spawning an agent batch, aggregating, writing the final
   receipt) — **re-read** the state file via Read tool. Completed checks (`[x]`) are not
   re-spawned on resume after compaction.
3. Mark each check `[x]` with the artifact path and verdict as soon as the per-check file
   is written.
4. On Re-verification Loop re-entry (§Re-verification Loop), increment `Cycle`, reset the
   `Planned Checks` list using the new diff/spec/test-plan hashes, move checks to be skipped
   to a **`## Re-used from previous cycle`** section (with artifact pointers), and append a
   new entry under `Aggregated Verdict History` when the cycle completes.
5. When `Status: done` is written, the state file becomes read-only operational history —
   it is not deleted automatically.

The state file and the e2e-scenario file (`<slug>-e2e-scenario.md`) are independent — the
latter is `manual-tester`'s internal re-anchor, owned by the agent; the state file is
acceptance's own fan-out cursor, owned by this skill.

---

## Step 3: Run Checks (parallel fan-out)

Pick the check plan by `has_ui_surface` plus conditional triggers read from spec frontmatter.
Emit **one** message containing all tool calls simultaneously (Agent calls + Bash smoke). Do
not wait for any to return before dispatching the others.

### Base check plan

| `has_ui_surface` | Base fan-out |
|---|---|
| `true` | `manual-tester` + `code-reviewer` (unless skipped by Step 2.5) |
| `false` | `code-reviewer` (unless skipped by Step 2.5) + build smoke (Bash) |

### Conditional triggers

Add to the fan-out only when the trigger fires. Each trigger maps to a specialist agent with a
narrow prompt. When no trigger fires for an agent, the agent is not spawned. Triggers read
either from spec frontmatter or directly from the diff.

| Trigger | Agent | Role |
|---|---|---|
| spec `acceptance_criteria_ids` non-empty | `business-analyst` | AC coverage — every `AC-N` has evidence in the diff, TC list, or manual-tester report |
| spec `design.figma` set, `has_ui_surface == true` | `ux-expert` design-review | Verify UI matches the referenced mockup + project design system |
| spec `non_functional.a11y` set, `has_ui_surface == true` | `ux-expert` a11y focus | Accessibility audit against the declared WCAG level |
| spec `risk_areas` includes any of `auth`, `payment`, `pii`, `data-migration` | `security-expert` | Security review against diff and any persisted state changes |
| spec `non_functional.sla` set, **or** `risk_areas` includes `perf-critical` | `performance-expert` | Bench/regress check against the declared SLA |
| diff touches a public API symbol, **or** changes span ≥ 3 top-level modules | `architecture-expert` | Module boundaries, dependency direction, public API contract |
| diff touches any build file (`build.gradle*`, `settings.gradle*`, `pom.xml`, `package.json`, `Cargo.toml`, `go.mod`, `pyproject.toml`, `Makefile`) | `build-engineer` | Build config sanity — plugin versions, task wiring, dependency additions |
| diff touches CI / release config (`.github/workflows/*`, `.gitlab-ci.yml`, `Dockerfile`, `docker-compose*`, `.circleci/config.yml`, `release.yml`) | `devops-expert` | Pipeline/release health, secret handling, rollout gates |

**Diff-based trigger detection.** Two cached passes over the same diff:

1. **Path pass** — run `git diff --name-only <base>...HEAD` once and cache the path set.
   Use the cached set for all path-only rules (build files, CI/release config, cross-module
   span).
2. **Content pass (on demand)** — when the `architecture-expert` rule needs to decide
   "diff touches a public API symbol", read the diff body once via
   `git diff --unified=0 <base>...HEAD -- <cached-paths>` and cache it for the whole run.
   Evaluate public-API heuristics against those patch hunks.

Both caches live for the duration of the acceptance run — do not re-probe per agent.

**Public API detection heuristic** for `architecture-expert`:
- **Kotlin/Java**: changes under `src/main/` that add/remove/rename a `public` / `open`
  symbol, or touch module-level files (`settings.gradle*`, `Module.kt`, `Dependencies.kt`).
- **TypeScript/JavaScript**: changes to `export` / re-export lines, `index.ts` public
  entrypoints, or `package.json` `"exports"` field.
- **Swift**: changes to `public` / `open` declarations or `Package.swift`
  `products` / `targets`.
- **HTTP/RPC surface**: changes to files matching `**/routes/**`, `**/controllers/**`,
  `**/handlers/**`, `**/api/**`, `*.proto`, `*.graphql`, `openapi.yaml`.
- **Cross-module threshold**: `git diff --name-only` spans ≥ 3 top-level module directories
  discovered from `settings.gradle*` / `package.json` workspaces / `Cargo.toml`
  `[workspace]` members.

If the heuristic is ambiguous, default to **not** spawning `architecture-expert` — a false
negative is safer than a false positive (the skill exists to catch high-risk changes, not
every diff).

When both design-review and a11y triggers fire, combine into one `ux-expert` invocation with
mode `both`. When no trigger fires, acceptance runs the base plan only — preserving
backward compatibility with specs written before iteration 2.

**Future iterations** will add `visual-check` as a separate sibling skill (not a fan-out
member) for pixel-level regression.

### Per-check artifact schema (shared by all sub-checks)

Each sub-check writes `swarm-report/<slug>-acceptance-<check>.md` with this frontmatter:

```yaml
---
type: acceptance-check
check: manual | code | build | ac-coverage | design | a11y | security | performance | architecture | build-config | devops
agent: <agent-name or "bash">
verdict: PASS | WARN | FAIL | SKIPPED
severity: critical | major | minor | null
confidence: high | medium | low | null
domain_relevance: high | medium | low | null
diff_hash: <sha256 of `git diff <base>...HEAD` at the moment the check ran; null for checks that do not depend on the diff>
blocked_on: <optional — what the user must resolve; also used when a planned per-check artifact is missing>
---
```

**`diff_hash` semantics.** Computed once per acceptance run from
`git diff <base>...HEAD | sha256sum`; every check written during that run records the same
value. The Re-verification Loop uses it to decide which checks to re-run (see §Re-verification
Loop). Bash-only checks (build smoke) record the same hash because their input is the same
diff. Checks whose verdict does not depend on the diff at all (e.g. a spec-only sanity check
with no code to review) may write `diff_hash: null` — the Re-verification Loop never skips
such a check purely on hash match.

File naming is **one file per `check` value**: `swarm-report/<slug>-acceptance-<check>.md`
(e.g. `-manual.md`, `-code.md`, `-design.md`, `-a11y.md`). When a single agent invocation
covers multiple concerns (see `ux-expert` below), it writes separate files per concern to
keep the one-file-per-check invariant intact.

`severity`, `confidence`, `domain_relevance` are required when `verdict` is `WARN` or `FAIL`;
null for `PASS` / `SKIPPED`. These drive the PoLL aggregation in Step 4.

### 3.1 Spawn `manual-tester` (UI branch)

`manual-tester` owns the runtime environment end-to-end per its Step 0 Environment Setup.
Acceptance does not pre-launch — that is intentional delegation.

Prompt contents:
1. **Spec context** — full text or clear pointers.
2. **Test plan** — the complete set of test cases.
3. **Target hints** (optional) — device/URL if the user already named one.
4. **Scope** — which tiers (default: Smoke + Feature).
5. **Output path** — `swarm-report/<slug>-acceptance-manual.md` with the per-check schema.

If the agent returns `WARN` with `blocked_on`, surface that text to the user as the primary
next-step requirement before re-running acceptance.

### 3.2 Spawn `code-reviewer` (delta review, skipped if Step 2.5 matched)

Prompt contents:
1. **Task description** — one sentence from spec or PR title.
2. **Plan pointer** — path to implement receipt or research report if present.
3. **Git diff** — current diff.
4. **Output path** — `swarm-report/<slug>-acceptance-code.md`.

Verdict rules: `PASS` if no semantic bugs, logic errors, or security issues; `WARN` for
style/minor; `FAIL` for blockers.

### 3.3 Build smoke (non-UI branch)

Pick the command by `ecosystem` (see ORCHESTRATION.md §Build system detection):

| `ecosystem` | Command |
|---|---|
| `gradle` | `./gradlew build -x test --quiet` (single-module) or `./gradlew :check` (multi-module) |
| `node` | `npm run build` (or `pnpm build` / `yarn build`) |
| `rust` | `cargo build --release --quiet` |
| `go` | `go build ./...` |
| `python` | `python -m compileall .` or package-specific build |

Multi-module detection: scan `settings.gradle*` for `include(` statements. If subprojects are
declared and the user did not specify a target module, ask which module is the smoke target
**before** entering Step 3 (do not block the fan-out message with a question).

If the `ecosystem` or command is not resolvable, skip with `verdict: SKIPPED` and
`blocked_on: build command unknown`. On success write `verdict: PASS`; on failure capture the
last ~50 lines and write `verdict: FAIL`. Receipt at
`swarm-report/<slug>-acceptance-build.md`.

### 3.4 Spawn `business-analyst` (conditional — AC coverage)

Fires when `acceptance_criteria_ids` in spec frontmatter is a non-empty list.

Prompt contents:
1. **Spec** — the spec file path.
2. **Diff / implement receipt** — evidence for each AC.
3. **Test plan** (if any) — TC list mapped to AC via each test case's `Source:` field
   (e.g. `Source: AC-1` or `Source: AC-2, AC-3`). This is the canonical mapping used by
   `generate-test-plan`; do not invent a new `AC-ref:` field.
4. **manual-tester output** (if running) — pointer to
   `swarm-report/<slug>-acceptance-manual.md`.
5. **Output path** — `swarm-report/<slug>-acceptance-ac-coverage.md`.

Verdict rules: `PASS` if every `AC-N` has at least one evidence pointer; `WARN` for weak
coverage (single witness on high-risk AC); `FAIL` for any missing AC. Severity: `FAIL` on
missing AC is `critical`; weak coverage is `major`.

### 3.5 Spawn `ux-expert` (conditional — design-review or a11y)

Fires when **`has_ui_surface == true`** AND (`design.figma` is set for design-review mode
**or** `non_functional.a11y` is set for a11y mode). Non-UI projects never trigger this even
if `non_functional.a11y` is present — a11y on backend/library/CLI has no surface to audit.

Design-review and a11y can both fire in one invocation. When both trigger, spawn `ux-expert`
once with mode `both`; the agent writes **two** artifacts (one per concern) so aggregation in
Step 4 treats them as independent checks:

- `swarm-report/<slug>-acceptance-design.md` with `check: design`
- `swarm-report/<slug>-acceptance-a11y.md` with `check: a11y`

When only one mode fires, only the corresponding artifact is written.

Prompt contents:
1. **Mode** — `design-review` / `a11y` / `both`.
2. **Spec** — file path.
3. **Design source** — `design.figma` URL (design-review mode).
4. **a11y target** — value of `non_functional.a11y` (e.g. `wcag-aa`).
5. **Running app pointer** — target hints; the agent reads running-app state via MCP only
   when the environment is already prepared, otherwise works from screenshots/code.
6. **Output paths** — one or both of the filenames listed above, matching the mode.

Verdict rules: `PASS` if design matches reference and a11y criteria met; `WARN` for minor
spacing/color deviations or AA soft failures; `FAIL` for missing components, broken
interaction paths, or hard a11y violations (keyboard trap, contrast below threshold).

### 3.6 Spawn `security-expert` (conditional)

Fires when `risk_areas` intersects `{auth, payment, pii, data-migration}`.

Prompt contents:
1. **Risk list** — the intersection subset.
2. **Diff** — full git diff.
3. **Spec** — file path.
4. **Output path** — `swarm-report/<slug>-acceptance-security.md`.

Verdict rules: `PASS` if no applicable OWASP / project-security-rule violations; `WARN` for
minor hardening opportunities; `FAIL` for exploitable issues, secret leaks, or regulation
breaches.

### 3.7 Spawn `performance-expert` (conditional)

Fires when `non_functional.sla` is set **or** `risk_areas` contains `perf-critical`.

Prompt contents:
1. **SLA target** — from `non_functional.sla`, or implicit `perf-critical` baseline.
2. **Diff** — full git diff.
3. **Output path** — `swarm-report/<slug>-acceptance-performance.md`.

Verdict rules: `PASS` if no regression; `WARN` for borderline; `FAIL` for violations.

### 3.8 Spawn `architecture-expert` (conditional — diff-triggered)

Fires when the diff touches a public API symbol **or** spans ≥ 3 top-level modules (see the
heuristic at §Conditional triggers).

Prompt contents:
1. **Trigger reason** — `public-api` / `cross-module` / `both` with the specific file list
   that matched.
2. **Diff** — full git diff (scoped to triggered files + their immediate neighbours).
3. **Module map** — list of top-level modules touched, discovered from
   `settings.gradle*` / `package.json` workspaces / `Cargo.toml` workspace members.
4. **Output path** — `swarm-report/<slug>-acceptance-architecture.md` with `check: architecture`.

Verdict rules: `PASS` if public contracts are preserved and module dependency direction is
clean; `WARN` for style issues (e.g., missing deprecation annotation, avoidable coupling);
`FAIL` for contract breakage, circular dependencies, or leaking internals into a public API.

### 3.9 Spawn `build-engineer` (conditional — diff-triggered)

Fires when the diff touches any build file listed in §Conditional triggers.

Prompt contents:
1. **Build files changed** — exact file list from the diff.
2. **Diff** — scoped to those files plus any touched module manifests.
3. **Ecosystem** — resolved `ecosystem` from Step 0 (drives which toolchain the agent should
   evaluate against).
4. **Output path** — `swarm-report/<slug>-acceptance-build-config.md` with
   `check: build-config`.

Note: `check: build` is already used by the non-UI build smoke (§3.3). The expert review of
**config changes** uses a distinct check identifier `build-config` so aggregation can treat
the two axes independently (a project can have a clean smoke and a broken config, or vice
versa).

Verdict rules: `PASS` if dependency additions are pinned/hash-verified, plugin versions are
consistent, and task wiring is intact; `WARN` for unpinned version ranges, unused
dependencies, or minor style issues; `FAIL` for breaking plugin mismatches, missing required
configuration, or dependency choices that conflict with project policy.

### 3.10 Spawn `devops-expert` (conditional — diff-triggered)

Fires when the diff touches CI / release configuration (see §Conditional triggers).

Prompt contents:
1. **CI files changed** — exact file list.
2. **Diff** — scoped to CI/release files.
3. **Repo context** — `public` vs `private` (affects secret handling guidance),
   and any related marketplace/deployment manifests if present.
4. **Output path** — `swarm-report/<slug>-acceptance-devops.md` with `check: devops`.

Verdict rules: `PASS` if pipeline health is preserved, secrets are handled correctly, and
rollout gates remain sound; `WARN` for minor inefficiencies or missing
`timeout-minutes` / `concurrency` guards; `FAIL` for leaked secrets, disabled safety gates,
or breaking workflow syntax.

---

## Step 4: Aggregate and Write Receipt

Read frontmatter of each `swarm-report/<slug>-acceptance-<check>.md` first (verdict +
severity + confidence + domain_relevance + blocked_on). Read the body only if
`verdict != PASS`. Do not inline artifact bodies — link them.

**Missing per-check artifact.** Step 2.5 writes a stub for skipped `code-reviewer`; Step 3.3
writes an artifact even on build-smoke failure. If a planned per-check artifact is
nonetheless missing at aggregation time, treat the check as `verdict: FAIL` with
`blocked_on: per-check artifact missing` — do not silently drop it. `blocked_on` is the
canonical field for surfacing unresolved conditions per the per-check schema; no separate
`error:` field exists.

### Aggregation — PoLL rules

Acceptance uses the same aggregation protocol as `plan-review` (see `plan-review/SKILL.md`
§"Aggregation Rules"). Input shape is per-check (not per-reviewer), reduction logic identical:

| Signal | Action |
|---|---|
| **`critical` severity** from any sub-check with `confidence: high` | → Blocker. Aggregated Status = `FAILED`. |
| **Same issue** (same file:line or same AC id) raised by 2+ sub-checks independently | → Escalate to `critical` regardless of individual severity. Multiple specialists seeing the same problem = real problem. |
| **`major` severity** from a sub-check with `domain_relevance: high` | → Important. Aggregated Status = `PARTIAL` if not already escalated. |
| **Contradicting verdicts** (one `PASS`, another `FAIL` on the same item) | → "Uncertainty — requires decision". Aggregated Status = `PARTIAL`, contradiction listed in the receipt. |
| **`minor` severity** or **`low` confidence** from a single check | → Note, not blocker. Does not affect aggregated Status. |
| **`low` domain_relevance** check flagging an issue | → Note, weight lower. |

**Bug severities (P0–P3) remain the primary routing axis** for
`feature-flow`/`bugfix-flow`. Any P0/P1 bug reported by any sub-check maps directly to
`FAILED` regardless of the PoLL above; PoLL layers additional rules on top for cases not
covered by bug severity alone (e.g. AC coverage FAIL without an associated P0 bug).

### Aggregated Status — final table

| Input | Aggregated Status |
|---|---|
| All checks `PASS` or `SKIPPED`, no P0–P3 bugs, no PoLL blocker | `VERIFIED` |
| Any P0 / P1 bug **or** PoLL blocker (critical high-confidence, or 2+-agent escalation) | `FAILED` |
| P2 / P3 bugs only, **or** PoLL important, **or** contradicting verdicts, **or** any `WARN` not otherwise classified | `PARTIAL` |
| `manual-tester` returned `WARN` with `blocked_on` | `PARTIAL` with `blocked_on` surfaced in Summary |

### Receipt format

Save to `swarm-report/<slug>-acceptance.md`. Legacy fields preserved; new sections appended.

```markdown
# Acceptance: <slug>

**Status:** VERIFIED / FAILED / PARTIAL
**Date:** <date>
**Type:** Feature / Bug fix
**Project type:** <project_type>
**Project type override:** <spec | user | none>
**Ecosystem:** <ecosystem>
**Spec source:** [what was used]
**Test plan:** [resolved permanent path / generated on-the-fly / none]
**test_plan_source:** receipt | mounted | on-the-fly | absent
**Context artifacts:** [paths to research.md, debug.md, implement.md, quality.md used as input]

## Idempotency Hashes
- `diff_hash`: <sha256 of `git diff <base>...HEAD`>
- `spec_hash`: <sha256 of the spec file bytes, or `null` if no file spec>
- `test_plan_hash`: <sha256 of the permanent test plan, or `null`>

These three hashes drive the Re-verification Loop decision table; downstream orchestrators
don't need to read them.

## Check Plan
- list of checks that ran, one per line, with their trigger
- e.g. `business-analyst` (AC coverage) — triggered by spec.acceptance_criteria_ids
- e.g. `ux-expert` — not triggered (no design.figma)

## Check Results

| Check | Agent / Tool | Verdict | Severity | Confidence | Artifact |
|---|---|---|---|---|---|
| Manual QA | manual-tester | … | … | … | swarm-report/<slug>-acceptance-manual.md |
| Code review | code-reviewer | … | … | … | swarm-report/<slug>-acceptance-code.md |
| AC coverage | business-analyst | … | … | … | swarm-report/<slug>-acceptance-ac-coverage.md |
| Design | ux-expert | … | … | … | swarm-report/<slug>-acceptance-design.md |
| A11y | ux-expert | … | … | … | swarm-report/<slug>-acceptance-a11y.md |
| Security | security-expert | … | … | … | swarm-report/<slug>-acceptance-security.md |
| Performance | performance-expert | … | … | … | swarm-report/<slug>-acceptance-performance.md |
| Architecture | architecture-expert | … | … | … | swarm-report/<slug>-acceptance-architecture.md |
| Build config | build-engineer | … | … | … | swarm-report/<slug>-acceptance-build-config.md |
| DevOps | devops-expert | … | … | … | swarm-report/<slug>-acceptance-devops.md |
| Build smoke | bash | … | … | … | swarm-report/<slug>-acceptance-build.md |

## Convergence signals
Issues raised by 2+ sub-checks independently. Strongest signal of real problems.
List one line each with the file:line or AC id and the list of checks that flagged it.

## Summary
[1–3 sentences. If PARTIAL with blocked_on — state the blocker first. If any convergence
signal — mention it in the first sentence.]

## Test Results
- Total: [n] | Passed: [n] | Failed: [n] | Blocked: [n]

## Bugs Found
[List by severity — P0 first, then P1, P2, P3. Link each to the per-check artifact that
reported it.]

## Bug Reproduction Check (bug fix only)
- Reproduction steps from debug.md: [executed / not applicable]
- Bug reproduces after fix: [yes / no]

## Recommendation
[Ship / Do not ship / Ship with known issues — and why]
```

### Routing (consumed by orchestrators)

- **VERIFIED** → `create-pr` (or mark existing PR ready for review).
- **FAILED** with P0/P1 and obvious cause → `implement` with the bug list as input. Max 3
  round-trips.
- **FAILED** with P0/P1 and unclear cause → `debug` first, then `implement`.
- **FAILED** with P0/P1 requiring regression coverage → `test-plan` append `## Regression TC`,
  then `implement`.
- **PARTIAL** with P2/P3 only or WARN — orchestrator asks the user: fix now or ship with
  known issues (continue to `create-pr`, include in PR description).
- **PARTIAL** with `blocked_on` — surface the blocker; do not continue until resolved.

---

## Re-verification Loop

On fix-loop re-entry (after `FAILED` → `implement` fix → re-run acceptance):

1. Re-probe Step 0 and Step 1 (project type rarely changes; inputs may).
2. Compute `diff_hash_new` = `sha256(git diff <base>...HEAD)`.
3. Decide per-check action using the previous per-check artifact and `diff_hash`:

   | Previous verdict | Previous `diff_hash` vs `diff_hash_new` | Action |
   |---|---|---|
   | `PASS` or `SKIPPED` | match | **Skip** — reuse the existing artifact as-is. Record `re-used previous verdict` in the aggregated receipt. |
   | `PASS` or `SKIPPED` | mismatch | Re-run. |
   | `WARN` | match | Skip. Re-used verdict keeps the WARN; user had the option to ship with it. |
   | `WARN` | mismatch | Re-run. |
   | `FAIL` | any | **Always re-run.** A FAIL is the point of the loop; hash match means the fix didn't land in the diff yet — still must re-run to confirm. |
   | any prior verdict with previous `diff_hash` = `null`, absent, or unreadable | any | Re-run — cannot prove idempotency without a usable hash. |

   An explicit `diff_hash: null` and a missing `diff_hash` field are treated the same way:
   both mean the prior artifact does not carry enough information to prove idempotency, so
   the check must be re-run.

4. For checks that are re-run:
   - Overwrite the per-check artifact with fresh content and a new `diff_hash`.
   - `manual-tester` specifically re-runs previously-failed TCs plus a Smoke tier by default;
     the full plan is re-run only on explicit request or when the spec changed.
5. Aggregate into a fresh `swarm-report/<slug>-acceptance.md`, overwriting the previous one.
6. Repeat until VERIFIED or the user decides to ship as-is.

**Spec/test-plan change override.** If the spec file or test-plan file changed between runs
(detected by comparing their `sha256` to values recorded in the previous aggregated receipt
under `spec_hash` / `test_plan_hash`), `business-analyst` and `manual-tester` are always
re-run regardless of `diff_hash` — their input is the spec/TC list, not just the code diff.
Other checks remain subject to the `diff_hash` policy.

**Back-compat rule.** If the previous aggregated receipt does not contain `spec_hash`
and/or `test_plan_hash` (e.g. a pre-iteration-3 receipt) — or either prior value is unknown
or unreadable — treat that input as **changed** and re-run the affected checks to be safe:
missing/unknown `spec_hash` forces `business-analyst`; missing/unknown `test_plan_hash`
forces `manual-tester`. If both are missing/unknown, re-run both. Other checks remain
subject to the `diff_hash` policy.

This is the full idempotency pass that iteration 2 parked. Cost saving: on a single-file fix
after a 5-agent FAIL, typically 2–3 passed checks are re-used instead of re-run.

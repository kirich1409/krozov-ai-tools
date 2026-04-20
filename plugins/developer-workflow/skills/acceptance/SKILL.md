---
name: acceptance
description: >
  This skill should be used when the user wants to confirm an implementation meets its spec
  (feature) or that a bug no longer reproduces (bug fix). Fans out parallel checks and
  aggregates verdicts into one receipt. Triggers: "test this", "verify against spec",
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

Procedural detail lives in reference files loaded only when the corresponding phase runs.
SKILL.md stays the stable orchestration contract.

| File | Covers |
|---|---|
| [`references/source-branches.md`](references/source-branches.md) | Step 1 spec frontmatter handling and the four `test_plan_source` branches (receipt / mounted / on-the-fly / absent), mount-receipt overrides |
| [`references/subcheck-prompts.md`](references/subcheck-prompts.md) | Step 3.1–3.10 per-agent prompt contracts — `manual-tester`, `code-reviewer`, build smoke, `business-analyst`, `ux-expert`, `security-expert`, `performance-expert`, `architecture-expert`, `build-engineer`, `devops-expert` |
| [`references/aggregation.md`](references/aggregation.md) | Step 4 PoLL aggregation rules, Aggregated Status table, full receipt template, downstream routing |
| [`references/re-verification.md`](references/re-verification.md) | Re-verification Loop `diff_hash` decision table, spec/test-plan change overrides, back-compat rules |

---

## Vocabulary

Canonical values used throughout this skill. Downstream consumers (`feature-flow`,
`bugfix-flow`, `create-pr`) read these from the receipt.

- **`project_type`** — one of: `android`, `ios`, `web`, `desktop`, `backend-jvm`,
  `backend-node`, `cli`, `library`, `generic`. Source of truth: `docs/ORCHESTRATION.md`
  §Project type detection.
- **`has_ui_surface`** — boolean derived from `project_type`. True for `android`, `ios`,
  `web`, `desktop`. False otherwise (`generic` → ask user).
- **`ecosystem`** — build stack: `gradle`, `node`, `rust`, `go`, `python`, `xcode`. Used
  for build-smoke command selection only; orthogonal to `project_type`.
- **Per-check verdict** — each sub-check reports `PASS | WARN | FAIL | SKIPPED`, plus
  `severity` (`critical | major | minor`), `confidence` (`high | medium | low`), and
  `domain_relevance` (`high | medium | low`) for aggregation.
- **Bug severity** — `P0 | P1 | P2 | P3`. Unchanged from prior receipt schema, primary
  axis for `feature-flow`/`bugfix-flow` routing.
- **Aggregated Status** — `VERIFIED | FAILED | PARTIAL`. Derived; table in
  `references/aggregation.md` §Aggregated Status.

---

## Step 0: Detect Project Type

Follow the canonical heuristic in `plugins/developer-workflow/docs/ORCHESTRATION.md`
§Project type detection. Output: `project_type`, `has_ui_surface`, `ecosystem`.

**Override policy.** If the spec frontmatter `platform:` list is non-empty, **spec wins** —
take the first platform value as the canonical `project_type`. If the list has more than
one entry, record the full list separately as `platforms: [...]` in the receipt; do not
invent a `multi-platform` `project_type`. Record `project_type_override: spec` in the
receipt. If the user corrects detection mid-run, record `project_type_override: user`.

Step 0 file reads and Step 1 file reads are disjoint. You MAY issue both sets in one
batched Read call set to avoid serial round-trips.

---

## Step 1: Gather Inputs

Acceptance requires at least one verification source. If none is available, Step 1.5
halts.

Read spec sources (Figma, PRD, AC list, PR description, issue) and load the spec
frontmatter (`platform`, `surfaces`, `risk_areas`, `non_functional`,
`acceptance_criteria_ids`, `design.figma`).

Probe artifacts in a single batched Read call set:

- `swarm-report/<slug>-test-plan.md` (receipt)
- `docs/testplans/<slug>-test-plan.md` (permanent)
- `swarm-report/<slug>-debug.md` (bug-fix reproduction)

The selected source fires one of four branches — `test_plan_source: receipt | mounted |
on-the-fly | absent`. If `swarm-report/<slug>-debug.md` is the only available verification
source, it qualifies Branch 3 (`on-the-fly`) — bug-fix verification treats `debug.md` as a
spec-like input. Full branch semantics, mount-receipt overrides, and spec frontmatter
consumers (including the `surfaces` invariant guards) live in
[`references/source-branches.md`](references/source-branches.md). Record the selected
branch as `test_plan_source` in the receipt.

---

## Step 1.5: Source-Missing Gate

Fires only on `test_plan_source: absent`.

### Proposal table

| Situation | Proposal |
|---|---|
| No spec, no test plan, implement receipt exists (feature) | Run `/write-spec` (requirements doc) or `/generate-test-plan` (tests only), then re-run acceptance. |
| Spec exists without acceptance criteria, no test plan, UI project | Run `/generate-test-plan` to produce executable TCs, or add acceptance criteria to the spec. |
| Bugfix path with no `swarm-report/<slug>-debug.md` | Run `/debug` to capture reproduction steps, then re-run acceptance. |
| Only `design.figma` in spec, no test plan, UI project | Design-only review possible via `ux-expert`; for functional acceptance also run `/generate-test-plan`. |

### Options

1. **Create the missing source** — invoke the proposed upstream skill, then re-run
   acceptance.
2. **Abort acceptance** — exit without a receipt; user re-invokes when ready.

Exploratory QA without a scenario is the `bug-hunt` skill's responsibility. Do not offer
it as a fallback inside acceptance.

From `feature-flow` / `bugfix-flow` this gate rarely fires — upstream skills guarantee a
source. Standalone invocations are the main user.

---

## Step 2: Persist E2E Scenario

**Only relevant if `has_ui_surface == true` and a scenario source exists** (test plan,
spec with AC, or `debug.md`). Re-anchoring against this file is enforced by
`manual-tester` — acceptance writes it once here; re-reads during aggregation only.

The running-app environment (device, simulator, emulator, browser) is **owned by
`manual-tester` itself** — see its Step 0 Environment Setup. This skill does not probe
devices, run `gradlew installDebug`, or start dev servers; it delegates that
responsibility wholesale to the agent.

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

Compaction-resilience (enforced by `manual-tester`, not by this skill): checkbox marks
survive compaction; completed steps (`[x]`) are not repeated; resume from the first
incomplete step.

---

## Step 2.5: Dedup Probe

Read `swarm-report/<slug>-quality.md` (produced by `implement`'s Quality Loop). Three
cases:

- **`Status: PASS`**, receipt from the current branch head → `code-reviewer` is skipped.
  Freshness is inferred from the receipt's `Date:` field vs the branch commit window; if
  it cannot be confirmed, do **not** skip — run `code-reviewer` normally. On skip, write a
  stub at `swarm-report/<slug>-acceptance-code.md` with `verdict: SKIPPED`,
  `blocked_on: null`, one-line body referencing `<slug>-quality.md`.
- **`Status: FAIL`** → Quality Loop failed upstream. Run `code-reviewer` anyway, surface
  `blocked_on: quality-loop failed — see <slug>-quality.md` in the Step 4 Summary. The
  aggregated Status is forced to `PARTIAL` at minimum (or `FAILED` if `code-reviewer`
  itself returns `FAIL`).
- **Receipt missing** → run `code-reviewer` normally. No skip.

Field name matches `implement`'s receipt schema. Note: `code-reviewer` skipping here is
decoupled from the Re-verification Loop's `diff_hash` policy
(see [`references/re-verification.md`](references/re-verification.md)) — the dedup here is
about "implement already ran code-review on this diff", whereas `diff_hash` idempotency is
about "previous acceptance run covered this same diff".

This probe is synchronous — it decides the Step 3 fan-out composition and emits the stub
before fan-out.

---

## Step 2.6: Persist Fan-out State

Before issuing the Step 3 fan-out — but **after** the full check plan has been finalized
(Step 3 intro resolves base + all conditional triggers) — save the plan and
compaction-resilient progress to `swarm-report/<slug>-acceptance-state.md`. Symmetric to
`multiexpert-review`'s state file. This file carries the acceptance run across context
compaction — it is never a receipt, just operational state.

Step ordering: 2.5 dedup probe → Step 3 intro resolves conditional triggers → write the
state file here (Step 2.6) with the complete `Planned Checks` list → Step 3 body
dispatches the fan-out.

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
4. On Re-verification Loop re-entry
   ([`references/re-verification.md`](references/re-verification.md)), increment `Cycle`,
   reset the `Planned Checks` list using the new diff/spec/test-plan hashes, move checks
   to be skipped to a **`## Re-used from previous cycle`** section (with artifact
   pointers), and append a new entry under `Aggregated Verdict History` when the cycle
   completes.
5. When `Status: done` is written, the state file becomes read-only operational history —
   it is not deleted automatically.

The state file and the e2e-scenario file (`<slug>-e2e-scenario.md`) are independent — the
latter is `manual-tester`'s internal re-anchor, owned by the agent; the state file is
acceptance's own fan-out cursor, owned by this skill.

---

## Step 3: Run Checks (parallel fan-out)

Pick the check plan by `has_ui_surface` plus conditional triggers read from spec
frontmatter. Emit **one** message containing all tool calls simultaneously (Agent calls +
Bash smoke). Do not wait for any to return before dispatching the others.

### Base check plan

| `has_ui_surface` | Base fan-out |
|---|---|
| `true` | `manual-tester` + `code-reviewer` (unless skipped by Step 2.5) |
| `false` | `code-reviewer` (unless skipped by Step 2.5) + build smoke (Bash) |

### Conditional triggers

Add to the fan-out only when the trigger fires. Each trigger maps to a specialist agent
with a narrow prompt. When no trigger fires for an agent, the agent is not spawned.
Triggers read either from spec frontmatter or directly from the diff.

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
   Use the cached set for all path-only rules (build files, CI/release config,
   cross-module span).
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
- **Cross-module threshold**: `git diff --name-only` spans ≥ 3 top-level module
  directories discovered from `settings.gradle*` / `package.json` workspaces /
  `Cargo.toml` `[workspace]` members.

If the heuristic is ambiguous, default to **not** spawning `architecture-expert` — a false
negative is safer than a false positive (the skill exists to catch high-risk changes, not
every diff).

When both design-review and a11y triggers fire, combine into one `ux-expert` invocation
with mode `both`. When no trigger fires, acceptance runs the base plan only — preserving
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
value. The Re-verification Loop uses it to decide which checks to re-run (see
[`references/re-verification.md`](references/re-verification.md)). Bash-only checks (build
smoke) record the same hash because their input is the same diff. Checks whose verdict
does not depend on the diff at all may write `diff_hash: null` — the Re-verification Loop
never skips such a check purely on hash match.

File naming is **one file per `check` value**: `swarm-report/<slug>-acceptance-<check>.md`
(e.g. `-manual.md`, `-code.md`, `-design.md`, `-a11y.md`). When a single agent invocation
covers multiple concerns (see `ux-expert` in subcheck-prompts.md), it writes separate
files per concern to keep the one-file-per-check invariant intact.

`severity`, `confidence`, `domain_relevance` are required when `verdict` is `WARN` or
`FAIL`; null for `PASS` / `SKIPPED`. These drive the PoLL aggregation in Step 4.

### Per-agent prompt contracts

Prompt contents, output paths, and verdict rules for every sub-check —
`manual-tester` (3.1), `code-reviewer` (3.2), build smoke (3.3), `business-analyst` (3.4),
`ux-expert` (3.5), `security-expert` (3.6), `performance-expert` (3.7),
`architecture-expert` (3.8), `build-engineer` (3.9), `devops-expert` (3.10) — live in
[`references/subcheck-prompts.md`](references/subcheck-prompts.md).

---

## Step 4: Aggregate and Write Receipt

Apply the PoLL rules and the Aggregated Status table in
[`references/aggregation.md`](references/aggregation.md) — same protocol as
`multiexpert-review` but with per-check input shape. Read frontmatter of each per-check
artifact first; read the body only if `verdict != PASS`. Missing per-check artifact →
treat as `verdict: FAIL` with `blocked_on: per-check artifact missing`; never silently
drop.

Save the aggregated receipt at `swarm-report/<slug>-acceptance.md` using the receipt
template in [`references/aggregation.md`](references/aggregation.md) §Receipt format.
Routing for downstream orchestrators (VERIFIED / FAILED / PARTIAL branches) lives in the
same reference §Routing.

---

## Re-verification Loop

On fix-loop re-entry (after `FAILED` → `implement` fix → re-run acceptance), compute
`diff_hash_new` and decide which checks to re-run vs reuse, per the decision table in
[`references/re-verification.md`](references/re-verification.md). Spec and test-plan
change overrides (`spec_hash` / `test_plan_hash` mismatch forces `business-analyst` /
`manual-tester`) and back-compat rules are documented there.

Aggregate into a fresh receipt, overwriting the previous one. Repeat until VERIFIED or
the user decides to ship as-is.

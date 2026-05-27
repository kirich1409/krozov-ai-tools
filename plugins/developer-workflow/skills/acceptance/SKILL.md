---
name: acceptance
description: >
  Verify an implementation against its spec (feature) or confirm a bug no longer reproduces
  (bug fix). Fans out parallel checks and aggregates verdicts into one receipt.
  Triggers: "test this", "verify against spec",
  "QA the implementation", "run the test plan", "validate acceptance criteria",
  "verify the PR", "verify the fix", "confirm bug is gone", "acceptance",
  "verify this", "test this".
---

# Acceptance

Choreographer skill. Detects project type, confirms a verification source exists, fans out parallel checks to specialized agents, aggregates verdicts into one receipt. Acceptance executes a pre-existing verification contract — it does not invent checks. No contract → halt and propose the correct upstream skill.

Procedural detail lives in reference files loaded only when the corresponding phase runs. SKILL.md stays the stable orchestration contract.

| File | Covers |
|---|---|
| [`references/source-branches.md`](references/source-branches.md) | Step 1 spec frontmatter handling and the four `test_plan_source` branches (receipt / mounted / on-the-fly / absent), mount-receipt overrides |
| [`references/subcheck-prompts.md`](references/subcheck-prompts.md) | Step 3.1–3.10 per-agent prompt contracts — `manual-tester`, `code-reviewer`, build smoke, `business-analyst`, `ux-expert`, `security-expert`, `performance-expert`, `architecture-expert`, `build-engineer`, `devops-expert` |
| [`references/aggregation.md`](references/aggregation.md) | Step 4 PoLL aggregation rules, Aggregated Status table, full receipt template, downstream routing |
| [`references/re-verification.md`](references/re-verification.md) | Re-verification Loop `diff_hash` decision table, spec/test-plan change overrides, back-compat rules |

---

## Vocabulary

Canonical values used throughout this skill. `create-pr` and any downstream consumer read these from the receipt.

- **`project_type`** — one of: `android`, `ios`, `web`, `desktop`, `backend-jvm`,
  `backend-node`, `cli`, `library`, `generic`.
- **`has_ui_surface`** — boolean derived from `project_type`. True for `android`, `ios`,
  `web`, `desktop`. False otherwise (`generic` → ask user).
- **`ecosystem`** — build stack: `gradle`, `node`, `rust`, `go`, `python`, `xcode`. Used
  for build-smoke command selection only; orthogonal to `project_type`.
- **Per-check verdict** — each sub-check reports `PASS | WARN | FAIL | SKIPPED`, plus
  `severity` (`critical | major | minor`), `confidence` (`high | medium | low`), and
  `domain_relevance` (`high | medium | low`) for aggregation.
- **Bug severity** — `P0 | P1 | P2 | P3`. Unchanged from prior receipt schema.
- **Aggregated Status** — `VERIFIED | FAILED | PARTIAL`. Derived; table in
  `references/aggregation.md` §Aggregated Status.

---

## Step 0: Detect Project Type

Detect from build files, manifests, and source layout: Android (`AndroidManifest.xml`, `build.gradle*` with `com.android.application`), iOS (`*.xcodeproj`, `Package.swift` with iOS targets, `Info.plist`), web (`package.json` with browser-targeted framework), desktop (Compose Desktop, Tauri, Electron), backend (Spring/Ktor/Express without UI), CLI / library (no UI surface). When ambiguous, ask the user. Output: `project_type`, `has_ui_surface`, `ecosystem`.

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

**Instrumentation verification.** When the test plan ends with a `## Non-functional /
Instrumentation` section that exists and is not `N/A: <reason>` (Log events / Metrics /
Traces / Alerts / Dashboards — see [`generate-test-plan` Field Definitions](../generate-test-plan/SKILL.md#non-functional--instrumentation-mandatory-for-user-facing--prod-bound)),
acceptance verifies, against the running app, that each declared event / metric / span
fires when its tested behavior runs. Mismatch (declared but not emitted, or emitted with
wrong fields) becomes a P1 acceptance finding routed through the standard FAILED → Implement
loop. An explicit `N/A: <reason>` in the test-plan section skips this check.

---

## Step 1.5: Source-Missing Gate

Fires only on `test_plan_source: absent`.

| Situation | Proposal |
|---|---|
| No spec, no test plan (feature) | Run `/write-spec` (requirements) or `/generate-test-plan` (tests only), then re-run. |
| Spec without AC, no test plan, UI project | Run `/generate-test-plan` for executable TCs, or add AC to the spec. |
| Bugfix without reproduction notes | Capture root cause + reproduction in `swarm-report/<slug>-debug.md` (plan-mode investigation), then re-run. |
| Only `design.figma` in spec, no test plan, UI project | Design-only review via `ux-expert`; for functional acceptance also run `/generate-test-plan`. |

Options: (1) create the missing source via the proposed upstream skill, then re-run; (2) abort without a receipt.

Exploratory QA without a scenario is performed by calling the `manual-tester` agent directly (see § Step 4b in `agents/manual-tester.md`) — never offered as a fallback inside acceptance.

After a structured upstream step (`write-spec`, `generate-test-plan`, captured `debug.md`) this gate rarely fires; standalone invocations are the main case.

---

## Step 2: Persist E2E Scenario

Only relevant when `has_ui_surface == true` and a scenario source exists (test plan, spec with AC, or `debug.md`). `manual-tester` enforces re-anchoring against this file; acceptance writes it here and re-reads during aggregation. Running-app environment (device, simulator, emulator, browser) is **owned by `manual-tester`** (its Step 0); this skill does not probe devices, run installs, or start dev servers.

Save to `swarm-report/<slug>-e2e-scenario.md` using the canonical template in `~/.claude/CLAUDE.md` § Context compaction resilience (E2E Scenario file). Add fields `Project type: <project_type>` and `Spec source: <what was used>` at the head.

Bug-fix-specific rule: steps come from `debug.md` reproduction inverted — "Step X triggers the bug" → "Step X no longer triggers the bug".

---

## Step 2.5: Dedup Probe

Read `swarm-report/<slug>-quality.md` (an upstream code-quality receipt that lets follow-up acceptance dedup work). Three cases:

- **`Status: PASS`**, receipt from current branch head → skip `code-reviewer`. Freshness inferred from receipt `Date:` vs the branch commit window; if unconfirmable, do **not** skip. On skip, write a stub at `swarm-report/<slug>-acceptance-code.md` with `verdict: SKIPPED`, `blocked_on: null`, one-line body referencing `<slug>-quality.md`.
- **`Status: FAIL`** → upstream quality loop failed. Run `code-reviewer` anyway; surface `blocked_on: quality-loop failed — see <slug>-quality.md` in Step 4 Summary. Aggregated Status is forced to `PARTIAL` minimum (or `FAILED` if `code-reviewer` itself returns FAIL).
- **Receipt missing** → run `code-reviewer` normally.

Decoupled from the Re-verification Loop `diff_hash` policy ([`references/re-verification.md`](references/re-verification.md)): dedup here is "upstream already ran code-review on this diff"; `diff_hash` idempotency is "previous acceptance run covered this same diff".

Synchronous probe — decides Step 3 fan-out composition and emits the stub before fan-out.

---

## Step 2.6: Persist Fan-out State

Save fan-out plan and compaction-resilient progress to `swarm-report/<slug>-acceptance-state.md` — operational state, never a receipt. Step ordering: 2.5 dedup probe → Step 3 intro resolves conditional triggers → write state file with complete `Planned Checks` → Step 3 body dispatches the fan-out.

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

## Completed Checks
- [x] code — swarm-report/<slug>-acceptance-code.md — PASS

## Aggregated Verdict History
### Cycle 1
Verdict: FAILED
Blockers: <copy from aggregated receipt>
```

**Rules:**

1. Populate only after the full check plan is finalized (base + all conditional triggers, spec- and diff-driven), before any agent batch spawns.
2. Re-read before each major action (spawn batch, aggregate, write final receipt). Completed `[x]` checks are not re-spawned on resume after compaction.
3. Mark each check `[x]` with artifact path and verdict as soon as the per-check file is written.
4. On Re-verification Loop re-entry ([`references/re-verification.md`](references/re-verification.md)): increment `Cycle`, reset `Planned Checks` using new hashes, move skipped checks to a `## Re-used from previous cycle` section with artifact pointers, append new `Aggregated Verdict History` entry on cycle completion.
5. `Status: done` makes the file read-only operational history (not deleted automatically).

The state file and `<slug>-e2e-scenario.md` are independent — the latter is `manual-tester`'s internal re-anchor; the state file is acceptance's own fan-out cursor.

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

**Diff-based trigger detection.** Two cached passes:

1. **Path pass** — `git diff --name-only <base>...HEAD` once, cache the path set; used for all path-only rules (build files, CI/release config, cross-module span).
2. **Content pass (on demand)** — when `architecture-expert` needs to decide "diff touches a public API symbol", read the diff body once via `git diff --unified=0 <base>...HEAD -- <cached-paths>` and cache for the whole run.

Both caches live for the duration of the acceptance run — never re-probe per agent.

**Public API detection heuristic** for `architecture-expert`:
- **Kotlin/Java**: changes under `src/main/` that add/remove/rename `public` / `open` symbols, or touch module-level files (`settings.gradle*`, `Module.kt`, `Dependencies.kt`).
- **TypeScript/JavaScript**: changes to `export` / re-export lines, `index.ts` public entrypoints, or `package.json` `"exports"`.
- **Swift**: `public` / `open` declarations or `Package.swift` `products` / `targets`.
- **HTTP/RPC**: files matching `**/routes/**`, `**/controllers/**`, `**/handlers/**`, `**/api/**`, `*.proto`, `*.graphql`, `openapi.yaml`.
- **Cross-module threshold**: `git diff --name-only` spans ≥ 3 top-level module directories from `settings.gradle*` / `package.json` workspaces / `Cargo.toml` `[workspace]`.

Ambiguous heuristic → default to **not** spawning `architecture-expert` (false negative is safer than false positive).

Both design-review and a11y triggers firing → combine into one `ux-expert` invocation with mode `both`. No trigger fires → base plan only (backward compatible with pre-iteration-2 specs).

**Future iterations** add `visual-check` as a separate sibling skill (not a fan-out member) for pixel-level regression.

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

**`diff_hash` semantics.** Computed once per run from `git diff <base>...HEAD | sha256sum`; every check records the same value. Used by Re-verification Loop ([`references/re-verification.md`](references/re-verification.md)) to decide which checks to re-run. Bash-only checks (build smoke) record the same hash. Checks whose verdict does not depend on the diff may write `diff_hash: null` — Re-verification Loop never skips them purely on hash match.

**File naming.** One file per `check` value: `swarm-report/<slug>-acceptance-<check>.md`. A single agent covering multiple concerns (e.g. `ux-expert`) writes separate files per concern.

`severity`, `confidence`, `domain_relevance` are required when `verdict` is `WARN` or `FAIL`; null for `PASS` / `SKIPPED`. These drive the PoLL aggregation in Step 4.

### Per-agent prompt contracts

Prompt contents, output paths, and verdict rules for every sub-check (3.1 `manual-tester`, 3.2 `code-reviewer`, 3.3 build smoke, 3.4 `business-analyst`, 3.5 `ux-expert`, 3.6 `security-expert`, 3.7 `performance-expert`, 3.8 `architecture-expert`, 3.9 `build-engineer`, 3.10 `devops-expert`) live in [`references/subcheck-prompts.md`](references/subcheck-prompts.md).

---

## Step 4: Aggregate and Write Receipt

Apply PoLL rules and the Aggregated Status table from [`references/aggregation.md`](references/aggregation.md) — same protocol as `multiexpert-review`, per-check input shape. Read frontmatter of each per-check artifact first; body only when `verdict != PASS`. Missing per-check artifact → `verdict: FAIL` with `blocked_on: per-check artifact missing`; never silently drop.

Save aggregated receipt at `swarm-report/<slug>-acceptance.md` using the template in `references/aggregation.md` §Receipt format. Downstream routing (VERIFIED / FAILED / PARTIAL) lives in the same reference §Routing.

Post a chat summary after saving the receipt (≤20 lines):

**VERIFIED:** "Acceptance: VERIFIED. N checks passed." Bullets (max 3): which checks ran, any skipped and why. Next step: `/create-pr` (or `/drive-to-merge` if PR exists).

**FAILED:** "Acceptance: FAILED. N check(s) failed." Bullets (max 5): one failure per bullet with check name + one-line description. ONE question: fix and re-run, or ship as-is accepting risk.

**PARTIAL:** "Acceptance: PARTIAL. N passed, M inconclusive." Bullets: inconclusive checks and why. ONE question: proceed to PR or re-run inconclusive?

Never paste receipt tables into chat — the file is the audit trail.

---

## Re-verification Loop

On fix-loop re-entry (after `FAILED` → fix on the branch → re-run acceptance), compute
`diff_hash_new` and decide which checks to re-run vs reuse, per the decision table in
[`references/re-verification.md`](references/re-verification.md). Spec and test-plan
change overrides (`spec_hash` / `test_plan_hash` mismatch forces `business-analyst` /
`manual-tester`) and back-compat rules are documented there.

Aggregate into a fresh receipt, overwriting the previous one. Repeat until VERIFIED or
the user decides to ship as-is.

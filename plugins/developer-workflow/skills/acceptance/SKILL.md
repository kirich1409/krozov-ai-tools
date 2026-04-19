---
name: acceptance
description: >
  This skill should be used when the user asks to "test this", "verify against spec",
  "QA the implementation", "run the test plan", "validate acceptance criteria",
  "verify the PR", "verify the fix", "confirm bug is gone", or says "acceptance",
  "приёмка", "проверь", "протестируй". Orchestrates acceptance verification — confirms an
  implementation meets its spec (feature) or that a reported bug no longer reproduces
  (bug fix). Detects project type, verifies a source exists (spec AC, test plan, or
  `debug.md`), fans out parallel checks to `manual-tester`, `code-reviewer`,
  `business-analyst`, `ux-expert`, `security-expert`, `performance-expert`,
  `architecture-expert`, `build-engineer`, `devops-expert`, plus a build smoke — triggered
  by spec frontmatter and diff — then aggregates via PoLL rules. When no verification
  source is available, halts and proposes `/write-spec`, `/generate-test-plan`, or
  `/debug`.
disable-model-invocation: true
---

# Acceptance

Choreographer skill. Detect project type, confirm a verification source exists, fan out
parallel checks to specialized agents, aggregate verdicts into one receipt. Acceptance
executes a pre-existing verification contract — it does not invent checks. When no
contract is available, halt and propose the correct upstream skill.

## Vocabulary

Canonical values used throughout the skill. Downstream consumers (feature-flow,
bugfix-flow, create-pr) read these from the receipt.

- **`project_type`** — one of: `android`, `ios`, `web`, `desktop`, `backend-jvm`,
  `backend-node`, `cli`, `library`, `generic`. Source of truth: `ORCHESTRATION.md`
  §Project type detection.
- **`has_ui_surface`** — boolean derived from `project_type`. True for `android`, `ios`,
  `web`, `desktop`. False otherwise (`generic` → ask user).
- **`ecosystem`** — build stack: `gradle`, `node`, `rust`, `go`, `python`, `xcode`. Used
  for build-smoke command selection only; orthogonal to `project_type`.
- **Per-check verdict** — each sub-check reports `PASS | WARN | FAIL | SKIPPED`, plus
  `severity` (`critical | major | minor`), `confidence` (`high | medium | low`), and
  `domain_relevance` (`high | medium | low`) for aggregation.
- **Bug severity** — `P0 | P1 | P2 | P3`. Primary routing axis for
  `feature-flow` / `bugfix-flow`.
- **Aggregated Status** — `VERIFIED | FAILED | PARTIAL`. Derived; see aggregation below.

## Step 0: Detect project type

Follow the canonical heuristic in `plugins/developer-workflow/docs/ORCHESTRATION.md`
§Project type detection. Output: `project_type`, `has_ui_surface`, `ecosystem`.

**Override policy.** If the spec frontmatter `platform:` list is non-empty, **spec wins** —
take the first platform value as the canonical `project_type`. If the list has more than
one entry, record the full list separately as `platforms: [...]` in the receipt; do not
invent a `multi-platform` `project_type`. Record `project_type_override: spec` in the
receipt. If the user corrects detection mid-run, record `project_type_override: user`.

Step 0 file reads and Step 1 file reads are disjoint. Both sets may be issued in one
batched Read call set to avoid serial round-trips.

## Step 1: Gather inputs

Acceptance requires at least one verification source. Before branching, probe in one
batched Read call set (each may error-as-absent):

- `swarm-report/<slug>-test-plan.md` (receipt)
- `docs/testplans/<slug>-test-plan.md` (permanent)
- `swarm-report/<slug>-debug.md` (bug-fix reproduction steps)

Combined with inline inputs and spec sources, one of four branches fires — record the
selected branch as `test_plan_source` in the receipt:

- **`receipt`** — receipt file present; read its frontmatter, interpret `review_verdict`,
  pass the permanent file to `manual-tester`.
- **`mounted`** — permanent file present without a matching receipt; emit a mount-receipt.
- **`on-the-fly`** — inline test plan, spec, or both; execute as-is, cross-reference, or
  generate a TC list from the spec.
- **`absent`** — no verification source at all; proceed to Step 1.5.

Full branch conditions, the spec-frontmatter reading (`platform`, `surfaces`,
`risk_areas`, `non_functional`, `acceptance_criteria_ids`, `design.figma`), and the
Step 1.5 source-missing proposal table — see **`references/step1-sources.md`**.

## Step 2: Persist E2E scenario

**Only relevant if `has_ui_surface == true` and a scenario source exists** (test plan,
spec with AC, or debug.md). Re-anchoring against this file is enforced by `manual-tester`
— acceptance writes it once here; re-reads during aggregation only.

The running-app environment (device, simulator, emulator, browser) is **owned by
`manual-tester` itself** — see its Step 0 Environment Setup. Do not probe devices, run
`gradlew installDebug`, or start dev servers; delegate that responsibility wholesale to
the agent.

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

## Step 2.5: Dedup probe

Read `swarm-report/<slug>-quality.md` (produced by `implement`'s Quality Loop). Three
cases:

- **`Status: PASS`, receipt is from the current branch head** — `code-reviewer` is
  skipped. Freshness is inferred from the receipt's `Date:` field vs the branch commit
  window; if freshness cannot be confirmed (e.g. receipt significantly older than the
  latest commit), do **not** skip — run `code-reviewer` normally. On skip, write a stub
  artifact at `swarm-report/<slug>-acceptance-code.md` with `verdict: SKIPPED`,
  `blocked_on: null`, and a one-line body referencing `<slug>-quality.md`.
- **`Status: FAIL`** — Quality Loop failed upstream; do not silently proceed. Run
  `code-reviewer` anyway, and surface
  `blocked_on: quality-loop failed — see <slug>-quality.md` in the Step 4 Summary. The
  aggregated Status is forced to `PARTIAL` at minimum (or `FAILED` if `code-reviewer`
  itself returns `FAIL`).
- **Receipt missing** — run `code-reviewer` normally. No skip.

Field name matches `implement`'s receipt schema. `code-reviewer` skipping here is
decoupled from the Re-verification Loop's `diff_hash` policy — the dedup here is about
"implement already ran code-review on this diff", whereas `diff_hash` idempotency is about
"previous acceptance run covered this same diff".

This probe is synchronous — it decides the Step 3 fan-out composition and emits the stub
before fan-out.

## Step 2.6: Persist fan-out state

Before issuing the Step 3 fan-out — but **after** the full check plan has been finalized
(base fan-out + all conditional triggers) — save the plan and compaction-resilient
progress to `swarm-report/<slug>-acceptance-state.md`. This file carries the acceptance
run across context compaction; it is never a receipt, just operational state.

Step ordering: 2.5 dedup probe → Step 3 intro resolves conditional triggers → write the
state file here with the complete `Planned Checks` list → Step 3 body dispatches the
fan-out.

Before each major action (spawning an agent batch, aggregating, writing the final
receipt) — **re-read** the state file via Read tool. Completed checks (`[x]`) are not
re-spawned on resume after compaction.

Full state-file schema and rules — see **`references/state-file.md`**.

## Step 3: Run checks (parallel fan-out)

Pick the check plan by `has_ui_surface` plus conditional triggers read from spec
frontmatter and from the diff. Emit **one** message containing all tool calls
simultaneously (Agent calls + Bash smoke). Do not wait for any to return before
dispatching the others.

### Base check plan

| `has_ui_surface` | Base fan-out |
|---|---|
| `true` | `manual-tester` + `code-reviewer` (unless skipped by Step 2.5) |
| `false` | `code-reviewer` (unless skipped by Step 2.5) + build smoke (Bash) |

### Conditional trigger summary

| Trigger source | Agent |
|---|---|
| spec `acceptance_criteria_ids` non-empty | `business-analyst` — AC coverage |
| spec `design.figma` (UI project) | `ux-expert` — design-review |
| spec `non_functional.a11y` (UI project) | `ux-expert` — a11y |
| spec `risk_areas` ∩ `{auth, payment, pii, data-migration}` | `security-expert` |
| spec `non_functional.sla`, or `risk_areas` has `perf-critical` | `performance-expert` |
| diff touches public API **or** spans ≥ 3 top-level modules | `architecture-expert` |
| diff touches any build file | `build-engineer` |
| diff touches CI / release config | `devops-expert` |

When no trigger fires, acceptance runs the base plan only. When both design-review and
a11y triggers fire, spawn `ux-expert` once with mode `both` (writes two artifacts).

Full trigger table, diff-based detection (two cached passes), and public-API heuristics
per language — see **`references/conditional-triggers.md`**. Full per-agent prompt
contents and verdict rules for every sub-check (3.1–3.10) — see
**`references/check-prompts.md`**.

### Per-check artifact schema

Each sub-check writes `swarm-report/<slug>-acceptance-<check>.md` with a YAML frontmatter
that captures `check`, `agent`, `verdict`, `severity`, `confidence`, `domain_relevance`,
`diff_hash`, and optional `blocked_on`. File naming is one file per `check` value.

Full schema, `diff_hash` semantics, and check-identifier conventions (including the
`build` vs `build-config` split) — see **`references/per-check-schema.md`**.

## Step 4: Aggregate and write receipt

Read the frontmatter of each `swarm-report/<slug>-acceptance-<check>.md` first (verdict +
severity + confidence + domain_relevance + blocked_on). Read the body only if
`verdict != PASS`. Do not inline artifact bodies — link them.

If a planned per-check artifact is missing at aggregation time, treat the check as
`verdict: FAIL` with `blocked_on: per-check artifact missing`. Do not silently drop it.

Aggregation uses the same PoLL protocol as `multiexpert-review` (see
`multiexpert-review/SKILL.md` §"Step 4 — Synthesize verdict"). Input shape is per-check
(not per-reviewer), reduction logic identical. Any P0/P1 bug from any sub-check maps
directly to `FAILED` regardless of PoLL.

### Aggregated Status — summary

| Input | Aggregated Status |
|---|---|
| All checks `PASS` or `SKIPPED`, no P0–P3 bugs, no PoLL blocker | `VERIFIED` |
| Any P0 / P1 bug **or** PoLL blocker | `FAILED` |
| P2 / P3 bugs only, PoLL important, contradicting verdicts, or unclassified `WARN` | `PARTIAL` |
| `manual-tester` returned `WARN` with `blocked_on` | `PARTIAL` with `blocked_on` surfaced |

Save the aggregated receipt to `swarm-report/<slug>-acceptance.md`.

Full PoLL rules table, receipt-markdown template, and routing rules consumed by
orchestrators (`VERIFIED` → `create-pr`, `FAILED` → `implement`/`debug`/`test-plan`,
`PARTIAL` policy) — see **`references/aggregation.md`**.

## Re-verification Loop

On fix-loop re-entry (after `FAILED` → `implement` fix → re-run acceptance):

1. Re-probe Step 0 and Step 1.
2. Compute `diff_hash_new` = `sha256(git diff <base>...HEAD)`.
3. Decide per-check action by comparing `diff_hash` and the previous verdict:
   - `PASS` / `SKIPPED` with matching hash → skip, reuse the artifact.
   - `WARN` with matching hash → skip; re-used verdict keeps the WARN.
   - `FAIL` → always re-run.
   - Mismatch, missing, or `null` hash → re-run.
4. For re-run checks, overwrite the per-check artifact with fresh content and a new
   `diff_hash`. `manual-tester` re-runs previously-failed TCs plus a Smoke tier by default.
5. Aggregate into a fresh `swarm-report/<slug>-acceptance.md`, overwriting the previous.
6. Repeat until VERIFIED or the user decides to ship as-is.

If the spec file or test-plan file changed between runs (compare `spec_hash` /
`test_plan_hash` to values in the previous aggregated receipt), `business-analyst` and
`manual-tester` are always re-run regardless of `diff_hash`.

Full decision table, back-compat rule for pre-iteration-3 receipts, and cost-saving notes
— see **`references/re-verification-loop.md`**.

## Reference files

- **`references/step1-sources.md`** — full Step 1 branch conditions (receipt / mounted /
  on-the-fly / absent) and Step 1.5 source-missing proposal table.
- **`references/state-file.md`** — Step 2.6 fan-out state file schema and rules.
- **`references/conditional-triggers.md`** — full trigger table, diff-based detection,
  public-API heuristics per language.
- **`references/per-check-schema.md`** — per-check artifact YAML frontmatter and
  `diff_hash` semantics.
- **`references/check-prompts.md`** — per-agent prompts and verdict rules for sub-checks
  3.1–3.10.
- **`references/aggregation.md`** — PoLL rules, aggregated-status final table, receipt
  markdown template, orchestrator routing rules.
- **`references/re-verification-loop.md`** — full loop decision table, spec/test-plan
  change override, back-compat rule.

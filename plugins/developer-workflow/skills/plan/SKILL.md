---
name: plan
description: "Produce a committed implementation plan document — the autonomous replacement for built-in plan mode. Investigates the codebase read-only, writes a reviewable plan (docs/plans/<slug>/plan.md + tasks.md) instead of an ephemeral approval prompt, then runs a MANDATORY multiexpert-review loop over the plan and revises until it passes. The plan is transient: kept through implementation and review, removed after merge. No approval pause by default, so an agent can plan and execute end-to-end; opt into a checkpoint with --interactive. Use when: \"plan this\", \"make a plan\", \"how do I build this\", \"plan the implementation\", \"break this into tasks\", \"plan before coding\" for an ALREADY-DECIDED change. Prefer this over built-in plan mode whenever the plan should be saved, reviewed by experts, or executed autonomously. Do NOT use for: deciding WHAT to build or comparing options (use research), writing the feature contract / acceptance criteria (use write-spec), or trivial single-line edits (just do them)."
---

# Plan

Turn an already-decided change into an **expert-reviewed implementation plan** that an
agent can execute end-to-end without stopping for approval. This is the autonomous replacement for
built-in plan mode: the plan is a file on disk (not an ephemeral `ExitPlanMode` prompt), so it can
be reviewed by a multiexpert panel, diffed in the PR, referenced by `create-pr` / `finalize`, and
resumed across sessions while the work is in progress. The plan is **transient implementation
scaffolding**: it lives in `docs/plans/<slug>/` throughout implementation and PR review, then
`drive-to-merge` deletes it after the change merges (and it should not survive an abandoned or
rejected change either). The contrast with built-in plan mode is the *file*, not its permanence —
an ephemeral approval prompt can be neither reviewed nor resumed.

**Role:** Tech Lead translating *what* into *how*. The decision is made (by the user, a spec, or
prior research); this skill produces the technical approach, the ordered task list, and the
per-task acceptance that makes autonomous execution safe.

**Where it sits:** `write-spec` answers *what* we build (requirements + acceptance criteria). `plan`
answers *how* (design + ordered tasks). If a spec exists, the plan **references** it and never
duplicates its requirements. If no spec exists (smaller change), the plan works directly from the
task description.

**Core principles:**

1. **The plan is a document, not a prompt.** Persist it before anything else needs it. Ephemeral
   plans cannot be reviewed, diffed, or resumed — that is the limitation this skill removes.
2. **Review replaces approval.** The quality gate is a mandatory multiexpert-review loop, not a
   human pause. The default flow is autonomous; a human checkpoint is opt-in (`--interactive`).
3. **Every task has a verifiable done-condition.** Tasks carry explicit acceptance (Given/When/Then
   or "THE SYSTEM SHALL …"). Autonomy is only safe when "done" is checkable, not approved.

### Headless mode (the autonomy contract)

`AskUserQuestion` is used **only** when `--interactive` was passed or a user is actively present.
In a headless / non-interactive run, never block on it: surface a genuine design fork to the caller
instead. Before the plan file exists (Phase 1), surface it as a blocking hand-off; after the plan
exists, record it as a `[blocking]` Open Question, set `review_verdict: escalate`, and stop. This
single rule governs every later phase — phases below reference it rather than restating it.

---

## Flags

| Flag | Effect |
|---|---|
| (default) | Autonomous. Investigate → write plan → mandatory review loop → on PASS/CONDITIONAL, hand off to implementation with no human pause. |
| `--interactive` | Add ONE human confirmation checkpoint after the review passes (Phase 4.2). The explicit, opt-in replacement for the `ExitPlanMode` gate. |
| `--quick` | Trivial, well-bounded change: lighter investigation, single-reviewer review (`allow_single_reviewer`). Review is never skipped entirely — a plan without review is the failure mode this skill exists to prevent. |
| `--from-spec <path>` | Anchor the plan to a specific spec instead of auto-discovering one. |

---

## Phase 0: Parse Input & Setup

### 0.1 Separate decision from design

The *what* is assumed decided. Extract:

- **The decided change** — what we are building (from the request, a spec, or research).
- **Source of truth** — auto-discover a spec: newest `docs/specs/*-<slug>.md` whose slug or title
  matches the candidate slug. If `--from-spec <path>` was passed, use that path directly and skip
  auto-discovery (verify the path exists; if not, stop and report). Record the path; the plan
  references it, never restates its AC. The slug is always the branch/task-derived candidate — do
  not parse a slug out of the `--from-spec` filename.
- **Known constraints** — platform, libraries, "no new deps", deadlines.

If the request is actually *undecided* ("should we use X or Y?", "is this feasible?"), STOP and
redirect to `research`. If it is a feature contract that has not been written ("what exactly are the
requirements?"), redirect to `write-spec`. This skill plans execution; it does not decide scope.

Generate a kebab-case slug (`offline-mode`, `push-notifications`). Strip common branch prefixes
(`feature/`, `fix/`, `chore/`, `claude/`, `hotfix/`). This candidate slug is used consistently
for all output paths (`docs/plans/<slug>/`). If a spec exists under `docs/specs/` whose slug or
title matches the candidate slug, reference it — but do not change the slug; plan, create-pr, and
finalize all resolve the same `docs/plans/<slug>/` path.

### 0.2 Artifacts

Three committed files under `docs/plans/<slug>/` (`plan.md`, `tasks.md`, `progress.md`) plus the
gitignored operational `./swarm-report/plan-<slug>-state.md` (deleted after). `docs/plans/` is
deliberately alongside `docs/specs/` (spec = *what*, plan = *how*), but their lifetimes differ: the
spec is permanent, the plan is transient. Plans live in git only *while the work is in progress* —
their value is being reviewable in the PR diff and resumable across sessions during implementation —
and `drive-to-merge` deletes `docs/plans/<slug>/` after the change merges. See
[`references/output-layout.md`](references/output-layout.md) for the full file/lifetime/purpose
table.

---

## Phase 1: Investigate (read-only)

Like plan mode, planning starts with read-only investigation — but the findings are persisted, not
discarded. Launch investigation **in a single message** (parallel) sized to the change:

- **Codebase (Explore)** — always. Existing code, patterns, module boundaries, the exact files and
  symbols this change touches, test infrastructure, related TODOs.
- **Architecture Expert** — when the change adds a module, shifts dependency direction, introduces
  an abstraction, or crosses layers.
- **Web / docs** — only for unfamiliar external APIs, protocols, or non-trivial algorithms the
  codebase doesn't already demonstrate.

Write findings into `./swarm-report/plan-<slug>-state.md` as agents complete. Do not ask the user
anything that investigation can answer. If a genuine design fork appears that investigation cannot
resolve, surface it with `AskUserQuestion` (each option with a recommended pick) — never park
questions in the plan file. The plan file does not exist yet at this phase, so per the **Headless
mode** contract above, a headless run surfaces the blocking fork to the caller (nothing to record
in-file).

`--quick`: skip the consortium; one inline Explore pass is enough.

---

## Phase 2: Write the Plan

Write `plan.md` and `tasks.md` for a reader who is an implementing agent with zero extra context.
Every decision is explicit with rationale; every task has a checkable done-condition.

Copy the templates from [`references/plan-template.md`](references/plan-template.md) verbatim and
fill every placeholder. Shape:

- **`plan.md`** — YAML frontmatter (`type: plan`, `slug`, `date`, `status: draft`, `spec:` link or
  `none`, `risk_areas`, `review_verdict: pending`) + body: Context & Decision, Technical Approach,
  Affected Modules & Files (table: path · change type · note), Decisions Made (with rationale),
  Risks & Mitigations, Out of Scope, Open Questions (tagged blocking / non-blocking).
- **`tasks.md`** — ordered list `T-N`, each with: short title, dependencies (`after: T-…`), the
  files it touches, and **acceptance** in Given/When/Then or "THE SYSTEM SHALL …" form, plus the
  check that proves it (test name, grep, build target). Tasks are small enough to implement and
  verify in one focused pass.
- **`progress.md`** — initialize with every `T-N` as an unchecked box and an empty Learnings log.

The plan must reference, not restate, the spec's acceptance criteria (cite `AC-N` ids); `tasks.md`
acceptance is the *implementation-level* check that each AC is met.

---

## Phase 3: Mandatory Review Loop

The review is the gate that replaces human approval. It is **not optional** (this is the whole
point — an unreviewed plan is low quality and must be sent back for rework until it meets the bar).

**Writer vs. skeptic.** The agent that wrote the plan (Phase 2) has an incentive to pass the gate
quickly; the critic is deliberately separate and adversarial. The reviewers act as a strict-but-fair
red team applying an anti-gaming rubric (reject hand-waving, demand `file:line` evidence, demand
checkable acceptance, hunt missing failure modes) — they look for what is *wrong*, not for reasons
to approve. See [`references/review-loop.md`](references/review-loop.md) for the writer/critic
rationale and the rubric.

This mirrors `write-spec` Phase 4.3: invoke `multiexpert-review` **inline** with an explicit profile
hint. The plan is already a file (`docs/plans/<slug>/plan.md`), so the engine classifies the source
as `file` and edits the plan in place on FAIL/CONDITIONAL.

Prepend to the review args:

```
profile: implementation-plan
---
docs/plans/<slug>/plan.md
```

(Why the hint and the full loop script: see
[`references/review-loop.md`](references/review-loop.md).)

The `implementation-plan` profile selects 2–3 reviewers by tech-match from the plan content
(e.g. `security-expert` only when the plan touches auth / tokens / user data; `architecture-expert`
only on new modules / dependency-direction / public-API changes). `--quick` permits a single
reviewer.

**Loop:** run the review loop — the cap and per-verdict actions live in
[`references/review-loop.md`](references/review-loop.md). PASS → proceed to Phase 4;
CONDITIONAL/FAIL → the engine edits the plan and re-reviews until the cap.

**Escalation (the only autonomous STOP):** if blockers remain after the cap, set `review_verdict: escalate`, write
the unresolved blockers into `## Open Questions` (tagged blocking), retire the state file (see Phase
4.3), and surface them — only for genuine blockers, never for routine polish.

---

## Phase 3.5: Adversarial Red-Team Pass

Reviewers grade against a rubric; an *implementer* discovers missing pieces — different failure
modes. After the panel passes, run **one** Agent (general-purpose, sonnet) as a hostile implementer
that tries to build from the plan and reports every gap it would hit; feeding findings back is
subject to the **Headless mode** contract above. The full agent brief and per-item handling live in
[`references/review-loop.md`](references/review-loop.md) §Phase 3.5.

Skip only with `--quick` on a small, well-bounded change with no risky tasks.

---

## Phase 4: Gate

### 4.1 Default — autonomous

On PASS/CONDITIONAL, flip `plan.md` `status` to `approved`, ensure `tasks.md` and `progress.md` are
written, retire the state file, and hand off to implementation **without pausing**. Confirm in one
sentence with the plan path and the first task. This is full autonomy: no `ExitPlanMode`, no
approval prompt.

### 4.2 `--interactive` — opt-in checkpoint

Only when `--interactive` was passed: present a compact summary (plan path, the 3–5 key decisions,
the task count, the review verdict, any non-blocking open questions) and ask for a single go / adjust
confirmation before flipping to `approved`. This is the deliberate, user-requested replacement for
the plan-mode approval gate — present only, never the default.

### 4.3 Escalate

On `review_verdict: escalate`, do not flip to `approved`. Retire (delete) the state file
`./swarm-report/plan-<slug>-state.md`, surface the blocking open questions, and stop — exactly as
`finalize` escalates on unresolved BLOCKs.

---

## Phase 5: Hand Off

Keep `progress.md` as the live execution ledger: as each `T-N` completes, check its box and append a
one-line learning. Suggest the next step (implement the tasks; then `/write-tests`, `/check`,
`/finalize`, `/acceptance`).

See [`references/output-layout.md`](references/output-layout.md) for path conventions, the
confirmation message, gitignore notes, and the hand-off rules (do-not-auto-invoke, the toolbox model,
and the Phase 3 / Phase 3.5 built-in exceptions).

---

## Red Flags / STOP Conditions

- **Undecided scope** — the request is "which approach?" or "is this feasible?". Redirect to
  `research`; do not plan an undecided change.
- **Missing contract** — a complex feature with no acceptance criteria anywhere. Recommend
  `write-spec` first; a plan without a target is guesswork.
- **Fundamental contradiction** — a constraint makes the change impossible, or two decided
  requirements conflict. Surface it; do not invent a workaround.
- **Missing critical access** — the change needs systems / APIs / credentials not available. List
  what's needed and stop.

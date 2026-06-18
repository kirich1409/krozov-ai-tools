---
name: plan
description: "Plan-as-document implementation planning — the autonomous replacement for built-in plan mode. Investigates the codebase read-only, writes a persistent, reviewable plan (docs/plans/<slug>/plan.md + tasks.md) instead of an ephemeral approval prompt, then runs a MANDATORY multiexpert-review loop over the plan and revises until it passes. No human approval pause by default, so an agent can plan and execute end-to-end; opt into a checkpoint with --interactive. Use when: \"plan this\", \"make a plan\", \"how do I build this\", \"plan the implementation\", \"break this into tasks\", \"plan before coding\" for an ALREADY-DECIDED change. Prefer this over built-in plan mode whenever the plan should be saved, reviewed by experts, or executed autonomously. Do NOT use for: deciding WHAT to build or comparing options (use research), writing the feature contract / acceptance criteria (use write-spec), or trivial single-line edits (just do them)."
---

# Plan

Turn an already-decided change into a **persistent, expert-reviewed implementation plan** that an
agent can execute end-to-end without stopping for approval. This is the autonomous replacement for
built-in plan mode: the plan is a file on disk (not an ephemeral `ExitPlanMode` prompt), so it can
be version-controlled, reviewed by a multiexpert panel, referenced by `create-pr` / `finalize`, and
resumed across sessions.

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
  matches, or `--from-spec`. Record the path; the plan references it, never restates its AC.
- **Known constraints** — platform, libraries, "no new deps", deadlines.

If the request is actually *undecided* ("should we use X or Y?", "is this feasible?"), STOP and
redirect to `research`. If it is a feature contract that has not been written ("what exactly are the
requirements?"), redirect to `write-spec`. This skill plans execution; it does not decide scope.

Generate a kebab-case slug (`offline-mode`, `push-notifications`). Strip common branch prefixes
(`feature/`, `fix/`, `chore/`, `claude/`, `hotfix/`). If a spec exists under `docs/specs/` whose
slug or title matches the candidate slug, adopt the spec's slug for all output paths (spec slug
wins over the branch-derived one).

### 0.2 Artifacts

| File | Lifetime | Purpose |
|---|---|---|
| `docs/plans/<slug>/plan.md` | Permanent (committed) | Technical approach, affected files, decisions, risks. Reviewed in PR. |
| `docs/plans/<slug>/tasks.md` | Permanent (committed) | Ordered task checklist with dependencies + per-task acceptance. |
| `docs/plans/<slug>/progress.md` | Permanent (committed) | Volatile status + learnings log. Split from the stable plan so execution churn never rewrites the design. |
| `./swarm-report/plan-<slug>-state.md` | Operational (gitignored) | Investigation findings, review-cycle log. Deleted after. |

> Naming: `docs/plans/` is deliberately alongside `docs/specs/` (spec = *what*, plan = *how*) and
> distinct from the gitignored `swarm-report/` working area. Plans live in git because their value
> is being reviewable in the PR and resumable later.

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
questions in the plan file. **Headless / non-interactive default:** if `--interactive` was not
passed and no user is present, do NOT block on `AskUserQuestion`; instead record the fork as a
`[blocking]` Open Question, set `review_verdict: escalate`, and stop. `AskUserQuestion` is only
used when `--interactive` or a user is actively present.

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

(The hint short-circuits detection deterministically — see
[`references/review-loop.md`](references/review-loop.md) for why and for the full loop script.)

The `implementation-plan` profile selects 2–3 reviewers by tech-match from the plan content
(e.g. `security-expert` only when the plan touches auth / tokens / user data; `architecture-expert`
only on new modules / dependency-direction / public-API changes). `--quick` permits a single
reviewer.

**Loop** — 3 review cycles total: 1 initial review + up to 2 re-reviews (same cap as `finalize`):

| Verdict | Action |
|---|---|
| **PASS** | Set `review_verdict: pass`, proceed to Phase 4. |
| **CONDITIONAL** | Engine edits the plan to address majors; re-review. If still CONDITIONAL after the cap (cycle 3), set `review_verdict: conditional`, record the residual majors in `## Open Questions` (non-blocking), and proceed. |
| **FAIL** | Engine edits the plan to fix the blockers, then re-reviews. On cycle 3 returning FAIL, go directly to escalate — no further re-review. |

**Escalation:** if blockers remain after the 3rd cycle (cap), set `review_verdict: escalate`, write
the unresolved blockers into `## Open Questions` (tagged blocking), and surface them. In an
autonomous run this is the *only* stop — and only for genuine blockers, never for routine polish.

---

## Phase 3.5: Adversarial Red-Team Pass

Reviewers grade against a rubric; an *implementer* discovers missing pieces — different failure
modes. After the panel passes, run **one** Agent (general-purpose, sonnet) as a hostile implementer
ordered to build from the plan with no questions allowed: it picks the riskiest task, mentally
implements it end-to-end, and reports every detail it would have to guess, every unfalsifiable
acceptance, every hand-waving verb, and every hidden-scope task. Strict but fair — only real gaps,
no invented blockers. Feed its findings back: trivially fillable → edit inline; real design gap →
fix the plan (or `AskUserQuestion` if it needs a decision and `--interactive` / user is present;
otherwise record as `[blocking]` Open Question and escalate as in Phase 1); already-specified →
no action.

Full brief and item handling in [`references/review-loop.md`](references/review-loop.md) §Phase 3.5.
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

Keep `progress.md` as the live execution ledger: as each `T-N` completes, check its box, append a
one-line learning, and let the implementer commit plan + code together. Suggest the next step
(implement the tasks; then `/write-tests`, `/check`, `/finalize`) — do not auto-invoke downstream
skills; the user/agent drives the flow (toolbox model). The sole exception is the mandatory Phase 3
inline `multiexpert-review` call: that is the review gate built into this skill, not a downstream
chain, and must always be invoked.

See [`references/output-layout.md`](references/output-layout.md) for path conventions, the
confirmation message, gitignore notes, and hand-off rules.

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

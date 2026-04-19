---
name: design-options
description: >
  This skill should be used when the user asks to "explore design options", "show me alternatives",
  "choose between approaches", "предложи варианты архитектуры", "разные подходы", or when a task
  has high architectural risk and multiple plausible approaches exist. Generates 2-3 alternative
  architectural approaches for a single task by launching architecture-expert agents in parallel,
  each under a different style constraint (minimal / clean / pragmatic), and presents the options
  side-by-side so the user can pick one informed choice instead of committing to the first
  approach that came to mind. Optional stage between write-spec (or decompose-feature for a
  single-task feature) and multiexpert-review. Also used when feature-flow runs this as an
  opt-in stage for high-arch-risk tasks. Do NOT use for straightforward tasks, bug fixes with
  a clear fix direction, or single-file changes.
---

# Design Options

Generate and present multiple architectural approaches for a single task before the plan is locked in. Reduces rework in later stages by making the architectural decision explicit and reviewable up front, instead of committing to the first plausible design.

---

## When to run this stage

Run `design-options` when at least one of (same trigger list as `feature-flow` §1.3a):

1. **High architectural risk** — the task touches module boundaries, introduces new abstractions, or replaces a core pattern.
2. **The plan settles the "what" but leaves the "how" open** — multiple plausible approaches exist, and the plan itself does not commit to one.
3. **User explicitly asks for alternatives** — "show me a few options", "what are the alternatives", "variants", "разные подходы".

Skip for:
- Straightforward tasks with a single obvious approach
- Bug fixes where the debug artifact already names the fix direction
- Single-file changes

Do NOT trigger when the spec itself is underspecified (no clear constraints, no observable behavior). That is a write-spec problem, not a design-options problem — ask the user to re-invoke `write-spec` first (see Escalation).

If invoked from an orchestrator when none of the triggers apply → orchestrator skips this stage without user prompt.

---

## Inputs

From the caller:
- **Slug** — task slug for artifact naming
- **Spec / plan artifact path** — the document that defines "what" to build. Accepted paths: `docs/specs/<YYYY-MM-DD>-<slug>.md` (from `write-spec`), `swarm-report/<slug>-plan.md`, or `swarm-report/<slug>-decomposition.md`. At least one is required.
- **Research artifact path (optional)** — `swarm-report/<slug>-research.md` if earlier stage ran
- **Debug artifact path (optional)** — `swarm-report/<slug>-debug.md` for bug-fix contexts
- **Options count (optional)** — default 3, minimum 2, maximum 3

---

## Phase 1: Scope the architectures

Read the spec and available artifacts. Extract:
- **Core problem** — what must this design solve?
- **Fixed constraints** — performance SLA, compatibility surface, team skill, timeline, external dependencies
- **Open questions** — parts of the design that are not predetermined
- **Existing patterns** — what conventions in the codebase are precedent?

If the spec is too vague to generate meaningful alternatives (no clear constraints, no observable behavior) — escalate: ask the user to re-invoke `write-spec` with more detail.

---

## Phase 2: Generate options in parallel

Launch `architecture-expert` agents (from `developer-workflow-experts`) in parallel, one per option, each with a different **style constraint**:

| Option | Style constraint |
|---|---|
| A — Minimal | Smallest surface area. Reuse existing structure. Minimize new abstractions, new modules, new dependencies. Optimize for "do the thing without disturbing the rest of the codebase". |
| B — Clean | Ideal architecture disregarding migration cost. Accept larger refactors, new modules, or dependency restructuring if it produces a cleaner long-term shape. |
| C — Pragmatic | Follow the existing project patterns as-is; extend only the specific seam this task needs. Do not generalize, do not abstract ahead of use. When in doubt, mirror the nearest similar feature in the codebase. |

For **Options count = 2**, drop C. Picking between Minimal and Clean is a common fast-path when the user only wants the two extremes.

### Prompt template for each architect

```
Produce one architectural option for this task, under the style constraint: {Minimal|Clean|Pragmatic}.

## Task (from spec)
{spec contents or reference path}

## Context
{research / debug artifacts references}

## Your constraint
{style description — verbatim from the table above}

## What to produce
A single coherent architecture option. Include:
1. Summary (2-3 sentences): what this design is, in plain language.
2. Structural choices: which modules touched, any new modules, public API surface affected, dependency direction.
3. Key abstractions introduced or avoided (and the trade-off for doing so).
4. Integration strategy: how this fits into the existing codebase without regressions.
5. Risks and unknowns: what could go wrong, what requires validation.
6. Effort estimate: relative to the other options you do NOT see. Express as S / M / L with one-sentence justification.
7. Breaking changes: any public API, database schema, or user-observable behavior that shifts.

Do NOT propose a full implementation plan — that is multiexpert-review's job. Stay at the "architectural shape" level.

Respond in the language of the task description. Stay under 600 words — brevity is a feature.
```

Agents run in parallel. Each produces its own option.

---

## Phase 3: Assemble comparison artifact

Save `swarm-report/<slug>-design-options.md`:

Adapt the template to the actual option count (2 or 3):

```markdown
# Design Options: <slug>

**Date:** <date>
**Slug:** <slug>
**Generated by:** design-options skill
**Count:** <N> (<labels — e.g., "A / B" for 2, "A / B / C" for 3>)

## Task summary
<1-2 sentence restatement of the task, from the spec>

## Options at a glance

Build the comparison table with one column per generated option — use the real labels
and titles for this run. Rows stay the same regardless of count:

| | <Option label 1> | <Option label 2> | [<Option label 3> if count ≥ 3] |
|---|---|---|---|
| **Summary** | ... | ... | ... |
| **Touched modules** | ... | ... | ... |
| **New dependencies** | ... | ... | ... |
| **Breaking changes** | ... | ... | ... |
| **Effort** | ... | ... | ... |
| **Biggest risk** | ... | ... | ... |

## Option A — <title>
<full text from architecture-expert under this constraint>

## Option B — <title>
<full text>

[repeat for each generated option — 2 or 3 total]

## Cross-cutting observations
<convergences: if all options agree on X, state the agreement>
<contradictions: if options disagree materially, surface the disagreement explicitly>
<unknowns: what none of the options could answer>

## Recommendation (optional, non-binding)
<If a clear front-runner exists based on the stated constraints, say so with reasoning. Otherwise: "Viable options with distinct trade-offs; user decision required">
```

---

## Phase 4: Present to user

Present the comparison artifact to the user with a brief summary:

> Generated <N> options (<labels — e.g., "A Minimal / B Clean / C Pragmatic">). Saved to `swarm-report/<slug>-design-options.md`.
> Summary of trade-offs: <1-2 sentences highlighting the most consequential differences>.
> Which option do you want to proceed with?

Accepted replies: `A` / `B` / `C` (pick one), `hybrid` (combine parts), `rerun` (regenerate with different constraints), `re-research` (options surfaced missing requirements — go back to `research` stage, matches feature-flow state machine `DesignOptions → Research` transition).

Wait for the user's choice before proceeding — one question per round, alternatives listed in the line above but not broadcast as additional questions.

---

## Phase 5: Persist the chosen option

Once the user picks an option (or a hybrid is specified):

1. Write `swarm-report/<slug>-design.md` containing **only** the chosen option's full text plus a short "Chosen because: <reason>" preamble. This is the downstream-friendly artifact for stages that care about the chosen architecture (not the multi-option file).
2. Leave the `<slug>-design-options.md` artifact in place as context for later review.

### Downstream consumption — current vs. future

**Current:** `multiexpert-review` does not auto-detect or consume `<slug>-design.md`. Workaround — the orchestrator (feature-flow §1.3a) passes this path to `multiexpert-review` as an additional context input when the design-options stage ran.

**Future (TODO):** extend `multiexpert-review` to auto-detect `<slug>-design.md` and ingest it without orchestrator assistance. Tracked as a follow-up — not a blocker for this skill to be useful today.

### If the user asks for a hybrid

1. Ask the user to specify which parts from which option (one short sentence per part is fine).
2. Re-invoke `architecture-expert` with a synthesis prompt: combine the specified parts from the chosen options, flag any coherency conflicts (e.g., "Minimal's reuse strategy clashes with Clean's new module boundary"), and produce a single option text.
3. Persist to `swarm-report/<slug>-design.md` with preamble `Option: Hybrid (A+B)` — or whichever combination — and `Chosen because: <reason>`. The option label in the file makes the hybrid origin explicit for later review.
4. If the synthesis surfaces incompatibilities the user did not resolve, report them in the preamble under "Known tensions" — the hybrid still persists, but downstream reviewers see the compromise.

---

## Scope rules

- **In scope:** generating and presenting architectural alternatives; helping the user pick.
- **Out of scope:** writing the implementation plan (that is multiexpert-review's input — we produce the *design*, not the steps); writing code; updating the spec.
- **Never** pick an option for the user silently. Always present, always wait.
- **Never** generate just one option — if only one survives scoping, there is nothing to choose; skip this stage entirely.
- **Never** generate more than 4 options — beyond 4, choice fatigue dominates.

---

## Escalation

Stop and report to the user when:

- Spec is too vague to produce distinct options (all architects converge on the same answer)
- A critical constraint is under-specified (e.g., "we can't decide without knowing the performance target")
- An option requires capability the team doesn't have (new language, unfamiliar tool) — flag explicitly

---

## Integration notes

- **`feature-flow`** invokes this skill as an optional stage between `write-spec` (or `decompose-feature` for single-task features) and `multiexpert-review`. Trigger detection described under "When to run this stage" — orchestrator uses that matrix.
- **`bugfix-flow`** rarely uses this — bugfixes almost always have a single fix direction from the debug artifact. But for bugs that reveal architectural issues (e.g., "this bug is a symptom of the wrong module owning state"), a user can invoke `design-options` manually before `implement`.
- **Manual invocation** is common: `/design-options --slug foo` on an existing spec for a human decision-making session.
- **Dependencies:** only `architecture-expert` from `developer-workflow-experts` (already a hard dep). No new deps needed.

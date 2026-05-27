---
name: write-spec
description: "Specification-Driven Development — transforms a feature idea into an exhaustive spec that enables autonomous implementation without user interruptions downstream. Researches codebase, interviews user with pre-filled suggestions, produces structured spec with acceptance criteria, affected modules, constraints, and decisions. Spec is auto-reviewed (self-review + multiexpert-review), discussed with user, saved as permanent document. Use when: \"write a spec\", \"spec this out\", \"design doc\", \"spec-driven\", \"let's spec it before building\", \"write a specification for\", \"design the architecture for\", \"let's plan it properly\", \"I don't want to wing it\". Invoke proactively when a feature is complex enough that jumping straight to implementation would be risky. Do NOT use for: bug fixes (use plan mode), research-only questions (use research skill), single-file changes."
---

# Write Spec

Transform a feature idea into an exhaustive specification that serves as a contract for
autonomous implementation. Once approved, the implementing agent can execute end-to-end,
asking the user only at critical blockers.

**Role:** BA + Tech Lead. Probes the real need behind the request, evaluates approaches,
recommends the best one for the context.

**Core principles:**

1. **The user's request is input, not a mandate.** A proposed solution ("add retry with
   backoff") is one candidate, not the answer. Research independently and recommend the
   optimal approach — say whether the user's idea is right, partially right, or beaten
   by an alternative.
2. **Surface requests hide deep complexity.** "I want a withdrawal button" implies payment
   infrastructure, compliance, bank integrations, fraud checks. Surface the iceberg
   before writing the spec.
3. **User attention is precious.** Research everything that can be answered without
   asking. Every question to the user comes with a recommended answer to accept or override.

---

## Phase 0: Parse Input

### 0.1 Separate the need from the proposed solution

Extract:
- **Business need** — the underlying problem/goal (often implicit).
- **Proposed solution** — what the user literally said (one candidate, not the answer).
- **Known constraints** — platform, libraries, "no new deps", deadline.
- **Assumed context** — what the user knows vs may not have considered.

When need and proposed solution differ ("I want a withdrawal button" → need: users cash
out earnings), acknowledge both. The spec addresses the business need with the best
available solution.

Generate kebab-case slug (`offline-mode`, `push-notifications`).

Artifacts:
- Spec: `docs/specs/YYYY-MM-DD-<slug>.md` (version-controlled, permanent)
- State: `./swarm-report/spec-<slug>-state.md` (operational, deleted after)

### 0.2 Hidden complexity & scope depth

Two pre-research checks:

**Hidden complexity** — flag in the state file when the request names a UI element but
the real work is backend, implies external services / money / legal / compliance, modifies
a flow other features depend on, or uses domain jargon that could mean different scopes.
Surfacing the iceberg early is one of the most valuable things this skill does. If the
feature is clearly enormous (months, multiple teams), say so upfront and ask one scoping
question.

**Scope depth ambiguity** — when the same phrase can mean radically different scopes
("push notifications" → local alerts vs full FCM/APNs integration), ask ONE question
laying out options from minimal to full, with a recommended option based on project
context. Skip if scope is clearly understood. Trigger on: external services,
multi-system integration, OS-level capabilities.

### Research track selection

Don't run everything by default. Activate tracks based on what gives useful signal:

| Signal | Tracks |
|---|---|
| Existing product functionality | Codebase + Business Analyst |
| New module / cross-layer / architectural change | Codebase + Architecture |
| External API / protocol / algorithm / unfamiliar domain | Web Research |
| Vague idea, unclear user-facing impact | Business Analyst |
| Library / versioning / dependency concern | Web Research (+ maven-mcp if JVM) |
| Straightforward single-module change | Codebase only |

**If the project has existing business / requirements docs** (`docs/`, `*.md` specs, linked issues), read them **before** launching agents — they often answer questions upfront.

**Default when uncertain:** Codebase + Business Analyst. Add others as findings reveal gaps.

---

## Phase 1: Research

### 1.1 Launch research consortium

Launch all selected agents **in a single message** (parallel). Each works independently.

Available tracks:

- **Codebase Expert (Explore)** — always include. Existing code, patterns, deps, module boundaries, TODOs, test infra.
- **Architecture Expert** — new module, dependency-direction change, new abstractions, multi-layer.
- **Web Research** — external protocols, non-trivial algorithms, third-party integration, unfamiliar domain.
- **Business Analyst** — user-facing impact, unclear scope, vague idea.
- **Critical Evaluation** — user proposed a specific technical approach, OR codebase has established patterns that may be outdated. Produces 3 approach options (Radical / Classic / Conservative).
- **Dependency Chain** — external services, OS-level capabilities, infrastructure, setup phase.

Use [`references/research-prompts.md`](references/research-prompts.md) verbatim per agent.

### 1.2 State file

Create `./swarm-report/spec-<slug>-state.md` before launching agents. Standard fields per global state-file template, plus skill-specific sections:

- **Input** — goal, motivation, known constraints
- **Research Tracks** — checklist of tracks launched/skipped (with skip reason)
- **Findings** — populated as agents complete
- **Interview Log** — populated during Phase 2

Update as each agent completes.

---

## Phase 2: Interview

**Entry contract:** research completed, state file holds findings, no user questions asked yet beyond optional scope-depth.

**Round loop** (the unique pattern of this skill):

1. Synthesize findings against the feature checklist (permissions, platform behavior, prerequisites, error states, security, performance, backward compat).
2. Sort remaining items: **already known** (skip), **proposed defaults** (propose for confirmation), **genuine gaps** (ask).
3. If Critical Evaluation produced 3 approach options and approach is unchosen, present them **first** and wait for the pick — it shapes every subsequent question.
4. Present open questions in Question Format (each with recommended answer + alternatives). Wait.
5. Record answers in state file. Check for new gaps. Loop.

**Exit:** no open gaps remain and approach chosen → Phase 3. Round-100 cap → remaining items become non-blocking open questions in the spec; blockers flagged for Phase 4 review.

**Large-feature phasing.** If the feature spans multiple independent phases, offer a phased approach. If accepted, spec Phase 1 only — remaining phases go in "Future Phases".

See [`references/interview-rounds.md`](references/interview-rounds.md) for the feature checklist, approach-options presentation, question format, round script, and phasing template.

---

## Phase 3: Write Spec Draft

Write the spec as if the reader is an implementing agent with zero additional context.
Nothing can be left to inference. Every requirement is verifiable. Every decision is
explicit with its rationale.

Follow the canonical Markdown spec template — YAML frontmatter with `type`/`slug`/`date`/`status` plus optional `platform`/`surfaces`/`risk_areas`/`non_functional`/`acceptance_criteria_ids`/`design` fields that drive downstream `acceptance` and `generate-test-plan`, followed by body sections: Context and Motivation, Acceptance Criteria (stable `AC-N` ids), Prerequisites, Affected Modules and Files, Technical Approach, Technical Constraints, Decisions Made, Out of Scope, Open Questions, and Future Phases.

See [`references/spec-template.md`](references/spec-template.md) for the full template (frontmatter fields, section headers, table shapes, and inline instructions) — copy it verbatim into the draft and fill in each placeholder.

---

## Phase 4: Review Loop

### 4.0 Pre-review TODO sweep

Before launching any reviewer, grep all source docs the spec depends on for unaddressed items:

```bash
grep -rniE 'TODO|FIXME|verify|needs investigation|to be confirmed|TBD|XXX' \
  --exclude='<spec-filename>' \
  <your-baseline-doc-dirs>
```

Replace `<spec-filename>` with the actual spec file name (e.g. `2026-05-27-offline-mode.md`) so the spec itself is never scanned.

Replace `<your-baseline-doc-dirs>` with the actual directories that hold source docs for this repo (e.g. `docs/design/ docs/research/`). **Do NOT add `2>/dev/null`** — if a directory doesn't exist, grep will print an error, which is what you want: missing dirs with `2>/dev/null` silently produce zero output, indistinguishable from "no findings".

For each hit:
- **Closed in spec** — spec explicitly addresses (AC, Decision, or Technical Approach paragraph). No action.
- **Out of Scope** — spec's `## Out of Scope` section explicitly lists it (optionally noting the owner or deferral target). No action.
- **Neither** — gap. Either address inline or add to Out of Scope before proceeding. **Do not skip.**

Why this exists: TODO lists in baseline / research / review docs encode the questions the source authors already knew were unanswered. A spec that ignores them is built on a knowingly incomplete foundation. Real-world failure mode: visual-parity doc says «Drop-shadow rendering TBD», spec never addresses it, pilot devs hit the gap in week 6 of implementation.

This is mechanical — automate it. Don't trust «I think we covered everything».

### 4.1 Present draft to user

Do NOT paste the full spec into chat — the spec file is the artifact; chat is for
navigation. Instead, present a compact summary:
- Spec title and one-sentence goal
- 3–5 key acceptance criteria (by AC-N id and a short label)
- Any open questions that remain unresolved

If there are open questions, ask exactly ONE of them now. After the user responds,
loop back for the next open question if any remain.

### 4.2 Self-review while user reads

While the user reviews, run a self-check:
- Every acceptance criterion is objectively verifiable (not "should feel fast")
- Every affected module listed with change type
- No decision left to the implementing agent's judgment
- Out of scope is explicit — nothing accidentally implied
- No blocking open questions remain unresolved
- **All source-doc TODOs from §4.0 addressed** — re-grep after edits, expect zero unhandled hits
- **Each user interaction (gesture / event / system trigger) has full mechanical specification** — for every drag, tap, long-press, swipe, back-gesture, system-event: trigger conditions, state precondition, visual feedback, hit-testing / coordinate-resolution rule, commit timing, callbacks emitted, failure modes. Half-specified interactions (e.g., "user can drag widget" without anchor / hit-test / drop-zone math) are a top source of post-approval rework.

Fix any self-identified gaps.

### 4.3 Run multiexpert-review (spec profile)

Run `multiexpert-review` with explicit profile hint — prepend to args:

```
profile: spec
---
<full spec content + original feature goal>
```

The hint is defense-in-depth: inline-arg callsites lack frontmatter the detector classifies
on, and the prefix short-circuits detection deterministically. See
[`references/profile-hint-rationale.md`](references/profile-hint-rationale.md).

The draft is in-memory (not yet saved to `docs/specs/`), so engine classifies source as
`conversation` and uses `inline-revise` for FAIL fixes — revise-loop iterations happen
inline in this flow.

The spec profile (panel: business-analyst + architecture-expert) checks AC falsifiability,
prerequisite realism, explicit Out of Scope, decisions with rationale, affected-modules
completeness, blocking vs non-blocking open questions, technical-approach detail.

**Do not shrink the reviewer panel.** Include ALL triggered reviewers that are installed —
if the profile's `optional_if` regex matches (security-expert on PII/auth/encryption,
performance-expert on SLA/latency/budget, ux-expert on a11y/UI/UX), the engine includes
them when installed and skips them when not; call out any skipped-due-to-missing reviewer
rather than silently dropping the perspective.
Skipping a profile-triggered reviewer because «that domain was already covered in an
earlier review of the underlying research» is false economy: each multiexpert cycle
reviews a different artifact (spec vs research are different texts even when they
overlap in topic), and the reviewer's perspective on the spec-level contract is what
matters here. Cost of including: ~2-5 minutes per extra agent. Cost of omission: gaps
that surface only after approval (visual-interaction details, perf budgets, a11y flows
are typical victims).

| Severity | Action |
|---|---|
| PASS | Proceed |
| Minor | Fix inline, note changes |
| CONDITIONAL / contradictions | Surface to user, resolve |
| FAIL | Engine drives revise-loop; iterate until PASS/CONDITIONAL or user escalation |

### 4.4 Discussion round after review

After self-review and multiexpert-review complete, if either surfaced issues or open questions:
present them to the user for a final discussion round. This may loop back into Phase 2
style Q&A to close remaining gaps.

### 4.5 Implementation walk-through pass (adversarial)

Reviewers find problems. **Implementers find missing pieces.** These are different
failure modes — a reviewer reading «AC-DRAG-1: drag shadow rendered from getWidgetIcon»
sees a satisfied AC; an implementer asked «build this» immediately wonders «where is
the shadow positioned relative to my finger? how do I know which slot is the drop
target?». The reviewer's mindset doesn't generate that question; the implementer's does.

Run **one** Agent (general-purpose, sonnet) with this brief:

> You are pretending to be the implementing engineer for `<spec-path>`. Don't review the
> spec — try to *use* it. Pick the single most complex user interaction in the spec
> (drag, complex gesture, multi-step flow) and mentally simulate implementing it
> end-to-end: from user trigger → state transitions → visual updates → callbacks → cleanup.
> Every time you'd have to *guess* a detail or ask a clarifying question — list it.
> Output: bullet list of «I'd have to guess X because the spec doesn't specify Y». Cap 15 items.

For each item the agent surfaces:
- **Trivially fillable** (one-line clarification) → fix inline, move on.
- **Requires design decision** → surface to user as a question (same format as Phase 2).
- **Already specified, agent missed it** → no action, mention in the discussion.

Cost: ~3-5 minutes of one agent. Avoided cost: post-approval fix-up commits when pilot
devs hit the gap weeks later.

Skip only if the spec is for a small, well-bounded change with no complex interactions.

### 4.6 Approval

Once the user is satisfied and no issues remain, update spec status from `draft` to
`approved` and proceed to save.

---

## Phase 5: Save

Save the approved spec to `docs/specs/YYYY-MM-DD-<slug>.md`, flip frontmatter `status`
from `draft` to `approved`, retire the state file, confirm in one sentence with a
suggested next step (`/generate-test-plan`, plan-mode implementation, or
`/multiexpert-review`). Do not auto-invoke downstream skills — the user decides.

See [`references/output-layout.md`](references/output-layout.md) for path conventions,
confirmation message, and hand-off rules.

---

## Red Flags / STOP Conditions

- **Fundamental contradiction** — acceptance criteria are mutually exclusive, or a constraint
  makes the feature impossible. Surface the conflict, don't invent a workaround.
- **Missing critical access** — feature requires systems, APIs, or credentials not available.
  List what's needed and stop.
- **Scope genuinely unbounded** — after one scoping attempt, still too large to spec.
  Propose phased approach and wait for user alignment.
- **Decision requires product authority** — choice has business, legal, or brand implications
  the team cannot make unilaterally. Flag as blocking open question.

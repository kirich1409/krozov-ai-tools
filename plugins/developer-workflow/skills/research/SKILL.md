---
name: research
description: "Research Consortium — parallel expert investigation of a topic, idea, problem, or technology before implementation. Launches up to 5 domain experts simultaneously (codebase, web, docs, dependencies, architecture), synthesizes findings into a structured report, optionally auto-reviews via business-analyst (product-angled topics) or a tech-sanity self-check (purely technical topics). Use when: \"research\", \"investigate options\", \"investigate approaches\", \"explore this idea\", \"technical spike\", \"feasibility\", \"can we do X?\", \"what are the options for\", \"compare approaches\", \"evaluate alternatives\", \"pros and cons of\", \"before we start — let's understand\", \"what do we need to know before\". Do NOT use for: code review (use code-reviewer agent), multiexpert review (use multiexpert-review), narrow codebase lookup (\"how is X done in our code\" — use Explore agent directly), single-library version or changelog lookup (use a dependency/version lookup tool directly), debugging existing bugs."
disable-model-invocation: true
---

# Research

Parallel expert investigation of a topic before implementation. The Research Consortium
launches up to 5 domain agents simultaneously, each investigating their slice independently,
then synthesizes findings into a single structured report.

**Synthesis-bias prevention.** The core invariant: **agents that gather data never synthesize
it.** Each gather-agent runs in isolation with no visibility into the others — only the
orchestrator merges their findings. This gather/synthesize separation is what makes the
consortium worth the cost; preserve it across every change.

A second, optional layer is the post-synthesis review: in product-angled topics a separate
`business-analyst` agent challenges the merged report (Phase 4 `business-analyst` mode);
in purely technical topics the orchestrator runs a self-check against a fixed checklist
(`tech-sanity` mode). The reviewer layer is a defense-in-depth, not the core value.

**Communication policy — non-negotiable.** All clarification with the user happens in the
chat session via the `AskUserQuestion` tool — never through files. The saved report under
`./swarm-report/research/` is a **handoff artifact** consumed by downstream skills/agents
(`/write-spec`, `/multiexpert-review`, Plan Mode, a future research re-run); the user does
not have to open it to participate in the research. The in-chat summary at Phase 5.3 is what
the user reads to make decisions. Every blocker the user can answer is resolved in dialogue
**before** the report is written; the file is never a parking lot for pending questions,
draft hedges, or "TBD — ask user" placeholders. If something needs the user's input, fire
`AskUserQuestion` now — do not write it to disk and hope the user opens it.

---

## Phase 1: Scope the Research

Extract from the user's request:
- **Topic** — what is being investigated
- **Context** — why this matters now
- **Constraints** — known boundaries (KMP, no new deps, deadline)

Select expert tracks:

| Track | Include when |
|---|---|
| **Codebase** | Topic touches existing code, patterns, or modules |
| **Web** | See criteria below — conditional, skip for purely internal topics |
| **Docs** | Topic involves specific libraries/frameworks with external documentation |
| **Dependencies** | Topic involves adding, replacing, or evaluating JVM/KMP deps |
| **Architecture** | Topic affects module boundaries, layer design, or API contracts |

**Web track inclusion** — launch when ANY of the following holds, otherwise skip:
- Topic compares against industry practices outside our code.
- Involves external libraries/frameworks/protocols whose best practices may diverge from the codebase.
- Benchmarks, post-mortems, or articles on similar problems are needed.
- The question explicitly asks about "industry consensus" / "how big projects do it".

Skipping Web on purely internal topics avoids generic web noise and saves a track for
something that adds signal.

### Clarifying questions (round-loop)

Use the `AskUserQuestion` tool for clarification — never plain prose that the user has to
parse and answer in their own format, and never a written question parked in any file.
`AskUserQuestion` with 2–4 concrete options surfaces the decision space and gives a
machine-checkable answer; use free-text (the implicit "Other" option) only when the option
space is genuinely open. **One question per round** still applies — fire `AskUserQuestion`
with exactly one question, wait for the answer, fold it into the scope, then fire the next
round only if a blocker still remains. Multiple rounds are fine; multiple questions in one
round are not. Each question must be the single most blocking ambiguity right now — not a
checklist of mild curiosities.

When to ask:
- **Scope is genuinely ambiguous** (multiple valid interpretations that lead to different expert tracks or different success criteria).
- **A constraint is missing without which the redirect / consortium decision flips** (e.g. KMP-only vs Android-only changes which tracks are relevant).

When NOT to ask:
- Mild gaps the consortium can fill itself (let agents gather, surface anything blocking later in Phase 5.1 dialogue).
- Stylistic preferences that don't change the recommendation.
- Anything the auto-review step (Phase 4) would catch.

State the assumed scope when proceeding without asking. Resume Phase 1 from the top after each answered round in case the answer reshuffles track selection or triggers the min-2-tracks redirect.

### Minimum-2-tracks rule

If the topic resolves to **only one** expert track after applying selection criteria, do NOT launch the consortium. The synthesis-bias prevention machinery only pays off when ≥2 independent perspectives are merged. Redirect instead:

| Single track | Redirect to |
|---|---|
| Codebase only | Delegate to a single `Explore` agent inline |
| Docs only | Use a library-docs lookup tool (Context7-style) directly |
| Dependencies only | Use a dependency/version lookup tool directly (e.g. the `maven-mcp` skill family if installed) |
| Architecture only | Delegate to `architecture-expert` agent directly |
| Web only | Answer inline with the available web-search tool; if none is available, answer from training knowledge and explicitly note the limitation |

Report the redirect in one line ("Topic is narrow — handing off to {target} instead of running the consortium"), then exit. Do not create state or report artifacts for redirected topics.

---

## Phase 2: Launch Research Consortium

Generate a kebab-case slug from the topic (e.g., `ktor-migration`, `push-notifications`)
— this is the first thing that happens once the consortium is committed (post-redirect).
Paths:
- Artifact: `./swarm-report/research/research-<slug>.md`
- State:    `./swarm-report/research-<slug>-state.md`

Launch all selected agents **in a single message** for maximum parallelism. Each works
independently — never share findings between agents.

Use the prompt templates in [`references/expert-prompts.md`](references/expert-prompts.md)
verbatim per agent. The reference covers all 5 tracks (Codebase / Web / Docs / Dependencies /
Architecture) with their tools and required structure.

### State persistence

Before launching, create `./swarm-report/research-<slug>-state.md`:

```markdown
# Research State: {topic}

Slug: {slug}
Status: investigating
Started: {date}

## Scope
- Topic: {topic}
- Context: {why}
- Constraints: {known boundaries}

## Expert Tracks
- [ ] Codebase — {launched | skipped: reason}
- [ ] Web — {launched | skipped: reason}
- [ ] Docs — {launched | skipped: reason}
- [ ] Dependencies — {launched | skipped: reason}
- [ ] Architecture — {launched | skipped: reason}

## Findings
(populated as each agent reports back — internal working storage for the orchestrator,
not user-facing)
```

The state file and any other temp files live at the `./swarm-report/` **root** —
that's the temp/working area. Use them freely for the orchestrator's internal needs:
progress tracking, inter-phase info passing, expert-output buffering for compaction
resilience. Update the checklist as each agent completes and fold raw findings here if
it helps survive a compaction.

The `./swarm-report/research/` subdirectory is reserved for **finished deliverables**
only — the polished report from Phase 5.2 lands there, nothing else.

**What does not go into any file** is the user-facing dialogue — clarification questions
and the user's answers from Phase 1 / Phase 5.1 round-loops live exclusively in the chat
session.

---

## Phase 3: Synthesize Findings

Combine findings into a structured synthesis held primarily in working memory. The
synthesis is mutable until Phase 5 closes the clarification round-loop, so **do not write
the final report here** — that is exclusively Phase 5.2. (Internal temp files allowed at
the `./swarm-report/` root per the Phase 2 rules.) Cross-reference findings for:
- **Convergence** — multiple experts independently agree (strongest signal)
- **Contradictions** — surface explicitly, do not paper over
- **Gaps** — what no expert covered
- **Dependencies between findings** — one expert's conclusion changes another's relevance

### Report structure

Use this exact structure when Phase 5.2 writes the final report to
`./swarm-report/research/research-<slug>.md`:

```markdown
# Research: {topic}

Date: {date}
Experts consulted: {tracks that ran}
Auto-review mode: {business-analyst or tech-sanity}

## Problem / Question Summary
{2–3 sentences: what was investigated and why}

## Approaches Found

Lay out 2–3 viable approaches in parallel before the recommendation. If only one is
genuinely viable, state that explicitly with reasons others were ruled out.

### Approach 1: {name}
- **Description:** ...
- **Trade-offs:** ...
- **Evidence:** {which experts found this, key details}
- **Compatibility:** ...

### Approach 2: {name}
...

### Side-by-side comparison

| Dimension | Approach 1 | Approach 2 | Approach 3 |
|---|---|---|---|
| Effort | S/M/L | ... | ... |
| Maintainability | + / − | ... | ... |
| Compatibility | ... | ... | ... |
| Risk | low/med/high | ... | ... |

Skip the table when one approach dominates on every dimension.

## Library / Dependency Recommendations
| Library | Version | KMP | Vulnerabilities | Notes |
|---|---|---|---|---|

## Risks and Concerns
- {risk — severity: critical/major/minor}

## Recommendation
{Preferred approach with reasoning, citing specific expert findings.}

## Known Unknowns
- {External factual gaps that no party in the chat session could resolve right now — e.g.
  "vendor SLA pending contract renegotiation", "library Y v3 GA date TBD", "pricing not
  publicly available". Each entry names what is unknown and who/when could resolve it.
  Omit this section entirely if there are no such gaps. NEVER use this section to record
  questions for the user — those are always resolved via `AskUserQuestion` in Phase 5.1
  before the report is written.}

## Sources
- {URLs, doc references, codebase locations}
```

---

## Phase 4: Auto-Review

Pick the review mode based on the topic profile, then record it in the report header
`Auto-review mode:` field as one of `business-analyst` or `tech-sanity` (not the literal
pipe — pick one).

### Mode selection

Use **`business-analyst`** when the topic has a product / scope angle:
- Decision affects feature scope, MVP boundaries, time-to-market, or user-facing trade-offs.
- The question contains an implicit or explicit "what to build" component (not only "how to build").
- The decision touches SLA / SLO / cost / business risk.

Use **`tech-sanity`** (lightweight self-check, no agent launch) when the topic is purely
technical with no product angle — e.g. "which DI", "which serializer", "which test runner",
"sync vs async retries". Running business-analyst here adds tokens and latency without
producing actionable output.

**Tiebreaker.** When the topic could plausibly fit either mode (e.g. "Coil vs Glide" where
the technical pick subtly affects app size and MVP scope), default to `tech-sanity`. Promote
to `business-analyst` only if the report's recommendation materially depends on a product /
scope judgement that the gatherers did not make. The cost asymmetry is real — `tech-sanity`
is free, `business-analyst` is a full agent launch — so bias toward the cheaper option when
in doubt.

### Mode `business-analyst`

Launch the `business-analyst` agent against the synthesized report. The reviewer holds a
distinct perspective from the gatherers — they check completeness, product sense,
practical viability:

```
Review this research report for completeness and practical viability.

{full research report}

Check:
1. Are all approaches properly evaluated with trade-offs?
2. Any obvious alternatives missed?
3. Do risks cover both technical and product concerns?
4. Is the recommendation well-supported by evidence?
5. Does the "Known Unknowns" section list only external factual gaps that no party in the
   chat session could resolve right now (vendor SLA, unpublished pricing, future-dated
   GA, etc.) — and contain NO questions directed at the user, NO "TBD — ask user"
   placeholders, NO rhetorical asks? Any user-resolvable trade-off must have been
   surfaced in Phase 5.1 chat dialogue via `AskUserQuestion` and folded into the
   recommendation, not parked in the report.
6. Does the recommendation align with practical constraints (time, team skills, maintenance)?

List gaps with severity (critical / major / minor).
Respond in the same language as the research topic description.
```

### Mode `tech-sanity`

Run a self-check pass on the report against this checklist (no agent — direct verification):

1. **Approaches evaluated ≥2** — at least two viable options laid out side-by-side, or an
   explicit justification why only one survived.
2. **Risks listed** — each approach has its risks called out with severity.
3. **Recommendation justified** — the chosen option cites specific expert findings, not
   "feels right".
4. **Sources cited** — every non-obvious claim links to a codebase location, doc URL, or
   dependency coordinate.

If any item fails, fix the report before saving (re-run a track or fill the gap from the
existing findings). Do not promote to `business-analyst` mode just because the checklist
fails — the failure is a content gap, not a mode mismatch.

The self-check produces no chat output; any fixes go into the synthesis silently. The
report's prose stays in the same language as the research topic description (consistent
with the gather-agent prompts).

### Handle findings (both modes)

- **No issues** → proceed to Phase 5
- **Minor** → incorporate inline, note changes, proceed to Phase 5
- **Major/critical, fillable from research** → re-run the relevant expert track, then re-review
- **Major/critical, the user can resolve** → carry into Phase 5.1 and ask via
  `AskUserQuestion` in chat; never pre-park the question in any file under `./swarm-report/`
- **Major/critical, no party in the session can resolve right now** (e.g. pending vendor SLA,
  unpublished pricing) → record under "Known Unknowns" in the final report as a factual gap,
  not as a question for anyone

The report is not saved at this phase; saving happens in Phase 5 after any user-blocking
clarifications have been resolved in dialogue.

---

## Phase 5: Resolve, Save, Summarize

The synthesis from Phase 3 (refined by Phase 4) is held in working memory only — nothing
is on disk yet. This phase walks through three steps in order.

### 5.1 Clarification round-loop (dialogue)

If the synthesis surfaces a question whose answer would materially change the recommendation
or a key finding, ask it in chat via the `AskUserQuestion` tool — 2–4 concrete options when
the option space is enumerable, free-text "Other" otherwise. Same pacing as Phase 1: **one
question per round**, wait for the answer, fold it into the synthesis, then check if any
blocker remains. Stop the moment no blocker remains. Multiple rounds are fine; multiple
questions in one round are not.

The dialogue lives in chat. The state file may flip to `Status: awaiting-clarification` as
process metadata, but the question text and the user's answer are never written to any file
under `./swarm-report/`. Writing a question into a file and waiting for the user to open it
is a violation of the communication policy — fire `AskUserQuestion` instead.

What does **not** belong in the round-loop:
- Stylistic preferences that don't change the recommendation.
- Mild gaps the consortium could plausibly fill on a re-run (re-run instead).
- Items no party in the session can answer right now (pending vendor SLA, unpublished
  pricing, future-dated dependency GA) → surface them in the report's "Known Unknowns"
  section as factual gaps, not as questions for anyone.

### 5.2 Save the final report

Once the loop exits, ensure `./swarm-report/research/` exists (`mkdir -p` it if needed —
fresh repos won't have the nested subdir), then write `./swarm-report/research/research-<slug>.md`.
The report is a finished deliverable for downstream consumers (`/write-spec`,
`/multiexpert-review`, Plan Mode, a future research re-run) — not a scratchpad and not a
discussion vehicle with the user. Every section reflects the post-clarification synthesis;
"Known Unknowns" holds only external factual gaps from above (and is omitted entirely when
empty); no section contains a question, "TBD — ask user" marker, or any other hook that
would force the user to open the file to make progress. If you catch yourself wanting to
write such a hook, return to Phase 5.1 and fire `AskUserQuestion` instead. Mark the state
file `Status: done`.

### 5.3 Chat summary

Post a compact summary (≤30 lines, no tables, no source lists, no inline citations) that
lets the user decide without opening the file:

1. One sentence: topic, tracks ran, overall recommendation.
2. 3–5 bullets: most decision-relevant findings / blockers / constraints.
3. One line: suggested next step.

### Suggest next action

| Situation | Suggested action |
|---|---|
| Feature is clear, single task, ready to build | Plan mode + start implementing |
| Complex approach, needs validation | Plan mode → `/multiexpert-review` |
| Research revealed a bug, not a feature need | Plan mode for the fix |
| Known Unknowns remain (external factual gaps no party in the session could resolve) | Surface them in the summary, suggest who/when could fill them |
| Multiple viable approaches, no clear winner | Present trade-offs, ask user to pick |

Frame as actionable proposal, not a question.

---

## Red Flags / STOP Conditions

Stop and escalate when:
- **Scope explosion** — topic is much larger than it appeared. Report findings, propose narrowing.
- **Contradictory requirements** — user constraints conflict. Present, ask which takes priority.
- **No viable approach** — all candidates have critical blockers. Report honestly.
- **Missing access** — research needs internal systems / paid APIs / credentials. List what's needed.
- **Stale/conflicting web data** — sources disagree or look outdated. Flag uncertainty.

---

## Output Format and Location

| Artifact | Path | Purpose |
|---|---|---|
| Research report | `./swarm-report/research/research-<slug>.md` | Handoff artifact for downstream skills/agents (not a user-facing discussion vehicle) |
| State file | `./swarm-report/research-<slug>-state.md` | Compaction-resilient progress tracking |
| Chat summary | — | ≤30-line user-facing post-save output — the primary thing the user reads |

The chat summary is what the user consumes; the research report is what the next skill
or agent consumes. The state file is operational and may be deleted after completion.

---
name: research
description: "Research Consortium — parallel expert investigation of a topic, idea, problem, or technology before implementation. Launches up to 5 domain experts simultaneously (codebase, web, docs, dependencies, architecture), synthesizes findings into a structured report, optionally auto-reviews via business-analyst. Use when: \"research\", \"investigate options\", \"investigate approaches\", \"explore this idea\", \"technical spike\", \"feasibility\", \"can we do X?\", \"what are the options for\", \"compare approaches\", \"evaluate alternatives\", \"pros and cons of\", \"before we start — let's understand\", \"what do we need to know before\". Do NOT use for: code review (use code-reviewer agent), multiexpert review (use multiexpert-review), narrow codebase lookup (\"how is X done in our code\" — use Explore agent directly), single-library version or changelog lookup (use maven-mcp:latest-version / dependency-changes), debugging existing bugs."
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
(`tech-sanity` mode). The reviewer layer is a defence-in-depth, not the core value.

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

**If scope is genuinely ambiguous** (multiple valid interpretations), state the assumed scope and ask **one** clarifying question. Otherwise proceed — the auto-review step catches major gaps.

### Minimum-2-tracks rule

If the topic resolves to **only one** expert track after applying selection criteria, do NOT launch the consortium. The synthesis-bias prevention machinery only pays off when ≥2 independent perspectives are merged. Redirect instead:

| Single track | Redirect to |
|---|---|
| Codebase only | Delegate to a single `Explore` agent inline |
| Docs only | Use `Context7` / library-docs lookup directly |
| Dependencies only | Use `maven-mcp:check-deps` or `latest-version` |
| Architecture only | Delegate to `architecture-expert` agent directly |
| Web only | Answer inline with `WebSearch` / `WebFetch` |

Report the redirect in one line ("Topic is narrow — handing off to {target} instead of running the consortium"), then exit. Do not create state or report artifacts for redirected topics.

Generate kebab-case slug from the topic (e.g., `ktor-migration`, `push-notifications`):
- Artifact: `./swarm-report/<slug>-research.md`
- State: `./swarm-report/research-<slug>-state.md`

---

## Phase 2: Launch Research Consortium

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
(populated as agents report back)
```

Update as each agent completes.

---

## Phase 3: Synthesize Findings

Combine findings into a structured report. Cross-reference for:
- **Convergence** — multiple experts independently agree (strongest signal)
- **Contradictions** — surface explicitly, do not paper over
- **Gaps** — what no expert covered
- **Dependencies between findings** — one expert's conclusion changes another's relevance

### Report structure

Save to `./swarm-report/<slug>-research.md`:

```markdown
# Research: {topic}

Date: {date}
Experts consulted: {tracks that ran}
Auto-review mode: {business-analyst | tech-sanity}

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

## Open Questions
- {What needs user decision or could not be determined}

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
5. Are open questions the right ones — nothing critical missing?
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

### Handle findings (both modes)

- **No issues** → save artifact
- **Minor** → incorporate inline, note changes
- **Major/critical, fillable** → re-run the relevant expert track
- **Major/critical, not fillable** → add to Open Questions, flag for user

---

## Phase 5: Save & Summarize

Save the report to `./swarm-report/<slug>-research.md`. Mark state file `done`.

Post a chat summary that lets the user decide without opening the file:

1. One sentence: topic, tracks ran, overall recommendation.
2. 3–5 bullets: most decision-relevant findings/blockers/constraints.
3. If open questions block next steps: ask exactly ONE now, labeled "Question 1 of N:".
   Save the rest in the report — present subsequent questions only after the user answers.
4. One line: suggested next step.

**Hard limit:** ≤30 lines in chat. No tables, no source lists, no inline citations.

### Suggest next action

| Situation | Suggested action |
|---|---|
| Feature is clear, single task, ready to build | Plan mode + start implementing |
| Complex approach, needs validation | Plan mode → `/multiexpert-review` |
| Research revealed a bug, not a feature need | Plan mode for the fix |
| Open questions block progress | List, ask user to resolve |
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
| Research report | `./swarm-report/<slug>-research.md` | Final synthesized findings |
| State file | `./swarm-report/research-<slug>-state.md` | Compaction-resilient progress tracking |
| Chat summary | — | ≤30-line user-facing post-save output |

The research report is the primary deliverable. The state file is operational and may be
deleted after completion.

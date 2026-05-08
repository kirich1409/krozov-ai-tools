---
name: research
description: "Research Consortium — parallel expert investigation of a topic, idea, problem, or technology before implementation. Launches up to 5 domain experts simultaneously (codebase, web, docs, dependencies, architecture), synthesizes findings into a structured report, auto-reviews via business-analyst. Use when: \"research\", \"investigate\", \"explore this idea\", \"technical spike\", \"feasibility\", \"can we do X?\", \"what are the options for\", \"compare approaches\", \"evaluate alternatives\", \"pros and cons of\", \"before we start — let's understand\", \"what do we need to know before\". Do NOT use for: code review (use code-reviewer agent), multiexpert review (use multiexpert-review), library version lookup (use maven-mcp:latest-version), debugging existing bugs."
disable-model-invocation: true
---

# Research

Parallel expert investigation of a topic before implementation. The Research Consortium
launches up to 5 domain agents simultaneously, each investigating their slice independently,
then synthesizes findings into a single structured report.

**Synthesis-bias prevention:** the agents that gather data never synthesize it. Each runs in
isolation with no visibility into the others. A separate reviewer (business-analyst) challenges
the merged synthesis afterwards. This separation is the core value of the skill — preserve it.

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
| **Web** | Always (mandatory — every research must produce ≥1 web-sourced insight) |
| **Docs** | Topic involves specific libraries/frameworks with external documentation |
| **Dependencies** | Topic involves adding, replacing, or evaluating JVM/KMP deps |
| **Architecture** | Topic affects module boundaries, layer design, or API contracts |

**If scope is genuinely ambiguous** (multiple valid interpretations), state the assumed scope and ask **one** clarifying question. Otherwise proceed — the auto-review step catches major gaps.

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
- [ ] Web — launched (mandatory)
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

Handle findings:
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

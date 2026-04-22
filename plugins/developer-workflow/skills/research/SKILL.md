---
name: research
description: "Research Consortium — parallel expert investigation of a topic, idea, problem, or technology before implementation. Launches up to 5 domain experts simultaneously (codebase, web, docs, dependencies, architecture), synthesizes findings into a structured report, auto-reviews via business-analyst. Use when: \"research\", \"investigate\", \"explore this idea\", \"technical spike\", \"feasibility\", \"can we do X?\", \"what are the options for\", \"compare approaches\", \"evaluate alternatives\", \"pros and cons of\", \"before we start — let's understand\", \"what do we need to know before\". Also invoked when implement or code-migration needs a Research stage, or when multiexpert-review verdict is FAIL. Do NOT use for: code review (use code-reviewer agent), implementation (use implement), multiexpert review (use multiexpert-review), library version lookup (use maven-mcp:latest-version), debugging existing bugs."
disable-model-invocation: true
---

# Research

Parallel expert investigation of a topic before implementation begins. The Research Consortium
launches domain-specific agents simultaneously, each investigating their slice of the question
independently, then synthesizes findings into a single structured report.

**Key principle:** research and review are separate concerns. The agents that gather data never
synthesize it — a different agent (business-analyst) reviews the combined findings for
completeness, gaps, and product sense. This separation prevents confirmation bias and ensures
the synthesis is challenged.

---

## Phase 1: Scope the Research

### 1.1 Extract the research question

From the user's request, extract:
- **Topic** — what is being investigated (technology, approach, problem, idea)
- **Context** — why this matters now (upcoming feature, migration, pain point, curiosity)
- **Constraints** — known boundaries (must work with KMP, must not add new dependencies, deadline)

### 1.2 Determine scope

Assess which expert tracks are relevant to this research:

| Expert track | When to include |
|--------------|----------------|
| **Codebase** | Topic touches existing code, patterns, or modules in the project |
| **Web** | Always included (mandatory — see Web-Lookup Mandate below) |
| **Docs** | Topic involves specific libraries or frameworks with external documentation |
| **Dependencies** | Topic involves adding, replacing, or evaluating JVM/KMP dependencies |
| **Architecture** | Topic affects module boundaries, layer design, or API contracts |

**Web-Lookup Mandate:** internet research is mandatory, not optional. Every research must
produce at least one web-sourced insight. Never rely solely on codebase analysis and training
data.

### 1.3 Confirm scope (if ambiguous)

If the topic is broad or could be interpreted multiple ways, state the assumed scope and ask
**one clarifying question** before launching experts. If the scope is clear — proceed without
asking.

Examples of when to ask:
- "Research notification systems" — too broad. Ask: push notifications? In-app? Email? All?
- "Investigate moving to Ktor" — clear scope. Proceed.

### 1.4 Generate slug

Create a short kebab-case slug from the topic for artifact naming:
`<slug>` (e.g., `ktor-migration`, `push-notifications`)

The slug is the topic only — no `research-` prefix. File paths add their own prefixes:
- Artifact: `./swarm-report/<slug>-research.md`
- State: `./swarm-report/research-<slug>-state.md`

---

## Phase 2: Launch Research Consortium

Launch all relevant expert agents **in a single message** to maximize parallelism (up to 5
simultaneously). Each agent works independently — never share one agent's findings with another.

### 2.1 Expert agents

#### Codebase Expert (Explore subagent)

**What:** Analyze existing code, patterns, dependencies, and relevant modules related to the
research topic.

**How:** Launch an Explore subagent with instructions to locate symbols, trace module
relationships, and map public API surface area. Prefer a structured code-index tool when
available — one that resolves classes, usages, dependencies, and API by symbol rather than
text. Fall back to `Grep` + `Read` when no index is available; the skill must still produce
a complete report in that mode. See the project README for any recommended index tooling.

**Prompt template:**
```
Investigate the codebase for everything related to: {topic}

Find and report:
1. Existing code that relates to this topic (classes, interfaces, modules)
2. Current patterns and approaches used for similar concerns
3. Dependencies already in the project that are relevant
4. Module boundaries and layers that would be affected
5. Any existing TODO/FIXME comments related to this topic

Use a code-index tool for symbol resolution when one is available in the environment —
look up classes, usages, dependencies, dependents, and public API surface by symbol rather
than by text. If no index is available, use `Grep` for text search and `Read` for targeted
file inspection; produce the same report structure either way.
Be thorough — check build files, configuration, and test code too.

Respond in the same language as the research topic description. Structure: overview, then findings grouped by category.
```

#### Web Expert

**What:** Search the web for approaches, best practices, common pitfalls, and real-world examples — if web search is available.

**How:** If web search is available, look for approaches and best practices; find recent articles and community discussions. If web search is not available, note this as a limitation in the research report.

**Prompt template:**
```
Research: {topic}

If web search is available, investigate:
1. Common approaches and best practices (with trade-offs for each)
2. Known pitfalls and mistakes to avoid
3. Real-world examples from open-source projects
4. Recent developments or changes (last 12 months)
5. Community consensus — what does the majority recommend and why?

If web search is available, perform an in-depth investigation first,
then follow up with targeted searches for specific details if needed.
If web search is not available, note this as a limitation in the research report
and rely on training knowledge where possible.

Respond in the same language as the research topic description. Include source URLs for key claims.
```

#### Docs Expert

**What:** Find official documentation for involved libraries and frameworks.

**How:** Look up official documentation for the libraries involved; fetch API reference and usage examples.

**Prompt template:**
```
Find official documentation for: {libraries/frameworks related to topic}

For each library/framework:
1. Look up official documentation for the library (API reference, guides, changelogs)
2. Find documentation for: API surface, migration guides, compatibility notes,
   configuration options, known limitations
3. Check for version-specific documentation if version matters

Respond in the same language as the research topic description. Quote relevant documentation sections. Note any gaps where
documentation is missing or unclear.
```

#### Dependencies Expert (maven-mcp)

**What:** Check compatibility, versions, vulnerabilities, and alternatives for JVM/KMP
dependencies.

**How:** Use maven-mcp tools:
- `search_artifacts` — find candidate libraries
- `get_latest_version` — current versions
- `get_dependency_vulnerabilities` — security issues
- `get_dependency_changes` — release notes, changelog entries between versions
- `compare_dependency_versions` — semver delta comparison between versions
- `check_multiple_dependencies` — batch version checks

**Prompt template:**
```
Analyze dependencies related to: {topic}

Investigate:
1. Current versions of relevant libraries and their latest available versions
2. Known vulnerabilities in current or candidate dependencies
3. Compatibility matrix — what works with what (Kotlin version, KMP targets, AGP)
4. Alternative libraries that serve the same purpose — compare by: maturity,
   maintenance activity, KMP support, community size
5. Breaking changes in recent versions

Respond in the same language as the research topic description. Include specific version numbers and groupId:artifactId coordinates.
```

#### Architecture Expert (architecture-expert agent)

**What:** Evaluate how the research topic fits into the project's architecture — module
boundaries, dependency direction, API design implications.

**How:** Launch the `architecture-expert` agent with context about the topic.

**Prompt template:**
```
Evaluate the architectural implications of: {topic}

Analyze:
1. Which modules and layers would be affected?
2. Does this align with the current architecture, or does it require structural changes?
3. Dependency direction — would this introduce any problematic dependencies?
4. API boundaries — what contracts need to change or be created?
5. Integration points — where does this touch existing abstractions?

Read the relevant module structure and build files before making judgments.
Respond in the same language as the research topic description.
```

### 2.2 State persistence

Before launching agents, create the state file at `./swarm-report/research-<slug>-state.md`:

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

Update the state file as each agent completes. This ensures work survives context compaction.

---

## Phase 3: Synthesize Findings

After all expert agents complete, the orchestrator combines their findings into a structured
research report. This is a synthesis step, not a copy-paste — cross-reference findings,
identify convergence and contradictions, and produce actionable conclusions.

### 3.1 Cross-reference

Look for:
- **Convergence** — multiple experts independently pointing to the same approach or concern
  (strongest signal)
- **Contradictions** — one expert recommends X, another warns against it (surface explicitly)
- **Gaps** — areas no expert covered, or questions that remain unanswered
- **Dependencies** — findings from one expert that change the relevance of another's conclusions

### 3.2 Draft research report

Structure the report as:

```markdown
# Research: {topic}

Date: {date}
Experts consulted: {list of tracks that ran}

## Problem / Question Summary
{What was investigated and why — 2-3 sentences}

## Approaches Found

Lay out 2–3 viable approaches in parallel before the recommendation. The point of this section is to make alternatives visible — a single approach with "the others were considered and rejected" is weaker than an explicit side-by-side. If only one approach is genuinely viable, state that explicitly with the reasons other candidates were ruled out.

### Approach 1: {name}
- **Description:** {what it is}
- **Trade-offs:** {pros and cons}
- **Evidence:** {which experts found this, with key details}
- **Compatibility:** {works with current stack? KMP? versions?}

### Approach 2: {name}
- **Description:** ...
- **Trade-offs:** ...
- **Evidence:** ...
- **Compatibility:** ...

### Approach 3: {name} (optional)
...

### Side-by-side comparison

| Dimension | Approach 1 | Approach 2 | Approach 3 |
|---|---|---|---|
| Effort | S/M/L | ... | ... |
| Maintainability | + / − | ... | ... |
| Compatibility | ... | ... | ... |
| Risk | low/med/high | ... | ... |

Use this table when the user will need to pick between approaches. Skip it if one approach dominates on every dimension.

## Library / Dependency Recommendations
| Library | Version | KMP | Vulnerabilities | Notes |
|---------|---------|-----|-----------------|-------|
| ... | ... | ... | ... | ... |

## Risks and Concerns
- {risk 1 — severity: critical/major/minor}
- {risk 2}

## Recommendation
{The preferred approach with reasoning — why this one over the others.
Reference specific findings from experts.}

## Open Questions
- {What still needs user decision}
- {What could not be determined}

## Sources
- {URLs from web research}
- {Documentation references}
- {Codebase locations examined}
```

---

## Phase 4: Auto-Review

Launch the `business-analyst` agent to review the synthesized report. The reviewer has a
different perspective than the researchers — they check for completeness, product sense,
and practical viability.

**Prompt for business-analyst:**
```
Review this research report for completeness and practical viability.

{full research report}

Check:
1. Are all approaches properly evaluated with trade-offs?
2. Are there obvious alternatives that were missed?
3. Do the risks cover both technical and product concerns?
4. Is the recommendation well-supported by the evidence?
5. Are the open questions the right ones — nothing critical missing?
6. Does the recommendation align with practical constraints (time, team skills, maintenance)?

If you find gaps or issues, list them with severity (critical / major / minor).
Respond in the same language as the research topic description.
```

### 4.1 Handle review findings

- **No issues** — proceed to save artifact
- **Minor issues** — incorporate feedback into the report, note what was added
- **Major/critical gaps** — if the gap can be filled by re-running a specific expert track,
  do so. Otherwise, add the gap to "Open Questions" and flag it for the user

---

## Phase 5: Save Artifact

Save the final research report to `./swarm-report/<slug>-research.md`.

Update the state file status to `done`.

After saving, post a chat summary. The summary must be self-contained — the user
should be able to make a decision without opening the file. Format:

1. One sentence: topic, how many tracks ran, overall recommendation.
2. 3–5 bullets: key findings, blockers, constraints discovered — pick the most decision-relevant ones. No sub-lists, no source citations.
3. If any open questions block next steps: ask exactly ONE question now. State
   which question it is out of N total (e.g. "Question 1 of 3:"). Save the rest
   to the report — present subsequent questions one-by-one only after the user
   answers the current one.
4. One line: suggested next step with command (e.g. `/decompose-feature` or `/implement`).

Hard limit: ≤30 lines in chat. No tables, no source lists, no inline markdown citations.
The swarm-report file is for downstream pipeline stages and compaction recovery — not for the user.

### Suggest next action

Based on the research findings, propose the logical next step:

| Situation | Suggested action |
|-----------|-----------------|
| Feature is large, multiple independent parts | `/decompose-feature` — break into tasks |
| Feature is clear, single task, ready to build | `/implement` — start implementation |
| Complex approach, needs validation before coding | Plan Mode → `/multiexpert-review` |
| Research revealed a bug, not a feature need | `/bugfix-flow` — switch to bug pipeline |
| Open questions block progress | List questions, ask user to resolve before proceeding |
| Multiple viable approaches, no clear winner | Present trade-offs, ask user to choose |

Frame the suggestion as an actionable proposal, not a question:

> **Next step:** feature splits into 3 independent parts → suggesting `/decompose-feature`.
> Or if ready to code right away — `/implement`.

---

## Scope Decision Guide

| Situation | Action |
|-----------|--------|
| Topic is clear and specific | Proceed without asking |
| Topic is broad but user gave enough context to infer scope | State assumed scope, proceed |
| Topic is genuinely ambiguous (multiple valid interpretations) | Ask one clarifying question |
| Topic requires domain knowledge you lack | Ask what aspect matters most |
| User said "research everything about X" | Scope to the 3 most impactful aspects, state what was excluded |

**Default bias:** proceed rather than ask. Over-asking slows down research without
improving quality. If wrong, the auto-review step will catch major gaps.

---

## Red Flags / STOP Conditions

Stop and escalate to the user when:

- **Scope explosion** — the topic is much larger than it appeared (e.g., "research authentication"
  turns into a full security audit). Report what was found, propose narrowing.
- **Contradictory requirements** — constraints from the user conflict with each other.
  Present the conflict, ask which constraint takes priority.
- **No viable approach** — all investigated approaches have critical blockers.
  Report findings honestly rather than recommending a bad option.
- **Missing access** — research requires access to internal systems, paid APIs, or
  credentials not available. List what's needed.
- **Stale/conflicting web data** — web sources disagree significantly or information
  appears outdated. Flag uncertainty explicitly.

---

## Integration with Pipeline

This skill operates both standalone and as a stage in larger workflows:

- **Standalone** (Research profile): user asks a question, gets a report. No implementation follows.
- **Pipeline stage** (Feature/Migration profile): the `implement` skill or `code-migration` invokes
  research as Phase 0. The output artifact (`<slug>-research.md`) feeds into the Plan stage
  via the receipt-based gating protocol.
- **Recovery** (backward transition): when `multiexpert-review` returns FAIL due to missing context,
  or when implementation reveals unexpected scope, the pipeline transitions back to Research.

In all cases, the artifact location and format are the same — downstream stages read
`./swarm-report/<slug>-research.md` regardless of how research was triggered.

---

## Output Format and Location

| Artifact | Path | Purpose |
|----------|------|---------|
| Research report | `./swarm-report/<slug>-research.md` | Final synthesized findings — the receipt for the next pipeline stage |
| State file | `./swarm-report/research-<slug>-state.md` | Compaction-resilient progress tracking during investigation |
| Chat summary | — | ≤30-line user-facing output posted after the file is saved |

The research report is the primary deliverable. The state file is operational and can be
deleted after the research is complete.

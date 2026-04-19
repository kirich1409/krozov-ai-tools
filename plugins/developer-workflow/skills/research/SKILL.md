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

Full prompt templates for each expert are in **`references/expert-prompts.md`**. Load that
file and substitute `{topic}` (and `{libraries/frameworks related to topic}` where applicable)
before launching.

| Expert | Delivery | Primary tools | When to launch |
|--------|----------|---------------|----------------|
| **Codebase Expert** | Explore subagent | `ast-index search/class/usages/deps/dependents/api`, `Read`, `Grep` | Topic touches existing code |
| **Web Expert** | Available web-search tool (or training knowledge with limitation noted) | Whatever web-search tool is available in the environment | Always (mandatory) |
| **Docs Expert** | Official library/framework documentation lookup | Whatever documentation tools are available (Context7, DeepWiki, WebFetch, etc.) | Topic involves specific libraries or frameworks |
| **Dependencies Expert** | maven-mcp | `search_artifacts`, `get_latest_version`, `get_dependency_vulnerabilities`, `get_dependency_changes`, `compare_dependency_versions`, `check_multiple_dependencies` | Topic involves JVM/KMP dependencies |
| **Architecture Expert** | `architecture-expert` agent | Agent's own toolset | Topic affects module boundaries, layer design, or API contracts |

Each expert's prompt enforces: respond in the same language as the research topic description,
and include sources (URLs, documentation quotes, codebase locations) for key claims.

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

### 3.2 Draft the research report

Use the full template in **`references/synthesis-templates.md`** ("Research Artifact Template").
Required sections, in order:

1. Title + metadata (date, experts consulted)
2. Problem / Question Summary (2–3 sentences)
3. Approaches Found — 2–3 viable approaches in parallel, each with Description, Trade-offs,
   Evidence, Compatibility. Include a side-by-side comparison table when the user will pick
   between approaches.
4. Library / Dependency Recommendations (table)
5. Risks and Concerns (with severity: critical/major/minor)
6. Recommendation (the preferred approach, with reasoning tied to expert findings)
7. Open Questions
8. Sources

If only one approach is genuinely viable, state that explicitly and list the reasons other
candidates were ruled out — do not fake alternatives.

---

## Phase 4: Auto-Review

Launch the `business-analyst` agent to review the synthesized report. The reviewer has a
different perspective than the researchers — they check for completeness, product sense,
and practical viability.

The full review prompt is in **`references/synthesis-templates.md`** ("Business-Analyst Review
Prompt"). It asks the reviewer to verify trade-offs, missed alternatives, risk coverage,
recommendation support, open questions, and alignment with practical constraints.

### 4.1 Handle review findings

- **No issues** — proceed to save artifact.
- **Minor issues** — incorporate feedback into the report, note what was added.
- **Major/critical gaps** — if the gap can be filled by re-running a specific expert track,
  do so. Otherwise, add the gap to "Open Questions" and flag it for the user.

---

## Phase 5: Save Artifact

Save the final research report to `./swarm-report/<slug>-research.md`.

Update the state file status to `done`.

Present the report to the user with a brief summary of:
- How many expert tracks ran
- Key recommendation (one sentence)
- Number of open questions that need user decision

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
| Topic requires domain knowledge not available in training data or context | Ask what aspect matters most |
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

The research report is the primary deliverable. The state file is operational and can be
deleted after the research is complete.

---

## Additional Resources

- **`references/expert-prompts.md`** — full prompt templates for all 5 expert agents (Codebase,
  Web, Docs, Dependencies, Architecture).
- **`references/synthesis-templates.md`** — the research artifact structure (Phase 3.2) and the
  business-analyst review prompt (Phase 4).

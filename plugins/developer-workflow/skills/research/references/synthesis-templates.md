# Synthesis and Review Templates

Templates for Phase 3 (synthesis) and Phase 4 (auto-review) of the `research` skill.

---

## Research Artifact Template (Phase 3.2)

Save the final artifact to `./swarm-report/<slug>-research.md` using this structure:

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

## Business-Analyst Review Prompt (Phase 4)

Launch the `business-analyst` agent with the full synthesized artifact and this prompt:

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

### Handling review findings

- **No issues** — proceed to save artifact.
- **Minor issues** — incorporate feedback into the synthesized artifact, note what was added.
- **Major/critical gaps** — if the gap can be filled by re-running a specific expert track, do so. Otherwise, add the gap to "Open Questions" and flag it for the user.

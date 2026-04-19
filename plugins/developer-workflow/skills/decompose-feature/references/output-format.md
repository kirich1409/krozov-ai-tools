# Decomposition Artifact — Output Format

Save the final decomposition to `./swarm-report/<slug>-decomposition.md` using the structure
below. Placeholders in `{braces}` are filled from the gathered context and decomposition work.

```markdown
# Feature Decomposition: {name}

Date: {date}
Source: {text | URL | file | PRD | Figma}
Experts consulted: {list of agents that ran}

## Feature Summary

{2-3 sentences: what the feature does, who benefits, key constraints}

## Constraints

- {constraint 1}
- {constraint 2}

## Tasks

### Wave 1 (no dependencies)

#### T-1: {title}

- **Description:** {what needs to be done}
- **Dependencies:** none
- **Acceptance criteria:**
  - {criterion 1}
  - {criterion 2}
- **Complexity:** S | M | L
- **Suggested agent:** {agent name}
- **Module / Layer:** {module} / {layer}
- **research-recommended:** false

#### T-2: {title}
...

### Wave 2 (depends on Wave 1)

#### T-3: {title}

- **Description:** {what needs to be done}
- **Dependencies:** T-1, T-2
- **Acceptance criteria:**
  - {criterion 1}
- **Complexity:** M
- **Suggested agent:** {agent name}
- **Module / Layer:** {module} / {layer}
- **research-recommended:** false

### Wave 3 (depends on Wave 2)
...

## Dependency Graph

{text-based graph showing task relationships}

## Scope Summary

| Metric | Value |
|--------|-------|
| Total tasks | {N} |
| Small (S) | {n} |
| Medium (M) | {n} |
| Large (L) | {n} |
| Waves | {N} |
| Research needed | {n tasks} |
| Agents involved | {list} |

## Open Questions

- {Question that needs user decision}
- {Ambiguity that could not be resolved}

## Review Notes

{Summary of auto-review findings and changes made}
```

## State file template

Create the state file at `./swarm-report/decompose-<slug>-state.md` before launching expert
agents. Update it as each agent completes so work survives context compaction.

```markdown
# Decomposition State: {feature name}

Slug: {slug}
Status: gathering-context
Started: {date}

## Input
- Goal: {goal}
- Constraints: {constraints}
- Source: {text | URL | file | PRD | Figma}

## Expert Tracks
- [ ] Codebase — launched
- [ ] Architecture — {launched | skipped: reason}
- [ ] Business Analyst — {launched | skipped: reason}

## Context Findings
(populated as agents report back)

## Tasks
(populated in Phase 3)
```

The state file is operational and may be deleted after the decomposition is complete.

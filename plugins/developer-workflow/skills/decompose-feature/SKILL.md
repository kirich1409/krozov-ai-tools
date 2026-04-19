---
name: decompose-feature
description: "This skill should be used when the user asks to break a feature idea, PRD, or epic into a structured task list with dependencies, acceptance criteria, complexity estimates, and implementation order. Launches parallel expert agents to gather codebase context, architectural fit, and scope analysis, then decomposes into waves of tasks sorted by dependency order. Trigger phrases: \"break this down\", \"decompose\", \"what tasks do I need\", \"plan the feature\", \"epic\", \"what's the scope\", \"I want to add\", \"here's a PRD\", \"split into tasks\", \"task breakdown\", \"scope this out\", \"work breakdown\", \"implementation steps\", \"feature planning\". Do NOT use for: bug fixes (use debug), code review (use code-reviewer agent), research-only questions (use research), trivial single tasks, or migrations (use code-migration / kmp-migration). Produces task lists feeding into implement; output artifact can be reviewed via multiexpert-review before implementation."
---

# Decompose Feature

Break a feature idea into a structured, dependency-ordered task list. The decomposition launches
parallel expert agents to understand the codebase, evaluate architectural fit, and assess scope
before splitting work into concrete tasks with acceptance criteria and implementation waves.

**Key principle:** decomposition and implementation are separate concerns. This skill produces
a task list — it does not implement anything. Each task in the output is a self-contained unit
that can be handed to `implement` or a specialist agent independently.

---

## Phase 1: Understand Input

### 1.1 Accept and parse the feature description

The input can be any of:
- **Plain text** — a feature idea described in the conversation
- **URL** — a link to a PRD, issue, Figma design, or specification document
- **File path** — a local document with requirements
- **Inline PRD** — a structured requirements document pasted into the conversation

Extract from the input:
- **Goal** — what the feature achieves for the user (one sentence)
- **Constraints** — known boundaries (platform, deadline, dependencies, team skills)
- **Success criteria** — how to know the feature is done (if stated)
- **Non-goals** — what is explicitly out of scope (if stated)

### 1.2 Confirm scope (if ambiguous)

If the feature description is broad or could be interpreted multiple ways, state the assumed
scope and ask **one clarifying question** before proceeding. If the scope is clear — proceed
without asking.

Examples of when to ask:
- "I want to add notifications" — too broad. Ask: push notifications? In-app? Email? All?
- "Add dark mode support" — clear scope. Proceed.

### 1.3 Generate slug

Create a short kebab-case slug from the feature name for artifact naming:
`<slug>` (e.g., `user-onboarding`, `offline-sync`, `dark-mode`)

The slug is the feature name only — no prefix. File paths add their own prefixes:
- Artifact: `./swarm-report/<slug>-decomposition.md`
- State: `./swarm-report/decompose-<slug>-state.md`

---

## Phase 2: Context Gathering

Launch up to 3 expert agents **in a single message** to gather context in parallel. Each agent
works independently — never share one agent's findings with another.

### 2.1 Expert agents

Launch the following agents based on inclusion criteria below. Use the prompt templates in
`references/expert-prompts.md` verbatim, substituting `{feature goal}` and related
placeholders.

| Agent | When to include | Role |
|-------|-----------------|------|
| **Codebase Expert** (Explore subagent) | Always | Map existing code, patterns, modules, and test infrastructure relevant to the feature |
| **Architecture Expert** (architecture-expert) | Feature affects module boundaries, introduces new modules, or changes dependency direction | Evaluate architectural fit and structural changes needed |
| **Business Analyst** (business-analyst) | User-facing impact, unclear scope, or PRD/epic input | Identify MVP boundaries, missing requirements, and scope creep risks |

Full prompt templates: see `references/expert-prompts.md`.

### 2.2 State persistence

Before launching agents, create the state file at `./swarm-report/decompose-<slug>-state.md`.
The template and final output format live in `references/output-format.md`.

Update the state file as each agent completes. This ensures work survives context compaction.

---

## Phase 3: Decompose

After all expert agents complete, break the feature into concrete tasks using the gathered
context. This is the core intellectual work — not a mechanical split, but a thoughtful
decomposition based on dependencies, module boundaries, and implementation order.

### 3.1 Decomposition principles

- **One task = one logical unit of work** — a task should produce a working, testable increment
- **Tasks follow module and layer boundaries** — do not mix data layer and UI in one task
- **Dependencies are explicit** — if task B needs task A's output, say so
- **Each task is independently implementable** — given its dependencies are met, an agent can
  pick it up without additional context beyond the task description
- **Complexity is honest** — do not underestimate; account for testing and edge cases

### 3.2 Task structure

Each task must include:

| Field | Description |
|-------|-------------|
| **ID** | Sequential identifier: `T-1`, `T-2`, etc. |
| **Title** | Short descriptive name (imperative mood) |
| **Description** | What needs to be done — specific enough for an agent to implement |
| **Dependencies** | List of task IDs this task depends on (`none` if independent) |
| **Acceptance criteria** | Concrete, verifiable conditions for "done" (1-5 items) |
| **Complexity** | `S` (< 1 hour), `M` (1-4 hours), `L` (4+ hours) |
| **Suggested agent** | Which agent or skill should implement this task |
| **Module / Layer** | Which module and architectural layer this task belongs to |
| **research-recommended** | `true` if the task involves unknowns that need investigation first |

### 3.3 Research flagging

Do NOT auto-invoke the `research` skill. Instead, flag tasks that need investigation:

- Set `research-recommended: true` on tasks with significant unknowns
- Add a note explaining what needs to be researched and why
- The user or orchestrator decides when to run research — this skill only flags the need

### 3.4 GitHub issues

Do NOT create GitHub issues automatically. The decomposition artifact is the deliverable.
The user decides whether and how to create issues from it.

---

## Phase 4: Implementation Order

### 4.1 Topological sort

Order tasks by their dependency graph:

1. **Wave 1** — tasks with no dependencies (can all run in parallel)
2. **Wave 2** — tasks that depend only on Wave 1 tasks
3. **Wave 3** — tasks that depend on Wave 1 or Wave 2 tasks
4. Continue until all tasks are assigned to a wave

### 4.2 Wave optimization

Within each wave, consider:
- Tasks in the same wave can run in parallel if handled by different agents
- Group related tasks (same module, same layer) for efficient context sharing
- If a wave has too many tasks (>5), consider whether some have hidden dependencies
  that should split the wave

### 4.3 Dependency graph

Create a text-based dependency graph showing the relationships:

```
T-1 ──→ T-3 ──→ T-5
T-2 ──→ T-3     T-6 (independent)
T-2 ──→ T-4 ──→ T-5
```

---

## Phase 5: Auto-Review

Launch the `business-analyst` agent to review the decomposition for completeness, missing
tasks, scope creep, and practical viability. Use the auto-review prompt template in
`references/expert-prompts.md`.

### 5.1 Handle review findings

- **No issues** — proceed to save artifact
- **Minor issues** — incorporate feedback into the decomposition, note what was added
- **Major/critical gaps** — add missing tasks, re-sort waves, update the dependency graph.
  If a gap requires research to resolve, flag it with `research-recommended: true` rather
  than guessing

---

## Phase 6: Save Artifact

Save the final decomposition to `./swarm-report/<slug>-decomposition.md` using the output
structure in `references/output-format.md`.

Update the state file status to `done`.

Present the decomposition to the user with a brief summary of:
- Total number of tasks and wave count
- Complexity breakdown (how many S/M/L)
- Tasks flagged for research
- Number of open questions that need user decision

---

## Scope Decision Guide

| Situation | Action |
|-----------|--------|
| Feature is clear and specific | Proceed without asking |
| Feature is broad but user gave enough context to infer scope | State assumed scope, proceed |
| Feature is genuinely ambiguous (multiple valid interpretations) | Ask one clarifying question |
| Feature requires domain knowledge not available | Ask what aspect matters most |
| User said "decompose everything about X" | Scope to the core feature, state what was excluded |
| Input is a large PRD with multiple features | Decompose only the primary feature, list others as out of scope |

**Default bias:** proceed rather than ask. Over-asking slows down decomposition without
improving quality. If wrong, the auto-review step will catch major gaps.

---

## Red Flags / STOP Conditions

Stop and escalate to the user when:

- **Not a feature** — the request is a bug fix, code review, or single concrete task that
  does not need decomposition. Suggest the appropriate tool instead.
- **Scope explosion** — the feature is much larger than it appeared (e.g., "add payments"
  turns into a full payment platform). Report what was found, propose narrowing.
- **Contradictory requirements** — constraints from the user conflict with each other.
  Present the conflict, ask which constraint takes priority.
- **Missing critical context** — the feature depends on systems, APIs, or codebases that
  cannot be accessed. List what is needed.
- **Architectural incompatibility** — the architecture expert flags that the feature
  fundamentally conflicts with the current architecture. Present the conflict and options.

---

## Integration with Pipeline

This skill operates as a pre-implementation planning tool:

- **Standalone:** user has a feature idea, gets a structured task list. Can be reviewed via
  `multiexpert-review` before implementation begins.
- **Pipeline entry:** the decomposition artifact (`<slug>-decomposition.md`) provides the
  task list for `implement` to execute. Each task becomes an independent implementation
  unit.
- **Research handoff:** tasks flagged with `research-recommended: true` can be individually
  investigated via the `research` skill before implementation.

The decomposition does not replace a detailed implementation plan for individual tasks —
each task gets its own plan during the Implement stage.

---

## Output Artifacts

| Artifact | Path | Purpose |
|----------|------|---------|
| Decomposition | `./swarm-report/<slug>-decomposition.md` | Structured task list — the primary deliverable |
| State file | `./swarm-report/decompose-<slug>-state.md` | Compaction-resilient progress tracking during decomposition |

The decomposition is the primary deliverable. The state file is operational and can be
deleted after the decomposition is complete.

---

## Additional Resources

### Reference Files

- **`references/expert-prompts.md`** — verbatim prompt templates for the Codebase, Architecture,
  Business Analyst, and Auto-Review agent launches
- **`references/output-format.md`** — full decomposition artifact structure and state file
  template

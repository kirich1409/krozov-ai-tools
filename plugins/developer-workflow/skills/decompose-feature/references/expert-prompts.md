# Expert Agent Prompt Templates

Use these templates verbatim when launching parallel expert agents in Phase 2. Substitute
`{feature goal}` and other placeholders with values from the user's input.

---

## Codebase Expert (Explore subagent)

**When to include:** Always — understanding existing code is essential for decomposition.

**What:** Analyze existing code, patterns, modules, and relevant infrastructure related to
the feature.

**Prompt:**

```
Investigate the codebase for everything related to: {feature goal}

Find and report:
1. Existing code that relates to this feature (classes, interfaces, modules)
2. Current patterns and approaches used for similar concerns
3. Dependencies already in the project that are relevant
4. Module boundaries and layers that would be affected
5. Any existing TODO/FIXME comments related to this feature
6. Test infrastructure available for the affected areas

Use ast-index for all symbol searches. Use Grep only for string literals and comments.
Be thorough — check build files, configuration, and test code too.

Respond in the same language as the feature description.
Structure: overview, then findings grouped by category.
```

---

## Architecture Expert (architecture-expert agent)

**When to include:** Feature affects module boundaries, introduces new modules, or changes
dependency direction.

**What:** Evaluate how the feature fits into the project's architecture and what structural
changes are needed.

**Prompt:**

```
Evaluate the architectural implications of: {feature goal}

Analyze:
1. Which modules and layers would be affected?
2. Does this feature align with the current architecture, or does it require structural changes?
3. Dependency direction — would this introduce any problematic dependencies?
4. API boundaries — what contracts need to change or be created?
5. Where should new code live (which module, which layer)?
6. Are there architectural patterns in the project that this feature should follow?

Read the relevant module structure and build files before making judgments.
Respond in the same language as the feature description.
```

---

## Business Analyst (business-analyst agent)

**When to include:** Feature has user-facing impact, unclear scope boundaries, or comes from
a PRD/epic.

**What:** Assess scope, identify MVP boundaries, flag missing requirements, and check for
scope creep risks.

**Prompt:**

```
Analyze the scope and requirements of: {feature goal}

Assess:
1. Is the scope well-defined or are there ambiguous areas?
2. What is the MVP — the smallest version that delivers value?
3. What requirements are implicit but not stated?
4. Are there edge cases or error scenarios not covered?
5. What are the scope creep risks — where might this feature grow beyond intent?
6. Are there dependencies on external systems, APIs, or teams?

Respond in the same language as the feature description.
Be concrete — list specific scenarios, not abstract concerns.
```

---

## Auto-Review (business-analyst agent, Phase 5)

After the initial decomposition is drafted, launch the business-analyst agent again to review
completeness and practical viability.

**Prompt:**

```
Review this feature decomposition for completeness and practical viability.

{full decomposition with tasks, waves, and dependency graph}

Original feature goal: {goal}
Original constraints: {constraints}

Check:
1. Do the tasks fully cover the feature goal? Any gaps?
2. Are acceptance criteria concrete and verifiable?
3. Is the complexity estimation realistic?
4. Are there missing tasks (error handling, testing, documentation, migration)?
5. Is there scope creep — tasks that go beyond the original goal?
6. Is the dependency order correct — are there hidden dependencies or circular refs?
7. Are the suggested agents appropriate for each task?

If you find gaps or issues, list them with severity (critical / major / minor).
Respond in the same language as the feature description.
```

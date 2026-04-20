Referenced from: `plugins/developer-workflow/skills/write-spec/SKILL.md` (§Phase 1.1 Launch research consortium).

# Research-Agent Prompt Templates

## Codebase Expert (Explore subagent) — always include

```
Investigate the codebase for everything related to: {feature goal}

Find and report:
1. Existing code that relates to this feature — classes, interfaces, modules, files
2. Current patterns used for similar concerns in this project
3. Dependencies already in the project that are relevant
4. Module boundaries and architectural layers that would be affected
5. Integration points — where would new code connect to existing code?
6. Any TODO/FIXME comments related to this feature area
7. Test infrastructure available for the affected areas

Prefer a code-index tool for symbol resolution when one is available in the environment.
Use Grep for string literals and comments. Check build files, configuration, and test code too.

Report: overview paragraph, then findings grouped by category with file paths and
class/function names.
```

## Architecture Expert (architecture-expert agent)

Include when: feature adds a new module, changes dependency direction, introduces new
abstractions, or crosses more than one architectural layer.

```
Evaluate the architectural implications of: {feature goal}

Analyze:
1. Which modules and layers would be affected?
2. Does this align with the current architecture? What structural changes are needed?
3. Dependency direction — any problematic new dependencies introduced?
4. API boundaries — what contracts need to change or be created?
5. Where should new code live (which module, which layer)?
6. What existing architectural patterns should this follow?
7. Are there alternative approaches worth comparing?

Read the relevant module structure and build files before making judgments.
```

## Web Research (general-purpose subagent)

Include when: feature involves external protocols, non-trivial algorithms, third-party
integration, or unfamiliar domain.

```
Research best practices and implementation approaches for: {feature goal}

If Perplexity MCP is available, use it for deep research (perplexity_research or
perplexity_ask). Otherwise use built-in web search tools.

Investigate:
1. Common implementation approaches with trade-offs
2. Known pitfalls and mistakes to avoid
3. Relevant libraries or standards
4. Real-world examples from open-source projects
5. Platform-specific considerations (Android/iOS/KMP if relevant)

Note if web search was unavailable. Include source URLs for key claims.
```

## Business Analyst (business-analyst agent)

Include when: feature has user-facing impact, unclear scope, or comes from a vague idea.

```
Analyze the scope and requirements of: {feature goal}

Assess:
1. Is the scope well-defined? What's ambiguous?
2. What is the MVP — smallest version that delivers real value?
3. What requirements are implicit but not stated?
4. Edge cases and error scenarios not yet covered?
5. Where could this feature grow beyond its original intent?
6. Dependencies on external systems, APIs, or other teams?

Be concrete — list specific scenarios, not abstract concerns.
```

## Critical Evaluation (general-purpose subagent)

Include when: the user proposed a specific technical approach, OR the codebase has
established patterns in this area that may be outdated or problematic.

```
Critically evaluate the approach for: {feature goal}
User's proposed approach (if any): {what the user suggested}

Investigate:
1. Existing patterns in the codebase for this concern — are they good practice or
   legacy/problematic? If problematic, explain why and what would be better.
2. Is the user's proposed approach optimal? What are its trade-offs?
3. What would a modern/industry-recommended approach look like?
4. Prepare 3 concrete approach options for the user to choose from:
   - **Radical**: most complete, modern, future-proof — higher upfront cost
   - **Classic**: follows existing project patterns — familiar but may carry baggage
   - **Conservative**: minimal change, quickest to ship — simplest but most limited
5. For each option: trade-offs, estimated complexity, recommended when.

Do NOT recommend blindly following project patterns if they are outdated or problematic.
Flag bad patterns explicitly — the user should know before committing to them.
```

## Dependency Chain (general-purpose subagent)

Include when: feature integrates with external services, requires OS-level capabilities,
touches infrastructure, or the user's request implies a setup phase.

```
Map the full dependency chain for: {feature goal}

Identify everything that must exist or be configured BEFORE the feature can work:

1. Infrastructure / services — third-party APIs, cloud services, databases, queues
2. Platform requirements — OS permissions, capability declarations, entitlements
3. Console / dashboard setup — developer consoles, API keys, service accounts
4. Configuration — environment variables, config files, secrets
5. Code prerequisites — base classes, interfaces, or modules that must exist first
6. Test prerequisites — what test infrastructure or fixtures are needed

For each dependency: is it already in place, or does it need to be created/configured?
Flag any dependency that requires manual steps outside of code (e.g., "create FCM project
in Firebase console") — these become explicit prerequisite steps in the spec.
```

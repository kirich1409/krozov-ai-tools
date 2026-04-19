# Expert Agent Prompt Templates

These are the prompts to pass to each expert agent in Phase 2 of the `research` skill. Substitute `{topic}` (and `{libraries/frameworks related to topic}` where applicable) with the actual research question.

All experts receive the same instruction about output language: respond in the same language as the research topic description.

---

## Codebase Expert (Explore subagent)

**What:** Analyze existing code, patterns, dependencies, and relevant modules related to the research topic.

**How:** Launch an `Explore` subagent with instructions to use:
- `ast-index search`, `ast-index class`, `ast-index usages` — find relevant code
- `ast-index deps`, `ast-index dependents` — module relationships
- `ast-index api` — public API surface of affected modules
- `Read`, `Grep` — examine specific files and patterns

**Prompt:**

```
Investigate the codebase for everything related to: {topic}

Find and report:
1. Existing code that relates to this topic (classes, interfaces, modules)
2. Current patterns and approaches used for similar concerns
3. Dependencies already in the project that are relevant
4. Module boundaries and layers that would be affected
5. Any existing TODO/FIXME comments related to this topic

Use ast-index for all symbol searches. Use Grep only for string literals and comments.
Be thorough — check build files, configuration, and test code too.

Respond in the same language as the research topic description. Structure: overview, then findings grouped by category.
```

---

## Web Expert

**What:** Search the web for approaches, best practices, common pitfalls, and real-world examples — if web search is available.

**How:** If web search is available, look for approaches and best practices; find recent articles and community discussions. If web search is not available, note this as a limitation in the research report.

**Prompt:**

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

---

## Docs Expert

**What:** Find official documentation for involved libraries and frameworks.

**How:** Look up official documentation for the libraries involved; fetch API reference and usage examples.

**Prompt:**

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

---

## Dependencies Expert (maven-mcp)

**What:** Check compatibility, versions, vulnerabilities, and alternatives for JVM/KMP dependencies.

**How:** Use maven-mcp tools:
- `search_artifacts` — find candidate libraries
- `get_latest_version` — current versions
- `get_dependency_vulnerabilities` — security issues
- `get_dependency_changes` — release notes, changelog entries between versions
- `compare_dependency_versions` — semver delta comparison between versions
- `check_multiple_dependencies` — batch version checks

**Prompt:**

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

---

## Architecture Expert (architecture-expert agent)

**What:** Evaluate how the research topic fits into the project's architecture — module boundaries, dependency direction, API design implications.

**How:** Launch the `architecture-expert` agent with context about the topic.

**Prompt:**

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

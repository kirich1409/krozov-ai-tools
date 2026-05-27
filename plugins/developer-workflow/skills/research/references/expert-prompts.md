# Research Consortium — Expert Prompt Templates

Use these prompts verbatim when launching each expert agent in Phase 2. Each agent runs independently — never share one agent's findings with another.

> **Intentional overlap with the `write-spec` skill.** The Codebase / Architecture / Web
> prompts here overlap with `../../write-spec/references/research-prompts.md`, where they
> appear as an enriched superset. This skill instead splits Docs and Dependencies into their
> own dedicated tracks (below). The two files are kept separate **on purpose** so each skill
> stays self-contained — do not merge them into a shared file.

All prompts must include this line: *"Respond in the same language as the research topic description."*

---

## Codebase Expert (Explore subagent)

Use a structured code-index tool when available (resolves classes, usages, dependencies, API by symbol). Fall back to `Grep` + `Read` if no index — same report structure either way.

```
Investigate the codebase for everything related to: {topic}

Find and report:
1. Existing code that relates to this topic (classes, interfaces, modules)
2. Current patterns and approaches used for similar concerns
3. Dependencies already in the project that are relevant
4. Module boundaries and layers that would be affected
5. Any existing TODO/FIXME comments related to this topic

Use a code-index tool for symbol resolution when one is available; fall back to
Grep + Read otherwise. Check build files, configuration, and test code too.

Respond in the same language as the research topic description. Structure: overview,
then findings grouped by category.
```

---

## Web Expert

Conditional track — launch only when the topic needs an external perspective (industry practices, third-party library best practices, benchmarks, post-mortems). Skip for purely internal questions. If web search is unavailable but the track was selected, note it as a limitation in the report.

```
Research: {topic}

If web search is available, investigate:
1. Common approaches and best practices (with trade-offs for each)
2. Known pitfalls and mistakes to avoid
3. Real-world examples from open-source projects
4. Recent developments or changes (last 12 months)
5. Community consensus — what does the majority recommend and why?

If web search is unavailable, note this as a limitation and rely on training knowledge
where possible.

Respond in the same language as the research topic description. Include source URLs
for key claims.
```

---

## Docs Expert

```
Find official documentation for: {libraries/frameworks related to topic}

For each library/framework:
1. API reference, guides, changelogs
2. Migration guides, compatibility notes, configuration options, known limitations
3. Version-specific documentation if version matters

Respond in the same language as the research topic description. Quote relevant
sections. Note gaps where documentation is missing or unclear.
```

---

## Dependencies Expert (maven-mcp)

Available tools: `search_artifacts`, `get_latest_version`, `get_dependency_vulnerabilities`, `get_dependency_changes`, `compare_dependency_versions`, `check_multiple_dependencies`.

```
Analyze dependencies related to: {topic}

Investigate:
1. Current versions of relevant libraries and their latest available versions
2. Known vulnerabilities in current or candidate dependencies
3. Compatibility matrix — what works with what (Kotlin version, KMP targets, AGP)
4. Alternative libraries that serve the same purpose — compare by maturity,
   maintenance activity, KMP support, community size
5. Breaking changes in recent versions

Respond in the same language as the research topic description. Include specific
version numbers and groupId:artifactId coordinates.
```

---

## Architecture Expert (architecture-expert agent)

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

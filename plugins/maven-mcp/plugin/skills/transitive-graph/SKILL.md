---
name: transitive-graph
description: >-
  Use when the user asks to "show me the dependency tree for X", "what does this library
  pull in transitively", "full transitive graph of Y", "what does adding this dependency
  bring with it", or wants the resolved dependency graph (nodes and edges) for a single
  Maven artifact.
---

# Transitive Graph

Fetch the resolved transitive dependency graph for one Maven GAV via deps.dev.

## Steps

1. Parse `groupId`, `artifactId`, `version` (all required — this tool needs one specific,
   already-known version; there is no "latest" shortcut).

2. Call **`get_transitive_graph`** with `groupId`, `artifactId`, `version`.

3. Present the result:
   - `nodes` — every `{groupId, artifactId, version}` in the graph
   - `edges` — `{from, to}` pairs, indices into `nodes` (render as an indented tree or a
     `groupId:artifactId:version → groupId:artifactId:version` list, whichever fits the
     size better)
   - If `partial: true` (deps.dev unreachable, returned an error, or the graph was
     truncated by the node cap) — say so explicitly; do not present a partial graph as
     complete.

## Constraints and non-goals

- Not for finding version conflicts across a whole project's dependencies — use
  `/dependency-conflicts`, which unions graphs like this one across every direct
  dependency.
- Not for a project's own declared (non-transitive) dependencies — use
  `/scan-project-dependencies`.

## Known limitations

deps.dev resolves in isolation from this one root — project-level `dependencyManagement`,
Gradle `ResolutionStrategy` / strict versions / exclusions are not modeled. State this when
the graph is used to make a decision (e.g. "is X actually on the classpath").

## Fallback (MCP unavailable only)

No practical manual fallback — hand-walking a transitive Maven/Gradle resolution from POMs
is impractical to reproduce correctly. Tell the user the live graph is unavailable rather
than guessing at transitive contents.

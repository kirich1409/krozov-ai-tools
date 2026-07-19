---
name: dependency-conflicts
description: >-
  Use when the user asks "do I have conflicting dependency versions", "is there a diamond
  dependency problem", "which libraries resolve to more than one version", "check for
  version conflicts across my project", or wants to know whether two paths in the
  dependency graph pull in incompatible versions of the same library.
---

# Dependency Conflicts

Detect Maven/Gradle coordinates (`groupId:artifactId`) that appear at more than one version
across a project's dependency graph, and report which version wins.

## Steps

1. Call **`detect_dependency_conflicts`** with `projectPath` (default: cwd) and optional
   `buildSystem` (`maven` or `gradle`) to override auto-detection.

   - **Gradle projects** compare versions across Gradle-resolved scan usages
     (`resolvedBy: "gradle"`) — mediation is `highest-wins`.
   - **Maven projects** fetch a deps.dev transitive graph per versioned direct dependency
     and union `groupId:artifactId → {versions seen}` — mediation is `nearest-wins` (BFS
     depth from each direct root; same-depth ties break to the highest version).

2. Present each conflict: the GA, `versions` seen, `resolvedTo` (what wins), `strategy`,
   and `risk` (`high`/`medium`/`low`). Sort by risk descending.

**No conflicts found:** say so; do not speculate about hidden ones.

## Known limitations

For Maven, this unions per-root deps.dev graphs resolved **in isolation** — it
approximates but is not a full project-wide resolve. Project `dependencyManagement`,
Gradle `ResolutionStrategy` / strict versions / `enforcedPlatform`, exclusions, and
private/unpublished coordinates are not modeled. Surface `notes[]` / per-root `errors[]` /
`partial` from the result when present rather than treating the report as exhaustive.

## Fallback (MCP unavailable only)

For Gradle, `./gradlew <module>:dependencies --configuration <name>` already prints
conflict resolution (`-> x.y.z` annotations) — read that output directly instead of
reimplementing mediation by hand. For Maven, `mvn dependency:tree -Dverbose` shows omitted
conflicting versions. Prefer the real build tool's own resolution over a hand-rolled graph
walk in both cases.

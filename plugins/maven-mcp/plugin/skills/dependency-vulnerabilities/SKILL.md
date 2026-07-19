---
name: dependency-vulnerabilities
description: >-
  Use when the user names one or a few specific dependencies (with version) — not a whole
  project — and asks "does io.ktor:ktor-server-core 3.1.0 have any known vulnerabilities",
  "check this library for CVEs before I add it", "is this version affected by any GHSA", or
  wants an OSV.dev vulnerability check for coordinates that may not even be in a build file
  yet. For scanning an entire Gradle/Maven project's declared dependencies use
  /check-deps-vulnerabilities instead.
---

# Dependency Vulnerabilities

Check specific, already-known Maven coordinates (groupId:artifactId:version) for known
CVE/GHSA advisories via OSV.dev — for artifacts the user names directly, not a project
scan.

## Steps

1. Parse `groupId`, `artifactId`, `version` for each dependency named by the user.

2. Call **`get_dependency_vulnerabilities`** with:
   - `dependencies`: `[{groupId, artifactId, version}, ...]` (capped at 100 items)
   - optional `projectPath` — improves Gradle plugin-marker resolution (a marker
     coordinate like `{id}:{id}.gradle.plugin` is resolved to its real implementation GAV
     before querying OSV, since OSV indexes the implementation, not the marker)

3. Present per-dependency findings: `id`, `severity`, `summary`, `fixedVersion`. Sort
   CRITICAL → HIGH → MEDIUM → LOW → unknown. Link advisories as
   `https://osv.dev/vulnerability/{id}`.

   **`malicious: true`** on any finding is a distinct, stronger signal than a CVE severity
   (OSSF Malicious Packages convention) — call it out separately and first; recommend
   removing the dependency rather than just tracking the CVE.

**No findings:** say so plainly.

**Disclaimer (always mention once):** OSV does not cover shaded/uber JARs — a dependency
bundled inside a fat JAR may carry CVEs this check will not surface.

## Constraints and non-goals

- Not for "are my project's dependencies vulnerable" with no specific coordinates in hand —
  use `/check-deps-vulnerabilities`, which resolves the project via `gradlew` first.

## Fallback (MCP unavailable only)

POST the coordinates to `https://api.osv.dev/v1/querybatch`, then **hydrate** each unique
returned id with `GET https://api.osv.dev/v1/vulns/{id}` before reporting
severity/summary/fixedVersion — the bare querybatch response (`{id, modified}` only) is not
enough to report severity. Note that Gradle plugin-marker resolution is skipped on this
path.

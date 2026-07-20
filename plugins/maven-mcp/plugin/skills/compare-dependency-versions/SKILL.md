---
name: compare-dependency-versions
description: >-
  Use when the user gives one or more dependencies together with their CURRENT version and
  asks "is my version of X behind latest", "how far behind is 3.0.0", "what upgrade type
  would this be — major, minor, or patch", "classify the version jump from A to B", or wants
  upgrade-type classification for specific coordinates outside of a full project scan.
---

# Compare Dependency Versions

Compare one or more Maven dependencies' current version against the latest available and
classify the upgrade as `major` / `minor` / `patch` / `none`.

## Steps

1. Parse `groupId`, `artifactId`, `currentVersion` for each dependency from the user's
   message (or from context, e.g. a version noticed in a build file).

2. Call **`compare_dependency_versions`** with:
   - `dependencies`: `[{groupId, artifactId, currentVersion}, ...]`
   - optional `projectPath`

3. Present per-dependency: current → latest, `latestStability`, `upgradeType`,
   `upgradeAvailable`. Use the `summary` block (`total`, `upgradeable`, `major`, `minor`,
   `patch`) for a one-line rollup when comparing more than a couple of dependencies.

**No upgrade available for any entry:** say so plainly; do not propose edits.

## Constraints and non-goals

- Not for scanning a whole project's build files for outdated dependencies — use
  `/check-deps` (which also offers to apply the updates).
- Not for a version with no current baseline to compare against — use `/latest-version` or
  `/check-multiple-versions`.

## Fallback (MCP unavailable only)

Fetch `maven-metadata.xml` per artifact, pick the highest version reachable from
`currentVersion` under prefer-stable rules, and classify the semver diff yourself
(major/minor/patch by first differing segment). Skips project-declared private repos.

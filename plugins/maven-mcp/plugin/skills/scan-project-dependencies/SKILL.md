---
name: scan-project-dependencies
description: >-
  Use when the user asks to "list my project's dependencies", "what dependencies does this
  project declare", "show me all the libraries in this build file", "extract dependencies
  from my Gradle/Maven project", or wants a raw inventory of declared coordinates without
  checking for updates or vulnerabilities. Does not fetch latest versions — see /check-deps
  for that.
---

# Scan Project Dependencies

Extract the dependencies a project declares in its build files — Gradle
(`build.gradle[.kts]`, version catalogs) or Maven (`pom.xml`) — as a raw inventory, with no
version-freshness or vulnerability checking.

## Steps

1. Call **`scan_project_dependencies`** with `projectPath` (default: cwd).

   For a Gradle project, this resolves production `*RuntimeClasspath` configurations via the
   project's own `gradlew` and merges build-file provenance (catalog alias, source file,
   usages) onto the Gradle-resolved coordinates — `resolvedBy: "gradle"` in the result means
   versions came from actual Gradle resolution (BOM/platform/constraints applied), not
   regex-guessed. A Maven-only project (no `gradlew`) is parsed from `pom.xml` directly.

2. Present the inventory grouped by `source.kind` (`catalog-library` / `catalog-plugin` /
   `module-direct` / `plugins-dsl` / `buildscript-classpath` / `gradle-resolved`), each with
   its declared/resolved version, module, and configuration.

3. Surface `deadRepositoryHints` when present (e.g. a lingering `jcenter()` declaration —
   read-only since 2021, fully sunset).

## Constraints and non-goals

- Not for checking whether any of these are outdated or vulnerable — use `/check-deps` or
  `/audit-project-dependencies`, which call this tool internally and add version/CVE data.
- Not for the resolved transitive closure of a single dependency — use `/transitive-graph`.

## Fallback (MCP unavailable only)

Glob/Read build files (`build.gradle*`, `settings.gradle*`, `pom.xml`,
`gradle/libs.versions.toml`) and regex-extract coordinates yourself. State that this skips
Gradle-resolved effective versions (BOM/platform/constraints) and dead-repository hints.

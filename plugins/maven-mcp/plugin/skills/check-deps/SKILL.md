---
name: check-deps
description: >-
  Use when the user asks to "check deps", "check dependencies",
  "outdated dependencies", "update dependencies", "are my deps up to date", "scan for updates",
  "find outdated libraries", "upgrade dependencies", or wants to know which Maven/Gradle
  dependencies have newer versions available. Resolves the Gradle project via gradlew and
  reports available updates.
---

# Check Dependencies

Scan the current project and report which dependencies have newer versions available, then
apply the updates the user confirms. Prefer the plugin MCP tools — they use project-declared
repositories, version classification, and OSV hydration already implemented in the server.

## Step 1 — Audit via MCP (preferred)

Call **`audit_project_dependencies`** with:

- `projectPath` — project root (default: cwd)
- `includeVulnerabilities` — `true` by default; set `false` if the user only wants updates
- `productionOnly` — `true` by default; set `false` to include test-scoped deps

This single call resolves production dependencies through Gradle (`./gradlew dependencies` /
`buildEnvironment`), merges build-file provenance (catalogs, module paths, plugin DSL), looks
up latest versions against project repos, and optionally queries OSV. Requires `gradlew` at
the project root.

Alternatively, when you only need the declared list first:

1. `scan_project_dependencies` → extract coordinates
2. `compare_dependency_versions` with `{groupId, artifactId, currentVersion}` per entry
3. `get_dependency_vulnerabilities` for versioned coordinates (optional)

Do **not** hand-parse `maven-metadata.xml` or POST to OSV yourself while MCP tools work.

## Step 2 — Build the report

From the audit / compare results, only include entries where an upgrade is available
(`upgradeType` ≠ `none`, or `latestVersion` ≠ `currentVersion`). Group by `source.kind`:

- **catalog-library** / **catalog-plugin** — alias, current → latest, upgrade type, catalog file, usages
- **module-direct** — module, file, artifact, current → latest, configuration; flag catalog drift
- **plugins-dsl** — split settings `pluginManagement` vs root/module `plugins {}`
- **buildscript-classpath** — artifact, current → latest, file; note legacy style
- **gradle-resolved** — Gradle-resolved direct dependency with no matching build-file provenance

When `resolvedBy: "gradle"` is present on the scan/audit result, versions are Gradle-resolved
(effective versions from BOM/platform/constraints), not regex-guessed from build files.

**Terminal branch — nothing outdated and no vulnerabilities:**

> All dependencies up to date.

Stop — do not continue to edit steps.

**Vulnerabilities:** after upgrade tables, add a **Vulnerabilities** section for every entry
with non-empty `vulnerabilities`. Use server fields (`id`, `severity`, `summary`,
`fixedVersion`, `malicious`) — do not re-derive severity from a raw querybatch response.
Sort CRITICAL → HIGH → MEDIUM → LOW → unknown. Omit the section when empty.

Surface `resolvedFrom.viaPublicFallback` when true (coordinate missing from declared repos).
Surface `deadRepositoryHints` from the scan/audit when present (e.g. `jcenter()`).

## Step 3 — Confirmation

Present the full report and **ask before making any edits**. Default proposal: update
catalog entries first. Ask separately for non-catalog groups. Flag every MAJOR upgrade
explicitly.

## Step 4 — Edit pass

Apply only the groups the user confirms. Touch only version values:

- Catalog — `[versions]` or inline version in `[libraries]` / `[plugins]`
- Module direct / Plugin DSL / Buildscript — inline version string in the build file
- pom.xml — `<version>` inside the matching `<dependency>`

### Catalog-aware edits (`catalog_entry`, #288)

Gradle has **no** built-in command to update `gradle/libs.versions.toml`. Before adding
or renaming catalog aliases, call **`catalog_entry`**:

- **Upgrade existing alias** — `mode: "generate"` with the same alias + new `version` and
  the current `catalogToml`. Prefer the returned `suggestedDiff` (usually a single
  `[versions]` key bump). Do not rewrite the whole file.
- **Add a library/plugin** — `mode: "generate"` with `coordinate` + `kind`. Use the
  returned `alias` / `accessor` / `suggestedDiff` as-is (kebab-case alias, reserved-segment
  safe, `libs.x` or `alias(libs.plugins.x)`).
- **Sanity-check before/after** — `mode: "validate"` with `catalogToml` and, when editing
  build scripts, `buildContent`. Fix any `violations` (reserved aliases, invalid first
  subgroups, `id(libs.plugins.x)` misuse, `libs` inside `subprojects {}` / `buildscript {}`).

Hard rules when editing catalogs by hand:

- Default catalog path is exactly `gradle/libs.versions.toml`.
- Plugins: `alias(libs.plugins…)` — never `id(libs.plugins…)`.
- Do not use reserved aliases (`extensions` / `class` / `convention`) or first segments
  `bundles` / `versions` / `plugins` (e.g. `versions-foo` is invalid; `versionsFoo` or
  `foo-versions` is fine).

## Step 5 — Build verification

After every edit pass:

- **Gradle:** `./gradlew build` (or a faster resolve check when a full build is slow)
- **Maven:** `mvn dependency:tree`

Surface failures immediately. Attempt trivial fixes; otherwise revert that entry and note
"manual upgrade required". **Never report "versions updated" without a passing build.**

## Constraints and non-goals

- Major version bumps require explicit per-entry confirmation.
- Direct production dependencies only — Gradle `dependencies` tree roots, not full transitive closure.
- This skill does not auto-select unstable/pre-release versions (server uses prefer-stable).
- Requires a Gradle wrapper (`gradlew`); Maven-only projects are out of scope for this scan path.

## Fallback (MCP unavailable only)

If MCP tools cannot be called: Glob/Read build files, extract GAVs, fetch public
`maven-metadata.xml` (Central / Google / Plugin Portal), classify versions, and optionally
POST OSV `/v1/querybatch` then hydrate via `GET /v1/vulns/{id}`. State clearly that
project-private repos, plugin-marker→implementation resolution, and server-side cache are
skipped.

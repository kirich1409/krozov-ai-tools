---
name: check-version-compatibility
description: >-
  Use when the user asks "is AGP 8.2 compatible with Gradle 8.4", "will this Kotlin version
  work with my AGP", "what Gradle version does this AGP need", "check Spring Boot BOM
  compatibility for my dependencies", "do I need to migrate javax to jakarta", or wants to
  validate a set of Android/Kotlin/Gradle/Spring Boot toolchain versions against each other
  before upgrading.
---

# Check Version Compatibility

Validate whether a set of versions is mutually compatible: Android Gradle Plugin ↔ Gradle ↔
JDK, Kotlin Gradle Plugin ↔ Gradle/AGP, Spring Boot BOM-managed versions, and javax→jakarta
migration need.

## Steps

1. Gather whichever of these the user is asking about:
   - `android`: `{agp, gradle, kotlin, jdk}` — any subset
   - `springBoot`: a version string
   - `dependencies`: `[{groupId, artifactId, version?}, ...]` (capped at 100 items) —
     checked against the Spring Boot BOM (when `springBoot` is set) and, when Spring Boot ≥
     3.0.0, flagged for javax→jakarta coordinate replacements

2. Call **`check_version_compatibility`** with whichever of `android`, `springBoot`,
   `dependencies`, `projectPath` apply. At least one of `android`/`springBoot`/`dependencies`
   should be present — an empty call has nothing to validate.

3. Present the result:
   - `compatible: true` with no `conflicts` → confirm compatibility plainly.
   - Each conflict: `kind`, `requested`, `expected`, `suggestion`, `reference` (an official
     doc URL) — always show the suggestion and reference together, never a bare
     "conflict".
   - Print any `notes[]` (coverage caveats) alongside the result, not as an afterthought.

## Known limitations

Coverage is intentionally bounded — AGP 7.0–9.2 lines, KGP 1.9.20–2.4.0 bands, no
published AGP max-Gradle (only min enforced), javax→jakarta is a coordinate heuristic (not
a bytecode scanner), Spring Cloud release trains are not a separate matrix. State the
specific gap when a requested version falls outside shipped coverage — never imply
"compatible" from silence.

## Constraints and non-goals

- Not for applying the suggested version bumps — that's a normal edit; verify with
  `/check-deps` or a project build afterward.

## Fallback (MCP unavailable only)

Check the official compatibility tables directly: Android Gradle Plugin release notes
(developer.android.com) for AGP↔Gradle↔JDK, the Kotlin Gradle plugin compatibility guide
for KGP↔Gradle/AGP, and the Spring Boot release notes / dependency versions page for
BOM-managed versions. Do not guess a compatibility matrix from memory — this stack changes
across releases.

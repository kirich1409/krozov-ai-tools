---
name: check-version-exists
description: >-
  Use when the user asks "does version X exist", "is version 3.2.0 released for okhttp",
  "check if this version is published", "was this version ever released", "check version
  exists", or provides a full groupId:artifactId:version and wants to confirm that exact
  version is available in a Maven repository — not what the latest is (use /latest-version
  for that).
---

# Check Version Exists

Confirm whether one specific, already-known version of a Maven artifact exists in any
resolvable repository.

## Steps

1. Parse `groupId`, `artifactId`, `version` from the user's input (e.g.
   `com.squareup.okhttp3:okhttp:4.12.0`, or a groupId:artifactId plus a version mentioned in
   conversation).

2. Call **`check_version_exists`** with:
   - `groupId`, `artifactId`, `version`
   - optional `projectPath` when the user is inside a project (uses declared repos)

3. Present the result:
   - `exists: true` — show `stability` and `repository` (which repo answered), and
     `relocatedTo` when present (the artifact was relocated via a Maven
     `<distributionManagement>` POM — tell the user the new coordinates).
   - `exists: false` — tell the user the version was not found in any resolvable
     repository. Do not guess a reason; offer `/latest-version` to check what *is*
     available, or `/search-artifacts` if the artifact name itself may be wrong.

## Error handling

Tool error / not found → report as-is, do not invent a version or existence status from
memory.

## Constraints and non-goals

- Not for "what's the latest version of X" — use `/latest-version`.
- Not for "is my current version behind latest" — use `/compare-dependency-versions`.
- Not for checking many artifacts at once — use `/check-multiple-versions`.

## Fallback (MCP unavailable only)

Fetch `maven-metadata.xml` from public repos (Maven Central → Google Maven → Gradle Plugin
Portal) and check whether `version` is present in the `<versions>` list. Note that this
skips project-declared private repos and relocation detection.

---
name: latest-version
description: >-
  Use when the user asks to "find the latest version", "what version is",
  "current version of", "what's the latest", "check version", "find version", or provides a
  groupId:artifactId and wants version information. Finds the latest version of a Maven artifact.
---

# Latest Version

Find the latest version of a Maven artifact via the plugin MCP server (project-aware
repository resolution, cache, relocation detection).

## Arguments

The user provides `groupId:artifactId`, for example:
- `io.ktor:ktor-server-core`
- `org.jetbrains.kotlin:kotlin-stdlib`
- `com.google.dagger:hilt-android`

## Steps

1. Parse the user's input to extract `groupId` and `artifactId` (split by `:`).
   If the input has no `:`, ask the user to provide it in `groupId:artifactId` form.

2. **Call `get_latest_version`** with:
   - `groupId`, `artifactId`
   - optional `stabilityFilter`: `PREFER_STABLE` (default), `STABLE_ONLY`, or `ALL`
   - optional `projectPath` when the user is inside a project (uses declared repos)

3. Present the tool result:
   - `latestVersion` and `stability`
   - `allVersionsCount` when useful
   - `resolvedFrom` (which repo answered; note `viaPublicFallback` if true)
   - `relocatedTo` when present — surface the new coordinates clearly

   Example:

   ```
   ## io.ktor:ktor-client-core

   Latest: 3.1.3 (STABLE)
   Resolved from: https://repo1.maven.org/maven2 (dependency)
   ```

## Error handling

- If the tool reports not found / error, tell the user and suggest checking spelling.
  Do **not** invent a version from memory.
- Optional: `verify_coordinates` with the same GA if the user may have hallucinated the name.

## Fallback (MCP unavailable only)

If `get_latest_version` cannot be called, fetch `maven-metadata.xml` from public repos
(Maven Central → Google Maven for Android/Google groups → Gradle Plugin Portal for
`.gradle.plugin` markers), parse `<version>` / `<latest>` / `<release>`, and pick the
highest stable version. Note that this path **skips project-declared private repos** and
relocation detection — say so when reporting.

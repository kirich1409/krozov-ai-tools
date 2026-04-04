---
name: latest-version
description: >-
  This skill should be used when the user asks to "find the latest version", "what version is",
  "current version of", "what's the latest", "check version", "find version", or provides a
  groupId:artifactId and wants version information. Finds the latest version of a Maven artifact.
---

# Latest Version

Find the latest version of a specific Maven artifact.

## Arguments

The user provides `groupId:artifactId`, for example:
- `io.ktor:ktor-server-core`
- `org.jetbrains.kotlin:kotlin-stdlib`
- `com.google.dagger:hilt-android`

## Steps

1. Parse the user's input to extract `groupId` and `artifactId` (split by `:`).

2. Call the `get_latest_version` MCP tool (from maven-mcp server) with:
   - `groupId`: extracted group ID
   - `artifactId`: extracted artifact ID
   - `stabilityFilter`: `PREFER_STABLE` (default)

3. Display the result:
   - Latest stable version
   - Latest version (if different from stable)
   - All available versions (abbreviated if more than 10)

## Error Handling

- If the artifact is not found, suggest checking the groupId and artifactId spelling.
- If the format is wrong (no `:`), ask the user to provide `groupId:artifactId`.

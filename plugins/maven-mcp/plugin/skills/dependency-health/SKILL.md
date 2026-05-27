---
name: dependency-health
description: >-
  Use when evaluating whether to adopt a Maven dependency: "is X maintained",
  "health of dependency", "check library health", "is this library active",
  "dependency activity", "GitHub stars", "is this abandoned", "release cadence",
  "dependency maintenance", "license of library", or when the dependency-evaluator
  agent needs raw maintenance signals for a library. Fetches latest version,
  stability, GitHub activity, issue dynamics, license, and archived status.
---

# Dependency Health

Assess the maintenance health of one or more Maven dependencies before adopting them.

## Arguments

The user provides one or more `groupId:artifactId` coordinates, optionally with a specific version:
- `io.ktor:ktor-server-core`
- `com.squareup.okhttp3:okhttp:4.12.0`

## Steps

1. Parse each coordinate into `groupId`, `artifactId`, and optional `version`.

2. Call the `get_dependency_health` MCP tool (from maven-mcp server) with:
   ```json
   {
     "dependencies": [
       { "groupId": "...", "artifactId": "...", "version": "..." }
     ]
   }
   ```
   `version` is optional — omit it to assess the latest available version.

3. For each result in `results[]`, present the signals in this order:

   **Identity & version**
   - `groupId:artifactId` — `latestVersion` (`stability`)
   - `versionCount` versions published; last Maven publish: `lastPublishedToMaven`

   **Repository**
   - GitHub URL from `repository.url`, or `scm.url` for non-GitHub forges.
   - If `github` is null and `healthError` is set, note the error briefly and skip the GitHub section.

   **Activity** (from `github`)
   - Stars / forks / archived status
   - Last commit: `lastCommit` — compute "N months ago" relative to today
   - Last release: `lastRelease`; release cadence: `releaseCadenceDays` days
   - License: `license`

   **Issues** (from `github.issues` — may be null if rate-limited)
   - Open / closed, close ratio, median days to close
   - If `issues` is null, note that issue stats were unavailable (rate limit or network).

   **Signals**
   - List every entry in `signals[]` as bullet points. These are the pre-computed red flags
     (archived repo, no stable release, slow issue response, etc.).

4. Do NOT interpret signals or issue an adopt/reject verdict in this skill. The raw signals
   are the output. If the user wants an adopt/reject recommendation, suggest calling the
   `dependency-evaluator` agent (from developer-workflow-experts) with the signals as input.

## Error handling

- `healthError` set with `github: null` — no public GitHub repo or rate-limited;
  present the Maven data that was retrieved and note what is missing.
- Tool unavailable — stop and tell the user:

  > The `get_dependency_health` tool is not available in the current session.
  > Check that the maven-mcp MCP server is running and registered, then retry.

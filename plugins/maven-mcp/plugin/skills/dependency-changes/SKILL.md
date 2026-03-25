---
name: dependency-changes
description: Show what changed between two versions of a Maven/Gradle dependency — fetches release notes, changelog entries, and GitHub releases for the version range. Use when the user says "what changed", "show changelog", "release notes", "what's new in version X", "what broke in the upgrade", "before I update show me", or provides two versions of a dependency and wants to know what's different. Also trigger when the user has just seen dependency update suggestions (from check-deps) and wants to review changes before committing to an upgrade.
---

# Dependency Changes

Show what changed between two versions of a Maven artifact — release notes, changelog entries, and links to GitHub releases.

## Input formats

The user can provide versions in several ways:

- **Explicit range:** "what changed in io.ktor:ktor-client-core from 2.3.0 to 3.1.3"
- **After check-deps:** "show me the changelog for the ktor upgrade" — infer from the update table in the conversation
- **Single artifact, one version:** "what's new in compose-bom 2025.01.00" — ask for the from-version, or assume the user's current version if visible in context

## Steps

1. Parse `groupId`, `artifactId`, `fromVersion`, `toVersion` from the user's input or conversation context.

   If `fromVersion` is missing and the current version is visible in context (e.g., from a check-deps table), use it. Otherwise ask.

2. Call the `get_dependency_changes` MCP tool:
   ```json
   {
     "groupId": "io.ktor",
     "artifactId": "ktor-client-core",
     "fromVersion": "2.3.0",
     "toVersion": "3.1.3"
   }
   ```

3. Present the results:

   **If changes have release notes (`body`)** — render each version as a section:
   ```
   ## io.ktor:ktor-client-core — 2.3.0 → 3.1.3

   ### 3.1.3
   <release notes body>
   [Release](https://github.com/...)

   ### 3.1.2
   <release notes body>
   ...
   ```

   **If changes exist but have no body** — show versions as a list with links where available:
   ```
   ## io.ktor:ktor-client-core — 2.3.0 → 3.1.3
   Versions in range: 3.1.3, 3.1.2, 3.1.1, 3.1.0, 3.0.3, ...
   No release notes available. Changelog: <changelogUrl if present>
   ```

   **If many versions in range (>6)** — collapse the middle:
   > Showing notes for 3.1.3, 3.1.2, 3.1.1 ... (8 more) ... 3.0.0

## Error handling

- **`repositoryNotFound: true`** — the tool couldn't locate a GitHub repo or known changelog source. Tell the user: "Couldn't find a changelog for `groupId:artifactId`. You can check the project's GitHub or release page manually." Include the Maven Central artifact URL as a starting point.
- **`error` field set** — surface the message and suggest checking the groupId/artifactId/version spelling.
- **`fromVersion` equals `toVersion`** — tell the user the versions are the same, nothing to show.

## Context: used after check-deps

When the user runs `check-deps` and sees an update table, they may then ask "show me what changed for X" without re-typing the artifact coordinates. In that case, pull `groupId`, `artifactId`, `currentVersion` (→ fromVersion), and the `Latest Stable` column (→ toVersion) from the table in context rather than asking the user to repeat them.

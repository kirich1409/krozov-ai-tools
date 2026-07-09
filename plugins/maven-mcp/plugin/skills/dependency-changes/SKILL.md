---
name: dependency-changes
description: Show what changed between two versions of a Maven/Gradle dependency — fetches release notes, changelog entries, and GitHub releases for the version range. Use when the user says "what changed", "show changelog", "release notes", "what's new in version X", "what broke in the upgrade", "before I update show me", or provides two versions of a dependency and wants to know what's different. Also trigger when the user has just seen dependency update suggestions (from check-deps) and wants to review changes before committing to an upgrade.
---

# Dependency Changes

Show what changed between two versions of a Maven artifact by fetching release notes and
changelog data.

## Preferred — MCP

1. Parse `groupId`, `artifactId`, `fromVersion`, `toVersion` from the user or conversation
   (e.g. a prior check-deps table). If `fromVersion` is missing, ask or use the current
   version from context. If `fromVersion` equals `toVersion`, say there is nothing to show.

2. Call **`get_dependency_changes`** with:
   - `groupId`, `artifactId`
   - `fromVersion` (exclusive)
   - `toVersion` (inclusive)
   - optional `projectPath`

   The server discovers the GitHub repo and fetches releases using `GITHUB_TOKEN`
   server-side when present — never pass the token in headers yourself.

3. Present the tool result: versions in range, release notes / bodies, links. If notes are
   sparse, still show the version list plus GitHub releases / Maven Central URLs from the
   response. Collapse the middle when many versions are returned.

## Context: used after check-deps

When the user asks "show me what changed for X" after an update table, pull coordinates and
current → latest versions from that table without re-asking.

## Error handling

- **No GitHub repo / no notes** — say so and provide the Maven Central artifact URL.
- **Rate limited** — note the limit; retry via `get_dependency_changes` (server-side token)
  rather than attaching a token to a client request.
- **Artifact not found** — suggest checking spelling; do not invent changelog text.

## Fallback (MCP unavailable only)

If the tool cannot be called: fetch the POM for SCM, public `maven-metadata.xml` for the
version list, then unauthenticated GitHub `/releases` (and optionally raw CHANGELOG.md).
Do **not** add `Authorization` / `GITHUB_TOKEN` on the client. State that project-private
repos are skipped. If rate-limited, say so and stop.

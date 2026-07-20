---
name: search-artifacts
description: >-
  Use when the user asks to "find a library for X", "search maven central for JSON parsing
  libraries", "what's the artifact id for Y", "look up an artifact by keyword", or doesn't
  know the exact groupId:artifactId and wants to search by keyword or partial coordinate.
---

# Search Artifacts

Search for Maven artifacts by keyword or partial coordinate when the exact
`groupId:artifactId` isn't known.

## Steps

1. Take the user's search phrase as `query` — a keyword (`"json parsing"`) or partial
   coordinate (`"okhttp"`, `"com.squareup:okhttp"`).

2. Call **`search_artifacts`** with:
   - `query`
   - optional `limit` (default 10, clamped to [1, 100])
   - optional `repositoryType` (`auto` / `nexus` / `artifactory` / `central`) — leave as
     `auto` unless the user is on a closed/offline repository manager and wants to force a
     backend
   - optional `projectPath` for mirror/closed-mode resolution

3. Present `results` as a table: `groupId:artifactId`, `latestVersion`, `versionCount`. If
   `searchBackendUnavailable` is present instead of results, say which backend was tried
   and that the search could not be served (not "no results found").

4. If `capabilityUnavailable` is present alongside empty `results`, the Central search
   backend itself failed — say so explicitly instead of "no results found", and
   distinguish the reason: `rate_limited` (Sonatype is throttling — a temporary
   condition, worth retrying shortly), `blocked` (a bulk-load lockout — do not retry
   aggressively), or `unreachable` (the backend could not be reached — a transient
   outage or transport failure).

## Constraints and non-goals

- Not for confirming a coordinate you already believe is correct isn't hallucinated —
  that's the write-time guard hook's job (`verify_coordinates`), not a conversational
  search.

## Fallback (MCP unavailable only)

Query the public Solr endpoint directly:
`https://search.maven.org/solrsearch/select?q={query}&rows={limit}&wt=json`. Note that
this skips closed-mode Nexus/Artifactory routing and any mirror configuration.

---
name: dependency-health
description: >-
  Use when evaluating whether to adopt a Maven dependency: "is X maintained",
  "health of dependency", "check library health", "is this library active",
  "dependency activity", "GitHub stars", "is this abandoned", "release cadence",
  "dependency maintenance", or "license of library". Fetches latest version,
  stability, GitHub activity, issue stats, license, and archived status.
  Do NOT use for an adopt/avoid recommendation — present raw signals only; the
  caller (or user) weighs them.
---

# Dependency Health

Assess the maintenance health of one or more Maven dependencies.

## Preferred — MCP

Call **`get_dependency_health`** with:

```json
{
  "dependencies": [
    {"groupId": "io.ktor", "artifactId": "ktor-server-core"},
    {"groupId": "com.squareup.okhttp3", "artifactId": "okhttp", "version": "4.12.0"}
  ],
  "projectPath": "<optional project root>"
}
```

The server resolves Maven metadata (project-aware repos), discovers the GitHub repo from
POM SCM / groupId heuristics, and fetches GitHub signals using `GITHUB_TOKEN` server-side
when present — never pass the token in headers yourself.

Present the tool fields as raw signals (do not invent an adopt/reject verdict):

- Version: latest / stability / version count / last Maven publish / `resolvedFrom`
- Repository: GitHub URL, license, stars, forks, archived, last commit / release, cadence
- Issues: open / closed / close ratio when present
- `signals` — list red flags from the tool as bullet points

**No GitHub data:** state what Maven data was returned and link
`https://search.maven.org/artifact/{groupId}/{artifactId}`.

## Important constraints

- Do NOT issue an adopt/reject verdict — present raw signals only.
- Degrade gracefully when GitHub is rate-limited or missing.
- Prefer `get_dependency_health` so any configured `GITHUB_TOKEN` stays server-side
  (5000 req/h vs 60 unauthenticated). Never hand-roll `Authorization: Bearer` headers.

## Fallback (MCP unavailable only)

If the tool cannot be called: fetch public `maven-metadata.xml` + POM, then unauthenticated
GitHub REST (`/repos`, `/releases`, search issues). Do **not** put `GITHUB_TOKEN` on a
command line or in WebFetch headers. Note that project-private repos are skipped.
Unauthenticated GitHub is fine (lower rate limit); if rate-limited, say so and stop.

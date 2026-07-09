---
name: dependency-health
description: >-
  Use when evaluating whether to adopt a Maven dependency: "is X maintained",
  "health of dependency", "check library health", "is this library active",
  "dependency activity", "GitHub stars", "is this abandoned", "release cadence",
  "dependency maintenance", or "license of library". Fetches latest version,
  stability, GitHub activity, issue dynamics, license, and archived status.
  Do NOT use for an adopt/avoid recommendation — present raw signals only; the
  caller (or user) weighs them.
---

# Dependency Health

Assess the maintenance health of one or more Maven dependencies.

**Preferred:** call the `get_dependency_health` MCP tool for each coordinate. The
server resolves Maven metadata, discovers the GitHub repo, and fetches GitHub
signals using `GITHUB_TOKEN` server-side when present — never pass the token in
headers yourself.

**Fallback** (MCP tool unavailable): query Maven Central and GitHub via HTTP as
below. Do **not** add an `Authorization` header or put `GITHUB_TOKEN` on a
command line — WebFetch cannot set auth headers, and shelling out with the token
leaks it into transcripts/process args. Unauthenticated GitHub calls are fine
(lower rate limit); if rate-limited, say so and stop.

## Arguments

The user provides one or more `groupId:artifactId` coordinates, optionally with a specific version:
- `io.ktor:ktor-server-core`
- `com.squareup.okhttp3:okhttp:4.12.0`

## Steps

For each dependency, execute steps 1–5 in parallel where possible.

### 1. Fetch Maven metadata

Build the group path: replace `.` with `/` in the groupId.

Fetch from Maven Central:
```
https://repo1.maven.org/maven2/{group_path}/{artifactId}/maven-metadata.xml
```

For Android/Google artifacts (`androidx.*`, `com.google.android.*`, `com.android.*`,
`com.google.firebase.*`), also try:
```
https://dl.google.com/dl/android/maven2/{group_path}/{artifactId}/maven-metadata.xml
```

Extract:
- All `<version>` entries → total version count
- `<latest>` and `<release>` tags → determine current stable and latest versions
- `<lastUpdated>` → last publish date (format: `YYYYMMDDHHMMSS`)

Classify the latest version for stability (STABLE / RC / BETA / ALPHA) using the same
rules as the `/latest-version` skill.

### 2. Fetch POM to find GitHub repo and license

Fetch the POM for the latest version:
```
https://repo1.maven.org/maven2/{group_path}/{artifactId}/{version}/{artifactId}-{version}.pom
```

Extract:
- `<scm><url>` or `<scm><connection>` → GitHub owner/repo
- `<licenses><license><name>` → license name

If no SCM URL in POM, guess from groupId:
- `io.github.{owner}.*` → `github.com/{owner}/{artifactId}`
- `com.github.{owner}.*` → `github.com/{owner}/{artifactId}`

### 3. Fetch GitHub repository info

If a GitHub repo was identified:

```
GET https://api.github.com/repos/{owner}/{repo}
```

Do not attach `Authorization` / `GITHUB_TOKEN` here (see Preferred path above).

Extract: `stargazers_count`, `forks_count`, `archived`, `pushed_at` (last commit date),
`license.name` (use this if POM license was missing), `open_issues_count`.

### 4. Fetch recent releases

```
GET https://api.github.com/repos/{owner}/{repo}/releases?per_page=20
```

From the releases list:
- `published_at` of the most recent release → last release date
- Compute release cadence: median days between the last 5 releases

### 5. Assess issue health (optional — skip if rate-limited)

GitHub's REST API does not expose closed issue counts directly. Use the Search API:

```
GET https://api.github.com/search/issues?q=repo:{owner}/{repo}+type:issue+state:closed&per_page=1
```

This returns `total_count` for closed issues. Combine with `open_issues_count` from step 3
to compute a close ratio. **Note:** This endpoint is heavily rate-limited (30 req/min with
token, 10 without). If it returns 403/429, skip this step and note issue stats as unavailable.

### 6. Present results

For each dependency, show signals in this order:

**Identity & version**
```
## groupId:artifactId

Latest stable: {version} ({stability})
Versions published: {count}
Last Maven publish: {date}
```

**Repository** (if found)
```
GitHub: https://github.com/{owner}/{repo}
License: {license}
Stars: {stars} | Forks: {forks} | Archived: yes/no
Last commit: {date} ({N months ago})
Last release: {date}
Release cadence: ~{N} days between releases
```

**Issues** (if available)
```
Open issues: {N} | Closed: {M} | Close ratio: {X}%
```

**Signals** — list any red flags as bullet points:
- Archived repository — no further development
- No stable release available
- Last commit more than 12 months ago
- Last release more than 18 months ago
- Release cadence slower than 365 days
- Close ratio below 50% (more issues open than ever closed)
- Only 1 version published (may indicate abandoned project)

**No GitHub repo found:**
- State what Maven data was retrieved
- Note that GitHub signals are unavailable
- Provide Maven Central URL: `https://search.maven.org/artifact/{groupId}/{artifactId}`

## Important constraints

- Do NOT issue an adopt/reject verdict — present raw signals only.
- If the user wants a recommendation, suggest they weigh the signals themselves.
- Degrade gracefully: if GitHub is unavailable or rate-limited, present Maven-only data
  and note what is missing.
- Prefer `get_dependency_health` so any configured `GITHUB_TOKEN` stays server-side
  (5000 req/h vs 60 unauthenticated). Never hand-roll `Authorization: Bearer` headers.

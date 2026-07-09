---
name: dependency-changes
description: Show what changed between two versions of a Maven/Gradle dependency — fetches release notes, changelog entries, and GitHub releases for the version range. Use when the user says "what changed", "show changelog", "release notes", "what's new in version X", "what broke in the upgrade", "before I update show me", or provides two versions of a dependency and wants to know what's different. Also trigger when the user has just seen dependency update suggestions (from check-deps) and wants to review changes before committing to an upgrade.
---

# Dependency Changes

Show what changed between two versions of a Maven artifact by fetching release notes and
changelog data.

**Preferred:** call the `get_dependency_changes` MCP tool with
`groupId`, `artifactId`, `fromVersion`, and `toVersion`. The server discovers the
GitHub repo and fetches releases using `GITHUB_TOKEN` server-side when present —
never pass the token in headers yourself.

**Fallback** (MCP tool unavailable): follow the HTTP steps below. Do **not** add an
`Authorization` header or put `GITHUB_TOKEN` on a command line — WebFetch cannot set
auth headers, and shelling out with the token leaks it into transcripts/process args.
Unauthenticated GitHub calls are fine (lower rate limit); if rate-limited, say so
and stop.

## Input formats

The user can provide versions in several ways:

- **Explicit range:** "what changed in io.ktor:ktor-client-core from 2.3.0 to 3.1.3"
- **After check-deps:** "show me the changelog for the ktor upgrade" — infer from the
  update table in the conversation.
- **Single artifact, one version:** "what's new in compose-bom 2025.01.00" — ask for the
  from-version, or assume the user's current version if visible in context.

## Steps

### 1. Parse input

Extract `groupId`, `artifactId`, `fromVersion`, `toVersion` from the user's input or
conversation context.

If `fromVersion` is missing and the current version is visible in context (e.g., from a
check-deps table), use it. Otherwise ask.

### 2. Discover GitHub repository

Find the GitHub owner/repo for this artifact using one of these strategies in order:

**a. Fetch the POM file** to extract the SCM URL:
```
https://repo1.maven.org/maven2/{group_path}/{artifactId}/{toVersion}/{artifactId}-{toVersion}.pom
```
(Convert groupId dots to slashes for `group_path`.)

Look for `<scm><url>` or `<scm><connection>` in the POM XML. Extract the GitHub owner/repo
from URLs like `https://github.com/owner/repo` or `scm:git:github.com/owner/repo.git`.

**b. Guess from groupId** if POM has no SCM info:
- `io.github.{owner}.*` → `{owner}/{artifactId}`
- `com.github.{owner}.*` → `{owner}/{artifactId}`
- `org.{word}.*` → try `{word}/{artifactId}`

**c. Use Maven Central search** as fallback:
```
https://search.maven.org/solrsearch/select?q=g:{groupId}+AND+a:{artifactId}&rows=1&wt=json
```
The `response.docs[0]` may include a project URL field.

### 3. Determine versions in range

Fetch `maven-metadata.xml` from Maven Central:
```
https://repo1.maven.org/maven2/{group_path}/{artifactId}/maven-metadata.xml
```

Extract all `<version>` entries between `fromVersion` (exclusive) and `toVersion`
(inclusive), sorted newest-first. If there are more than 20 versions in the range, note
the count and show only the first and last 5.

### 4. Fetch GitHub release notes

If a GitHub repo was found:

```
https://api.github.com/repos/{owner}/{repo}/releases?per_page=100
```

Do not attach `Authorization` / `GITHUB_TOKEN` here (see Preferred path above).
Unauthenticated GitHub allows 60 requests/hour — this call counts as one.

Match each version in the range to GitHub release tags. Common tag patterns:
`v{version}`, `{version}`, `{artifactId}-{version}`, `release-{version}`.

Collect matching releases and their `body` fields.

### 5. Check for CHANGELOG.md

If the GitHub repo is known, fetch the raw changelog file:
```
https://raw.githubusercontent.com/{owner}/{repo}/HEAD/CHANGELOG.md
```
(Also try `CHANGELOG.md`, `CHANGES.md`, `HISTORY.md`.)

If found, extract sections for versions in the range. A section header typically looks like
`## [3.1.3]`, `## 3.1.3`, or `### Version 3.1.3`.

### 6. Present results

**If release notes exist** — render each version as a section:
```
## io.ktor:ktor-client-core — 2.3.0 → 3.1.3

### 3.1.3
<release notes body>
[Release](https://github.com/...)

### 3.1.2
<release notes body>
```

**If no release notes / CHANGELOG found** — show a version list and the project URL:
```
## io.ktor:ktor-client-core — 2.3.0 → 3.1.3

Versions in range: 3.1.3, 3.1.2, 3.1.1, 3.1.0 (4 versions)
No release notes found.
GitHub: https://github.com/{owner}/{repo}/releases
Maven: https://search.maven.org/artifact/{groupId}/{artifactId}
```

**If many versions in range (>6)** — collapse the middle:
> Showing notes for 3.1.3, 3.1.2, 3.1.1 ... (8 more) ... 3.0.0

## Error handling

- **No GitHub repo found** — tell the user a GitHub repo could not be determined for the
  artifact, and provide the Maven Central artifact URL as a starting point:
  `https://search.maven.org/artifact/{groupId}/{artifactId}`
- **GitHub API rate limited (HTTP 403/429)** — note that the limit is reached and suggest
  retrying via `get_dependency_changes` (uses server-side `GITHUB_TOKEN` when configured)
  rather than attaching the token to a client request.
- **fromVersion equals toVersion** — tell the user the versions are the same, nothing to show.
- **Artifact not found in Maven Central** — suggest checking spelling.

## Context: used after check-deps

When the user runs `check-deps` and sees an update table, they may ask "show me what changed
for X" without re-typing coordinates. Pull `groupId`, `artifactId`, current version
(→ fromVersion), and latest version (→ toVersion) from the table in context.

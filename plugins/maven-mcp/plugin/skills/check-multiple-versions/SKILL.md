---
name: check-multiple-versions
description: >-
  Use when the user provides a list of several groupId:artifactId coordinates (with no
  current version to compare against) and asks "what are the latest versions of these
  libraries", "look up versions for this list", "batch check these dependencies", "what
  version should I use for each of these", or is considering adding a handful of new
  libraries and wants their latest versions before picking one. For updating an existing
  project's declared dependencies use /check-deps instead.
---

# Check Multiple Versions

Batch-resolve the latest version for several Maven artifacts at once — for artifacts the
user is evaluating or about to add, not for auditing an existing project's declared
dependencies and not for comparing against a *current* version.

## Steps

1. Parse a list of `groupId:artifactId` pairs from the user's message.

2. Call **`check_multiple_dependencies`** with:
   - `dependencies`: `[{groupId, artifactId}, ...]`
   - optional `projectPath` when the user is inside a project (uses declared repos)

   Note: unlike `/latest-version`, this tool has no `stabilityFilter` override — it always
   selects PREFER_STABLE. Call `get_latest_version` per-artifact instead if the user needs
   `STABLE_ONLY` or `ALL` for one of them.

3. Present a table: artifact → latest version → stability → resolved-from repo. Entries
   with an `error` (e.g. no version found) are shown separately with the error message —
   never silently dropped.

## Constraints and non-goals

- Not for a single artifact — use `/latest-version`.
- Not for comparing against versions already in the project — use
  `/compare-dependency-versions` or `/check-deps`.

## Fallback (MCP unavailable only)

Fetch `maven-metadata.xml` per artifact from public repos and pick the highest stable
version from each. Skips project-declared private repos.

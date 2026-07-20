---
name: dependency-license
description: >-
  Use when the user asks "what license does this library use", "is this dependency GPL",
  "check the license of X before I add it", "what's the SPDX id for this artifact", or
  wants license intelligence (SPDX id, category, plain-English notes) for one or more
  specific Maven dependencies — direct lookup, not a transitive-closure scan.
---

# Dependency License

Resolve license intelligence for one or more Maven dependencies directly: SPDX id, license
category, plain-English notes, and where the data came from.

## Steps

1. Parse `groupId`, `artifactId`, and optionally `version` for each dependency (when
   `version` is omitted, the latest preferred-stable version is used).

2. Call **`get_dependency_license`** with `dependencies: [{groupId, artifactId, version?}, ...]`
   (capped at 100 items) and optional `projectPath`.

3. Present per dependency: `spdxId`, `name`, `category` (`permissive` / `weak-copyleft` /
   `strong-copyleft` / `network-copyleft` / `proprietary` / `unknown`), `notes`, and
   `source` (`pom` / `github` / `spdx-normalized`). Call out `unknown` or any
   copyleft/`proprietary` category explicitly — do not bury it in a table row.

## Constraints and non-goals

- Not for checking the full transitive closure of a dependency against a project's license
  policy — use `/license-compliance`.
- Do not issue an adopt/avoid verdict from the category alone — present it as a raw signal
  and let the user (or their license policy) decide, same convention as
  `/dependency-health`.

## Fallback (MCP unavailable only)

Fetch the POM and read `<licenses><license><name>/<url>`; optionally check the GitHub
repo's `license.spdx_id` via the unauthenticated REST API. Category classification
(permissive vs copyleft) then has to be done by hand against a known SPDX list — state that
this is a manual judgment call on this path, not the server's static lookup table.

---
name: audit-project-dependencies
description: >-
  Use when the user asks for "a full dependency audit", "audit my project for outdated,
  vulnerable, and non-compliant licenses in one report", "comprehensive dependency report",
  "give me everything on my dependencies at once", or wants one combined report covering
  version freshness, vulnerabilities, and (optionally) license posture in a single call,
  rather than three separate checks.
---

# Audit Project Dependencies

Run one combined dependency audit: scan the project, check for available updates,
optionally query OSV.dev for vulnerabilities, and optionally add license categorization —
in a single tool call instead of chaining `/scan-project-dependencies` +
`/compare-dependency-versions` + `/dependency-vulnerabilities` + `/dependency-license` by
hand.

## Steps

1. Call **`audit_project_dependencies`** with:
   - `projectPath` (default: cwd)
   - `includeVulnerabilities` — default `true`
   - `productionOnly` — default `true` (excludes test-scope dependencies)
   - `includeLicenses` — default `false`; set `true` when the user wants license posture
     in the same report (adds extra POM/GitHub fetches, so it's opt-in)

2. Present the report:
   - Upgrade table from `dependencies[]` (current → latest, `upgradeType`), grouped by
     `source.kind` like `/check-deps` does.
   - Vulnerabilities section for any entry with non-empty `vulnerabilities[]`, sorted by
     severity; call out `malicious: true` findings first.
   - When `includeLicenses` was set, a `licenses` section (`summary.byCategory`,
     `uniqueSpdxIds`, `hasProprietaryOrCopyleft`) plus `newLicenseCategories` — categories
     that appear exactly once in the scanned set (e.g. one AGPL dependency in an otherwise
     Apache/MIT tree).
   - Lead with the `summary` block (`total`, `upgradeable`, `vulnerable`, `major`, `minor`,
     `patch`) as the headline, details below.

3. Follow the same confirm-before-edit discipline as `/check-deps` if the user wants
   updates applied — this skill's job is the combined report, not unattended edits.

## Constraints and non-goals

- Not for only checking for updates — `/check-deps` is narrower and offers to apply them.
- Not for only checking vulnerabilities against a whole project —
  `/check-deps-vulnerabilities`.
- Not for a single named dependency outside project context —
  `/check-multiple-versions`, `/compare-dependency-versions`, `/dependency-vulnerabilities`,
  or `/dependency-license`.

## Fallback (MCP unavailable only)

Compose the fallbacks of `/scan-project-dependencies`, `/compare-dependency-versions`, and
`/dependency-vulnerabilities` (plus `/dependency-license` when licenses were requested) by
hand. State clearly that this loses the single-call dedup (metadata/POM fetches are no
longer cached across the three checks).

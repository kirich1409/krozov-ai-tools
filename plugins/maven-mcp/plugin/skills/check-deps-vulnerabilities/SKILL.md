---
name: check-deps-vulnerabilities
description: >-
  Use when the user asks to "check vulnerabilities",
  "scan CVEs", "check dependency vulnerabilities", "are my dependencies
  vulnerable", "security audit dependencies", "find CVEs in deps", "OSV scan",
  or wants to know which Maven/Gradle dependencies have known CVE/GHSA
  advisories. Scans build files (including Gradle/Maven submodules) and reports
  vulnerabilities via OSV.dev.
---

# Check Dependency Vulnerabilities

Scan the current Maven/Gradle project for known CVE/GHSA advisories on declared
dependencies and offer remediation through targeted version updates.

## Step 1 — Collect coordinates via MCP (preferred)

**Option A (full audit):** call `audit_project_dependencies` with
`includeVulnerabilities: true` and `productionOnly: true` (unless the user asks to include
test scopes). Use the per-dependency `vulnerabilities` from the result.

**Option B (vulns only):**

1. Call `scan_project_dependencies` with `projectPath` (default cwd).
2. Keep production-scoped, versioned coordinates (exclude test configurations unless asked).
3. Call **`get_dependency_vulnerabilities`** with those `{groupId, artifactId, version}`
   entries (and `projectPath` so Gradle plugin markers resolve to implementation GAVs).

Use the tool output fields as-is: `id`, `summary`, `severity`, `fixedVersion`, `malicious`,
and `resolvedImplementation` when present. Do **not** re-derive severity/summary from a raw
OSV querybatch response while the MCP tool works.

## Step 2 — Build the report

Filter to dependencies with non-empty vulnerabilities.

Sort: CRITICAL → HIGH → MEDIUM → LOW → unknown, then lexicographic by
`groupId:artifactId`.

Render a markdown table (one row per dependency × finding):

| Source file | Artifact | Current | Severity | CVE/GHSA | Summary | Fixed in |
|-------------|----------|---------|----------|----------|---------|----------|

Link advisories as `https://osv.dev/vulnerability/{id}`.

**Summary line:**
`Total: N findings across M packages (X critical, Y high, Z medium, W low).`
`Scanned: K dependencies total. Test configurations excluded.`

**If none:**
> No known vulnerabilities found in production dependencies. (Scanned K dependencies. Test configurations were excluded.)

Then stop — no remediation prompt.

**Disclaimer (always print once):**
> Note: OSV does not cover shaded/uber JARs. Dependencies bundled inside a fat JAR may
> carry CVEs that this scan will not surface.

## Step 3 — Remediation

When at least one finding exists, ask the user — one question, four options:

1. **Update all** — upgrade every vulnerable package to its recommended fixed version.
2. **Update CRITICAL + HIGH only** — leave MEDIUM/LOW for later.
3. **Show details for a specific CVE/GHSA** — ask which one; prefer the hydrated fields
   already returned, or fetch `https://api.osv.dev/v1/vulns/{id}` only if more detail is needed.
4. **Report only** — make no changes.

**Recommended fixed version per package:** `max(fixedVersion)` across findings for that GA.
If every finding lacks `fixedVersion`, list under "Manual upgrade required".

## Step 4 — Apply updates

When the user picks option 1 or 2:

1. Edit only the version value in the catalog / build file / pom.xml.
2. **MANDATORY:** run the project build (`./gradlew build` or `mvn compile`).
3. On success, report what was updated and which advisories each upgrade closes.
4. On failure, attempt a trivial fix or revert that entry; re-run the build.

**Never report "vulnerabilities patched" without a passing build.**

## Known limitations

State when relevant:

- Test / build / annotation-processor configurations excluded by default.
- Transitive dependencies are not scanned — only scanner-declared coordinates.
- OSV coverage for unresolved Gradle plugin markers is limited; the MCP tool resolves
  markers to implementation GAVs when possible.
- Composite builds via `includeBuild` may be incomplete.

## Fallback (MCP unavailable only)

Glob/Read build files, extract production GAVs, POST
`https://api.osv.dev/v1/querybatch`, then **hydrate** each unique id with
`GET https://api.osv.dev/v1/vulns/{id}` before reporting severity/summary/fixedVersion.
Bare querybatch `{id, modified}` is not enough. Note that plugin-marker resolution and
project-repo awareness are skipped on this path.

## Language

This SKILL.md is in English. Runtime output follows the user's chat language. CVE/GHSA
identifiers, package coordinates, and version numbers stay in their original form.

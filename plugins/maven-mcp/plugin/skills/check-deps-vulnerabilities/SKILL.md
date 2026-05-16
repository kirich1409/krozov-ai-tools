---
name: check-deps-vulnerabilities
description: >-
  This skill should be used when the user asks to "check vulnerabilities",
  "scan CVEs", "check dependency vulnerabilities", "are my dependencies
  vulnerable", "security audit dependencies", "find CVEs in deps", "OSV scan",
  or wants to know which Maven/Gradle dependencies have known CVE/GHSA
  advisories. Scans build files (including Gradle/Maven submodules) and reports
  vulnerabilities via OSV.dev.
---

# Check Dependency Vulnerabilities

Scan the current Maven/Gradle project for known CVE/GHSA advisories on its
declared dependencies (including submodules), grouped by severity, and offer
remediation through targeted version updates.

## Preflight

Before doing anything else, confirm the `audit_project_dependencies` MCP tool
is available. If it is not, stop and tell the user:

> The maven-mcp plugin is required for this skill. Install it with
> `claude plugin add maven-mcp`, then retry.

Do not attempt to fall back to manual web searches — this skill requires the
MCP server.

## Steps

1. Call the MCP tool with the default flags:

   ```json
   {
     "includeVulnerabilities": true,
     "productionOnly": true
   }
   ```

   Do not pass any other parameters unless the user explicitly asks for
   test/build configurations (then set `productionOnly: false`).

2. Filter the response to entries where `vulnerabilities` is non-empty. Drop
   the rest from the report (still mention the total scanned count in the
   summary).

3. Sort findings by severity desc, then by `groupId:artifactId` asc:

   - `CRITICAL` → `HIGH` → `MEDIUM` → `LOW` → unknown (`undefined`)
   - Within a band: lexicographic order of `groupId:artifactId`.

4. Render the findings as a markdown table. One row per `(module, finding)`:

   | Module | Artifact | Current | Severity | CVE/GHSA | Fixed in |
   |--------|----------|---------|----------|----------|----------|
   | `:app` | `org.apache.logging.log4j:log4j-core` | 2.14.1 | CRITICAL | GHSA-jfh8-c2jp-5v3q | 2.17.1 |

   - `Module`: `dep.module` if set; otherwise `(root)`.
   - `Artifact`: `groupId:artifactId`.
   - `CVE/GHSA`: the OSV `id` (link it if the chat client renders Markdown links).
   - `Fixed in`: `dep.vulnerabilities[*].fixedVersion`; if absent, write
     `(no fixed version)`.

5. Print a one-line summary after the table:

   `Total: N findings across M packages (X critical, Y high, Z medium, W low).`

   `M` counts distinct `groupId:artifactId` strings (a single package
   accumulating multiple CVEs counts once).

6. If `vulnerabilities` is empty for every dependency, print:

   `No known vulnerabilities found in production dependencies. (Test/build configurations were excluded.)`

   Then stop — no remediation prompt.

7. Print this disclaimer verbatim once, immediately after the summary:

   > Note: OSV does not cover shaded/uber JARs. Dependencies bundled inside
   > a fat JAR may carry CVEs that this scan will not surface.

## Remediation

When at least one finding exists, ask the user with `AskUserQuestion` — one
question, exactly four options, in this order:

1. **Update all** — upgrade every vulnerable package to its recommended fixed
   version.
2. **Update CRITICAL + HIGH only** — leave MEDIUM/LOW for later.
3. **Show details for a specific CVE/GHSA** — when chosen, ask which one,
   then call `get_dependency_vulnerabilities` for that single GAV and present
   the full advisory text + reference URL.
4. **Report only** — make no changes.

### Recommended fixed version per package

Per package, the recommended fixed version is `max(fixedVersion)` across all
findings for that `groupId:artifactId` — a single bump must close every CVE
the package carries. If a finding has no `fixedVersion`, exclude that finding
from the max computation; if every finding for the package lacks a
`fixedVersion`, the package cannot be auto-remediated — list it under a
"Manual upgrade required" subsection instead of editing.

## After updating versions

When the user picks option 1 or 2:

1. Edit the build files (`gradle/libs.versions.toml`, `build.gradle[.kts]`,
   or `pom.xml`) to apply the recommended versions. Touch only the lines that
   own the vulnerable dependency — do not reformat or reorder unrelated
   entries.

2. **MANDATORY: Run the project build to verify compatibility.** Do NOT skip
   this step.

   - Gradle: `./gradlew build` (or `./gradlew assembleDebug` for Android).
   - Maven: `mvn compile`.
   - Wait for the build to complete fully.

3. **If the build succeeds:** report success, list which dependencies were
   updated and which CVE/GHSA each upgrade closes.

4. **If the build fails:**
   - Read the build error output carefully.
   - Identify which upgraded dependency caused the incompatibility.
   - Try to fix the incompatibility (API changes, import updates, deprecation
     replacements).
   - If the fix is non-trivial, revert that specific dependency to its
     previous version and surface the CVE as "manual upgrade required".
   - Re-run the build to confirm it passes.
   - Report which packages were updated, which were reverted, and why.

5. **Never report "vulnerabilities patched" without a passing build.** The
   remediation is not complete until the project compiles successfully.

## Language

This SKILL.md is in English. The runtime output (tables, summary, prompts)
should follow the user's chat language. CVE/GHSA identifiers, package
coordinates, and version numbers stay in their original form regardless of
language.

## Known limitations

State these once at the top of the report when relevant:

- Test, build, and annotation-processor configurations (`testImplementation`,
  `kapt`, `ksp`, `annotationProcessor`, etc.) are excluded by default. Pass
  `productionOnly: false` to include them.
- Submodule discovery uses default Gradle layout (`:foo:bar` →
  `foo/bar/build.gradle[.kts]`). Modules with
  `project(":foo").projectDir = file(...)` overrides and Gradle composite
  builds (`includeBuild`) are not scanned.
- Transitive dependencies are not enumerated — only direct declarations in
  build files. A direct dependency that pulls a vulnerable transitive will
  not appear in the report; investigate via `./gradlew dependencies` /
  `mvn dependency:tree` when in doubt.
- Android variant-prefixed configurations (`releaseImplementation`,
  `debugImplementation`, `<flavor>ReleaseImplementation`, etc.) ship in the
  final artifact but are not recognized by the underlying parser today, so
  CVEs declared only on variant-specific configurations are silently
  invisible to this scan. Workaround: declare security-critical deps on
  plain `implementation` / `api`, or run `./gradlew dependencies` for the
  target variant and audit the result manually.
- OSV does not cover shaded/uber JARs.

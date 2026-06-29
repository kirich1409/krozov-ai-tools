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

## Step 1 — Discover build files

Use Glob to find all build files in the project:

```
**/libs.versions.toml
**/build.gradle.kts
**/build.gradle
**/pom.xml
```

Exclude files under `.gradle/`, `build/`, `.idea/`, `node_modules/`, and any path
containing `/build/`.

Read each found file with the Read tool.

## Step 2 — Extract declared dependencies

Parse each file to collect `groupId`, `artifactId`, and `version` for every production
dependency. Default: exclude test-scoped entries (see Scopes section). If the user passes
`productionOnly: false`, include them.

### Version catalogs (`libs.versions.toml`)

In the `[versions]` section, collect `key = "value"` pairs as a version map.

In the `[libraries]` section, each entry has one of these forms:
```toml
alias = "group:artifact:version"
alias = { group = "...", name = "...", version = "..." }
alias = { group = "...", name = "...", version.ref = "key" }
```
Resolve `version.ref` entries using the version map.

In the `[plugins]` section:
```toml
alias = { id = "...", version = "..." }
alias = { id = "...", version.ref = "key" }
```
Convert plugin ID to Maven coordinates: `groupId = id`, `artifactId = "{id}.gradle.plugin"`.

### Gradle build files (`build.gradle.kts` / `build.gradle`)

Match patterns like:
```
implementation("group:artifact:version")
api("group:artifact:version")
compileOnly("group:artifact:version")
runtimeOnly("group:artifact:version")
```
Also the Kotlin DSL map form:
```
implementation(group = "...", name = "...", version = "...")
```

Skip entries that reference version catalog variables (e.g. `libs.ktor.client.core`) —
those versions are already captured from the catalog.

**Production scopes** (include): `implementation`, `api`, `compileOnly`, `runtimeOnly`,
`compile`, `runtime`, `provided`, `releaseImplementation`, `debugImplementation`.

**Test scopes** (exclude by default): `testImplementation`, `testApi`,
`androidTestImplementation`, `kaptTest`, `kaptAndroidTest`, `testCompileOnly`,
`testRuntimeOnly`.

### Maven POM files (`pom.xml`)

Match entries inside `<dependencies>`:
```xml
<dependency>
  <groupId>...</groupId>
  <artifactId>...</artifactId>
  <version>...</version>
  <scope>...</scope>
</dependency>
```

**Production scopes** (include): `compile` (default), `runtime`, `provided`.
**Exclude**: `test`, `system`.

### Plugins blocks

Match `plugins { id("...") version "..." }` and `id("...") version "..."` lines.
Convert the plugin ID to Maven coordinates as above.

## Step 3 — Deduplicate

After parsing all files, deduplicate by `groupId:artifactId:version`. Keep track of
which file each dependency came from for the report.

## Step 4 — Query OSV.dev for vulnerabilities

Send a batch request to OSV.dev for all unique `groupId:artifactId:version` combinations.

**Request:**
```
POST https://api.osv.dev/v1/querybatch
Content-Type: application/json

{
  "queries": [
    {
      "package": {
        "name": "{groupId}:{artifactId}",
        "ecosystem": "Maven"
      },
      "version": "{version}"
    },
    ...
  ]
}
```

OSV.dev accepts up to 1000 entries per batch. If there are more, split into multiple
requests and merge results.

**Response:**
```json
{
  "results": [
    {
      "vulns": [
        {
          "id": "GHSA-xxxx-xxxx-xxxx",
          "summary": "...",
          "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/..."}],
          "affected": [
            {
              "ranges": [
                {
                  "type": "ECOSYSTEM",
                  "events": [
                    {"introduced": "0"},
                    {"fixed": "2.17.1"}
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

The `results` array corresponds 1:1 to the `queries` array. For each result:
- If `vulns` is empty or missing, the dependency has no known advisories.
- For each vuln, extract:
  - `id` — advisory identifier (GHSA-... or CVE-...)
  - `summary` — short description
  - `severity` — derive from CVSS score: ≥9.0 CRITICAL, ≥7.0 HIGH, ≥4.0 MEDIUM,
    <4.0 LOW; if no CVSS score is present use the `database_specific.severity` field
    if available, otherwise "unknown"
  - `fixedVersion` — the `fixed` event value from the first matching ECOSYSTEM range;
    if absent, leave empty

## Step 5 — Build the report

Filter to dependencies where `vulns` is non-empty.

Sort: CRITICAL → HIGH → MEDIUM → LOW → unknown, then lexicographic by
`groupId:artifactId`.

Render as a markdown table. One row per `(dependency, finding)`:

| Source file | Artifact | Current | Severity | CVE/GHSA | Summary | Fixed in |
|-------------|----------|---------|----------|----------|---------|----------|
| `gradle/libs.versions.toml` | `org.apache.logging.log4j:log4j-core` | 2.14.1 | CRITICAL | [GHSA-jfh8-c2jp-5v3q](https://osv.dev/vulnerability/GHSA-jfh8-c2jp-5v3q) | Remote code execution in Log4Shell | 2.17.1 |

**Summary line after the table:**
`Total: N findings across M packages (X critical, Y high, Z medium, W low).`
`Scanned: K dependencies total. Test configurations excluded.`

**If no vulnerabilities found:**
> No known vulnerabilities found in production dependencies. (Scanned K dependencies. Test configurations were excluded.)

Then stop — no remediation prompt.

**Disclaimer (always print once):**
> Note: OSV does not cover shaded/uber JARs. Dependencies bundled inside a fat JAR may
> carry CVEs that this scan will not surface.

## Step 6 — Remediation

When at least one finding exists, ask the user with `AskUserQuestion` — one question,
exactly four options:

1. **Update all** — upgrade every vulnerable package to its recommended fixed version.
2. **Update CRITICAL + HIGH only** — leave MEDIUM/LOW for later.
3. **Show details for a specific CVE/GHSA** — ask which one, then fetch:
   `https://api.osv.dev/v1/vulns/{id}` and present the full advisory text.
4. **Report only** — make no changes.

**Recommended fixed version per package:** `max(fixedVersion)` across all findings for
that `groupId:artifactId`. If a finding has no `fixedVersion`, exclude it from the max;
if every finding lacks one, list under "Manual upgrade required".

## Step 7 — Apply updates

When the user picks option 1 or 2:

1. Edit the appropriate file:
   - **Version catalog** (`libs.versions.toml`): update the `[versions]` entry or inline
     version in `[libraries]`/`[plugins]`. Touch only the version value.
   - **Gradle build file**: update the inline version string in the dependency declaration.
   - **pom.xml**: update `<version>` inside the `<dependency>` block.

2. **MANDATORY: Run the project build to verify compatibility.** Do NOT skip this step.
   - Gradle: `./gradlew build` (or `./gradlew assembleDebug` for Android)
   - Maven: `mvn compile`

3. If the build succeeds, report which dependencies were updated and which CVEs each
   upgrade closes.

4. If the build fails, identify the incompatibility, attempt to fix it (API changes, import
   updates). If non-trivial, revert that entry and mark it "manual upgrade required".
   Re-run the build to confirm it passes. Report what was updated and what was reverted.

**Never report "vulnerabilities patched" without a passing build.**

## Known limitations

State these at the top of the report when relevant:

- Test, build, and annotation-processor configurations are excluded by default.
- Version catalog entries referenced via `version.ref` are resolved; complex expressions
  (e.g. multi-catalog from() form) may not be detected.
- Transitive dependencies are not scanned — only direct declarations in build files.
- Variant-specific configurations (`releaseImplementation`, `debugImplementation`, etc.)
  are included in production scope but flavor-prefixed ones
  (`<flavor>ReleaseImplementation`) may be missed.
- OSV coverage for Gradle plugin marker artifacts is limited — plugin CVEs may not appear.
- `buildSrc/` and composite builds (`includeBuild`) are not scanned.

## Language

This SKILL.md is in English. Runtime output follows the user's chat language. CVE/GHSA
identifiers, package coordinates, and version numbers stay in their original form.

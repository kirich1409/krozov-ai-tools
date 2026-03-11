---
name: check-deps
description: Scan current project build files for Maven/Gradle dependencies and check for available updates. Use when user says "check deps", "check dependencies", "outdated dependencies", "update dependencies", or "/check-deps".
---

# Check Dependencies

Scan the current project for Maven/Gradle dependencies and report available updates.

## Steps

1. Find build dependency files in the project root:
   - `gradle/libs.versions.toml` (Gradle version catalog)
   - `build.gradle.kts` or `build.gradle`
   - `pom.xml`

2. Read the found files and extract ALL dependencies with their current versions.
   - For `libs.versions.toml`: parse the `[versions]` and `[libraries]` sections
   - For Gradle files: find `implementation`, `api`, `compileOnly`, `testImplementation` etc. with group:artifact:version
   - For `pom.xml`: find `<dependency>` blocks with `<groupId>`, `<artifactId>`, `<version>`

3. Call the `compare_dependency_versions` MCP tool with the extracted dependencies. Use the EXACT parameter format defined in the tool schema:

```json
{
  "dependencies": [
    {"groupId": "io.ktor", "artifactId": "ktor-client-core", "currentVersion": "3.1.2"},
    {"groupId": "androidx.compose", "artifactId": "compose-bom", "currentVersion": "2025.05.00"}
  ]
}
```

Do NOT pass dependencies as a string. Do NOT add extra parameters like `stabilityFilter` or `includeSecurityScan` — they don't exist on this tool.

4. Present results as a markdown table showing only dependencies with available updates:

   | Artifact | Current | Latest Stable | Upgrade |
   |----------|---------|---------------|---------|
   | io.ktor:ktor-client-core | 3.1.2 | 3.1.3 | PATCH |

5. If all dependencies are up to date, say so.

6. After presenting the table, ask the user: "Do you want me to update the versions in the build files? After updating I will verify the project builds successfully."

## Stability policy

- By default, only report **stable** versions. The MCP server returns stable versions by default.
- Do NOT suggest alpha, beta, RC, milestone, or snapshot versions unless the user explicitly asks for unstable/pre-release versions.
- If the user asks for unstable versions, call `get_latest_version` with `stabilityFilter: "ALL"` for each dependency.

## After updating versions

When the user confirms they want to update versions:

1. Edit the build files with new versions.

2. **MANDATORY: Run the project build to verify compatibility.** Do NOT skip this step.
   - Gradle: `./gradlew build` (or `./gradlew assembleDebug` for Android)
   - Maven: `mvn compile`
   - Wait for the build to complete fully.

3. **If the build succeeds:** Report success and list the updated dependencies.

4. **If the build fails:**
   - Read the build error output carefully.
   - Identify which updated dependency caused the incompatibility.
   - Try to fix the incompatibility (API changes, import updates, deprecation replacements).
   - If the fix is non-trivial, revert that specific dependency to its previous version.
   - Re-run the build to confirm it passes.
   - Report which dependencies were updated and which were reverted with reasons.

5. **Never report "versions updated" without a passing build.** The update is not complete until the project compiles successfully.

## Important

- Always check `libs.versions.toml` first — it's the modern Gradle standard for version management.
- Dependencies in `libs.versions.toml` may use version references — resolve them to actual versions.
- Skip dependencies without explicit versions (e.g., BOM-managed or platform dependencies).
- **Send ALL dependencies to the MCP tool** — the server searches Maven Central, Google Maven, and Gradle Plugin Portal automatically. Do NOT skip or filter any dependencies by group ID.
- **Use the exact tool schema** — pass `dependencies` as an array of objects with `groupId`, `artifactId`, `currentVersion` fields. No other format is accepted.

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

2. Read the found files and extract all dependencies with their current versions.
   - For `libs.versions.toml`: parse the `[versions]` and `[libraries]` sections
   - For Gradle files: find `implementation`, `api`, `compileOnly`, `testImplementation` etc. with group:artifact:version
   - For `pom.xml`: find `<dependency>` blocks with `<groupId>`, `<artifactId>`, `<version>`

3. Call the `check_multiple_dependencies` MCP tool (from maven-mcp server) with all extracted dependencies.

4. Present results as a markdown table:

   | Artifact | Current | Latest | Upgrade |
   |----------|---------|--------|---------|
   | io.ktor:ktor-server-core | 2.3.5 | 2.3.8 | PATCH |

5. If all dependencies are up to date, say so.

## Important

- Always check `libs.versions.toml` first — it's the modern Gradle standard for version management.
- Dependencies in `libs.versions.toml` may use version references in build files — resolve them.
- Skip dependencies without explicit versions (e.g., BOM-managed or platform dependencies).

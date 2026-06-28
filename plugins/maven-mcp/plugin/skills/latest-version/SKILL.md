---
name: latest-version
description: >-
  Use when the user asks to "find the latest version", "what version is",
  "current version of", "what's the latest", "check version", "find version", or provides a
  groupId:artifactId and wants version information. Finds the latest version of a Maven artifact.
---

# Latest Version

Find the latest version of a specific Maven artifact by querying Maven Central directly.

## Arguments

The user provides `groupId:artifactId`, for example:
- `io.ktor:ktor-server-core`
- `org.jetbrains.kotlin:kotlin-stdlib`
- `com.google.dagger:hilt-android`

## Steps

1. Parse the user's input to extract `groupId` and `artifactId` (split by `:`).
   If the input has no `:`, ask the user to provide it in `groupId:artifactId` form.

2. Convert `groupId` to a URL path by replacing every `.` with `/`.
   Example: `io.ktor` → `io/ktor`.

3. Fetch metadata from Maven repositories. Use WebFetch in order:

   **a. Maven Central** (always try first):
   ```
   https://repo1.maven.org/maven2/{group_path}/{artifactId}/maven-metadata.xml
   ```

   **b. Google Maven** (try if the artifact looks Android-related — `groupId` starts with
   `androidx.`, `com.google.android.`, `com.android.`, `com.google.firebase.`,
   `com.google.gms.`, `com.google.mlkit.`):
   ```
   https://dl.google.com/dl/android/maven2/{group_path}/{artifactId}/maven-metadata.xml
   ```

   **c. Gradle Plugin Portal** (try if `artifactId` ends with `.gradle.plugin` or the
   groupId matches known Gradle plugin patterns):
   ```
   https://plugins.gradle.org/m2/{group_path}/{artifactId}/maven-metadata.xml
   ```

4. From the XML response, extract all `<version>` entries inside `<versions>`.
   Also note `<latest>` and `<release>` tags if present.

5. Classify each version for stability:
   - **STABLE** — no pre-release suffix (no alpha/beta/rc/dev/snapshot/milestone/preview,
     case-insensitive)
   - **RC** — contains `-rc`, `-RC`, `-RC.`, `-rc.`
   - **BETA** — contains `-beta`, `-Beta`, `-b`
   - **ALPHA** — contains `-alpha`, `-Alpha`, `-dev`, `-Dev`, `-SNAPSHOT`, `-snapshot`,
     `-milestone`, `-M`, `-preview`, `-Preview`, `-eap`, `-EAP`

6. Determine the latest versions to display:
   - **Latest stable** — highest stable version (by semantic version ordering).
     If no stable versions exist, note that.
   - **Latest overall** — highest version across all stability levels (if different from
     stable, show it too).

7. Display the result:

   ```
   ## io.ktor:ktor-client-core

   Latest stable:  3.1.3
   Latest overall: 3.1.3

   Recent versions: 3.1.3, 3.1.2, 3.1.1, 3.1.0, 3.0.3 ... (N total)
   ```

   If stable and overall are the same, show only "Latest: X".
   If there are more than 10 versions total, show the 5 most recent and note "(N total)".

## Error Handling

- If all repository fetches return 404 or fail, tell the user the artifact was not found
  and suggest checking the `groupId` and `artifactId` spelling.
- If only Google Maven succeeds (404 on Maven Central), present that result and note the
  source.
- If the XML response is empty or malformed, note the parse failure and surface the raw URL
  so the user can check manually.

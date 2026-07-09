---
name: check-deps
description: >-
  Use when the user asks to "check deps", "check dependencies",
  "outdated dependencies", "update dependencies", "are my deps up to date", "scan for updates",
  "find outdated libraries", "upgrade dependencies", or wants to know which Maven/Gradle
  dependencies have newer versions available. Scans build files and reports available updates.
---

# Check Dependencies

Scan the current project — version catalogs, all submodules, plugin DSL blocks, and
buildscript classpath — and report which dependencies have newer versions available, then
apply the updates the user confirms.

## Step 1 — Discover build files

Use Glob to find all build files:

```
**/libs.versions.toml
**/build.gradle.kts
**/build.gradle
**/pom.xml
**/settings.gradle.kts
**/settings.gradle
```

Exclude files under `.gradle/`, `build/`, `.idea/`, `node_modules/`, and any path
containing `/build/`.

Read each found file with the Read tool.

## Step 2 — Extract declared dependencies

Parse each file to collect a list of dependency records. Each record has:
- `groupId`, `artifactId`, `version` (resolved, not a variable reference)
- `source.kind` — one of: `catalog-library`, `catalog-plugin`, `module-direct`,
  `plugins-dsl`, `buildscript-classpath`
- `source.file` — path to the file containing the declaration
- `source.tomlPath` — for catalog entries, path to the .toml file
- `source.alias` — for catalog entries, the alias key
- `source.settingsBlock` — `true` for `pluginManagement { plugins {} }` entries
- `usages` — list of `{ module, configuration }` for where the dependency is used

### Version catalogs (`libs.versions.toml`) — `catalog-library` and `catalog-plugin`

In the `[versions]` section, collect `key = "value"` pairs as a version map.

In the `[libraries]` section:
```toml
alias = "group:artifact:version"
alias = { group = "...", name = "...", version = "..." }
alias = { group = "...", name = "...", version.ref = "key" }
```
Resolve `version.ref` using the version map.

In the `[plugins]` section:
```toml
alias = { id = "...", version = "..." }
alias = { id = "...", version.ref = "key" }
```
Convert plugin ID to Maven coordinates: `groupId = id`, `artifactId = "{id}.gradle.plugin"`.
Set `source.kind = "catalog-plugin"`.

To find which Gradle modules use a catalog alias, scan `build.gradle[.kts]` files for
`libs.{alias-with-dots}` references. Record the module name (derived from the file path
relative to the project root).

### Gradle build files — `module-direct`

Match dependency declarations with inline string versions:
```
implementation("group:artifact:version")
api("group:artifact:version")
implementation(group = "...", name = "...", version = "...")
```

**Include** (production scopes): `implementation`, `api`, `compileOnly`, `runtimeOnly`,
`compile`, `runtime`, `provided`, `releaseImplementation`, `debugImplementation`,
`ksp`, `kapt`, `annotationProcessor`.

**Exclude** (test scopes): `testImplementation`, `testApi`, `androidTestImplementation`,
`kaptTest`, `kaptAndroidTest`, `testCompileOnly`, `testRuntimeOnly`.

Skip entries that reference catalog variables (no inline version string).

Set `source.kind = "module-direct"`.

### Plugin DSL blocks — `plugins-dsl`

Match `plugins { }` blocks:
```
id("plugin.id") version "1.0.0"
kotlin("jvm") version "2.0.0"
```

Also match `pluginManagement { plugins { } }` in `settings.gradle[.kts]` — set
`source.settingsBlock = true`.

Set `source.kind = "plugins-dsl"`.
Convert plugin ID to Maven coordinates as described above.

### Buildscript classpath — `buildscript-classpath`

Match inside `buildscript { dependencies { ... } }` blocks:
```
classpath("group:artifact:version")
classpath("group:artifact:version") { ... }
```

Set `source.kind = "buildscript-classpath"`.

### Maven POM files — `module-direct`

Match `<dependency>` blocks with `<version>` present and scope `compile` (default),
`runtime`, or `provided`. Exclude `test` and `system` scope.

## Step 3 — Deduplicate

If the same `groupId:artifactId` appears both as a `catalog-library` entry and as a
`module-direct` entry (same or different version), flag it as a drift case. Keep both
records.

## Step 4 — Check latest versions from Maven Central

For each unique `groupId:artifactId`, fetch the Maven metadata. Build the group path by
replacing `.` with `/` in the groupId.

**Maven Central:**
```
https://repo1.maven.org/maven2/{group_path}/{artifactId}/maven-metadata.xml
```

**Google Maven** (for `androidx.*`, `com.google.android.*`, `com.android.*`,
`com.google.firebase.*`, `com.google.gms.*`, `com.google.mlkit.*`):
```
https://dl.google.com/dl/android/maven2/{group_path}/{artifactId}/maven-metadata.xml
```

**Gradle Plugin Portal** (for plugin marker artifacts — `artifactId` ends in
`.gradle.plugin`):
```
https://plugins.gradle.org/m2/{group_path}/{artifactId}/maven-metadata.xml
```

Extract all `<version>` entries from the XML.

**Version classification** (same rules as `/latest-version` skill):
- STABLE: no pre-release suffix
- RC: contains `-rc`, `-RC`
- BETA: contains `-beta`, `-b`
- ALPHA: contains `-alpha`, `-dev`, `-SNAPSHOT`, `-milestone`, `-M`, `-preview`, `-eap`

**Latest stable:** highest version classified as STABLE.
If no stable version, use the highest RC, then BETA, then ALPHA.

**Upgrade type** (comparing `currentVersion` to `latestVersion`):
Split both versions into `[major, minor, patch]`. First differing segment:
- Different `major` → `MAJOR`
- Different `minor` → `MINOR`
- Different `patch` or rest → `PATCH`

Batch fetches: run up to 10 fetches in parallel. Process in batches of 10 to avoid
overwhelming the network.

## Step 5 — Check vulnerabilities (optional, enabled by default)

**Preferred:** call `get_dependency_vulnerabilities` (hydrated severity/summary/fixedVersion).

**Fallback:** POST to OSV.dev, then hydrate — never report severity from querybatch alone:

```
POST https://api.osv.dev/v1/querybatch
Content-Type: application/json

{
  "queries": [
    {
      "package": {"name": "{groupId}:{artifactId}", "ecosystem": "Maven"},
      "version": "{currentVersion}"
    }
  ]
}
```

`/v1/querybatch` returns only `{id, modified}`. Hydrate each unique id via
`GET /v1/vulns/{id}` (N extra calls; dedupe) before deriving severity/fixed version
as described in `/check-deps-vulnerabilities`.

## Step 6 — Build the report

Only include entries where `latestVersion !== currentVersion`. If nothing to show in a
group, omit that section.

**Terminal branch — nothing outdated and no vulnerabilities:**

> All dependencies up to date.

Stop here — do not continue to Steps 7–10.

**Vulnerabilities only (no outdated deps):** skip the upgrade tables below and go to
Step 7.

**Outdated deps present:** render the matching sections below, then continue to Step 7
(even if the vulnerabilities list is empty — Step 7 omits itself when empty).

---

### Catalog libraries (`source.kind === "catalog-library"`)

Columns: alias | current → latest | upgrade type | catalog file | used by

- `alias` — catalog alias key
- `current → latest` — e.g., `2.3.12 → 3.1.3`
- `upgrade type` — MAJOR / MINOR / PATCH
- `catalog file` — source.tomlPath
- `used by` — count of usages (e.g. `4 modules`) or `unused`

When there are multiple catalogs, prefix alias with catalog name: `libs.alias`.

Example:
```
| ktor-client-core | 2.3.12 → 3.1.3 | MAJOR | gradle/libs.versions.toml | 4 modules |
```

---

### Catalog plugins (`source.kind === "catalog-plugin"`)

Columns: alias | plugin ID | current → latest | upgrade type | catalog file | used by

---

### Module direct (`source.kind === "module-direct"`)

Columns: module | file | artifact | current → latest | configuration

- `module` — relative path of the module (or `(root)`)
- `file` — source file path
- `artifact` — `groupId:artifactId`
- `configuration` — e.g. `implementation`

Drift flag: if the same artifact is also a catalog entry, append:
> ⚠ drift — same artifact declared in catalog and hardcoded here

---

### Plugin DSL (`source.kind === "plugins-dsl"`)

Split by `source.settingsBlock`:

**Root / module `plugins {}` block** (`settingsBlock` is false/undefined):
Columns: plugin ID | current → latest | upgrade type | file

**Settings `pluginManagement { plugins {} }` block** (`settingsBlock === true`):
Same columns.

---

### Buildscript classpath (`source.kind === "buildscript-classpath"`)

Columns: artifact | current → latest | file

> *Note: `buildscript { dependencies { classpath … } }` is the pre-Plugin-DSL style.
> Consider migrating to `plugins {}` blocks.*

---

## Step 7 — Vulnerabilities section

After all upgrade tables, add a **Vulnerabilities** section for every entry where
vulnerabilities are non-empty (regardless of whether an upgrade is available).

Columns: artifact | version | severity | advisory | fixed in | source | where to fix

Sort: CRITICAL → HIGH → MEDIUM → LOW → unknown, then lexicographic by artifact.

If no vulnerabilities: omit this section entirely.

## Step 8 — Confirmation step

Present the full report and **ask before making any edits**. Default proposal: update
catalog entries first (single source of truth, safest edit).

Ask separately for each non-catalog group (Module direct, Plugin DSL, Buildscript
classpath) — they require targeted edits in different files.

Flag every MAJOR upgrade explicitly — major version bumps may contain breaking changes and
warrant individual confirmation.

## Step 9 — Edit pass

Apply only the groups the user confirms.

**Catalog libraries / plugins** — Edit the `.toml` file. Update `[versions]` value or the
inline version in `[libraries]`/`[plugins]`. If the entry uses `version.ref`, update the
referenced `[versions]` key. Touch only the version value.

**Module direct** — Edit the build file. Update only the inline version string.

**Plugin DSL root / module** — Edit the build file, update version in `plugins {}` block.

**Plugin DSL settings** — Edit `settings.gradle[.kts]`, update version in
`pluginManagement { plugins {} }` block.

**Buildscript classpath** — Edit the root build file, update version in
`buildscript { dependencies { classpath … } }` block.

## Step 10 — Build verification

After every edit pass:

- **Gradle:** `./gradlew build` — or `./gradlew :module:dependencies` for a fast
  dependency-resolve check when a full build is slow.
- **Maven:** `mvn dependency:tree`.

Surface any build failure immediately. Identify which updated dependency caused it.
Attempt to fix incompatibilities. If non-trivial, revert that entry and note it as
"manual upgrade required". Re-run the build to confirm it passes.

**Never report "versions updated" without a passing build.**

## Constraints and non-goals

- **Major version bumps** require explicit per-entry confirmation.
- **Multi-catalog `from("g:a:v")` form** is not supported.
- **Transitive dependencies** are not enumerated — only direct declarations.
- This skill does not auto-select unstable/pre-release versions.
- **Vulnerabilities for plugin entries** may not be detected (OSV coverage gap for
  `.gradle.plugin` marker artifacts).

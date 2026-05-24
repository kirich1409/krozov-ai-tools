---
name: check-deps
description: >-
  This skill should be used when the user asks to "check deps", "check dependencies",
  "outdated dependencies", "update dependencies", "are my deps up to date", "scan for updates",
  "find outdated libraries", "upgrade dependencies", or wants to know which Maven/Gradle
  dependencies have newer versions available. Scans build files and reports available updates.
---

# Check Dependencies

Scan the current project — version catalogs, all submodules, plugin DSL blocks, and
buildscript classpath — and report which dependencies have newer versions available, then
apply the updates the user confirms.

## Preflight

Before doing anything else, confirm the `audit_project_dependencies` MCP tool is available.
If it is not, stop and tell the user:

> The maven-mcp plugin is required for this skill. Install it with
> `claude plugin add maven-mcp`, then retry.

Do not attempt to fall back to manual file parsing — this skill requires the MCP server.

## One-shot scan

Call the tool once with both flags set:

```json
{
  "includeVulnerabilities": true,
  "productionOnly": true
}
```

`productionOnly: true` is the default. It excludes test-scoped usages but still includes
unused catalog entries — the catalog is the single source of truth for declared versions
and those entries still need to be kept current.

Keep the single tool call. Do not read build files manually before or after — the MCP
server handles all file discovery and parsing.

## Grouping the result

Group `dependencies[]` by `source.kind`. Only include entries where
`latestVersion !== currentVersion` OR `vulnerabilities.length > 0`. If a group has nothing
to show, omit that section entirely. If every group is empty, output:

> All dependencies up to date.

Then skip to the Vulnerabilities section.

---

### Catalog libraries (`source.kind === "catalog-library"`)

Columns: alias | current → latest | upgrade type | catalog file | used by

- `alias` — `source.alias`
- `current → latest` — `currentVersion → latestVersion`
- `upgrade type` — `upgradeType` (MAJOR / MINOR / PATCH)
- `catalog file` — `source.tomlPath`
- `used by` — count of `usages[]` entries; write `N modules` or `unused`

When the project has more than one catalog (`source.catalogName` differs across entries),
prefix the alias with the catalog name: `libs.ktor-client-core` vs `bundles.okhttp`.

Example row:
```
| ktor-client-core | 2.3.12 → 3.1.3 | MAJOR | gradle/libs.versions.toml | 4 modules |
```

---

### Catalog plugins (`source.kind === "catalog-plugin"`)

Columns: alias | plugin ID | current → latest | upgrade type | catalog file | used by

- `alias` — `source.alias`
- `plugin ID` — `groupId` (plugin marker convention: `groupId` is the plugin ID)
- remaining fields same as catalog libraries

---

### Module direct (`source.kind === "module-direct"`)

Columns: module | file | artifact | current → latest | configuration

- `module` — `usages[0].module` if set; otherwise `(root)`
- `file` — `source.file`
- `artifact` — `groupId:artifactId`
- `configuration` — `usages[0].configuration`

Drift flag: if another entry in the result has the same `groupId:artifactId` with
`source.kind === "catalog-library"`, append a note:
> ⚠ drift — same artifact declared in catalog and hardcoded here

---

### Plugin DSL (`source.kind === "plugins-dsl"`)

Split into two sub-tables based on `source.settingsBlock`:

**Root / module `plugins {}` block** (`settingsBlock` is `undefined` or `false`):

Columns: plugin ID | current → latest | upgrade type | file

**Settings `pluginManagement { plugins {} }` block** (`settingsBlock === true`):

Same columns.

---

### Buildscript classpath (`source.kind === "buildscript-classpath"`)

Columns: artifact | current → latest | file

> *Note: `buildscript { dependencies { classpath … } }` is the pre-Plugin-DSL style.
> Consider migrating to `plugins {}` blocks.*

---

## Vulnerabilities

After all upgrade tables, add a separate **Vulnerabilities** section listing every entry
where `vulnerabilities` is non-empty, regardless of whether an upgrade is available.

Columns: artifact | version | severity | advisory | fixed in | source | where to fix

- `artifact` — `groupId:artifactId`
- `version` — `currentVersion`
- `severity` — `vulnerabilities[i].severity` (CRITICAL / HIGH / MEDIUM / LOW / unknown)
- `advisory` — `vulnerabilities[i].id` (link it if the client renders Markdown)
- `fixed in` — `vulnerabilities[i].fixedVersion`; if absent write `(no fixed version)`
- `source` — `source.kind`
- `where to fix` — `source.tomlPath` for catalog entries; `source.file` for all others

Sort rows: CRITICAL → HIGH → MEDIUM → LOW → unknown, then lexicographic by
`groupId:artifactId`.

If no vulnerabilities exist, omit this section entirely.

## Confirmation step

Present the full report to the user and **ask before making any edits**. Default
proposal: update catalog entries first (they are the single source of truth and the
safest edit).

Ask separately for each non-catalog group (Module direct, Plugin DSL, Buildscript
classpath) — they require targeted edits in different files and carry more risk.

Flag every entry with `upgradeType === "major"` explicitly — major version bumps may
contain breaking changes and warrant individual confirmation.

## Edit pass

Apply only the groups the user confirms.

**Catalog libraries / plugins** — `Edit` the `.toml` file at `source.tomlPath`.
Update the `version` value or the referenced `[versions]` entry if a `version.ref` is
used. Touch only the version value — do not reformat or reorder unrelated entries.

**Module direct** — `Edit` the file at `source.file` inside the module directory
indicated by `usages[0].module`. Update the inline version string only.

**Plugin DSL root / module** — `Edit` the root or module `build.gradle[.kts]` file
(`source.file`). Update the version in the `plugins {}` block.

**Plugin DSL settings** — `Edit` `settings.gradle[.kts]` (`source.file`). Update the
version in the `pluginManagement { plugins {} }` block.

**Buildscript classpath** — `Edit` the root `build.gradle[.kts]` (`source.file`).
Update the version in the `buildscript { dependencies { classpath … } }` block.

## Build verification

After every edit pass, verify the project still builds.

- **Gradle:** `./gradlew build` — or `./gradlew :module:dependencies` for a fast
  dependency-resolve check when a full build is slow.
- **Maven:** `mvn dependency:tree`.

Do not invent flags. If the `/check` skill is available in the current environment,
prefer it — it applies the project's own verification sequence.

Surface any build failure immediately. Read the error output, identify which updated
dependency caused it, attempt to fix the incompatibility (API changes, import updates,
deprecation replacements). If the fix is non-trivial, revert that specific entry to its
previous version and note it as "manual upgrade required". Re-run the build to confirm it
passes.

**Never report "versions updated" without a passing build.** The update is not complete
until the project resolves and compiles successfully.

## Constraints and non-goals

- **Major version bumps** are flagged in the report and require explicit per-entry
  confirmation — do not batch-apply them silently.
- **Multi-catalog `from("g:a:v")` form** (catalog declared as a Maven dependency) is not
  supported; such entries are not scanned.
- **`buildSrc/` and convention plugins** are not scanned.
- **Transitive dependencies** are not enumerated — only direct declarations in build
  files. Run `./gradlew dependencies` or `mvn dependency:tree` to inspect transitive
  trees when needed.
- This skill does not auto-select unstable/pre-release versions. The MCP server returns
  the latest stable version by default.

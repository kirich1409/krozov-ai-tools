---
name: catalog-entry
description: >-
  Use when the user asks to "add this dependency to my version catalog", "generate a
  libs.versions.toml entry for X", "what alias should I use for this library", "validate my
  version catalog", "check my libs.versions.toml for mistakes", or wants a new Gradle
  version-catalog entry generated or an existing catalog validated — Gradle has no built-in
  command for either.
---

# Catalog Entry

Generate a rule-correct Gradle version-catalog (`gradle/libs.versions.toml`) entry for a
new dependency/plugin, or validate an existing catalog for common mistakes. Gradle has no
native command for either operation.

## Mode: generate (new dependency/plugin)

Call **`catalog_entry`** with:
- `mode: "generate"`
- `coordinate: {groupId, artifactId, version?}`
- `kind`: `"library"` (default) or `"plugin"`
- optional `alias` — a preferred alias; sanitized if it violates catalog rules
- optional `catalogToml` — existing catalog content, so the generator avoids alias clashes
  and can suggest a version-only bump instead of a fresh entry when the alias already
  exists
- optional `catalogName` (default `"libs"`)

Present the returned `alias`, `accessor` (`libs.x.y` for a library,
`alias(libs.plugins.x.y)` — never `id(...)` — for a plugin), and `suggestedDiff`. Apply the
diff, not a full-file rewrite.

## Mode: validate (existing catalog)

Call **`catalog_entry`** with `mode: "validate"` and either `catalogToml` directly or
`projectPath` (reads `gradle/libs.versions.toml` under the project when `catalogToml` is
omitted). Pass `buildContent` too when checking for `id(libs.plugins.x)` misuse or `libs`
accessors inside `subprojects {}` / `buildscript {}`.

Present `violations[{rule, detail}]` — reserved alias segments
(`extensions`/`class`/`convention`), reserved first segments
(`bundles`/`versions`/`plugins`), undefined `version.ref`, accessor clashes, wrong default
catalog path, plugin DSL misuse.

**No violations:** say so plainly.

## Constraints and non-goals

- Not for bumping the version of an *existing* catalog entry as part of a broader update
  sweep — that's `/check-deps`, which calls this tool internally (`mode: "generate"` with
  the same alias) to produce a minimal version bump rather than a full rewrite.
- Default catalog path is exactly `gradle/libs.versions.toml`.

## Fallback (MCP unavailable only)

Apply the naming rules directly: kebab-case alias, no reserved segment/first-word, library
accessor `libs.x.y`, plugin accessor `alias(libs.plugins.x.y)` (never `id(...)`). Add a
single `[versions]` / `[libraries]` / `[plugins]` line rather than rewriting the file.

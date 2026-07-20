---
name: expand-bom
description: >-
  Use when the user asks to "expand this BOM", "what versions does the Spring Boot BOM
  manage", "show me the managed versions in this platform", "what does importing
  io.ktor:ktor-bom pin", or provides a Maven BOM / Gradle platform() coordinate and wants
  its full set of managed dependency versions.
---

# Expand BOM

Expand a Maven BOM (Bill of Materials) or Gradle `platform()` coordinate into the full set
of dependency versions it manages.

## Steps

1. Parse `groupId`, `artifactId`, `version` for the BOM coordinate (for example
   `org.springframework.boot:spring-boot-dependencies:3.2.5`, `io.ktor:ktor-bom:3.1.3`).

2. Call **`expand_bom`** with `groupId`, `artifactId`, `version`, and optional
   `projectPath`.

3. Present the `managed` list (`groupId:artifactId → version`). For a long BOM (Spring Boot
   manages hundreds of entries), let the user filter — ask which group(s) or artifact(s)
   they care about rather than dumping the entire list unprompted.

Import-scope BOMs referenced by the target BOM are expanded recursively with first-wins
merge order (an entry already seen is never overwritten by a nested import) — the same
semantics as Maven's own dependency-management resolution.

## Error handling

- BOM POM not found / not a BOM → say so; do not fabricate managed versions.
- A managed entry with an unresolved `${...}` property is skipped, not guessed.

## Fallback (MCP unavailable only)

Fetch the BOM's POM directly and parse `<dependencyManagement><dependencies>` (plus parent
POM properties for `${...}` interpolation) by hand. State that recursive import-BOM
expansion and property interpolation across parents are error-prone to reproduce manually.

---
name: eol-status
description: >-
  Use when the user asks "is Kotlin 1.9 still supported", "when does Gradle 7 reach end of
  life", "is this Spring Boot version EOL", "is JDK 17 still maintained", "check end-of-life
  status", "when do I need to upgrade", or wants the support/end-of-life status of a JDK,
  Kotlin, Gradle, or Spring Boot version via endoflife.date.
---

# EOL Status

Check end-of-life / support status for JDK, Kotlin, Gradle, and/or Spring Boot via
endoflife.date.

## Steps

1. Identify which of the four the user is asking about — one call can check any combination:
   - `kotlin` — a version string, e.g. `"2.4.10"`
   - `gradle` — a version string, e.g. `"8.14.5"`
   - `springBoot` — a version string, e.g. `"3.5.16"`
   - `jdk` — `{vendor, version}`. **endoflife.date has no generic "java" product** — JDK
     end-of-life is vendor-specific. If the user just says "Java 17" without naming a
     distribution, ask which vendor/distribution they run (common ones: `eclipse-temurin`,
     `amazon-corretto`, `oracle-jdk`, `redhat-build-of-openjdk`) rather than guessing — never
     default to "java".

   At least one of the four is required.

2. Call **`get_eol_status`** with whichever of `kotlin` / `gradle` / `springBoot` / `jdk` apply.

3. Present each entry in `results`:
   - `isEol: true` — flag clearly, with `eolDate`.
   - `isMaintained` — note when this differs from what `isEol` alone would suggest (e.g. Spring
     Boot commercial/extended support can keep a cycle `isMaintained: true` past community EOL).
   - `isLts` — call out when true (relevant for JDK/Gradle upgrade planning).
   - `latestInCycle` — the latest patch release still available in that same cycle — a same-
     cycle upgrade suggestion, distinct from a major-version upgrade.
   - `cycle` — which release-cycle line the requested version was matched against (e.g. `"2.4"`
     for Kotlin `2.4.10`, `"21"` for a JDK 21 patch version — cycle granularity varies by
     product, see Known limitations).

   **Per-item `error`** (no crash) — either the product/vendor slug is not known to
   endoflife.date, or the requested version does not fall into any published cycle. Report
   which, plainly; do not treat either case as EOL or as not-EOL.

## Constraints and non-goals

- Not a general changelog/release-notes tool — use `/dependency-changes` for what changed
  between two versions of a Maven/Gradle dependency.
- Not for arbitrary Maven artifacts — only JDK (vendor-scoped) / Kotlin / Gradle / Spring Boot,
  the products endoflife.date + this tool cover.

## Known limitations

- No generic "java" product — a JDK check always needs an explicit vendor; never guess one.
- Cycle granularity is product-specific (major-only for Gradle/JDK vendors, major.minor for
  Kotlin/Spring Boot) — the tool matches this correctly, but do not assume a fixed depth when
  reasoning about `cycle` yourself.
- EOL/support data is cached for a long TTL (support windows are set well in advance and change
  rarely) — a just-announced schedule change may take a while to be reflected.

## Fallback (MCP unavailable only)

`GET https://endoflife.date/api/v1/products/{slug}` (no auth) and match `requestedVersion`
against the returned `result.releases[]` cycle whose `name` it starts with (as a version
prefix, not a fixed-depth split — see Known limitations). For JDK, `{slug}` is the vendor
(e.g. `eclipse-temurin`), never `java`.

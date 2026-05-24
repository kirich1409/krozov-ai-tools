# Cleanup

The migration is not done until the FROM technology is removed. Parallel stacks accumulate cognitive load, double build cost, doubled onboarding tax, and coupling drift. Cleanup is part of the migration, not a follow-up.

## The ten-item universal checklist

Walk this top to bottom for the specific migration. Each item must end up in one of three states: **done**, **N/A with reason**, or **deferred with sunset date and tracker link**. Nothing else.

### 1. No FROM imports outside frozen legacy modules

**Check.** Search the entire repo for FROM imports.

```bash
# Example: Databinding cleanup (matches both pre-AndroidX and AndroidX packages).
# The trailing `.` is the search root — omitting it leaves grep reading from stdin and hanging.
grep -rn -E "import (android\.databinding|androidx\.databinding)" \
  --include="*.kt" --include="*.java" . \
  | grep -v ":legacy:"  # exclude explicitly-frozen modules
```

**Allowable exceptions.** Modules explicitly named `:legacy:*` or `:*-legacy` with a frozen status and a sunset plan. Anything else is a leftover.

For Compose-specific audits, run an aggressive residue scan for the legacy View stack: `android.view.*`, `android.widget.*`, `androidx.databinding.*`, `androidx.viewbinding.*`, `findViewById`, XML layout files, `@BindingAdapter`, and references to removed adapters. Any hit on a screen claimed migrated means the migration is incomplete on that screen.

### 2. `libs.versions.toml` no longer references FROM

**Check.** Open the version catalog and grep for the FROM artifact coordinates.

```bash
grep -E "(databinding|com.google.dagger|io.reactivex)" gradle/libs.versions.toml
```

**Allowable exceptions.** None. If a transitive dependency still pulls FROM, that is a Phase 2 (Discover) miss — track it and resolve.

### 3. `build.gradle*` plugin declarations removed

**Check.** Search Gradle files for the FROM activation flags and plugin applications specifically — not for the TO plugin (the TO plugin is supposed to stay).

Substitute the regex for the actual FROM technology of the current migration:

```bash
# Databinding -> ViewBinding: look for the FROM activation flag.
grep -rn -E "dataBinding\s*=\s*true" --include="*.gradle*" .

# KAPT -> KSP (when no other processors need KAPT): look for the FROM plugin.
grep -rn -E "kotlin\(\"kapt\"\)|kotlin-kapt" --include="*.gradle*" .

# RxJava -> Coroutines: look for the FROM dependency coordinates.
grep -rn -E "io\.reactivex\.rxjava3" --include="*.gradle*" .
```

For Databinding → ViewBinding: remove `dataBinding = true`, keep `viewBinding = true`.
For KAPT → KSP (full): remove `kotlin("kapt")` plugin if no other processors require KAPT. The KSP plugin (`com.google.devtools.ksp`) is the TO and must remain.
For Dagger → Metro: remove dagger-compiler dependency and the KAPT (or KSP) invocations that exist solely for Dagger; keep KAPT/KSP if other processors still need them.

**Allowable exceptions.** If another active migration still needs the same plugin (e.g., other modules have not migrated KAPT yet), leave the plugin and note the cross-migration dependency in `<slug>-cleanup-checklist.md`.

### 4. Bridge / adapter / interop layers removed or registered

**Check.** Locate every bridge introduced during Phase 5.

- DI: Dagger-Metro / Hilt-Metro bridge modules.
- UI: `AndroidView { ... }` wrappers around legacy custom views.
- Async: `rxSingle { }`, `asObservable()`, `asFlow()`, `await()` calls.
- Build: gradle subprojects exposing FROM as `api` to maintain consumers during migration.

**Decision for each bridge:**

- **Delete.** Default action — the bridge was temporary.
- **Promote to long-term public API.** Requires an ADR. Justification: real cross-paradigm need (e.g., `AndroidView` around a Maps SDK with no Compose equivalent).
- **Defer with sunset date.** A documented tracker entry with a date and a closure criterion. If a sunset date is missed once, the bridge is becoming permanent debt — escalate.

### 5. Generated-code directories no longer populate for FROM

**Check.** After a clean build, the FROM technology's generated directories should be empty or absent.

```bash
./gradlew clean
find . -type d -path "*/build/generated/*" | xargs ls -la 2>/dev/null \
  | grep -E "(databinding|dagger|hilt|kapt)"
```

**Allowable exceptions.** Other active processors. Note them and verify they are not for FROM.

### 6. Lint baseline / Konsist rules updated

**Check.** Lint baseline files (`lint-baseline.xml`) and Konsist tests for migration-specific rules.

If the migration used `LintBaseline` to gate growth: regenerate from current state (should be empty for migration-related issues) or delete the file if it was migration-specific.

If Konsist tests enforced direction rules (`no new imports of FROM in package X`): keep them if they remain valuable invariants (preventing accidental reintroduction), or delete them if FROM is fully gone and the rule is no longer enforceable.

See `references/anti-orchestrator.md` for the dependency-direction Konsist patterns.

### 7. Documentation updated

**Check.** Each of these mentions FROM by name:

- `CLAUDE.md` (project root and any per-module files) — onboarding notes, conventions.
- Architecture decision records (`docs/adr/`, `docs/architecture/`) — if FROM was a documented decision, write an ADR superseding it.
- Onboarding guides, READMEs, contributor docs.
- Internal wiki / Notion / Confluence pages — out of scope for this skill but should be flagged to the user.

Update or mark as historical with date and link to the migration report.

### 8. CI passes without legacy-related warnings

**Check.** Trigger a CI run on the cleanup branch. Watch for:

- Deprecation warnings related to FROM.
- "Unused dependency" warnings (if a build-scan plugin is configured).
- Lint warnings that were previously suppressed in the baseline.

**Allowable exceptions.** Warnings unrelated to the migration. If a CI step was disabled to unblock the migration ("we'll re-enable lint after"), re-enable it now.

### 9. APK / AAB size reduced (Android-only)

**Check.** Compare before/after.

```bash
./gradlew :app:bundleRelease
# Compare app/build/outputs/bundle/release/*.aab sizes
```

A meaningful reduction is sanity check that the FROM library actually left. If size is unchanged, suspect a transitive dependency or a wrong scope in the version catalog.

**Allowable exceptions.** Library-only or KMP-only migrations with no APK build. Mark as N/A.

### 10. Release notes list intentional behavioral changes

**Check.** The list of "intentional behavioral changes" agreed in Phase 4 (Strategy) appears in:

- Release notes for the next user-facing release.
- The migration report (`<slug>-migration-report.md`).
- Any "behavior change" announcement channel the team uses (Slack, dev mailing list, in-app notice if user-visible).

If the list is empty (truly invisible migration), state so explicitly in the release notes — "DI framework migrated from Hilt to Metro; no user-visible changes."

---

## When cleanup gets stuck

If one or more items cannot be completed, the migration is not done. Be explicit about the partial state:

1. Mark each blocked item with the blocker and the owner.
2. Open a tracker entry (issue, ticket, ADR-style note) for each item.
3. Update `<slug>-migration-report.md` Status field: **Done** / **Partial** / **Blocked**.
4. Do not claim "migration complete" in release notes. Use "phase 1 complete; cleanup in progress" with the link to the tracker.

The worst outcome is a migration that is 90% done and called complete — the remaining 10% sits forever, paralleling the FROM stack indefinitely.

---

## Cleanup audit (optional, for horizontal migrations)

For horizontal migrations (DI, async, serialization), invite a `developer-workflow-experts:architecture-expert` review after Cleanup completes. The reviewer checks:

- Dependency direction (FROM → TO only, never TO → FROM).
- No surviving FROM imports outside frozen modules.
- Generated-code footprint matches expectations.
- Bridge layers either gone or registered with ADRs.

This is optional and user-initiated. The skill does not invoke it automatically.

---

## Cleanup checklist template

Save the per-migration status to `<slug>-cleanup-checklist.md`:

```markdown
# Cleanup Checklist: <slug>

Migration: <FROM> -> <TO>
Date: <YYYY-MM-DD>
Status: Done | Partial | Blocked

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | No FROM imports outside :legacy:* | done | grep clean |
| 2 | libs.versions.toml no FROM | done | removed androidx.databinding entries |
| 3 | build.gradle* plugin declarations removed | done | removed `dataBinding = true` in 14 modules |
| 4 | Bridge layers removed or registered | done | no bridges in this migration |
| 5 | Generated-code directories clean | done | no databinding/* in build/generated |
| 6 | Lint baseline / Konsist updated | done | removed databinding-related lint baselines |
| 7 | Documentation updated | done | CLAUDE.md updated; ADR-0023 supersedes ADR-0007 |
| 8 | CI passes without warnings | done | green |
| 9 | APK/AAB size reduced | done | -180 KB |
| 10 | Release notes list intentional changes | done | "no user-visible changes" |
```

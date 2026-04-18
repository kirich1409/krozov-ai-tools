# Migration Checklist Template

Use this template for two purposes:
1. **Large-scope migration plan** (Phase 1 Discover gate) — one row per migration unit
2. **API behavioral checklist** (Phase 2 Snapshot, `api` category) — one row per public surface or known caller

---

## Template

| Unit | Category | Strategy | Snapshot | Dependencies | Status |
|------|----------|----------|----------|--------------|--------|
| `path/to/File.kt` | logic / ui / api | in-place / parallel / — | test: `path/TestFile.kt` \| screenshot: `before.png` \| "checklist item description" | comma-separated dependencies, or — | pending / in-progress / done |

---

## Example: Large-Scope Migration Plan (Android → KMP)

| Unit | Category | Strategy | Snapshot | Dependencies | Status |
|------|----------|----------|----------|--------------|--------|
| `:shared:DateUtils` | logic | in-place | test: `DateUtilsTest.kt` — 8 tests green | — | pending |
| `:shared:UserRepository` | logic, api | parallel | test: `UserRepositoryTest.kt` — 12 tests green; callers: `LoginViewModel`, `ProfileViewModel` | `:shared:DateUtils` | pending |
| `LoginFragment` | ui | parallel | screenshot: `login_before.png`; manual: form layout, error states | `:shared:UserRepository` | pending |
| `build.gradle (:shared)` | api | in-place | checklist: KMP plugin applied, `commonMain`/`androidMain` defined | — | pending |

---

## Example: API Behavioral Checklist

| Unit | Category | Strategy | Snapshot | Dependencies | Status |
|------|----------|----------|----------|--------------|--------|
| `UserRepository.getUser(id)` | api | — | caller: `LoginViewModel` — compiles ✓, `LoginViewModelTest` passes ✓ | — | pending |
| `UserRepository.saveUser(user)` | api | — | caller: `ProfileViewModel` — compiles ✓, no tests | — | pending |
| `UserRepository` (Gradle dep) | api | — | `:app` depends on `:shared` — compiles ✓ | — | pending |

---

## Fields Reference

| Field | Description | Values |
|-------|-------------|--------|
| `unit` | What is being migrated or verified | File path, class name, Gradle module, or function signature |
| `category` | What kind of code this is | `logic`, `ui`, `api` — comma-separated if multiple |
| `strategy` | How it will be migrated | `in-place`, `parallel`, or `—` (for API checklist entries) |
| `snapshot` | Evidence of current behavior captured | Path to test file, screenshot file, or text description |
| `dependencies` | Units that must be done before this one | Comma-separated unit names, or `—` if none |
| `status` | Current state | `pending`, `in-progress`, `done` |

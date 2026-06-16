---
name: check
description: >-
  Run all mechanical verification checks on the project — build, static analysis (lint),
  tests, and typecheck — in a single command. Reusable utility called by any skill that
  modifies code: write-tests, finalize, or directly by the user.

  Auto-detects project tooling (Gradle, npm/pnpm/yarn, cargo, Swift SPM, Xcode, Python,
  Go, Makefile) and runs the appropriate commands. Does NOT modify code — it only verifies.

  Use when: "check the project", "run tests", "verify build", "does it build?", "smoke check",
  "make sure nothing is broken", "validate the branch", "after I edited X run checks",
  "is everything clean?", "did I break anything?",
  or when a pipeline stage needs to confirm that code modifications
  did not break anything. Do NOT use for code review (that is finalize Phase A), functional
  acceptance testing (use acceptance), or exploratory QA (call manual-tester agent directly).
---

# Check

Mechanical verification pass — detect project tooling, run build + lint + typecheck + tests, report pass/fail per category and an aggregate verdict. Fail-fast by default. **Read-only with respect to code:** the skill executes commands and reports; the caller owns the fix cycle.

---

## Phase 1: Detect tooling

Marker-file detection (`gradlew`, `package.json`, `Cargo.toml`, `Package.swift`, `*.xcodeproj`, `pyproject.toml`, `go.mod`, `Makefile`) follows the table in `~/.claude/rules/qa-and-testing.md` § Test infrastructure detection markers. Stack-specific defaults below override that table only where the test runner alone is insufficient for a full check.

If multiple stacks are detected (monorepo) — run checks for each. No marker found → escalate to the caller.

---

## Phase 2: Resolve commands

### Gradle

`./gradlew check` runs verification but does **not** compile production sources. Always pair with `assemble`:

```
./gradlew assemble check
```

**Android (AGP)** — `check` alone usually runs only unit tests, and `connectedCheck` needs a device (out of scope). Use variant-scoped commands:

```
./gradlew assembleDebug lintDebug testDebug
```

Detect Android via `android { }` block or `com.android.application` / `com.android.library` plugin. Always honor the wrapper (`./gradlew`); never invoke a system-installed `gradle`. If the wrapper is non-executable, invoke as `sh ./gradlew assemble check` rather than mutating tracked file mode.

### Node (`package.json`)

Read `scripts` and run whichever exist, in this order — **stack override of the default Phase 3 sequence**, since JS projects rarely need a build to surface lint/type/test problems and `build` is the slowest:

1. `lint` (or `lint:all`)
2. `typecheck` (or `tsc` / `type-check`)
3. `test` (or `test:unit`)
4. `build` — only if CI runs it (check `.github/workflows/*.yml`)

Pick the package manager by lockfile: `pnpm-lock.yaml` → `pnpm run`, `yarn.lock` → `yarn`, `package-lock.json` → `npm run`. No `lint`/`test` scripts → escalate.

### Xcode

Never guess scheme or destination. Escalate with: "Xcode project detected but no check commands configured. Provide `xcodebuild -scheme <Scheme> test -destination '<destination>'` or configure them as a project override." Phase 3 cannot proceed without these.

### Python

Inspect `pyproject.toml` / `setup.cfg` and run only configured tools — `[tool.ruff]` → `ruff check .`, `[tool.mypy]` → `mypy .`, `[tool.pyright]` → `pyright`, `[tool.pylint]` → `pylint <package>`, `[tool.flake8]` → `flake8 .`, `[tool.pytest.ini_options]` → `pytest`, `[tool.black]` → `black --check .`. Prefer `uv run <tool>` when `uv.lock` or `[tool.uv]` is present. Do not install missing tools.

### Other stacks

- **Rust:** `cargo fmt --check` + `cargo clippy --all-targets -- -D warnings` + `cargo test --all-features` (clippy already type-checks).
- **Swift SPM:** `swift build` + `swift test`; add `swiftlint` or `swift-format lint` if a config file exists.
- **Go:** `go vet ./...` + `go test ./...` + `go build ./...`.
- **Makefile:** `make check` if defined (authoritative); otherwise `make test`. Never both.

---

## Phase 3: Execute

Default: **sequential, fail-fast** in this order — Build → Lint → Typecheck → Tests. On the first failure: stop, report with stderr excerpt, hand back to caller.

### Opt-in modes

| Flag | Effect |
|---|---|
| `--all` | Run every check regardless of earlier failures (PARTIAL verdict if mixed). |
| `--fast` | Skip tests AND the public-API coverage gate; build + lint + typecheck only. |
| `--only <category>` | Single category (`build` / `lint` / `typecheck` / `tests`); coverage gate skipped. |
| `--no-coverage-gate` | Skip Phase 3.5 only. Recorded as `skipped: [coverage]` plus a Notes entry. |

Callers pass the mode as the first `--<flag>` token or via natural language ("fast mode", "only the tests"). Mutually exclusive flags → fail with a clear error.

### Output capture

For each command: capture exit code; on failure, capture last ~50 lines of stderr (truncate from the top); on success, do not include stdout in the report — just status.

---

## Phase 3.5: Public-API coverage gate (default-on)

Runs after the test category. Even when build / lint / typecheck / tests all pass, a new public symbol with no matching test fails this gate — the early check; the late audit lives in `finalize` Phase D.

**Symbol classification, trivial-no-test allow-list, and test-matching priority** — see `~/.claude/rules/qa-and-testing.md` § Public-API coverage gate.

**When the gate runs:** current branch differs from the remote default branch (derive base via `git remote show origin | grep "HEAD branch"`, fallbacks `main`/`master`/`develop`; operate on `git diff $(git merge-base origin/<base> HEAD)..HEAD`). Branch at default → skip silently. `--no-coverage-gate` → record as `skipped: [coverage]`.

**Per-language matching extras** beyond the global rule:
- Kotlin annotation `@NoTestRequired` or `@Suppress("MissingTest")` satisfies the gate; equivalent line comment `// no-test-required: <reason>` works for Swift / Rust / Go / TS / JS / Python.
- Files under `no-test-harness/` are an escape hatch for legacy modules.

**Output:** a `coverage` row in the report and arrays of the verdict block. Result: `PASS` (every symbol matched or trivial), `FAIL` (one or more unmatched — list `<file>:<line>: <symbol>` with the rule that was tried), or `SKIP` (explicit override).

A `coverage: FAIL` from `/check` means the engineer adds tests, marks trivial, or passes `--no-coverage-gate` (discouraged, recorded). When invoked from `finalize`, the engineer who introduced the symbol owns the fix in the same run.

---

## Phase 4: Report

Two parts: human-readable body + mandatory machine-readable summary block at the end.

**Body:**

- `## Check report` with `Stack detected`, `Mode`, `Verdict` lines.
- `### Results` — one row per check with Command / Status / Notes.
- `### Failures` (if any) — per failure: command, exit code, stderr excerpt, suggested next step.
- `### Summary` — passed/failed/skipped counts + total wall time.

**Machine-readable trailer** — required, orchestrator/skills tail-parse it:

~~~
verdict: FAIL
passed: [build, coverage]
failed: [lint]
skipped: [tests]
~~~

`verdict` is one of:

- **PASS** — every executed check exit 0 AND coverage gate (when run) matched every new public symbol.
- **FAIL** — at least one executed check non-zero OR coverage gate had unmatched symbols. Default fail-fast: a failure followed by SKIP for remaining categories is still FAIL.
- **PARTIAL** — reserved for `--all` when some passed and some failed.

---

## Scope rules

- **In scope:** running mechanical checks; reporting results; truncating noisy output.
- **Out of scope:** editing code, suggesting fixes, running interactive commands, installing missing tools, creating branches, committing.
- **Never** auto-fix formatting / lint (even with `--fix`); never modify build files to silence a failure; never run destructive ops (`./gradlew clean` only if the caller asked for it).

---

## Escalation

Stop and report to the caller when:

- No recognized tooling AND no commands provided.
- A check hangs or exceeds 15 minutes wall time — abort with a timeout note.
- Auth / network unavailable (private Maven repo down, etc.).
- Build wrapper referenced but missing (e.g., `gradlew` absent) — report; do not regenerate.

State what was detected, what was attempted, what the caller needs to decide.

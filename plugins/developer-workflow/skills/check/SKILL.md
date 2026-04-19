---
name: check
description: >-
  Run all mechanical verification checks on the project — build, static analysis (lint),
  tests, and typecheck — in a single command. Reusable utility called by any stage that
  modifies code: implement, finalize, migration skills, or directly by the user.

  Auto-detects project tooling (Gradle, npm/pnpm/yarn, cargo, Swift SPM, Xcode, Python,
  Go, Makefile) and runs the appropriate commands. Does NOT modify code — it only verifies.

  Use when: "check the project", "run tests", "verify build", "after I edited X run checks",
  "проверь проект", "запусти проверки", or when a pipeline stage needs to confirm that
  code modifications did not break anything. Do NOT use for code review (that is gate
  4 of implement / Phase A of finalize) or acceptance testing (use acceptance).
---

# Check

Mechanical verification pass. Detect the project's tooling, run build + lint + tests + typecheck, report pass/fail per check and an aggregate verdict. Fail-fast by default.

This skill is **read-only with respect to code** — it executes commands and reports, but does not apply any fixes. Callers own the fix cycle.

---

## Phase 1: Detect project tooling

Inspect the working tree for marker files to decide which check suite to run. A project can have multiple (e.g., a monorepo with Gradle + Node) — run checks for each detected stack.

| Marker files | Stack | Default check suite |
|---|---|---|
| `gradlew`, `build.gradle`, `build.gradle.kts`, `settings.gradle*` | Gradle | `./gradlew assemble check` — `check` alone does not compile production sources; AGP projects prefer variant-scoped commands (see §2.1) |
| `package.json` | Node (npm/pnpm/yarn) | Derive from scripts — see §2.2 |
| `Cargo.toml` | Rust / Cargo | `cargo fmt --check` + `cargo clippy --all-targets -- -D warnings` + `cargo test --all-features` (clippy already performs type-check; no separate `cargo check` needed) |
| `Package.swift` | Swift SPM | `swift build` + `swift test` — add `swiftlint` or `swift-format lint` if a config file is present |
| `*.xcodeproj`, `*.xcworkspace` | Xcode | Requires project-specific commands — see §2.3 |
| `pyproject.toml`, `setup.py`, `setup.cfg` | Python | Derive from configured tools — see §2.4 |
| `go.mod` | Go | `go vet ./...` + `go test ./...` + `go build ./...` |
| `Makefile` with `check`/`test` targets | Generic | `make check` (or `make test` as fallback) |

No marker found → report "no recognized project tooling detected" and ask the caller to provide commands explicitly.

---

## Phase 2: Resolve commands

### 2.1 Gradle

`./gradlew check` by itself runs the *verification* suite (lint, static analysis, tests) but does **not** compile the project. Build failures in production sources are only surfaced by `assemble`. Always run them together:

```
./gradlew assemble check
```

**Android (AGP) projects** — prefer explicit variant-scoped commands; plain `check` on AGP usually runs only unit tests, and `connectedCheck` requires a device and is out of scope for `/check`:

```
./gradlew assembleDebug lintDebug testDebug
```

Detect Android via `android { }` block in `build.gradle*` or `com.android.application` / `com.android.library` plugin.

Honor the wrapper — never use system-installed `gradle`. If `gradlew` is not executable, invoke it non-mutatingly via `sh ./gradlew assemble check` rather than changing tracked file mode with `chmod +x` (the wrapper script is sh-compatible, not bash-specific). If the permission issue persists, escalate to the caller with a note to fix the wrapper permission themselves — `/check` does not modify the working tree.

### 2.2 Node (package.json)

Read `scripts` from `package.json` and run whichever of these exist, in this order:

1. `lint` (or `lint:all`)
2. `typecheck` (or `tsc` / `type-check`)
3. `test` (or `test:unit`)
4. `build` (only if the project's CI runs it — check `.github/workflows/*.yml` for signal)

Pick the package manager from lockfile:

| Lockfile | Manager |
|---|---|
| `pnpm-lock.yaml` | `pnpm run <script>` |
| `yarn.lock` | `yarn <script>` |
| `package-lock.json` | `npm run <script>` |

If no `lint`/`test` scripts exist — report "no check scripts configured" and ask the caller to define them or provide explicit commands.

### 2.3 Xcode

Xcode projects require knowing the scheme and destination. If the caller did not provide commands, ask:

> "Xcode project detected but no check commands configured. Provide build and test commands (e.g., `xcodebuild -scheme MyApp test -destination 'platform=iOS Simulator,name=iPhone 16'`)."

Do not guess — wrong destination/scheme wastes time and produces misleading errors.

### 2.4 Python

Inspect `pyproject.toml` / `setup.cfg` for configured tools. Run only the tools the project actually uses:

- `[tool.ruff]` → `ruff check .`
- `[tool.mypy]` → `mypy .` (with project path)
- `[tool.pytest.ini_options]` or `tests/` present → `pytest`
- `[tool.black]` → `black --check .`

Do not install missing tools. If none are configured — report "no check tools configured" and ask the caller.

---

## Phase 3: Execute

Default behaviour: **sequential, fail-fast**. Run checks in this order (whichever apply):

1. Build / compile
2. Static analysis / lint
3. Typecheck
4. Tests

On the first failure — stop, report failure with stderr excerpt, let the caller decide. This matches the typical fix cycle: you cannot meaningfully review test output if the code does not compile.

### Opt-in modes (via caller's input)

- `--all` — run every check regardless of earlier failures. Useful for getting a full picture before a batch of fixes.
- `--fast` — skip tests, only build + lint + typecheck. Useful during tight fix loops when the failing surface is known to be non-test.
- `--only lint` / `--only tests` / `--only build` — single-category check.

If none specified → default sequential fail-fast.

### Output capture

For each command:
- Capture exit code
- Capture last ~50 lines of stderr on failure (truncate from the top if larger)
- On success, do not include stdout in the report — just status

---

## Phase 4: Report

Always produce a structured report, even on single-command runs.

### Format

The report has two parts: a human-readable body and a mandatory machine-readable summary block at the end.

**Body (markdown)** — structured with headers, table of results, and per-failure details:

- `## Check report` with `Stack detected`, `Mode`, `Verdict` lines
- `### Results` — one row per check with Command / Status / Notes
- `### Failures` (only if any) — per failure: command, exit code, stderr excerpt (~50 lines), suggested next step
- `### Summary` — passed/failed/skipped counts + total wall time

**Machine-readable summary** — keep as the final fenced block of the output so callers can tail-parse reliably:

~~~
verdict: FAIL
passed: [build]
failed: [lint]
skipped: [tests]
~~~

The machine-readable block is **mandatory** — orchestrator/skills that loop on `/check` rely on it. Parse the `verdict:` line first; the arrays identify which categories are in each state. `verdict` is one of `PASS`, `FAIL`, or `PARTIAL`.

### Verdict rules

- **PASS** — every executed check returned exit 0. Skipped checks are not failures.
- **FAIL** — at least one executed check returned non-zero exit.
- **PARTIAL** — used in `--all` mode when some checks passed and some failed. Signals "here's everything" rather than "stopped at first break".

---

## Scope Rules

- **In scope:** running mechanical checks; reporting results; truncating noisy output.
- **Out of scope:** editing code, suggesting fixes, running interactive commands, installing missing tools, creating branches, committing.
- **Never** auto-fix formatting or lint issues — even if the tool offers `--fix`. The caller owns the fix cycle.
- **Never** modify build files to make a failure go away. Report and let the caller decide.
- **Never** run destructive operations (`./gradlew clean` is allowed only if the caller explicitly requested it; otherwise, verify with existing build state).

---

## Escalation

Stop and report to the caller when:

- **No recognized tooling detected** and no commands provided.
- A check **hangs or exceeds 15 minutes** wall time. Abort with a timeout note.
- The project requires **authentication or network** that is not available (e.g., private Maven repo down).
- Build wrapper **missing** (`gradlew` referenced but absent) — report rather than trying to regenerate.

When escalating, state what was detected, what was attempted, and what the caller needs to decide.

---

## Integration notes for callers

- `implement` — call `/check` inside its Quality Loop after each code change; fix based on the report, re-run until PASS.
- `finalize` — call `/check` after each Phase's fix round in the multi-round loop.
- Migration skills (`code-migration`, `kmp-migration`, `migrate-to-compose`) — call `/check` after every migration step to verify the step preserved build health.
- User-invoked — run standalone at any time to verify the current branch state (`/check`, `/check --fast`, etc.).

Callers pass the detected slug and working directory; this skill does not manage artifacts. Output is returned to the caller, who decides what to record.

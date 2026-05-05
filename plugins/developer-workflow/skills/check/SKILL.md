---
name: check
description: >-
  Run all mechanical verification checks on the project — build, static analysis (lint),
  tests, and typecheck — in a single command. Reusable utility called by any stage that
  modifies code: implement, finalize, migration skills, or directly by the user.

  Auto-detects project tooling (Gradle, npm/pnpm/yarn, cargo, Swift SPM, Xcode, Python,
  Go, Makefile) and runs the appropriate commands. Does NOT modify code — it only verifies.

  Use when: "check the project", "run tests", "verify build", "does it build?", "smoke check",
  "make sure nothing is broken", "validate the branch", "after I edited X run checks",
  "is everything clean?", "did I break anything?",
  or when a pipeline stage needs to confirm that code modifications
  did not break anything. Do NOT use for code review (that is finalize Phase A), functional
  acceptance testing (use acceptance), or exploratory QA (use bug-hunt).
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
| `Makefile` with `check`/`test` targets | Generic | `make check` if the target exists (authoritative — includes what the maintainer decided to include); otherwise `make test` as fallback. Do not run both: `check` wins when both exist. |

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

**For Node projects this stack-specific order is authoritative** and intentionally overrides the general Phase 3 sequence (Build → Lint → Typecheck → Tests). Rationale: JavaScript projects usually run tests without a compilation step, so lint and typecheck surface problems faster than building first; `build` is the slowest and often unnecessary for local verification, so it's opt-in and last. The Phase 3 description in §3 describes the *default* order for stacks that do not override it.

Pick the package manager from lockfile:

| Lockfile | Manager |
|---|---|
| `pnpm-lock.yaml` | `pnpm run <script>` |
| `yarn.lock` | `yarn <script>` |
| `package-lock.json` | `npm run <script>` |

If no `lint`/`test` scripts exist — report "no check scripts configured" and ask the caller to define them or provide explicit commands.

### 2.3 Xcode

Xcode projects require knowing the scheme and destination — the skill does not guess. Escalate to the caller with a clear ask:

> "Xcode project detected but no check commands configured. Provide build and test commands (e.g., `xcodebuild -scheme MyApp test -destination 'platform=iOS Simulator,name=iPhone 16'`), or configure them in a project-specific override so subsequent `/check` invocations pick them up automatically."

This is an escalation, not an interactive prompt — Phase 3 cannot proceed without the commands. Wrong destination/scheme wastes time and produces misleading errors.

### 2.4 Python

Inspect `pyproject.toml` / `setup.cfg` for configured tools. Run only the tools the project actually uses:

- `[tool.ruff]` → `ruff check .`
- `[tool.mypy]` → `mypy .` (with project path)
- `[tool.pyright]` → `pyright`
- `[tool.pylint]` → `pylint <package>`
- `[tool.flake8]` → `flake8 .`
- `[tool.pytest.ini_options]` or `tests/` present → `pytest` (or `uv run pytest` if the project uses uv)
- `[tool.black]` → `black --check .`

If the project uses `uv` (presence of `uv.lock` or `[tool.uv]` section), prefer `uv run <tool>` over bare invocation — it respects the project's virtual environment.

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
- `--fast` — skip tests AND the public-API coverage gate, only build + lint + typecheck. Useful during tight fix loops when the failing surface is known to be non-test.
- `--only lint` / `--only tests` / `--only build` / `--only typecheck` — single-category check. Each value maps to one of the Phase 3 categories; pass only one at a time. The public-API coverage gate (Phase 3.5) is skipped for any single-category mode.
- `--no-coverage-gate` — skip the Phase 3.5 public-API coverage gate while running the rest of the suite. Discouraged; recorded as `skipped: [coverage]` in the verdict block plus a Notes entry.

If none specified → default sequential fail-fast.

**Flag parsing.** Callers pass the mode as the first `--<flag>` token in the invocation prompt, or via a natural-language directive ("fast mode", "all checks", "only the tests"). The skill parses this early — if multiple mutually-exclusive flags are given (e.g., `--all --fast`), fail with a clear error rather than picking a silent default.

### Output capture

For each command:
- Capture exit code
- Capture last ~50 lines of stderr on failure (truncate from the top if larger)
- On success, do not include stdout in the report — just status

---

## Phase 3.5: Public-API coverage gate (default-on)

Runs after the test category has executed. Even when build / lint / typecheck / tests all pass, a new public symbol that has no matching test file fails this gate. Implements the [`docs/TESTING-STRATEGY.md`](../../docs/TESTING-STRATEGY.md#coverage-audit) "early" check; the late audit lives in `finalize` Phase D.

### When the gate runs

- Current branch differs from the remote default branch — derive the base the same way `finalize` does (`git remote show origin | grep "HEAD branch" | awk '{print $NF}'`, fallbacks `main` / `master` / `develop`), then operate on `git diff $(git merge-base origin/<base> HEAD)..HEAD`.
- Branch is at the default branch (no diff against base) → skip silently.
- `--no-coverage-gate` flag passed by the caller → skip and add `coverage` to the `skipped: [...]` array of the verdict block.

### What counts as a "new public symbol"

| Language | Public symbol patterns | Skip patterns |
|---|---|---|
| Kotlin | top-level `class` / `interface` / `object` / `fun` / `val` / `var` without `internal` / `private` / `protected`; `enum class`, `sealed class`, `data class` *with non-trivial methods* | `data class` with no body, `enum class` with no methods, `typealias`, generated code under `build/`, `internal` symbols |
| Swift | `public` / `open` `class` / `struct` / `enum` / `protocol` / `func` / `var` / `let`; `package` symbols crossing module boundaries | `internal` / `private` / `fileprivate`, plain marker `enum` with no methods, generated code |
| TypeScript / JavaScript | exported `class`, `interface`, `type`, `function`, `const` from `index.ts` or another barrel file | non-exported symbols, `type` aliases that wrap a primitive, generated type defs |
| Python | top-level `class` / `def` not prefixed with `_`, in modules listed in `__all__` | `_`-prefixed names, dataclasses without methods |
| Rust | `pub` items in `lib.rs` / `mod.rs` exposing the crate root | `pub(crate)`, `pub(super)`, derive-only structs |
| Go | exported identifiers (Capitalised) at package level | unexported (lowercase) names, generated `*.pb.go` |

The detection is heuristic — keep it cheap, defer the deep audit to `finalize` Phase D (#152). When the diff includes only modifications to existing public symbols, no new symbols are reported.

### Test-file matching

For each new public symbol, succeed on the FIRST match:

1. Test file added or modified in the same diff with name `<Symbol>Test*`, `<Symbol>Spec*`, `<Symbol>Tests*`, `Test<Symbol>*`, or platform variants.
2. Test file added or modified in the same diff whose contents reference the symbol's qualified name (substring match in source — language-aware enough to ignore comments).
3. Symbol carries an explicit no-test annotation:
   - Kotlin: `@NoTestRequired` annotation, or `@Suppress("MissingTest")`.
   - Swift / Rust / Go / TS / JS: `// no-test-required: <reason>` line comment on the symbol declaration.
   - Python: `# no-test-required: <reason>` line comment on the symbol declaration.
   - or the symbol's file lives under a directory named `no-test-harness/` (escape hatch for legacy modules).

If none of the three matches → the symbol is reported as a coverage failure.

### Trivial-no-test allow-list

The following do NOT require a test even when public:

- Data classes / structs / records with no methods beyond auto-generated equality, hashing, and `toString` / `Codable`.
- Enums / sealed objects with no methods.
- Type aliases / `typealias` / `type`.
- Re-exports (e.g. an `index.ts` that re-exports a module).
- DI module / `@Module` declarations and binding wiring (covered by integration tests, not unit tests).
- Generated code under conventional output directories (`build/`, `Build/`, `target/`, `out/`, `__generated__/`).

Project-specific extensions of this list belong in the project's CLAUDE.md.

### Output

This gate adds a `coverage` category to the report and the verdict block. Result is one of:

- `PASS` — every new public symbol has a match in test files (or is on the trivial / no-test-required list).
- `FAIL` — at least one symbol is unmatched. The Failures section lists each `<file>:<line>: <symbol>` with the rule that was tried and a short remediation hint.
- `SKIP` — gate explicitly skipped via `--no-coverage-gate` (recorded as `skipped: [coverage]` in the verdict block, with the override fact captured in the Notes column).

### Integration with callers

- `implement` Quality Loop Gate 1 fails when `/check` returns `coverage: FAIL`. Engineer agent must add tests, mark trivial, or pass `--no-coverage-gate` (which is recorded in the quality artifact and is discouraged).
- `finalize` invocations of `/check` honour the same gate; a coverage failure surfaced inside finalize is owned by the engineer who introduced the symbol (see [`docs/TESTING-STRATEGY.md`](../../docs/TESTING-STRATEGY.md#author-fixes-broken-tests-non-negotiable)).

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
passed: [build, coverage]
failed: [lint]
skipped: [tests]
~~~

The machine-readable block is **mandatory** — orchestrator/skills that loop on `/check` rely on it. Parse the `verdict:` line first; the arrays identify which categories are in each state. `verdict` is one of `PASS`, `FAIL`, or `PARTIAL`.

### Verdict rules

- **PASS** — every executed check returned exit 0 AND the Phase 3.5 coverage gate (when not explicitly skipped) found a match for every new public symbol. Skipped checks are not failures.
- **FAIL** — at least one executed check returned non-zero exit, OR the Phase 3.5 coverage gate reported one or more unmatched new public symbols. This applies to default (fail-fast) mode: a failure followed by `SKIP` for remaining categories is still FAIL, not PARTIAL.
- **PARTIAL** — reserved for `--all` mode when some checks passed and some failed. Signals "here's everything" rather than "stopped at first break". Never emit PARTIAL when any check was SKIP due to fail-fast.

The coverage gate appears as a `coverage` entry in the `passed` / `failed` / `skipped` arrays of the machine-readable summary block.

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

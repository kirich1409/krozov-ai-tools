# Step 3 — Per-Agent Prompts and Verdict Rules

Each fan-out member receives a narrow prompt. Verdict rules below apply to the per-check
artifact (see `references/per-check-schema.md`). Agents write their artifact at
`swarm-report/<slug>-acceptance-<check>.md`.

## 3.1 `manual-tester` — UI branch

`manual-tester` owns the runtime environment end-to-end per its Step 0 Environment Setup.
Acceptance does not pre-launch — that is intentional delegation.

Prompt contents:

1. **Spec context** — full text or clear pointers.
2. **Test plan** — the complete set of test cases.
3. **Target hints** (optional) — device/URL if the user already named one.
4. **Scope** — which tiers (default: Smoke + Feature).
5. **Output path** — `swarm-report/<slug>-acceptance-manual.md` with the per-check schema.

If the agent returns `WARN` with `blocked_on`, surface that text to the user as the primary
next-step requirement before re-running acceptance.

## 3.2 `code-reviewer` — delta review (skipped if Step 2.5 matched)

Prompt contents:

1. **Task description** — one sentence from spec or PR title.
2. **Plan pointer** — path to implement receipt or research report if present.
3. **Git diff** — current diff.
4. **Output path** — `swarm-report/<slug>-acceptance-code.md`.

Verdict rules: `PASS` if no semantic bugs, logic errors, or security issues; `WARN` for
style/minor; `FAIL` for blockers.

## 3.3 Build smoke — non-UI branch (Bash)

Pick the command by `ecosystem` (see ORCHESTRATION.md §Build system detection):

| `ecosystem` | Command |
|---|---|
| `gradle` | `./gradlew build -x test --quiet` (single-module) or `./gradlew :check` (multi-module) |
| `node` | `npm run build` (or `pnpm build` / `yarn build`) |
| `rust` | `cargo build --release --quiet` |
| `go` | `go build ./...` |
| `python` | `python -m compileall .` or package-specific build |

Multi-module detection: scan `settings.gradle*` for `include(` statements. If subprojects
are declared and the user did not specify a target module, ask which module is the smoke
target **before** entering Step 3 (do not block the fan-out message with a question).

If the `ecosystem` or command is not resolvable, skip with `verdict: SKIPPED` and
`blocked_on: build command unknown`. On success write `verdict: PASS`; on failure capture
the last ~50 lines and write `verdict: FAIL`. Receipt at
`swarm-report/<slug>-acceptance-build.md`.

## 3.4 `business-analyst` — AC coverage (conditional)

Fires when `acceptance_criteria_ids` in spec frontmatter is a non-empty list.

Prompt contents:

1. **Spec** — the spec file path.
2. **Diff / implement receipt** — evidence for each AC.
3. **Test plan** (if any) — TC list mapped to AC via each test case's `Source:` field
   (e.g. `Source: AC-1` or `Source: AC-2, AC-3`). This is the canonical mapping used by
   `generate-test-plan`; do not invent a new `AC-ref:` field.
4. **manual-tester output** (if running) — pointer to
   `swarm-report/<slug>-acceptance-manual.md`.
5. **Output path** — `swarm-report/<slug>-acceptance-ac-coverage.md`.

Verdict rules: `PASS` if every `AC-N` has at least one evidence pointer; `WARN` for weak
coverage (single witness on high-risk AC); `FAIL` for any missing AC. Severity: `FAIL` on
missing AC is `critical`; weak coverage is `major`.

## 3.5 `ux-expert` — design-review or a11y (conditional)

Fires when **`has_ui_surface == true`** AND (`design.figma` is set for design-review mode
**or** `non_functional.a11y` is set for a11y mode). Non-UI projects never trigger this even
if `non_functional.a11y` is present — a11y on backend/library/CLI has no surface to audit.

Design-review and a11y can both fire in one invocation. When both trigger, spawn `ux-expert`
once with mode `both`; the agent writes **two** artifacts (one per concern) so aggregation
in Step 4 treats them as independent checks:

- `swarm-report/<slug>-acceptance-design.md` with `check: design`
- `swarm-report/<slug>-acceptance-a11y.md` with `check: a11y`

When only one mode fires, only the corresponding artifact is written.

Prompt contents:

1. **Mode** — `design-review` / `a11y` / `both`.
2. **Spec** — file path.
3. **Design source** — `design.figma` URL (design-review mode).
4. **a11y target** — value of `non_functional.a11y` (e.g. `wcag-aa`).
5. **Running app pointer** — target hints; the agent reads running-app state via MCP only
   when the environment is already prepared, otherwise works from screenshots/code.
6. **Output paths** — one or both of the filenames listed above, matching the mode.

Verdict rules: `PASS` if design matches reference and a11y criteria met; `WARN` for minor
spacing/color deviations or AA soft failures; `FAIL` for missing components, broken
interaction paths, or hard a11y violations (keyboard trap, contrast below threshold).

## 3.6 `security-expert` (conditional)

Fires when `risk_areas` intersects `{auth, payment, pii, data-migration}`.

Prompt contents:

1. **Risk list** — the intersection subset.
2. **Diff** — full git diff.
3. **Spec** — file path.
4. **Output path** — `swarm-report/<slug>-acceptance-security.md`.

Verdict rules: `PASS` if no applicable OWASP / project-security-rule violations; `WARN` for
minor hardening opportunities; `FAIL` for exploitable issues, secret leaks, or regulation
breaches.

## 3.7 `performance-expert` (conditional)

Fires when `non_functional.sla` is set **or** `risk_areas` contains `perf-critical`.

Prompt contents:

1. **SLA target** — from `non_functional.sla`, or implicit `perf-critical` baseline.
2. **Diff** — full git diff.
3. **Output path** — `swarm-report/<slug>-acceptance-performance.md`.

Verdict rules: `PASS` if no regression; `WARN` for borderline; `FAIL` for violations.

## 3.8 `architecture-expert` — diff-triggered (conditional)

Fires when the diff touches a public API symbol **or** spans ≥ 3 top-level modules (see the
heuristic in `references/conditional-triggers.md`).

Prompt contents:

1. **Trigger reason** — `public-api` / `cross-module` / `both` with the specific file list
   that matched.
2. **Diff** — full git diff (scoped to triggered files + their immediate neighbours).
3. **Module map** — list of top-level modules touched, discovered from
   `settings.gradle*` / `package.json` workspaces / `Cargo.toml` workspace members.
4. **Output path** — `swarm-report/<slug>-acceptance-architecture.md` with
   `check: architecture`.

Verdict rules: `PASS` if public contracts are preserved and module dependency direction is
clean; `WARN` for style issues (e.g., missing deprecation annotation, avoidable coupling);
`FAIL` for contract breakage, circular dependencies, or leaking internals into a public API.

## 3.9 `build-engineer` — diff-triggered (conditional)

Fires when the diff touches any build file listed in the conditional-triggers table.

Prompt contents:

1. **Build files changed** — exact file list from the diff.
2. **Diff** — scoped to those files plus any touched module manifests.
3. **Ecosystem** — resolved `ecosystem` from Step 0 (drives which toolchain the agent
   should evaluate against).
4. **Output path** — `swarm-report/<slug>-acceptance-build-config.md` with
   `check: build-config`.

Note: `check: build` is already used by the non-UI build smoke (§3.3). The expert review
of **config changes** uses a distinct check identifier `build-config` so aggregation can
treat the two axes independently (a project can have a clean smoke and a broken config, or
vice versa).

Verdict rules: `PASS` if dependency additions are pinned/hash-verified, plugin versions are
consistent, and task wiring is intact; `WARN` for unpinned version ranges, unused
dependencies, or minor style issues; `FAIL` for breaking plugin mismatches, missing
required configuration, or dependency choices that conflict with project policy.

## 3.10 `devops-expert` — diff-triggered (conditional)

Fires when the diff touches CI / release configuration (see the conditional-triggers table).

Prompt contents:

1. **CI files changed** — exact file list.
2. **Diff** — scoped to CI/release files.
3. **Repo context** — `public` vs `private` (affects secret handling guidance), and any
   related marketplace/deployment manifests if present.
4. **Output path** — `swarm-report/<slug>-acceptance-devops.md` with `check: devops`.

Verdict rules: `PASS` if pipeline health is preserved, secrets are handled correctly, and
rollout gates remain sound; `WARN` for minor inefficiencies or missing
`timeout-minutes` / `concurrency` guards; `FAIL` for leaked secrets, disabled safety gates,
or breaking workflow syntax.

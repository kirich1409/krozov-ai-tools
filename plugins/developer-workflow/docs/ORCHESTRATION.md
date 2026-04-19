# Dev Workflow Orchestration

Rules for routing developer tasks through the correct pipeline and managing stage transitions. Applies to all projects that use the `developer-workflow` plugin.

## Task Profiling

When receiving a task, classify it by **size and complexity**, then pick the appropriate pipeline:

| Size | Criteria | Pipeline |
|------|----------|----------|
| Small | 1-3 files, clear change, no new APIs | Implement → Quality (build+test only) → done |
| Medium | Multiple files, one module, known patterns | Plan → Implement → Quality → PR |
| Large | Cross-module, new APIs, unfamiliar libraries | Research → Plan → Implement → Quality → Verify → PR |
| Migration | Library/technology swap | Research → Snapshot → Migrate → Verify → PR |
| Research | Investigation only, no code changes | Research → Report |

**Skip stages that add no value for the task at hand.** A one-line bug fix does not need Research or a formal Plan. A large feature with unfamiliar dependencies needs the full pipeline.

Auto-detect from scope and context. If ambiguous — state the assumed profile and ask the user to confirm before proceeding.

Migration tasks use the `code-migration` skill. Feature tasks with explicit `/developer-workflow:implement-task` use that skill's built-in pipeline instead of these rules.

## Research Consortium

On the Research stage, launch parallel experts (up to 5 agents simultaneously):

| Agent | Responsibility | Tool |
|-------|---------------|------|
| Explore | Codebase analysis: existing code, patterns, dependencies, call sites | ast-index, Read, Grep |
| Web search | Approaches, best practices, recent changes | Perplexity (`perplexity_search`, `perplexity_research`) or WebSearch |
| Docs | Library documentation for involved dependencies | DeepWiki / Context7 |
| Deps | Compatibility, versions, vulnerabilities | maven-mcp tools |
| Architecture | How the change fits into the project structure | `architecture-expert` agent |

Not every task needs all five. Launch only what the task demands — a simple bug fix may need only Explore + Docs; a large feature or migration needs the full consortium.

After results arrive, launch `business-analyst` agent to review the combined findings: check completeness, flag gaps, surface conflicting data.

Artifact: `swarm-report/<slug>-research.md`

## Web Lookup

Use web sources when the task involves external libraries, migrations, or unfamiliar APIs. Skip for internal-only changes where codebase analysis is sufficient.

- Perplexity — approaches, best practices, common pitfalls
- DeepWiki / Context7 — library docs and API reference
- WebSearch — recent releases, breaking changes, migration guides
- maven-mcp — dependency compatibility and vulnerability data

## Re-Anchoring

Before each pipeline stage, the executing agent must re-read:

1. The original user intent / task description
2. The research report (`swarm-report/<slug>-research.md`) — if exists
3. The plan (`swarm-report/<slug>-plan.md` or Plan Mode output) — if exists

Include these paths in the agent's context handoff prompt. This prevents drift from the original goal during long sessions and across agent boundaries.

## State Machine

Allowed transitions between stages. Forward is default; backward transitions are explicit recovery paths.

```
Research ──→ Plan
Plan ──→ TestPlan           (test-plan stage not skipped)
Plan ──→ Implement          (test-plan stage skipped: skip-detector conditions or --skip-test-plan)
Plan ──→ Research           (plan review reveals gaps or missing context)
TestPlan ──→ TestPlanReview
TestPlanReview ──→ Implement  (PASS or WARN)
TestPlanReview ──→ TestPlan   (FAIL — revise loop, max 3 cycles, then escalate)
Implement ──→ Quality
Implement ──→ Research      (scope is larger than expected — escalate)
Quality ──→ Verify
Quality ──→ Implement       (quality loop found issues to fix)
Verify ──→ PR
Verify ──→ Implement        (verification fails — fix and re-verify)
Verify ──→ TestPlan         (new P0/P1 bugs require a `## Regression TC` section appended to the permanent test plan)
PR ──→ Merge
PR ──→ Implement            (review feedback requires code changes)
```

Backward transition requires a reason logged in the stage artifact. No silent rollbacks.

## Receipt-Based Gating

Each stage produces an artifact in `swarm-report/`. The next stage reads it before starting. No stage begins without the receipt from the previous one.

| Stage | Artifact |
|-------|----------|
| Research | `<slug>-research.md` |
| Plan | `<slug>-plan.md` |
| TestPlan | `docs/testplans/<slug>-test-plan.md` (permanent, source of truth) + `<slug>-test-plan.md` (receipt: `status`, `permanent_path`, `source_spec`, `review_verdict`, `phase_coverage`). Created by `generate-test-plan` when invoked from the orchestrator with a slug; read by `plan-review` (test-plan branch) and `acceptance`. |
| TestPlanReview | `<slug>-test-plan.md` receipt updated in place: `review_verdict` set to PASS / WARN / FAIL, `status` advances Draft → Ready on PASS/WARN. |
| Implement | `<slug>-implement.md` (summary of changes, files touched) |
| Quality | `<slug>-quality.md` (build/lint/test results, issues found/fixed) |
| Verify | `<slug>-verify.md` / `<slug>-acceptance.md` (verification result: VERIFIED/FAILED/PARTIAL, evidence, `test_plan_source: receipt / mounted / on-the-fly / absent` when the Acceptance stage consumed a test plan) |
| PR | `<slug>-pr.md` (PR URL, description, reviewers) |

If a stage artifact is missing — the previous stage did not complete. Do not skip ahead.

## Quality Loop

When the user asks to "prepare for PR", "quality check the branch", "run the quality loop", or "make it PR-ready" — run these gates on the current branch.

After implementation completes and before PR creation, run a mandatory quality loop. Each gate runs in order; a failure triggers a fix cycle before advancing.

### Build system detection

Use the highest-priority match when multiple build files are present:

| Priority | File present | Build | Lint | Test |
|----------|---|---|---|---|
| 1 | `Makefile` (with targets) | `make build` | `make lint` | `make test` |
| 2 | `package.json` | `npm run build` | `npm run lint` | `npm test` |
| 3 | `Cargo.toml` | `cargo build` | `cargo clippy` | `cargo test` |
| 4 | `build.gradle(.kts)` | `./gradlew build` | `./gradlew lint` | `./gradlew test` |
| 5 | `pom.xml` | `mvn package -q` | `mvn checkstyle:check` | `mvn test` |
| 6 | `go.mod` | `go build ./...` | `golangci-lint run` | `go test ./...` |
| 7 | `pyproject.toml` / `setup.py` | `pip install -e .` | `ruff check .` | `pytest` |

Monorepo: if all changed files are under a single subdirectory with its own build file, use that subdirectory's build system.

### Project type detection

Orthogonal to build-system detection: build system answers "how to build/test",
project type answers "what kind of product is this". Drives which acceptance checks are
meaningful (e.g., manual UI QA only on UI surfaces). Consumed by `acceptance`, and may be
consumed by `research`, `generate-test-plan`, `create-pr` as those skills evolve.

Cheap heuristic over the repository root plus a few well-known paths (e.g. `app/`, `android/`,
`ios/`) — no external tools required, no exhaustive tree walk:

Each row resolves to exactly one `ecosystem` value — downstream steps (e.g. acceptance build-smoke command selection) assume a single value. Split cases where the same `project_type` has multiple possible stacks into distinct rows.

| Signal found at repo root or a well-known subdirectory | `project_type` | `has_ui_surface` | `ecosystem` |
|---|---|---|---|
| `AndroidManifest.xml` under `app/` / `android/`, or `build.gradle*` with `com.android.application` | `android` | true | `gradle` |
| `*.xcodeproj` / `*.xcworkspace`, `Package.swift` iOS/macOS target, or `Podfile` iOS pods | `ios` | true | `xcode` |
| `package.json` with a frontend framework (`react`, `vue`, `svelte`, `next`, `vite`, `astro`) or root `index.html` | `web` | true | `node` |
| `package.json` with `electron` | `desktop` | true | `node` |
| Compose Desktop entrypoint (Gradle with `org.jetbrains.compose` applied to a JVM target) | `desktop` | true | `gradle` |
| Swift AppKit entrypoint (`NSApplication` main or `@main App` targeting macOS) | `desktop` | true | `xcode` |
| `build.gradle*` with Spring / Ktor / Micronaut / Quarkus / `application` plugin (not Android) | `backend-jvm` | false | `gradle` |
| `package.json` with a Node server (`express`, `fastify`, `koa`, `nest`) and no frontend framework | `backend-node` | false | `node` |
| `Cargo.toml` without web/GUI frameworks, or Rust `bin/` entrypoints | `cli` | false | `rust` |
| `pyproject.toml` without web/GUI frameworks, or Python `bin/` entrypoints | `cli` | false | `python` |
| `go.mod` without web/GUI frameworks, or Go `bin/` entrypoints | `cli` | false | `go` |
| `.claude-plugin/` directory (or `.claude-plugin/plugin.json`) | `library` | false | `node` |
| Gradle/Maven library packaging without application plugin | `library` | false | `gradle` |
| None of the above matches unambiguously | `generic` | ask user | ask user |

**Override policy.** When `write-spec` records `platform:` in the spec frontmatter or the user
explicitly corrects a detection, that value takes precedence over the heuristic and is recorded
as `project_type_override` in the consuming skill's receipt.

**Scope.** Root-level glance plus the listed subdirectories is enough. Do not recurse. If the
detection is ambiguous (`generic`), ask the user once — do not guess and do not fall back to a
default like `library`.

### Scope decision

- **In current changes** (`git diff $BASE...HEAD`) — fix autonomously
- **Out of scope, obvious fix** (missing import, typo in new string) — fix autonomously
- **Out of scope, non-obvious** (pre-existing failures, unrelated deps) — note for user, don't fix; include what the issue is, why it's unrelated, and options (fix / skip / separate issue)

**Minor (exit loop):** style preferences, cosmetic suggestions with no correctness impact.
**Non-minor (keep looping):** bugs, broken tests, lint errors, security issues, incorrect logic.

### Gates (sequential)

| # | Gate | Action | Agent |
|---|------|--------|-------|
| 1 | Build | Compile the project, resolve all errors | Implementation agent |
| 2 | Static analysis | Lint, formatting, unused imports — fix violations | Implementation agent |
| 3 | Tests | Run unit + integration tests, fix failures | Implementation agent |
| 4 | Semantic self-review | Compare original intent ↔ actual `git diff` | `code-reviewer` agent |
| 5 | Expert reviews | Parallel domain-specific reviews (only when triggered) | Specialist agents |
| 6 | Intent check | Re-read original task + plan, verify the diff addresses them | Orchestrator |

### Separation of author and reviewer

The agent that wrote the code must NOT perform the semantic self-review (gate 4). Launch the `code-reviewer` agent that receives only:

1. The original task description (verbatim)
2. The plan artifact (`swarm-report/<slug>-plan.md`) — if exists
3. The `git diff` of all changes

Nothing else. No implementation context, no conversation history. This prevents the author's assumptions from leaking into the review.

Questions the reviewer must answer:
- Does the code solve the original problem?
- Is there scope creep beyond the plan?
- Are acceptance criteria from the plan met?

### Invocation template for gate 4

The orchestrator prepares the diff before launching the agent:
1. `git diff $(git merge-base origin/main HEAD)..HEAD > swarm-report/<slug>-diff.txt`
2. Launch `code-reviewer` agent with this prompt structure:

```
## Task description
{original task description verbatim}

## Plan
Read the plan at: {path to swarm-report/<slug>-plan.md, or "No plan for this task"}

## Changes to review
Read the diff at: {path to swarm-report/<slug>-diff.txt}

Review these changes and produce a structured verdict.
```

### Expert review triggers

Not every change needs all expert reviews. Launch only the relevant ones, in parallel.

| Expert | Trigger — files touch any of: |
|--------|-------------------------------|
| `security-expert` | Auth, encryption, token/secret storage, network requests, permissions, user data handling |
| `performance-expert` | RecyclerView/LazyColumn adapters, database queries, image loading, coroutine dispatchers, hot loops, large collections |
| `architecture-expert` | New modules created, dependency direction changed, public API modified, new abstractions introduced |

If no trigger matches — skip expert reviews entirely.

### Iteration cap

- **Per gate:** max 3 fix attempts. If still failing after 3 — stop and escalate to user with the failure details and what was tried.
- **Total quality loop:** max 5 full iterations (gate 1–6 cycles). If the loop does not converge — escalate. This prevents infinite fix-break-fix loops.

### Quality report artifact

After the loop completes (pass or escalation), save `swarm-report/<slug>-quality.md` with:

- Gates passed / failed (with attempt counts)
- Issues found and fixes applied
- Expert review findings (per expert, if any ran)
- Semantic self-review verdict
- Intent check result: PASS or DRIFT (with explanation)

This artifact is the receipt for the Verify stage — Verify must not start without it.

### Verdict handling (gate 4)

| Verdict | Orchestrator action |
|---------|---------------------|
| PASS | Proceed to gate 5 (expert reviews) |
| WARN | Proceed, but include major issues in `swarm-report/<slug>-quality.md` under "Acknowledged risks". If creating a PR, add these to the PR description. |
| FAIL | Backward transition → Implement. Fix critical issues, re-run gate 4 (max 3 cycles). |

## Testing Strategy in Planning

The Plan stage MUST include these sections:

- **Testing Strategy** — unit / integration / manual QA; which tools (`manual-tester`, device testing, etc.); what is covered by automated tests vs manual verification
- **Verification Approach** — how to verify on a live app or in a running environment; what commands to run; what to visually inspect
- **Acceptance Criteria** — derived from research, task description, or user requirements; concrete and verifiable conditions for "done"

A plan without these sections is incomplete. Use `plan-review` skill to validate before proceeding to implementation.

## Skill and Agent Selection

Route implementation to the right specialist:

| Task type | Skill / Agent |
|-----------|--------------|
| Research / investigation | `research` skill |
| Feature decomposition | `decompose-feature` skill |
| Compose UI from design/spec | `compose-developer` agent |
| Kotlin business logic, data layer | `kotlin-engineer` agent |
| View → Compose migration | `migrate-to-compose` skill |
| Library / technology swap | `code-migration` skill |
| Module → KMP | `kmp-migration` skill |
| Full autonomous cycle | `implement-task` skill (explicit-only) |
| Quality check before PR | Quality Loop gates (this section) |
| PR creation | `create-pr` skill |
| Triage feedback (PR comments or pasted text) — categorize, prioritize, group; optionally post replies / resolve threads for items with terminal verdicts via an editable manifest; never edits code | `triage-feedback` skill |
| Plan review (PoLL) | `plan-review` skill |
| Test plan creation | `generate-test-plan` skill |
| Feature verification on device | `test-feature` skill |
| Retroactive test writing | `write-tests` skill |
| Undirected QA / bug hunting | `exploratory-test` skill |
| Research findings review | `business-analyst` agent |

## Stage Boundary Protocol

At every stage boundary:

1. Write the stage artifact to `swarm-report/`
2. Include the artifact path in the next agent's prompt — the agent reads it itself
3. Validate the artifact before advancing: does it address the original task? Is it concrete (file paths, findings, code), not generic filler?
4. Run `/compact` only for Large/Migration tasks or when context is noticeably degraded. Skip for Small/Medium tasks.


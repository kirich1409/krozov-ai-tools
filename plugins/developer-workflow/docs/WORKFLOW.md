# Full Development Cycle: From Idea to Merge

## 1. Overview

developer-workflow implements a fully autonomous development cycle driven by a state machine
with explicit transitions between stages. Each incoming task is classified into one of five
profiles (Feature, Bug Fix, Migration, Research, Trivial), and the profile determines which
pipeline stages will be executed. This is not a rigid waterfall — a profile can skip stages
(Trivial does not require Research and Plan) or replace them (Migration delegates to
`code-migration`).

Research is performed by the Research Consortium — up to five parallel expert agents, each
working independently in its own domain (codebase, web, documentation, dependencies,
architecture). Results are reviewed and validated by `business-analyst`.
This ensures decisions are made based on data, not solely on the model's training data.

Quality is split into three stages, each answering a different question:
**implement** (does the code work and match the plan?) → **finalize** (is the code written
well?) → **acceptance** (does the feature solve the user's problem?). `implement` runs a
2-gate Quality Loop: mechanical checks via `/check` (build/lint/typecheck/tests) and intent
check. `finalize` runs a multi-round review-and-fix loop (code-reviewer → /simplify →
optional pr-review-toolkit trio → conditional expert reviews) with `/check` between each fix. Key
principle: the author of the code never reviews their own code — `finalize` Phase A
launches a separate `code-reviewer` agent that receives only the task description, plan,
and git diff, without any implementation context. Receipt-based gating ensures no stage
starts without the previous stage's artifact. Re-anchoring at every stage transition prevents
drift from the original intent.


## 2. Pipeline Overview

### Feature pipeline

```
IDEA / FEATURE REQUEST
  |
  v
[research] ---- Research Consortium (up to 5 parallel experts)
  |                Artifact: swarm-report/<slug>-research.md
  v
[decompose-feature] ---- Break into tasks with dependencies (optional)
  |                        Artifact: swarm-report/<slug>-decomposition.md
  v
[multiexpert-review] ---- PoLL review of the plan (optional)
  |                  Artifact: multiexpert review verdict
  v
[test-plan] ---- Generate test plan (default-on, skip per detector conditions or --skip-test-plan)
  |                Artifacts: docs/testplans/<slug>-test-plan.md (permanent)
  |                           swarm-report/<slug>-test-plan.md (receipt)
  v
[test-plan-review] ---- multiexpert-review with test-plan profile (PASS / WARN / FAIL)
  |                 FAIL → revise loop back to [test-plan] (max 3 cycles)
  |                 Artifact: receipt review_verdict updated
  v
  |   ┌────────────── for each task ──────────────┐
  |   │                                            │
  |   v                                            │
  | [implement] ---- Write code + Quality Loop (2 gates)
  |   |  |-- specialist agents                     │
  |   |  '-- /check + intent check                 │
  |   |        Artifacts: <slug>-implement.md      │
  |   |                   <slug>-quality.md        │
  |   v                                            │
  | [finalize] ---- Code-quality pass (3-round loop)│
  |   |  |-- Phase A: code-reviewer               │
  |   |  |-- Phase B: /simplify                    │
  |   |  |-- Phase C: pr-review-toolkit trio (opt) │
  |   |  '-- Phase D: experts (conditional)        │
  |   |        Artifact: <slug>-finalize.md        │
  |   v                                            │
  | [acceptance] ---- Verify against spec          │
  |   |  '-- manual-tester agent                   │
  |   |        Artifact: <slug>-acceptance.md      │
  |   |                                            │
  |   |── FAILED? back to implement ───────────────┘
  |   v
  | [create-pr] ---- PR per task or bundled
  |   │
  └───┘ next task
  v
PR CREATED (all tasks) ---- drive-to-merge: autonomous CI + review loop; user confirms final merge
```

**PR granularity** is decided by the orchestrator:
- One PR per task — when tasks are independent and reviewable separately
- Bundled PR — when tasks are tightly coupled or the feature is small enough

### Bug pipeline

```
BUG REPORT / ISSUE
  |
  v
[debug] ---- Reproduce -> Binary search -> Hypothesis -> Confirm root cause
  |             Artifact: swarm-report/<slug>-debug.md
  v
[implement] ---- Fix based on root cause + Quality Loop (2 gates)
  |                Artifacts: swarm-report/<slug>-implement.md
  |                           swarm-report/<slug>-quality.md
  v
[finalize] ---- Code-quality pass (3-round loop)
  |                Artifact: swarm-report/<slug>-finalize.md
  v
[acceptance] ---- Verify bug no longer reproduces on live app
  |                Artifact: swarm-report/<slug>-acceptance.md
  v
[create-pr] ---- Draft PR -> Ready for Review
  |                Artifact: swarm-report/<slug>-pr.md
  v
PR CREATED ---- drive-to-merge: autonomous CI + review loop; user confirms final merge
```


## 3. Task Profiles and Routing

| Profile | Pipeline | Signals | Skips |
|---------|----------|---------|-------|
| **Feature** | Research -> Decompose -> Plan Review -> Test Plan -> Test Plan Review -> [Implement -> Acceptance] per task -> Create PR | "add", "implement", "build", "create" | Decompose optional for single-task features; Test Plan skipped per [detector conditions](../skills/feature-flow/SKILL.md#testplan-stage-skip-detection) or `--skip-test-plan` override |
| **Bug Fix** | Debug -> Implement -> Acceptance -> Create PR | "fix", "broken", "crash", "regression" | Research, Plan |
| **Migration** | Research -> Snapshot -> Migrate -> Acceptance -> Create PR | "migrate", "replace", "switch to" | Plan (delegates to `code-migration`) |
| **Research** | Research -> Report | "investigate", "compare", "evaluate" | Implement, Acceptance, PR |
| **Trivial** | Implement -> Create PR | Single-file change, config tweak | Research, Plan, Debug, Acceptance |

Auto-detection is based on keywords and context. When ambiguous — ask the user to confirm
before starting work.


## 4. Quality pipeline — three stages

Quality is enforced across three stages, each answering a different question:

| Stage | Skill | Question |
|---|---|---|
| 1. Mechanical + intent | `implement` | Does it compile, lint, test, and match the plan? |
| 2. Code quality | `finalize` | Is the code written well? |
| 3. Functional correctness | `acceptance` | Does the feature solve the user's problem? |

### 4.1 Implement — 2-gate Quality Loop

```
     __________________________________________
    |                                          |
    v                                          |
+----------+   +--------------+                |
| Gate 1   |-->| Gate 2       |                |
| /check   |   | Intent Check |                |
+----------+   +--------------+                |
    |fail          |fail                       |
    v              v                           |
 [fix cycle] -- re-run /check ------------------'
 max 3 iterations total; per-gate 3 fix attempts
```

| # | Gate | Action | Executor |
|---|------|--------|----------|
| 1 | Mechanical checks | Invoke `/check` — build + lint + typecheck + tests (fail-fast); fix reported issues, re-invoke until PASS | Implementation agent + `/check` skill |
| 2 | Intent Check | Re-read task + plan, verify correspondence | Orchestrator |

### 4.2 Finalize — multi-round code-quality loop

After implement PASSes both gates, orchestrator invokes `/finalize`:

```
Round N  (max 3 rounds):
  Phase A  code-reviewer       -> fix BLOCK -> /check
  Phase B  /simplify (auto-fix)                -> /check
  Phase C  pr-review-toolkit trio (parallel, optional) -> fix BLOCK -> /check
  Phase D  experts (conditional, parallel)    -> fix BLOCK -> /check
  end round: any BLOCK? yes -> next round. no -> PASS, exit.
```

| Phase | Agent / skill | Purpose |
|---|---|---|
| A | `code-reviewer` (from `developer-workflow-experts`) | Plan conformance, CLAUDE.md, bugs — confidence 0/25/50/75/100 rubric |
| B | `/simplify` (built-in) | Reuse / quality / efficiency with auto-fix |
| C | `pr-review-toolkit:pr-test-analyzer`, `silent-failure-hunter`, `type-design-analyzer` (parallel, optional soft-ref — skipped if plugin not installed) | Test quality, silent failures, type design invariants |
| D | `security-expert`, `performance-expert`, `architecture-expert` (conditional, parallel) | Domain-specific deep review |

### Phase D trigger table

| Expert | Trigger — changed files touch any of: |
|--------|---------------------------------------|
| `security-expert` | Auth, encryption, token storage, network, permissions, PII |
| `performance-expert` | RecyclerView/LazyColumn, DB queries, image loading, hot loops |
| `architecture-expert` | New modules, changed dependency direction, public API |

If no trigger fired — Phase D is skipped for that round.

### Verdict handling (Phase A code-reviewer)

| Verdict | Orchestrator action |
|---------|---------------------|
| **PASS** | Continue to Phase B (/simplify) |
| **WARN** | Continue to Phase B; items listed in the finalize report as "Acknowledged risks" |
| **FAIL** | Apply BLOCK fixes, re-run `/check`, then re-run Phase A in next round; after 3 rounds with FAIL — escalate to user |

### Finalize exit criteria

- **PASS** — no BLOCK-severity findings across A/B/C/D. WARN and NIT surface in `<slug>-finalize.md`.
- **ESCALATE** — 3 rounds complete, BLOCK findings remain. Stop and report to user.

### Build System Detection

Handled by the `/check` skill — it auto-detects Gradle, Node (npm/pnpm/yarn), Cargo, Swift SPM, Python, Go, or Makefile markers and runs the appropriate commands. See [`skills/check/SKILL.md`](../skills/check/SKILL.md) for the full detection matrix and per-stack behaviour.


## 5. Research Consortium

```
                    [Scope the Research]
                           |
              Topic + Context + Constraints
                           |
         .-----------------+------------------.
         |         |         |        |        |
         v         v         v        v        v
    +--------+ +------+ +------+ +------+ +-----------+
    |Codebase| | Web  | | Docs | | Deps | |Architecture|
    |Expert  | |Expert| |Expert| |Expert| |  Expert    |
    +--------+ +------+ +------+ +------+ +-----------+
    |ast-index| |Perplex| |Deep- | |maven-| |arch.-     |
    |Read     | |ity    | |Wiki  | |mcp   | |expert     |
    |Grep     | |Web-   | |Cont- | |tools | |agent      |
    |         | |Search | |ext7  | |      | |           |
    +----+----+ +--+---+ +--+---+ +--+---+ +-----+-----+
         |         |         |        |           |
         '-----.---'----.----'----.---'-----.-----'
               |                            |
               v                            v
        +-------------+             +--------------+
        |  Synthesis  |             | State file   |
        | (cross-ref, |             | (compaction- |
        |  converge,  |             |  resilient)  |
        |  contradict)|             +--------------+
        +------+------+
               |
               v
      +----------------+
      |business-analyst|
      | auto-review    |
      +------+---------+
             |
             v
    swarm-report/<slug>-research.md
```

### Expert Tracks

| Expert | When to include | Tools |
|--------|----------------|-------|
| **Codebase** | Topic touches existing code, patterns, modules | `ast-index`, Read, Grep |
| **Web** | Always (mandatory — Web-Lookup Mandate) | Perplexity (`perplexity_search`, `perplexity_research`), WebSearch |
| **Docs** | Topic involves specific libraries/frameworks | DeepWiki, Context7 |
| **Dependencies** | Adding, replacing, or evaluating JVM/KMP dependencies | maven-mcp tools |
| **Architecture** | Impact on module boundaries, dependency direction, API | `architecture-expert` agent |

**Web-Lookup Mandate:** internet research is mandatory. Every research must produce at
least one web-sourced insight. Relying solely on the codebase and training data is prohibited.

### Data Flow

1. Experts work **in parallel and independently** — results from one are not passed to another
2. **Synthesis** — orchestrator aggregates: finds convergence, contradictions, gaps
3. **Auto-review** — `business-analyst` checks completeness, product sense, practicality
4. If auto-review finds gaps — targeted re-run of individual experts


## 6. State Machine

```
Research --> Decompose --> Plan Review --> Test Plan --> Test Plan Review --> Implement --> Acceptance --> PR --> Merge
   ^            |              |               ^              |                   ^  ^           |          |
   |            |              |               |              |                   |  |           |          |
   '-- gaps ----'              |               '- revise -----'                   |  '-- FAILED -'          |
   ^                           |                 (max 3 cycles)                   |                         |
   '-- scope too large --------+--------------------------------------------------'                         |
                               |              ^                                                             |
                               '-- FAIL ------'                                                             |
                                                                                  ^                         |
                                                                                  '-- review feedback ------'
                                                          ^
                                                          '-- Regression TC (Acceptance → Test Plan)
```

Test Plan + Test Plan Review are **default-on**. They are skipped when the skip-detector
conditions hold (see [`feature-flow` SKILL §TestPlan Stage Skip Detection](../skills/feature-flow/SKILL.md#testplan-stage-skip-detection))
or when the user passes the `--skip-test-plan` override — in both cases the pipeline
transitions directly from Plan Review to Implement.

For Bug Fix pipeline, replace Research + Decompose with Debug:

```
Debug --> Implement --> Acceptance --> PR --> Merge
             ^              |
             '--- FAILED ---'
```

### Forward Transitions (default)

| From | To | Condition |
|------|----|-----------|
| Research | Decompose | Research complete |
| Debug | Implement | Root cause identified |
| Decompose | Plan Review | Tasks defined |
| Plan Review | Test Plan | Plan PASS or CONDITIONAL; test-plan stage not skipped |
| Plan Review | Implement | Plan PASS or CONDITIONAL; test-plan stage skipped (skip detector or `--skip-test-plan`) |
| Test Plan | Test Plan Review | Test plan receipt produced (`status: Draft`, `review_verdict: pending`) |
| Test Plan Review | Implement | Test plan verdict PASS or WARN |
| Implement | Acceptance | `implement.md` + `quality.md` produced, all gates passed |
| Acceptance | PR | VERIFIED |
| PR | Merge | CI green, review approved |

### Backward Transitions (recovery paths)

| From | To | Trigger |
|------|----|---------|
| Plan Review | Research | Plan review FAIL — knowledge gaps |
| Test Plan Review | Test Plan | Test plan verdict FAIL — revise loop (max 3 cycles, then escalate) |
| Implement | Research | Scope significantly larger than expected |
| Acceptance | Implement | FAILED — P0/P1 bugs found, fix needed |
| Acceptance | Test Plan | FAILED — new bugs require `## Regression TC` appended to permanent test plan |
| PR | Implement | Review feedback requires code changes |

### User Decision Points

| From | Condition | Options |
|------|-----------|---------|
| Acceptance | PARTIAL (P2/P3 only) | Fix now → back to Implement / Ship as-is → proceed to PR |
| Decompose | Multiple tasks produced | One PR per task / Bundled PR |

**Backward transition rules:**
1. Reason for the transition is logged in the current stage's artifact
2. Re-anchoring to the original intent before entering the previous stage
3. Carry forward — do not repeat completed work
4. If 3rd return to the same stage — escalate to the user


## 7. Receipt-Based Gating

Each stage produces an artifact in `swarm-report/`. The next stage **must** read it before
starting work. No stage starts without the previous stage's receipt.

| Stage | Artifact | Required before next |
|-------|----------|----------------------|
| Research | `<slug>-research.md` | Plan / Implement (Feature) |
| Debug | `<slug>-debug.md` | Implement (Bug Fix) |
| Plan | `<slug>-plan.md` | Implement (when planning is done) |
| Test Plan | `docs/testplans/<slug>-test-plan.md` (permanent) + `<slug>-test-plan.md` (receipt) | Test Plan Review (Feature) |
| Test Plan Review | `<slug>-test-plan.md` receipt updated with `review_verdict` PASS / WARN | Implement (Feature) |
| Implement | `<slug>-implement.md` + `<slug>-quality.md` | Acceptance |
| Acceptance | `<slug>-acceptance.md` (with `test_plan_source` field when Test Plan ran) | PR |
| PR | `<slug>-pr.md` | Merge |

**Slug:** kebab-case from the task description, 2–4 words.
Example: task "Add user avatar upload" -> slug `user-avatar-upload`.

**Profile-dependent gating:** artifacts are only required for stages included in the profile.
Trivial: first artifacts are `<slug>-implement.md` + `<slug>-quality.md`, skips Acceptance —
PR stage depends on `<slug>-quality.md`. Bug Fix: starts from `<slug>-debug.md`, no research
artifact required.

**If an artifact is missing** -> the previous stage did not complete -> do not proceed.

### Stage Input/Output Contracts

| Stage | Skill | Input | Output |
|-------|-------|-------|--------|
| Research | `research` | Research question + constraints | `<slug>-research.md`: approaches, recommendations, risks, open questions |
| Debug | `debug` | Bug description (text, issue URL, error log) | `<slug>-debug.md`: symptom, reproduction steps, root cause, fix direction |
| Decompose | `decompose-feature` | Feature idea/PRD + research artifact | `<slug>-decomposition.md`: tasks with dependencies, acceptance criteria, waves |
| Plan review | `multiexpert-review` | Plan or decomposition artifact | Verdict: PASS / CONDITIONAL / FAIL with blockers |
| Test Plan | `generate-test-plan` | Feature slug + available artifacts (`research.md`, `decomposition.md`, `plan.md`, spec) | `docs/testplans/<slug>-test-plan.md` (permanent) + `<slug>-test-plan.md` (receipt: `status`, `permanent_path`, `review_verdict`, `phase_coverage`) |
| Test Plan Review | `multiexpert-review` (test-plan profile) | Permanent test plan file | Receipt updated with `review_verdict`: PASS / WARN / FAIL |
| Implement | `implement` | Task + optional artifacts (`research.md`, `debug.md`, `plan.md`) | `<slug>-implement.md`: changes summary, files, decisions + `<slug>-quality.md`: gate results |
| Acceptance | `acceptance` | Spec source (requirements / `debug.md` reproduction steps) + test-plan receipt (when available) + running app | `<slug>-acceptance.md`: VERIFIED / FAILED / PARTIAL with bug list; includes `test_plan_source: receipt / mounted / on-the-fly / absent` |
| PR | `create-pr` | Branch with commits | PR URL |
| Drive to merge | `drive-to-merge` | Open PR/MR | Autonomous CI + review loop; in-session decision tables; merged PR or surfaced blocker. State file: `<slug>-drive-state.md` (resumption only, not user-editable) |

### Pipeline Cycles

The pipeline is **not linear** — stages form feedback loops when issues are found.

```
                         ┌────── FAILED ──────┐
                         │                    v
research/debug ──→ implement ──→ acceptance ──→ create-pr ──→ drive-to-merge ──→ merged
                     ^  │            │                              │
                     │  │            │ PARTIAL: user decides         │ CI fail / review fixes
                     │  │            │   fix → back to implement     │
                     │  │            │   ship → proceed to create-pr │
                     │  └── inner ───┘                               │
                     │    quality loop                               │
                     │    (build/lint/                               │
                     │     tests/review)                             │
                     │                                               │
                     └─────── drive-to-merge delegation ─────────────┘
                              (FIXABLE items, CI-failure code-fixes)
```

**Acceptance → Implement loop:**
- `acceptance` produces `<slug>-acceptance.md` with VERIFIED / FAILED / PARTIAL
- VERIFIED → proceed to `create-pr`
- FAILED (P0/P1 bugs) → back to `implement` with the bug list as input. After fix, re-run `acceptance`
- PARTIAL (P2/P3 only) → orchestrator asks user: fix now or ship with known issues

**Implement inner loop:**
- Two quality gates inside `implement`: mechanical checks via `/check`, then intent check
- Gate failure → fix → re-run gate (max 3 attempts per gate, max 3 full cycles)
- If not converging → escalate to user

**Finalize loop:**
- Runs after `implement` passes both gates, before `acceptance`
- Four phases per round: code-reviewer → /simplify → optional pr-review-toolkit trio → conditional expert reviews
- `/check` invoked between fixes
- Max 3 rounds; PASS when no BLOCK remains; ESCALATE otherwise

**PR drive-to-merge loop:**
- `drive-to-merge` owns the round. It fetches comments, categorizes them inline,
  proposes concrete fixes (edit snippets or delegation instructions), delegates
  code changes to `implement` / `debug`, posts replies, resolves threads,
  re-requests review (Copilot + humans), and polls for new activity.
- The skill shows a decision table per round; by default it waits for `approve`,
  with `--auto` it proceeds without waiting. The final merge step always asks.
- If review requires significant code changes, the full quality path still applies:
  delegation goes through `implement` (which runs its quality loop) rather than
  direct edits. `finalize` is re-invoked only when the change is large enough to
  warrant another full code-quality pass — the orchestrator decides.
- CI diagnosis, infra-flake retry, rebase-when-behind, and merge are all inside
  `drive-to-merge`. The user is consulted only at merge or on surfaced blockers.

**Loop limits:**
- Acceptance → Implement: max 3 round-trips. After that → escalate
- Implement quality gates: max 3 attempts per gate, max 3 full cycles
- Finalize: max 3 rounds (A → D per round)
- PR review: no hard limit, but escalate if same feedback repeats

### Artifact Contents

Each artifact includes:
- Stage name and timestamp
- Summary of what was done / found
- Key decisions (with rationale)
- Files touched (for implementation)
- PASS/FAIL verdict (for Quality and Acceptance)
- Backward transition log (if any occurred)


## 8. Skill and Agent Map

### Skills

| Skill | Pipeline stage | Description |
|-------|---------------|-------------|
| **`feature-flow`** | **Orchestrator** | **Thin orchestrator: research → decompose → implement → acceptance → create-pr** |
| **`bugfix-flow`** | **Orchestrator** | **Thin orchestrator: debug → implement → acceptance → create-pr** |
| `research` | Research | Research Consortium — up to 5 parallel experts, synthesis, auto-review |
| `debug` | Debug | Systematic root cause investigation — stops at diagnosis |
| `multiexpert-review` | Plan | PoLL review of the plan by multiple agents |
| `implement` | Implement -> Quality | Standalone implementation stage with quality loop |
| `code-migration` | Implement (Migration) | Discover -> snapshot -> migrate -> verify -> cleanup |
| `kmp-migration` | Implement (Migration) | Module migration to Kotlin Multiplatform |
| `migrate-to-compose` | Implement (Migration) | View -> Compose migration with visual baseline |
| `create-pr` | PR | PR/MR creation: title, description, labels, reviewers |
| `drive-to-merge` | Post-PR | Autonomous orchestrator: monitors CI, diagnoses failures, fetches and categorizes review comments inline, proposes concrete fixes, delegates to `implement` / `debug`, posts replies, resolves threads, re-requests review (Copilot + humans), polls for activity via `ScheduleWakeup`, loops until merged. In-session decision tables, no user-editable manifest. Final merge step always requires user confirmation. |
| `generate-test-plan` | Plan / Acceptance | Structured test plan from specification |
| `acceptance` | Acceptance | Acceptance verification on live app — features and bug fixes |
| `bug-hunt` | Acceptance | Undirected bug hunting without a specification |
| `decompose-feature` | Research / Plan | Feature decomposition into tasks |
| `write-tests` | Implement | Retroactive test writing |
| `simplify`* | Finalize Phase B | Reuse, quality, and efficiency review with auto-fix |
| `finalize` | Finalize | Multi-round code-quality loop (A/B/C/D phases) |
| `check` | Implement (gate 1), Finalize | Mechanical verification — build, lint, typecheck, tests |

*Skill from another plugin / built-in.


### Agents

| Agent | Stage | Role |
|-------|-------|------|
| `code-reviewer` | Finalize Phase A | Independent review: intent vs. diff |
| `kotlin-engineer` | Implement | Kotlin business logic, data/domain layer, ViewModel |
| `compose-developer` | Implement | Compose UI: screens, components, themes, navigation |
| `architecture-expert` | Research, Finalize Phase D | Module structure, dependency direction, API design |
| `business-analyst` | Research (auto-review) | Completeness, product sense, practicality |
| `security-expert` | Finalize Phase D | Auth, encryption, token storage, OWASP |
| `performance-expert` | Finalize Phase D | N+1, memory leaks, UI jank, hot loops |
| `build-engineer` | Finalize Phase D | Gradle config, build performance, module structure |
| `manual-tester` | Acceptance | QA on live app: test cases, bug reports |
| `ux-expert` | Finalize Phase D | UX review, accessibility, platform conventions |
| `devops-expert` | PR / Merge | CI/CD, deployment, release automation |


## 9. Agent Models

| Agent | Model | Rationale |
|-------|-------|-----------|
| `architecture-expert` | opus | Deep structural analysis, multi-module reasoning |
| `business-analyst` | opus | Strategic thinking, product sense, trade-off analysis |
| `security-expert` | opus | Security requires thoroughness and deep analysis |
| `code-reviewer` | sonnet | Fast iteration in quality loop, stateless invocations |
| `kotlin-engineer` | sonnet | Standard implementation, code generation |
| `compose-developer` | sonnet | UI code, patterns, preview generation |
| `build-engineer` | sonnet | Gradle config, build optimization |
| `performance-expert` | sonnet | Performance analysis from code |
| `manual-tester` | sonnet | QA execution, bug reporting |
| `ux-expert` | sonnet | UX patterns, accessibility checks |
| `devops-expert` | sonnet | CI/CD pipelines, deployment config |


## 10. External Integrations

| Integration | Usage | Stage |
|-------------|-------|-------|
| **maven-mcp** | Dependency versions, vulnerabilities, compatibility, changelog | Research (Dependencies Expert), Implementation |
| **sensitive-guard** | File scanning for secrets and PII before sending | Pre-tool hook (all stages) |
| **Perplexity** | Web research: approaches, best practices, pitfalls | Research (Web Expert) |
| **DeepWiki** | AI-generated documentation for GitHub repositories | Research (Docs Expert) |
| **Context7** | Library and framework documentation | Research (Docs Expert) |
| **mobile MCP** | Testing on real devices and emulators | Acceptance (`manual-tester`, `acceptance`) |
| **playwright MCP** | Web application testing in the browser | Acceptance (`manual-tester`) |


## 11. Re-Anchoring Protocol

Before each stage transition, the orchestrator performs re-anchoring:

1. Re-read the **original task description** (verbatim from the user's request)
2. Re-read the **research report** (`swarm-report/<slug>-research.md`) — if it exists
3. Re-read the **plan** (`swarm-report/<slug>-plan.md`) — if it exists
4. Include artifact paths in the next agent's prompt — the agent reads them itself

This is mandatory at every transition, including backward ones. The agent entering a stage
must have the original intent loaded — not a retelling that passed through a chain of agents.


## 12. Escalation

Autonomous work stops and the task is returned to the user when:

- Scope is **2x+** larger than the initial estimate (plan: 3 files, reality: 8+)
- **3rd return** to the same stage (loop detected)
- A **new dependency** is required, not covered by the plan
- **Multiple architectural approaches** with no clear winner
- **Conflict with existing code** requiring a design decision
- Verification **consistently fails** after 3 Implement -> Quality cycles
- **Access or credentials** are needed that are not available

---

*Details of each component are in the corresponding files:*
- *Skills:* `plugins/developer-workflow/skills/<name>/SKILL.md`
- *Agents:* `plugins/developer-workflow/agents/<name>.md`
- *Orchestration rules:* `~/.claude/rules/dev-workflow-orchestration.md`

# Full Development Cycle: From Idea to Merge

## 1. Overview

developer-workflow implements a fully autonomous development cycle driven by a state machine
with explicit transitions between stages. Each incoming task is classified into one of five
profiles (Feature, Bug Fix, Migration, Research, Trivial), and the profile determines which
pipeline stages will be executed. This is not a rigid waterfall — a profile can skip stages
(Trivial does not require Research and Plan) or replace them (Migration delegates to
`code-migration`).

**Autonomy principle:** all interaction with the user is front-loaded into the preparation
phase (Research → Test Plan → Plan Review → Consolidated Approval). After the user approves,
execution runs autonomously. The orchestrator interrupts the user only for critical blockers
that cannot be resolved without a decision.

Research is performed by the Research Consortium — up to five parallel expert agents, each
working independently in its own domain (codebase, web, documentation, dependencies,
architecture). Results are reviewed and validated by `business-analyst`.
This ensures decisions are made based on data, not solely on the model's training data.

The test plan is produced during preparation — before implementation — and serves as the
acceptance contract. `acceptance` executes this pre-agreed plan rather than generating
test cases after the fact.

Quality is enforced by the Quality Loop — five sequential gates from compilation to expert
review. Key principle: the author of the code never reviews their own code — gate 4 launches
a separate `code-reviewer` agent that receives only the task description, plan, and git diff,
without any implementation context. Intent verification (does the implementation meet
requirements?) is handled by `acceptance`, not the quality loop. Receipt-based gating ensures
no stage starts without the previous stage's artifact. Re-anchoring at every stage transition
prevents drift from the original intent.

Feedback from any source (CI, reviewers, bots, UAT) is processed by `feedback-stage` — a
source-agnostic classifier that reads the full diff, generalizes specific comments to systemic
patterns, and routes each item to the appropriate stage.


## 2. Pipeline Overview

### Feature pipeline

```
IDEA / FEATURE REQUEST
  |
  v  [worktree created by environment / parent orchestrator]
[research] ---- Research Consortium (up to 5 parallel experts)   (optional)
  |                Artifact: swarm-report/<slug>-research.md
  v
[generate-test-plan] ---- Acceptance contract before implementation
  |                         Artifact: swarm-report/<slug>-test-plan.md
  v
[decompose-feature] ---- Break into tasks with dependencies        (optional)
  |                        Artifact: swarm-report/<slug>-decomposition.md
  v
[plan-review] ---- PoLL review of the plan                         (optional)
  |                  Artifact: plan review verdict
  v
[CONSOLIDATED APPROVAL] ---- User reviews research + test plan + implementation plan
  |                            Single stop point before execution starts
  v
  |   ┌──── wave 1: tasks in parallel ────────────────────────────┐
  |   │  ┌─ task 1 ─────────────────────────────────────────────┐ │
  |   │  │                                                       │ │
  |   │  v                                                       │ │
  |   │ [implement] ---- Code + simplify + Quality Loop (5 gates)│ │
  |   │  |  |-- specialist agents                                │ │
  |   │  |  '-- Quality Loop: build→lint→tests→code-reviewer     │ │
  |   │  |        →expert reviews                                │ │
  |   │  |        Artifacts: <slug>-implement.md                 │ │
  |   │  |                   <slug>-quality.md                   │ │
  |   │  v                                                       │ │
  |   │ [acceptance] ---- Execute test-plan, verify requirements │ │
  |   │  |  |-- intent check (requirements vs. implementation)   │ │
  |   │  |  '-- manual-tester agent                              │ │
  |   │  |        Artifact: <slug>-acceptance.md                 │ │
  |   │  |                  (includes failure_type if FAILED)    │ │
  |   │  │                                                       │ │
  |   │  ├─ FAILED (code bug)    → back to implement ───────────┘ │
  |   │  ├─ FAILED (approach)    → back to research/plan-review   │
  |   │  └─ VERIFIED → next stage                                  │
  |   └───────────────────────────────────────────────────────────┘
  |   (wave 2, wave 3... sequentially after previous wave)
  v
[create-pr] ---- PR per task or bundled
  v
[feedback-stage] ---- Monitor all feedback sources, classify, delegate
  |  Sources: CI/CD · code reviewer · bots · UAT · stakeholder
  |  Fast feedback (CI, bots): active monitoring
  |  Slow feedback (human review): stop session, resume on user signal
  |  Generalizes specific comments to systemic patterns across full diff
  |
  ├─ code issue    → implement → acceptance → feedback-stage
  ├─ approach      → research / plan-review → implement → acceptance → feedback-stage
  ├─ functional    → acceptance → feedback-stage
  └─ CLEAR verdict → orchestrator executes merge → MERGED
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
[implement] ---- Fix based on root cause + simplify + Quality Loop
  |                Artifacts: swarm-report/<slug>-implement.md
  |                           swarm-report/<slug>-quality.md
  v
[acceptance] ---- Verify bug no longer reproduces on live app
  |                Artifact: swarm-report/<slug>-acceptance.md
  v
[create-pr] ---- Draft PR -> Ready for Review
  |                Artifact: swarm-report/<slug>-pr.md
  v
[feedback-stage] ---- Monitor feedback, classify, route, merge when ready
  v
MERGED
```


## 3. Task Profiles and Routing

| Profile | Pipeline | Signals | Skips |
|---------|----------|---------|-------|
| **Feature** | Research → TestPlan → Decompose → PlanReview → Approval → [Implement → Acceptance] per task → PR → FeedbackStage → Merge | "add", "implement", "build", "create" | Decompose optional for single-task; TestPlan optional for trivial |
| **Bug Fix** | Debug → Implement → Acceptance → PR → FeedbackStage → Merge | "fix", "broken", "crash", "regression" | Research, TestPlan, Plan |
| **Migration** | Research → Snapshot → Migrate → Acceptance → PR → FeedbackStage → Merge | "migrate", "replace", "switch to" | Plan (delegates to `code-migration`) |
| **Research** | Research → Report | "investigate", "compare", "evaluate" | Implement, Acceptance, PR, Merge |
| **Trivial** | Implement → PR → FeedbackStage → Merge | Single-file change, config tweak | Research, TestPlan, Plan, Debug, Acceptance |

Auto-detection is based on keywords and context. When ambiguous — ask the user to confirm
before starting work.


## 4. Quality Loop

Quality loop runs inside `implement`. It validates code quality only — functional correctness
(does this meet requirements?) is verified by `acceptance`, not here.

```
                              Iteration cap: max 5 full cycles
                              Per gate: max 3 fix attempts
     _______________________________________________________________
    |                                                               |
    v                                                               |
+--------+    +---------+    +-------+    +-------------+    +--------+
| Gate 1 |--->| Gate 2  |--->| Gate 3|--->|   Gate 4    |--->| Gate 5 |
| Build  |    | Static  |    | Tests |    | code-       |    | Expert |
|        |    | Analysis|    |       |    | reviewer    |    | Reviews|
+--------+    +---------+    +-------+    +-------------+    +--------+
    |fail         |fail          |fail         |                  |
    v             v              v             v                  v
 [fix]         [fix]          [fix]     PASS: gate 5          PASS/SKIP
    |             |              |      WARN: gate 5 +
    '-----.-------'-------.------'       acknowledged risks
          |               |             FAIL: fix, re-run gate 4
          '--------.------'
                   |
                   '------- (fix cycle) ------'
```

### Gates

| # | Gate | Action | Executor |
|---|------|--------|----------|
| 1 | Build | Compile project, resolve all errors | Implementation agent |
| 2 | Static Analysis | Lint, formatting, unused imports | Implementation agent |
| 3 | Tests | Unit + integration tests, fix failures | Implementation agent |
| 4 | Semantic Self-Review | Compare code quality vs. `git diff` | `code-reviewer` agent |
| 5 | Expert Reviews | Parallel domain-specific reviews (by trigger) | Specialist agents |

**Gate 6 (Intent Check) has been removed.** Verifying that the implementation matches
requirements is the responsibility of `acceptance`, which runs the pre-agreed test plan.

### Expert Review Triggers (gate 5)

| Expert | Trigger — changed files touch any of: |
|--------|---------------------------------------|
| `security-expert` | Auth, encryption, token storage, network, permissions, PII |
| `performance-expert` | RecyclerView/LazyColumn, DB queries, image loading, hot loops |
| `architecture-expert` | New modules, changed dependency direction, public API |

If no trigger fired — gate 5 is skipped.

### Verdict Handling (gate 4)

| Verdict | Orchestrator action |
|---------|---------------------|
| **PASS** | Advance to gate 5 (expert reviews) |
| **WARN** | Advance to gate 5; major issues recorded in `<slug>-quality.md` as "Acknowledged risks" |
| **FAIL** | Backward transition -> Implement; fix critical issues, re-run gate 4 (max 3 cycles) |

### Build System Detection

| Priority | File | Build | Lint | Test |
|----------|------|-------|------|------|
| 1 | `Makefile` | `make build` | `make lint` | `make test` |
| 2 | `package.json` | `npm run build` | `npm run lint` | `npm test` |
| 3 | `Cargo.toml` | `cargo build` | `cargo clippy` | `cargo test` |
| 4 | `build.gradle(.kts)` | `./gradlew build` | `./gradlew lint` | `./gradlew test` |
| 5 | `pom.xml` | `mvn package -q` | `mvn checkstyle:check` | `mvn test` |
| 6 | `go.mod` | `go build ./...` | `golangci-lint run` | `go test ./...` |
| 7 | `pyproject.toml` | `pip install -e .` | `ruff check .` | `pytest` |


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
Research → TestPlan → Decompose → PlanReview → [Approval] → Implement → Acceptance → FeedbackStage → Merge
   ^           |           |            |                       ^  ^           |              |
   |           |           |            |                       |  |           |              |
   '-- gaps ---'           |            |                       |  '- code bug-'              |
   ^                       |            |                       |                             |
   '-- approach issue -----+------------+-----------------------'                             |
                           |            |                       ^                             |
                           |            '-- FAIL ---------------'                             |
                           |                                    ^                             |
                           |                                    '-- code issue ───────────────'
                           |                                    ^
                           |                                    '-- approach issue ───────────'
                           v (waves)
                    [T1] [T2] [T3] parallel
```

For Bug Fix pipeline:

```
Debug → Implement → Acceptance → FeedbackStage → Merge
             ^            |
             '-- FAILED --'
```

### Forward Transitions (default)

| From | To | Condition |
|------|----|-----------|
| Research | TestPlan | Research complete |
| TestPlan | Decompose / PlanReview / Implement | Task size and complexity |
| PlanReview | Approval | Plan PASS or CONDITIONAL |
| Approval | Implement | User confirmed |
| Debug | Implement | Root cause identified |
| Implement | Acceptance | `implement.md` + `quality.md` produced, all gates passed |
| Acceptance | FeedbackStage | VERIFIED |
| FeedbackStage | Merge | All feedback resolved, CI green, approved |

### Backward Transitions (recovery paths)

| From | To | Trigger | Max |
|------|----|---------|-----|
| PlanReview | Research | FAIL — knowledge gaps | 2 |
| Acceptance | Implement | FAILED — code bug | 3 |
| Acceptance | PlanReview | FAILED — design flaw | 2 |
| Acceptance | Research | FAILED — wrong approach | 2 |
| FeedbackStage | Implement | code issue in feedback | 3 |
| FeedbackStage | Research | approach issue | 2 |
| FeedbackStage | Acceptance | functional issue | 2 |

### User Decision Points

| From | Condition | Options |
|------|-----------|---------|
| Approval | After preparation phase | Confirm plan or give corrections |
| Acceptance | PARTIAL (P2/P3 only) | Fix now → back to Implement / Ship as-is → FeedbackStage |
| Decompose | Multiple tasks produced | One PR per task / Bundled PR |
| FeedbackStage | Slow feedback (human review) | Session stops; user resumes when review arrives |

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
| Research | `<slug>-research.md` | TestPlan / Implement (Feature) |
| TestPlan | `<slug>-test-plan.md` | Decompose / PlanReview / Implement |
| Debug | `<slug>-debug.md` | Implement (Bug Fix) |
| Plan | `<slug>-plan.md` | Implement (when planning is done) |
| Implement | `<slug>-implement.md` + `<slug>-quality.md` | Acceptance |
| Acceptance | `<slug>-acceptance.md` (includes `failure_type`) | FeedbackStage |
| FeedbackStage | `<slug>-feedback.md` | Merge or routed stage |

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
| TestPlan | `generate-test-plan` | Task description + `research.md` (optional) | `<slug>-test-plan.md`: structured test cases, the acceptance contract |
| Debug | `debug` | Bug description (text, issue URL, error log) | `<slug>-debug.md`: symptom, reproduction steps, root cause, fix direction |
| Decompose | `decompose-feature` | Feature idea/PRD + research + test-plan | `<slug>-decomposition.md`: tasks with dependencies, acceptance criteria, waves |
| Plan review | `plan-review` | Plan or decomposition artifact | Verdict: PASS / CONDITIONAL / FAIL with blockers |
| Implement | `implement` | Task + optional artifacts (`research.md`, `debug.md`, `plan.md`, `test-plan.md`) | `<slug>-implement.md`: changes summary, files, decisions + `<slug>-quality.md`: gate results |
| Acceptance | `acceptance` | `<slug>-test-plan.md` (pre-built contract) + `implement.md` + running app | `<slug>-acceptance.md`: VERIFIED / FAILED / PARTIAL + `failure_type` |
| PR | `create-pr` | Branch with commits | PR URL |
| Feedback | `feedback-stage` | PR ref + git diff + all artifacts | `<slug>-feedback.md`: routing plan per feedback item |
| Merge | orchestrator (after CLEAR verdict) | CI green, approved, no actionable feedback | Merged PR |

### Pipeline Cycles

The pipeline is **not linear** — stages form feedback loops when issues are found.

```
prepare: research → test-plan → decompose → plan-review → [approval]
                                                                │
                              ┌─────────────────────────────────┘
                              │       (per task, parallel within wave)
                              v
                    implement (quality loop: 5 gates)
                         │  ^
                         │  └── gate failure → fix (max 3x per gate)
                         v
                    acceptance (executes test-plan, intent check)
                         │
              ┌──────────┼──────────────────────┐
              │          │                      │
         code bug    design flaw /          VERIFIED
              │      wrong approach              │
              v          │                      v
          implement   research /          create-pr
                      plan-review               │
                                                v
                                        feedback-stage
                                         │   │    │
                                    code  appr  func
                                    issue oach  issue
                                     │    │      │
                                  impl  research  acceptance
                                         │
                                    all resolved
                                         │
                                   CLEAR → orchestrator merges → MERGED
```

**Acceptance failure routing (by failure_type):**
- VERIFIED → `feedback-stage`
- FAILED, code bug → `implement` (max 3x)
- FAILED, design flaw → `plan-review` (max 2x)
- FAILED, wrong approach → `research` (max 2x)
- FAILED, requirements misunderstood → escalate to user

**Implement inner loop:**
- Quality gates (build → lint → tests → code-reviewer → expert reviews) run inside `implement`
- Gate failure → fix → re-run gate (max 3 attempts per gate, max 5 full cycles)
- If not converging → escalate to user

**Feedback loop:**
- `feedback-stage` reads all feedback, generalizes specific comments to full diff
- Routes by issue type: code → implement, approach → research, functional → acceptance
- Fast sources (CI, bots): actively monitored. Slow sources (human review): session stops.

**Loop limits:**
- Acceptance → Implement: max 3 round-trips. After that → escalate
- Quality gates: max 3 attempts per gate, max 5 full cycles
- FeedbackStage backward transitions: see Backward Transitions table

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
| **`feature-flow`** | **Orchestrator** | **Thin orchestrator: research → test-plan → decompose → approval → [implement → acceptance] → feedback-stage → merge** |
| **`bugfix-flow`** | **Orchestrator** | **Thin orchestrator: debug → implement → acceptance → feedback-stage → merge** |
| `research` | Research | Research Consortium — up to 5 parallel experts, synthesis, auto-review |
| `generate-test-plan` | Preparation | Acceptance contract before implementation: structured test cases from spec/research |
| `debug` | Debug | Systematic root cause investigation — stops at diagnosis |
| `plan-review` | Plan | PoLL review of the plan by multiple agents |
| `implement` | Implement → Quality | Standalone implementation stage with quality loop (5 gates, no intent check) |
| `code-migration` | Implement (Migration) | Discover → snapshot → migrate → verify → cleanup |
| `kmp-migration` | Implement (Migration) | Module migration to Kotlin Multiplatform |
| `migrate-to-compose` | Implement (Migration) | View → Compose migration with visual baseline |
| `acceptance` | Verify | Execute pre-built test plan, verify requirements, classify failure type |
| `feedback-stage` | Feedback | Source-agnostic feedback: read, generalize, classify, route to the right stage |
| `create-pr` | PR | PR/MR creation: title, description, labels, reviewers |
| ~~`pr-drive-to-merge`~~ | — | **Removed** — merge mechanics now live inside `feedback-stage` |
| `bug-hunt` | Verify | Undirected bug hunting without a specification |
| `decompose-feature` | Research / Plan | Feature decomposition into tasks with waves |
| `write-tests` | Implement | Retroactive test writing |
| `simplify`* | Quality | Code review for reuse, quality, and efficiency |

*Skill from another plugin / built-in.

**Removed skills:**
- `address-review-feedback` — absorbed into `feedback-stage`


### Agents

| Agent | Stage | Role |
|-------|-------|------|
| `code-reviewer` | Quality (gate 4) | Independent review: intent vs. diff |
| `kotlin-engineer` | Implement | Kotlin business logic, data/domain layer, ViewModel |
| `compose-developer` | Implement | Compose UI: screens, components, themes, navigation |
| `architecture-expert` | Research, Quality (gate 5) | Module structure, dependency direction, API design |
| `business-analyst` | Research (auto-review) | Completeness, product sense, practicality |
| `security-expert` | Quality (gate 5) | Auth, encryption, token storage, OWASP |
| `performance-expert` | Quality (gate 5) | N+1, memory leaks, UI jank, hot loops |
| `build-engineer` | Quality (gate 5) | Gradle config, build performance, module structure |
| `manual-tester` | Verify | QA on live app: test cases, bug reports |
| `ux-expert` | Quality (gate 5) | UX review, accessibility, platform conventions |
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
| **mobile MCP** | Testing on real devices and emulators | Verify (`manual-tester`, `acceptance`) |
| **playwright MCP** | Web application testing in the browser | Verify (`manual-tester`) |


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

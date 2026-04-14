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

Quality is enforced by the Quality Loop — six sequential gates from compilation to intent
verification. Key principle: the author of the code never reviews their own code — gate 4
launches a separate `code-reviewer` agent that receives only the task description, plan,
and git diff, without any implementation context. Receipt-based gating ensures no stage
starts without the previous stage's artifact. Re-anchoring at every stage transition prevents
drift from the original intent.


## 2. Pipeline Overview

```
IDEA / FEATURE REQUEST
  |
  v
[Task Profiling] ---- Classification: Feature / Bug Fix / Migration / Research / Trivial
  |
  v
[research] ---- Research Consortium (up to 5 parallel experts)
  |                Artifact: swarm-report/<slug>-research.md
  v
[Plan Mode + plan-review] ---- Implementation plan + PoLL review
  |                              Artifact: swarm-report/<slug>-plan.md
  v
[implement] ---- Full autonomous cycle
  |  |-- kotlin-engineer / compose-developer / code-migration
  |  |-- Quality Loop (6 gates + code-reviewer)
  |  |     Artifact: swarm-report/<slug>-quality.md
  |  '-- Verification (Phase 2.5)
  |        Artifact: swarm-report/<slug>-verify.md
  |
  | [Implement] --- swarm-report/<slug>-implement.md
  v
[create-pr] ---- Draft PR -> Ready for Review
  |                Artifact: swarm-report/<slug>-pr.md
  v
[pr-drive-to-merge] ---- CI monitoring -> Review handling -> Merge
  |  '-- address-review-feedback (sub-skill)
  v
MERGED
```


## 3. Task Profiles and Routing

| Profile | Pipeline | Signals | Skips |
|---------|----------|---------|-------|
| **Feature** | Research -> Plan -> Implement -> Quality -> Verify -> PR -> Merge | "add", "implement", "build", "create" | -- |
| **Bug Fix** | Reproduce -> Diagnose -> Fix -> Quality -> PR -> Merge | "fix", "broken", "crash", "regression" | Research, Plan, Verify |
| **Migration** | Research -> Snapshot -> Migrate -> Verify -> PR -> Merge | "migrate", "replace", "switch to" | Plan (delegates to `code-migration`) |
| **Research** | Research -> Report | "investigate", "compare", "evaluate" | Implement, Quality, Verify, PR, Merge |
| **Trivial** | Implement -> Quality -> PR -> Merge | Single-file change, config tweak | Research, Plan, Verify |

Auto-detection is based on keywords and context. When ambiguous — ask the user to confirm
before starting work.


## 4. Quality Loop

```
                              Iteration cap: max 5 full cycles
                              Per gate: max 3 fix attempts
     ___________________________________________________________________
    |                                                                   |
    v                                                                   |
+--------+    +---------+    +-------+    +-------------+    +--------+ |
| Gate 1 |--->| Gate 2  |--->| Gate 3|--->|   Gate 4    |--->| Gate 5 | |
| Build  |    | Static  |    | Tests |    | code-       |    | Expert | |
|        |    | Analysis|    |       |    | reviewer    |    | Reviews| |
+--------+    +---------+    +-------+    +-------------+    +--------+ |
    |fail         |fail          |fail         |                  |     |
    v             v              v             v                  v     |
 [fix]         [fix]          [fix]     PASS: gate 5        +--------+ |
    |             |              |      WARN: gate 5 +      | Gate 6 | |
    '-----.-------'-------.------'       acknowledged risks | Intent  | |
          |               |             FAIL: --> Implement | Check   | |
          '--------.------'                                 +--------+ |
                   |                                           |       |
                   '------- (fix cycle) -----------------------'-------'
```

### Gates

| # | Gate | Action | Executor |
|---|------|--------|----------|
| 1 | Build | Compile project, resolve all errors | Implementation agent |
| 2 | Static Analysis | Lint, formatting, unused imports | Implementation agent |
| 3 | Tests | Unit + integration tests, fix failures | Implementation agent |
| 4 | Semantic Self-Review | Compare intent vs. `git diff` | `code-reviewer` agent |
| 5 | Expert Reviews | Parallel domain-specific reviews (by trigger) | Specialist agents |
| 6 | Intent Check | Re-read task + plan, verify correspondence | Orchestrator |

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
Research ------> Plan ------> Implement ------> Quality ------> Verify ------> PR ------> Merge
    ^               |              |                |               |              |
    |               |              |                |               |              |
    '---- gaps -----'              |                |               |              |
    ^                              |                |               |              |
    |                              |                |               |              |
    '---- scope too large ---------'                |               |              |
                                   ^                |               |              |
                                   |                |               |              |
                                   '---- issues ----'               |              |
                                   ^                                |              |
                                   |                                |              |
                                   '---- verify fails --------------'              |
                                   ^                                               |
                                   |                                               |
                                   '---- review feedback --------------------------'
```

### Forward Transitions (default)

| From | To | Condition |
|------|----|-----------|
| Research | Plan | Research complete |
| Plan | Implement | Plan passed review |
| Implement | Quality | Implementation complete |
| Quality | Verify | All gates passed |
| Verify | PR | Verification PASS |
| PR | Merge | CI green, review approved |

### Backward Transitions (recovery paths)

| From | To | Trigger |
|------|----|---------|
| Plan | Research | Plan review revealed knowledge gaps |
| Implement | Research | Scope turned out significantly larger than expected |
| Quality | Implement | Quality loop found issues requiring code changes |
| Verify | Implement | Verification failed — fix and re-verify |
| PR | Implement | Review feedback requires code changes |

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
| Research | `<slug>-research.md` | Plan (Feature / Migration) |
| Plan | `<slug>-plan.md` | Implement |
| Implement | `<slug>-implement.md` | Quality |
| Quality | `<slug>-quality.md` | Verify |
| Verify | `<slug>-verify.md` | PR |
| PR | `<slug>-pr.md` | Merge |

**Slug:** kebab-case from the task description, 2–4 words.
Example: task "Add user avatar upload" -> slug `user-avatar-upload`.

**Profile-dependent gating:** artifacts are only required for stages included in the profile.
Trivial: first artifact is `<slug>-implement.md`. Bug Fix: `<slug>-research.md` is not required.

**If an artifact is missing** -> the previous stage did not complete -> do not proceed.

### Artifact Contents

Each artifact includes:
- Stage name and timestamp
- Summary of what was done / found
- Key decisions (with rationale)
- Files touched (for implementation)
- PASS/FAIL verdict (for Quality and Verify)
- Backward transition log (if any occurred)


## 8. Skill and Agent Map

### Skills

| Skill | Pipeline stage | Description |
|-------|---------------|-------------|
| `research` | Research | Research Consortium — up to 5 parallel experts, synthesis, auto-review |
| `plan-review` | Plan | PoLL review of the plan by multiple agents |
| `implement` | Implement -> Quality | Standalone implementation stage with quality loop |
| `code-migration` | Implement (Migration) | Discover -> snapshot -> migrate -> verify -> cleanup |
| `kmp-migration` | Implement (Migration) | Module migration to Kotlin Multiplatform |
| `migrate-to-compose` | Implement (Migration) | View -> Compose migration with visual baseline |
| `create-pr` | PR | PR/MR creation: title, description, labels, reviewers |
| `pr-drive-to-merge` | Merge | CI monitoring, review handling, drive to merge |
| `address-review-feedback` | Merge (sub-skill) | Analysis and handling of reviewer comments |
| `generate-test-plan` | Plan / Verify | Structured test plan from specification |
| `acceptance` | Verify | Acceptance verification on live app — features and bug fixes |
| `exploratory-test` | Verify | Undirected bug hunting without a specification |
| `decompose-feature` | Research / Plan | Feature decomposition into tasks |
| `write-tests` | Implement | Retroactive test writing |
| `simplify`* | Quality | Code review for reuse, quality, and efficiency |

*Skill from another plugin / built-in.


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

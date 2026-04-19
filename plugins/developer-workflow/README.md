# developer-workflow

Lifecycle pipeline for the full developer workflow — from research through implementation to PR merge. Platform-neutral; pair with `developer-workflow-kotlin` or `developer-workflow-swift` for platform-specific engineering.

This plugin is the **core** of the `developer-workflow` family:

```
                 developer-workflow-experts
                 (9 review/consult agents)
                          ▲
                          │ depends on
                          │
                 developer-workflow (core)  ◀── you are here
                          ▲
                          │ depends on
                          │
        ┌─────────────────┴─────────────────┐
developer-workflow-kotlin          developer-workflow-swift
(kotlin-engineer, compose-         (swift-engineer,
 developer, migrations)             swiftui-developer)
```

Installing this plugin automatically pulls `developer-workflow-experts`. Installing `-kotlin` or `-swift` additionally pulls this plugin.

## Skills (17)

### Planning / research
| Skill | Purpose |
|---|---|
| `/research` | Parallel expert investigation (up to 5 agents) — codebase, web, docs, dependencies, architecture |
| `/decompose-feature` | Break an idea or PRD into a structured task list with dependencies, ACs, complexity |
| `/write-spec` | Specification-Driven Development — multi-round interview producing an exhaustive spec |
| `/design-options` | Generate 2-3 parallel architectural alternatives (Minimal / Clean / Pragmatic) for high-arch-risk tasks; user picks one before plan-review. Optional, default-skip. |
| `/plan-review` | Panel of LLM evaluators (PoLL) review of an implementation plan |

### Implementation
| Skill | Purpose |
|---|---|
| `/implement` | Writes code to meet the plan; mechanical checks via `/check` + intent check only. Semantic review, simplify, and expert review live in `/finalize`. |
| `/check` | Mechanical verification utility — auto-detects project tooling (Gradle/Node/Cargo/Swift/Python/Go), runs build + lint + typecheck + tests. Called by `implement`, `finalize`, migration skills, or user. |
| `/finalize` | Code-quality pass between `implement` and `acceptance`. Multi-round loop: `code-reviewer` → `/simplify` → `pr-review-toolkit` trio → conditional expert reviews, with `/check` between fixes. Max 3 rounds. |
| `/debug` | Read-only root cause analysis (via `debugging-expert` from `-experts`) |
| `/write-tests` | Retroactive tests for existing code — delegates test generation to engineers |

### QA / testing
| Skill | Purpose |
|---|---|
| `/generate-test-plan` | Produce a prioritized test plan document (no execution) |
| `/acceptance` | Verify feature against spec on a running app (via `manual-tester` + mobile MCP) |
| `/bug-hunt` | Undirected exploratory QA / bug hunting on a running app |

### PR workflow
| Skill | Purpose |
|---|---|
| `/create-pr` | Create a draft or ready GitHub PR / GitLab MR with generated metadata |
| `/triage-feedback` | Analyze and prioritize review comments or pasted feedback; optional post-triage reply/resolve |

### Orchestrators
| Skill | Purpose |
|---|---|
| `/feature-flow` | End-to-end feature pipeline: research → decompose → plan-review → implement → acceptance → create-pr |
| `/bugfix-flow` | End-to-end bug fix: debug → implement → acceptance → create-pr |

## Agents (1)

| Agent | Source | Purpose |
|---|---|---|
| `manual-tester` | this plugin | Real-device QA via mobile/browser MCP (disallowed Edit/Write/NotebookEdit) |

Agents from sibling plugins invoked by skills in this plugin:
- From [`developer-workflow-experts`](../developer-workflow-experts/): `code-reviewer`, `architecture-expert`, `security-expert`, `performance-expert`, `ux-expert`, `build-engineer`, `devops-expert`, `business-analyst`, `debugging-expert`
- From [`developer-workflow-kotlin`](../developer-workflow-kotlin/): `kotlin-engineer`, `compose-developer`
- From [`developer-workflow-swift`](../developer-workflow-swift/): `swift-engineer`, `swiftui-developer`

Skills invoke these by short name. If a platform plugin is not installed and you invoke a skill that needs its engineer (e.g., `/implement` on Kotlin code without `developer-workflow-kotlin`), the Task tool will error with a clear missing-agent message — install the matching platform plugin and retry.

## Recommended external plugins / MCP servers

These are not installed as dependencies — install them yourself if the capability is useful.

For **most skills**, these integrations are optional enhancements: when present, the skill uses them; when absent, the skill still runs with reduced capability.

**QA execution is the exception.** The `manual-tester` agent and the live-execution parts of `acceptance` / `bug-hunt` perform real device/browser automation. If the matching `mobile` / `playwright` MCP server is not installed and enabled, those QA steps cannot run — they stop with a missing-tool message rather than falling back to a dry-run.

| Tool | Kind | Used by | Required for |
|---|---|---|---|
| `mobile` | MCP server | `manual-tester`, `acceptance`, `bug-hunt` | Live mobile QA execution (iOS/Android UI automation + store management). Required to run mobile-QA steps. |
| `playwright` | MCP server (from `claude-plugins-official`) | `manual-tester`, `acceptance`, `bug-hunt` | Live browser QA execution. Required to run web-QA steps. |
| `/code-review` | Slash command (from `claude-plugins-official`) | optional post-PR review | Optional. Standalone GitHub PR review with confidence-based scoring — separate from in-pipeline `code-reviewer` gate. |
| `ralph-loop` | Plugin (from `claude-plugins-official`) | ad-hoc use outside pipeline | Optional. While-true iteration on a single prompt until completion marker — alternative to our structured orchestrators for exploratory work. |

## Installation

**Prerequisite — cross-marketplace dependency.** `developer-workflow` declares a hard dependency on `pr-review-toolkit` from Anthropic's official plugin marketplace. That marketplace's name is `claude-plugins-official` (see [`.claude-plugin/marketplace.json`](https://github.com/anthropics/claude-plugins-official/blob/main/.claude-plugin/marketplace.json)) and it is added by giving Claude Code the GitHub repo path `anthropics/claude-plugins-official`:

```
/plugin marketplace add anthropics/claude-plugins-official
```

After that, the marketplace is registered under its declared name `claude-plugins-official`, which matches the `marketplace` field in our `plugin.json` dependency entry.

Then add our marketplace and install the plugin:

```
/plugin marketplace add kirich1409/krozov-ai-tools
/plugin install developer-workflow@krozov-ai-tools
```

`developer-workflow-experts` and `pr-review-toolkit` install automatically as declared dependencies. Add platform plugins as needed:

```
/plugin install developer-workflow-kotlin@krozov-ai-tools
/plugin install developer-workflow-swift@krozov-ai-tools
```

If the cross-marketplace dep fails to resolve (e.g., `claude-plugins-official` marketplace not registered in the user's environment), `developer-workflow` installation will abort with a clear message. Add the marketplace and retry.

## Pipeline documentation

Full pipeline with diagrams and gate-level detail:
- [`docs/WORKFLOW.md`](docs/WORKFLOW.md) — stages, artifacts, decision points
- [`docs/ORCHESTRATORS.md`](docs/ORCHESTRATORS.md) — feature-flow and bugfix-flow state diagrams
- [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md) — task profiling, Research Consortium, re-anchoring, State Machine, Receipt-Based Gating, Quality Loop gates

## License

See the [root README](../../README.md) of the monorepo.

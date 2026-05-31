# developer-workflow

Toolbox of on-demand skills for the developer workflow — review, finalize, create-pr, drive-to-merge, write-spec, acceptance, generate-test-plan, and more. Exploratory QA without a spec is performed by calling the `manual-tester` agent directly. Platform-neutral; pair with `developer-workflow-kotlin` or `developer-workflow-swift` for platform-specific engineering.

This plugin is the **core** of the `developer-workflow` family:

```
                 developer-workflow-experts
                 (10 review/consult agents)
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

## Skills (13)

Skills are independent on-demand tools — invoke them when the task calls for the capability. They do not orchestrate each other; the model drives sequencing through plan mode.

### Planning / research
| Skill | Purpose |
|---|---|
| `/research` | Parallel expert investigation (up to 5 agents) — codebase, web, docs, dependencies, architecture |
| `/write-spec` | Specification-Driven Development — multi-round interview producing an exhaustive spec |
| `/reverse-spec` | Reverse-engineer an existing feature from code into a tech-agnostic spec |
| `/multiexpert-review` | Panel of LLM evaluators (PoLL) review of a plan, spec, or test-plan via the appropriate profile |
| `/evaluate-dependency` | Vet a new library before adding it — gathers health signals (via maven-mcp when available) + web reputation, delegates to `dependency-evaluator` for an adopt/avoid verdict |

`/research`, `/write-spec`, and built-in **plan mode** all investigate before acting, but
answer different questions. Use **plan mode** for *"how do I build this already-decided
change?"* (codebase-only, ephemeral plan). Use **`/research`** for *"what are the options / is
this feasible / which approach?"* when the answer needs more than the codebase (web, docs,
dependencies, architecture) — it produces a durable comparative report. Use **`/write-spec`**
to turn an already-decided feature into a permanent implementation contract under `docs/specs/`.
For a codebase-only topic `/research` steps aside and delegates to a single inline `Explore` agent instead of running the consortium.

### Implementation
| Skill | Purpose |
|---|---|
| `/check` | Mechanical verification utility — auto-detects project tooling (Gradle/Node/Cargo/Swift/Python/Go), runs build + lint + typecheck + tests |
| `/finalize` | Code-quality pass: multi-round loop `code-reviewer` → `/simplify` → optional `pr-review-toolkit` trio → conditional expert reviews, with `/check` between fixes. Max 3 rounds |
| `/write-tests` | Retroactive tests for existing code — delegates test generation to platform engineers |

### QA / testing
| Skill | Purpose |
|---|---|
| `/generate-test-plan` | Produce a prioritized test plan document (no execution) |
| `/acceptance` | Verify feature against spec on a running app (via `manual-tester` + mobile MCP) |

For undirected exploratory QA without a spec — call the `manual-tester` agent directly via the Task tool. Heuristics, scope budget, and OBSERVATION reporting live in `agents/manual-tester.md` § Step 4b.

### PR workflow
| Skill | Purpose |
|---|---|
| `/create-pr` | Create a draft or ready GitHub PR / GitLab MR with generated metadata |
| `/drive-to-merge` | Autonomous CI-monitor + review-handler + merge loop: categorize comments inline, propose concrete fixes, delegate, reply, resolve threads, re-request review (Copilot + humans), poll, confirm merge with user |

## Agents (1)

| Agent | Source | Purpose |
|---|---|---|
| `manual-tester` | this plugin | Real-device QA via mobile/browser MCP (disallowed Edit/Write/NotebookEdit) |

Agents from sibling plugins invoked by skills in this plugin:
- From [`developer-workflow-experts`](../developer-workflow-experts/): `code-reviewer`, `architecture-expert`, `security-expert`, `performance-expert`, `ux-expert`, `build-engineer`, `devops-expert`, `business-analyst`, `debugging-expert`, `dependency-evaluator`
- From [`developer-workflow-kotlin`](../developer-workflow-kotlin/): `kotlin-engineer`, `compose-developer`
- From [`developer-workflow-swift`](../developer-workflow-swift/): `swift-engineer`, `swiftui-developer`

Skills invoke these by short name. If a platform plugin is not installed and you invoke a skill that needs its engineer (e.g., `/write-tests` on Kotlin code without `developer-workflow-kotlin`), the Task tool will error with a clear missing-agent message — install the matching platform plugin and retry.

## Recommended external plugins / MCP servers

These are not installed as dependencies — install them yourself if the capability is useful.

For **most skills**, these integrations are optional enhancements: when present, the skill uses them; when absent, the skill still runs with reduced capability.

**QA execution is the exception.** The `manual-tester` agent and the live-execution parts of `acceptance` perform real device/browser automation. If the matching `mobile` / `playwright` MCP server is not installed and enabled, those QA steps cannot run — they stop with a missing-tool message rather than falling back to a dry-run.

| Tool | Kind | Used by | Required for |
|---|---|---|---|
| `mobile` | MCP server | `manual-tester`, `acceptance` | Live mobile QA execution (iOS/Android UI automation + store management). Required to run mobile-QA steps. |
| `playwright` | MCP server (from `claude-plugins-official`) | `manual-tester`, `acceptance` | Live browser QA execution. Required to run web-QA steps. |
| `ast-index` | CLI + plugin | `research`, `write-spec`, `write-tests`, `reverse-spec` | Optional. Structured code index for symbol / usages / deps / API lookups — non-QA skills use it when available and fall back to `Grep` + `Read` otherwise. |
| `/code-review` | Slash command (from `claude-plugins-official`) | optional post-PR review | Optional. Standalone GitHub PR review with confidence-based scoring — separate from in-`finalize` `code-reviewer` gate. |
| `pr-review-toolkit` | Plugin (from `claude-plugins-official`) | `finalize` Phase C | Optional. Enables the `pr-test-analyzer` / `silent-failure-hunter` / `type-design-analyzer` trio. When absent, `finalize` skips Phase C and continues. |

## Installation

```
/plugin marketplace add kirich1409/krozov-ai-tools
/plugin install developer-workflow@krozov-ai-tools
```

`developer-workflow-experts` installs automatically as a declared dependency. Add platform plugins as needed:

```
/plugin install developer-workflow-kotlin@krozov-ai-tools
/plugin install developer-workflow-swift@krozov-ai-tools
```

### Recommended — richer `finalize` Phase C

The `finalize` skill's Phase C invokes the `pr-review-toolkit` trio (test quality, silent failures, type design) when available. To enable it, install `pr-review-toolkit` from Anthropic's official marketplace:

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install pr-review-toolkit@claude-plugins-official
```

The plugin is **not** declared as a hard dependency because `claude-plugins-official` publishes marketplace entries without `version` fields, making semver resolution impossible for Claude Code. When `pr-review-toolkit` is absent, `finalize` logs `phase: C, status: skipped, reason: pr-review-toolkit not installed` and continues normally.

## License

See the [root README](../../README.md) of the monorepo.

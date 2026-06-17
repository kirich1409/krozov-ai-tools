# developer-workflow (core)

## Non-negotiables

Rules that are not open for discussion. Violating these is an error, not a judgment call.

- **Non-QA skills must not hardcode MCP tool names.** They must run (with reduced capability) when an MCP server is absent. Exception: QA-execution skills (`manual-tester`, live parts of `acceptance`) that require real device/browser automation may fail fast with an install/enable message — graceful degradation is impossible there.
- **Tier-3 hard-dep escalation requires explicit user approval per change.** Proposing is allowed; editing `plugin.json` `dependencies` or `.mcp.json` without explicit go-ahead is not.
- **The author of a change that breaks tests fixes those tests in the same PR.** No `--skip-test-fix`, no "TODO fix later", no "merge red". `/check` is the gate; if tests fail, work does not exit. The only escape hatch is an explicit, justified test skip-marker plus a follow-up issue — treated as an exception, not a routine.

## Structure

```
skills/<name>/SKILL.md    # 12 on-demand skills, each a directory with YAML frontmatter
agents/manual-tester.md   # only agent in core (QA executor; covers exploratory mode)
evals/                    # eval-harness fixtures (gitignored iterations + tracked README)
```

## Plugin family

This plugin is part of a split family. Depending on the task, Claude Code will have access to agents from sibling plugins:

| Plugin | Contributes |
|---|---|
| `developer-workflow` (this) | 12 on-demand skills + `manual-tester` |
| `developer-workflow-experts` | `code-reviewer`, `architecture-expert`, `security-expert`, `performance-expert`, `ux-expert`, `build-engineer`, `devops-expert`, `business-analyst`, `debugging-expert` — required, auto-installed as a dependency |
| `developer-workflow-kotlin` | `kotlin-engineer`, `compose-developer` — install for Kotlin/Android/KMP work |
| `developer-workflow-swift` | `swift-engineer`, `swiftui-developer` — install for Swift/iOS/macOS work |

Skills in this plugin delegate to engineer agents (kotlin-engineer / compose-developer / swift-engineer / swiftui-developer) by short name via the Task tool. Agent names are unique across the family, so short-name resolution works as long as the corresponding platform plugin is installed. If `write-tests` is invoked and the referenced engineer is not installed, the Task call will fail with a clear message — install the matching platform plugin and retry.

## Conventions

- Toolbox model: each skill is independent and on-demand. There is no forced sequencing — the model chooses skills when their capability is needed and drives the overall flow through plan mode.
- Self-contained core: skills only. No platform-specific engineers live here.
- **Dependency policy (three tiers):**
  1. **Built-in Claude Code features** (`/simplify`, Agent tool, Plan Mode, Bash, skills framework) — always allowed, used freely.
  2. **Sibling plugins in this family** (`developer-workflow-experts`, `-kotlin`, `-swift`) — declared normally via `dependencies` in plugin.json.
  3. **External plugins and MCP servers** — default is **soft-reference**: mention in README as recommended, detect-and-use in agent prompts, non-QA skills must still run (with reduced capability) when they are absent. Escalation to **hard dependency** (plugin.json `dependencies`) or **MCP server declaration** (.mcp.json) requires **explicit user approval per change** — propose first, wait, then edit.
  - **QA-execution exception:** `manual-tester` and the live-execution parts of `acceptance` perform real device/browser automation through the `mobile` / `playwright` MCP servers. Those flows reference the MCP tool by name and may fail fast with an install/enable message when the capability is unavailable — graceful degradation is impossible when real automation is required. This is a documented exception, not a license for other skills to hardcode tool names.
- **MCP servers:** `mobile` MCP is pre-approved for testing and required for live mobile QA; `playwright` is documented as a recommended dependency for browser-based QA (see `developer-workflow/README.md`). Non-QA skills (research, multiexpert-review, documentation lookup, etc.) must NOT hardcode MCP tool names and must keep working without them — describe the task, not the tool.
- **External tools:** if a capability requires something the user may not have installed, describe what is needed (one short line in README's "Recommended" section) and let the user decide. For the QA-execution exception above, the skill may stop with a clear install/enable message instead of attempting to continue without the required MCP.
- Skills use YAML frontmatter: `name`, `description` (≤ 1024 chars), optionally `disable-model-invocation`.
- `code-reviewer` (in `developer-workflow-experts`) is read-only — no Edit, Write, NotebookEdit, or Bash tools.

## Skills roster (11)

- Planning / research: `research`, `write-spec`, `multiexpert-review`, `evaluate-dependency`
- Implementation: `check`, `finalize`, `write-tests`
- QA: `generate-test-plan`, `acceptance`
- PR / orchestration: `create-pr`, `drive-to-merge`

### Planning: which tool to reach for

`research`, `/write-spec`, and built-in **plan mode** look similar (all do read-only
investigation first) but answer different questions. Pick by the question, not the surface:

| Reach for | When the question is | Output |
|---|---|---|
| **plan mode** (built-in) | "How do I build this *already-decided* change?" — investigation stays inside the codebase | Ephemeral plan, then implement |
| **`research`** | "What are the options / is this feasible / which approach?" — needs ≥2 of codebase·web·docs·dependencies·architecture | Durable comparative report in `swarm-report/research/` |
| **`/write-spec`** | "Specify this *already-decided* feature as an implementation contract" — interview-heavy | Permanent spec in `docs/specs/` |

`research` deliberately steps aside for codebase-only topics: its min-2-tracks rule redirects
a single-track investigation to a plain inline Explore agent instead of running the consortium. `research` and `write-spec` each run a parallel expert consortium; their
Codebase / Architecture / Web prompt templates overlap **intentionally** (write-spec's are an
enriched superset) and are kept as separate per-skill files on purpose — do not collapse them
into a shared file (same "duplicate + note" idiom as the `acceptance` ↔ `multiexpert-review`
PoLL protocol).

Exploratory QA without a spec → call the `manual-tester` agent directly via the Task tool (formerly `bug-hunt` skill — removed in v0.15.0; heuristics live in `agents/manual-tester.md` § Step 4b).

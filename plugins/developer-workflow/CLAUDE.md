# developer-workflow (core)

## Structure

```
skills/<name>/SKILL.md    # 15 lifecycle skills, each a directory with YAML frontmatter
agents/manual-tester.md   # only agent in core (QA executor)
docs/WORKFLOW.md          # Full pipeline documentation with diagrams
docs/ORCHESTRATORS.md     # feature-flow and bugfix-flow diagrams
```

## Plugin family

This plugin is part of a split family. Depending on the task, Claude Code will have access to agents from sibling plugins:

| Plugin | Contributes |
|---|---|
| `developer-workflow` (this) | 14 lifecycle skills + `manual-tester` |
| `developer-workflow-experts` | `code-reviewer`, `architecture-expert`, `security-expert`, `performance-expert`, `ux-expert`, `build-engineer`, `devops-expert`, `business-analyst`, `debugging-expert` — required, auto-installed as a dependency |
| `developer-workflow-kotlin` | `kotlin-engineer`, `compose-developer`; skills `code-migration`, `kmp-migration`, `migrate-to-compose` — install for Kotlin/Android/KMP work |
| `developer-workflow-swift` | `swift-engineer`, `swiftui-developer` — install for Swift/iOS/macOS work |

Skills in this plugin delegate to engineer agents (kotlin-engineer / compose-developer / swift-engineer / swiftui-developer) by short name via the Task tool. Agent names are unique across the family, so short-name resolution works as long as the corresponding platform plugin is installed. If `implement` or `write-tests` is invoked and the referenced engineer is not installed, the Task call will fail with a clear message — install the matching platform plugin and retry.

## Conventions

- Self-contained core: lifecycle orchestration only. No platform-specific engineers live here.
- **Dependency policy (three tiers):**
  1. **Built-in Claude Code features** (`/simplify`, Agent tool, Plan Mode, Bash, skills framework) — always allowed, used freely.
  2. **Sibling plugins in this family** (`developer-workflow-experts`, `-kotlin`, `-swift`) — declared normally via `dependencies` in plugin.json.
  3. **External plugins and MCP servers** — default is **soft-reference**: mention in README as recommended, detect-and-use in agent prompts, non-QA skills must still run (with reduced capability) when they are absent. Escalation to **hard dependency** (plugin.json `dependencies`) or **MCP server declaration** (.mcp.json) requires **explicit user approval per change** — propose first, wait, then edit.
  - **QA-execution exception:** `manual-tester` and the live-execution parts of `acceptance` / `bug-hunt` perform real device/browser automation through the `mobile` / `playwright` MCP servers. Those flows reference the MCP tool by name and may fail fast with an install/enable message when the capability is unavailable — graceful degradation is impossible when real automation is required. This is a documented exception, not a license for other skills to hardcode tool names.
- **MCP servers:** `mobile` MCP is pre-approved for testing and required for live mobile QA; `playwright` is documented as a recommended dependency for browser-based QA (see `developer-workflow/README.md`). Non-QA skills (research, plan-review, documentation lookup, etc.) must NOT hardcode MCP tool names and must keep working without them — describe the task, not the tool.
- **External tools:** if a capability requires something the user may not have installed, describe what is needed (one short line in README's "Recommended" section) and let the user decide. For the QA-execution exception above, the skill may stop with a clear install/enable message instead of attempting to continue without the required MCP.
- Skills use YAML frontmatter: `name`, `description` (≤ 1024 chars), optionally `disable-model-invocation`.
- `code-reviewer` (in `developer-workflow-experts`) is read-only — no Edit, Write, NotebookEdit, or Bash tools.
- Workspace directories (`*-workspace/`) are runtime artifacts, not skills. Gitignored.
- Pipeline orchestration rules (task profiling, Research Consortium, Quality Loop gates, State Machine, receipt-based gating) ship with this plugin at [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md) — skills and the core feature-flow/bugfix-flow orchestrators read from there.
- Quality Loop gates are defined in `docs/ORCHESTRATION.md`, not in any individual skill.

## Skills roster (15)

- Planning/research: `research`, `decompose-feature`, `write-spec`, `plan-review`, `design-options` (optional pre-plan-review stage — generates 2-3 architectural alternatives for high-arch-risk tasks)
- Implementation: `implement`, `write-tests`, `debug`
- Verification utility: `check` — reusable mechanical-check runner (build + lint + typecheck + tests), invoked by `implement` and any code-modifying skill
- QA: `generate-test-plan`, `acceptance`, `bug-hunt`
- PR: `create-pr`, `triage-feedback`
- Orchestrators: `feature-flow`, `bugfix-flow`

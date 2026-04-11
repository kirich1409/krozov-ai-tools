# developer-workflow

## Structure

```
skills/<name>/SKILL.md    # Each skill is a directory with YAML frontmatter
agents/<name>.md          # Each agent is a single .md with YAML frontmatter
agents/references/        # Shared reference material used by agents
docs/WORKFLOW.md          # Full pipeline documentation with diagrams
```

## Conventions

- 100% self-contained — no dependencies on external plugins. Own plugins from this monorepo (maven-mcp, sensitive-guard, extend) are allowed as they ship together.
- **Dependency policy:** only built-in Claude Code features + own plugins from this repo (maven-mcp, sensitive-guard, extend). No third-party plugin skills/agents.
- **MCP servers:** `mobile` MCP is explicitly allowed for testing. Other MCP servers (Perplexity, DeepWiki, Context7, etc.) are environment-level — use when available, but skills must NOT hardcode their tool names or break without them. Describe the task ("search the web for approaches"), not the tool (`perplexity_research`).
- **External tools:** if a capability requires something the user may not have installed, describe what's needed and let the user decide — don't write it as a mandatory instruction.
- Skills use YAML frontmatter: `name`, `description` (required), optionally `disable-model-invocation`
- Agents use YAML frontmatter: `name`, `description`, `model`, `color`, `memory`, `tools`, optionally `maxTurns`, `disallowedTools`
- `swift-engineer` and `swiftui-developer` agents mirror `kotlin-engineer` and `compose-developer` for iOS/macOS targets
- `code-reviewer` agent is read-only — no Edit, Write, NotebookEdit, or Bash tools
- Workspace directories (`*-workspace/`) are runtime artifacts, not skills
- Pipeline orchestration rules live at `~/.claude/rules/dev-workflow-orchestration.md` (user-global, not in this repo)
- Quality Loop gates are defined in orchestration rules, not in any skill

## Expert Agents

Seven expert agents (architecture, build, business-analyst, devops, performance, security, ux) are specialists invoked by skills during quality loop or research. They are not meant for direct user invocation.

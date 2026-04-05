# Agent Frontmatter Fields Reference

Complete reference of all YAML frontmatter fields available in Claude Code agent files.

## Required fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique identifier, kebab-case. Used for invocation and display. |
| `description` | string | What the agent does and when to use it. Primary trigger mechanism for auto-delegation. |

## Optional fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tools` | string/list | inherit all | Allowlist of tools: Read, Write, Edit, Bash, Glob, Grep, Agent, etc. |
| `disallowedTools` | string/list | none | Tools explicitly blocked (removed from inherited list). |
| `model` | string | `inherit` | Model to use: `sonnet`, `opus`, `haiku`, full model ID, or `inherit`. |
| `permissionMode` | string | `default` | Permission behavior: `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan`. |
| `maxTurns` | number | unlimited | Maximum agentic turns before agent stops. Useful for bounded tasks, harmful for open-ended coding. |
| `skills` | list | none | Skill names to preload at startup. |
| `memory` | string | none | Persistent memory scope: `user` (all projects), `project` (this project), `local` (this session). |
| `background` | boolean | false | Always run as background task. |
| `effort` | string | default | Reasoning effort: `low`, `medium`, `high`, `max`. |
| `isolation` | string | none | Set to `worktree` to run in isolated git worktree. |
| `mcpServers` | object | none | MCP servers available to the agent. |
| `hooks` | object | none | Lifecycle hooks scoped to this subagent. |
| `initialPrompt` | string | none | Text prepended to first user turn. Slash commands work here. |

## Tool categories for reference

**Read-only** (safe for reviewers, analyzers):
Read, Glob, Grep, WebSearch, WebFetch

**Modification** (grant intentionally):
Write, Edit, Bash

**Orchestration**:
Agent (spawn subagents)

**Special**:
LSP (language server), MCP tools (external integrations)

## Model selection guidance

| Model | Best for | Trade-off |
|-------|----------|-----------|
| `opus` | Architecture review, security audit, complex analysis, nuanced reasoning | Slowest, most expensive, highest quality |
| `sonnet` | Most coding tasks, implementation, debugging, refactoring | Good balance of speed and quality |
| `haiku` | Search, lookups, simple transforms, dependency checks | Fastest, cheapest, least capable |
| `inherit` | When agent should match parent conversation model | No overhead, consistent experience |

## Permission modes explained

| Mode | Behavior | Use case |
|------|----------|----------|
| `default` | Asks for approval on edits and bash | Getting started, learning |
| `acceptEdits` | Auto-approves file edits in working dir | Iterative coding |
| `plan` | Analyze and propose, no execution | Safe exploration |
| `auto` | Most actions permitted with safety checks | Production workflows |
| `dontAsk` | Auto-denies unless pre-approved | CI/CD, automation |
| `bypassPermissions` | No permission checks | Trusted automation only |

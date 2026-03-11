# sensitive-guard

Claude Code plugin that prevents sensitive data (secrets, PII) from reaching AI servers by scanning files before they are read into the conversation.

## How it works

A PreToolUse hook intercepts `Read`, `Grep`, and `Bash` tool calls. Before the tool executes, it scans target files for:

- **Secrets** — API keys, tokens, passwords, private keys (via [gitleaks](https://github.com/gitleaks/gitleaks))
- **PII** — emails, SSNs, credit cards, IBANs (via built-in regex patterns)

If sensitive data is found, you choose per item: pass once, add to allowlist, or block the tool call entirely. If blocked, the data never enters the conversation and never reaches the API.

### Built-in PII patterns

| Pattern | Default |
|---------|---------|
| Email addresses | enabled |
| US SSN | enabled |
| Credit card numbers | enabled |
| IBAN | enabled |
| Phone numbers (international) | disabled — high false positive rate |
| IPv4 addresses | disabled — high false positive rate with version strings |

### Bash tool support

For `Bash` commands, the plugin does best-effort file path extraction from commands like `cat`, `head`, `tail`, `less`, `source`, `grep <file>`, and input redirection (`< file`). Dynamic paths (`$VAR`), piped output, and subshell results are not resolved.

## Prerequisites

- **jq** (required) — JSON processing
- **perl** (required) — PII regex matching, binary detection (pre-installed on macOS/most Linux)
- **gitleaks** (recommended) — secret detection. Install:
  - macOS: `brew install gitleaks`
  - Linux: [github.com/gitleaks/gitleaks/releases](https://github.com/gitleaks/gitleaks/releases)
  - Any OS: `go install github.com/gitleaks/gitleaks/v8@latest`

If gitleaks is not installed, the plugin runs with PII detection only.

## Installation

```bash
claude plugin add /path/to/sensitive-guard
```

## Configuration

Global config at `~/.claude/sensitive-guard.json`:

```json
{
  "tools": ["Read", "Grep", "Bash"],
  "pii": {
    "enabled": true,
    "disabled": [],
    "custom": []
  },
  "gitleaks": {
    "enabled": true,
    "configPath": null
  },
  "display": {
    "maxValuePreview": 12
  }
}
```

Project-level override at `.claude/sensitive-guard.json` merges on top of global config (arrays append, scalars replace).

### Disable specific PII patterns

```json
{ "pii": { "disabled": ["ipv4", "phone"] } }
```

### Add custom PII patterns

```json
{ "pii": { "custom": [{ "id": "employee_id", "regex": "EMP-[0-9]{6}", "description": "Employee ID" }] } }
```

## Allowlists

Two scopes:
- **Project**: `.claude/sensitive-guard-allowlist.json`
- **Global**: `~/.claude/sensitive-guard-allowlist.json`

When prompted about a finding, choose:
- `p` — pass once (one-time allow)
- `a` — add to project allowlist
- `g` — add to global allowlist
- `b` — block the tool call

Allowlists store SHA-256 hashes of values, never plaintext.

### Pattern-based allowlisting

You can also add regex patterns to allowlists to match groups of values (e.g., all work emails):

```json
{
  "patterns": [
    { "regex": ".*@mycompany\\.com", "type": "email", "note": "work emails ok" }
  ]
}
```

## Non-interactive mode

When stdin is not a TTY (CI, headless), all findings are blocked by default.

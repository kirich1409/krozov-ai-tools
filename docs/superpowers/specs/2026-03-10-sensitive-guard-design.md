# sensitive-guard: Claude Code Plugin Design

## Overview

Claude Code plugin with a PreToolUse hook that scans files for secrets and PII before they're read into the conversation. Prevents sensitive data from reaching AI servers by blocking tool calls at the source. Uses gitleaks (secrets) + custom regex (PII). Interactive prompt lets user block or explicitly allow per finding. Allowlists scoped to project and global levels.

**Core principle:** Prevention at the source — if sensitive data is never read, it never reaches the API.

## Detection Engines

| Category | Engine | Coverage |
|----------|--------|----------|
| API keys, tokens, passwords, private keys | gitleaks | 700+ built-in rules |
| AWS/GCP/Azure credentials | gitleaks | built-in |
| Connection strings, DSNs | gitleaks | built-in |
| Email addresses | custom regex | built-in default |
| Phone numbers (international) | custom regex | built-in default (disabled) |
| SSN (US) | custom regex | built-in default |
| Credit card numbers | custom regex | built-in default |
| IP addresses (v4) | custom regex | built-in default (disabled) |
| IBAN | custom regex | built-in default |

Users can disable any default pattern or add custom regex patterns via config.

## Plugin Structure

```
sensitive-guard/
  .claude-plugin/
    manifest.json                # Plugin metadata, hook registration
    hooks/
      pre-tool-use.sh           # Entry point: routes to scanner
  src/
    scanner.sh                  # Orchestrator: runs gitleaks + PII, merges results
    gitleaks-runner.sh          # Wraps gitleaks CLI, parses JSON output
    pii-detector.sh             # Runs default + custom PII regex patterns
    prompt.sh                   # Interactive prompt: shows findings, collects actions
    allowlist.sh                # Read/write project + global allowlists
    bash-parser.sh              # Best-effort file path extraction from Bash commands
    config.sh                   # Loads plugin config, merges defaults
  config/
    default-pii-patterns.json   # Built-in PII regexes
    default-config.json         # Default settings
```

## Data Flow

```
PreToolUse fires
  |
Check tool_name against config.tools -> if not listed -> exit 0 (allow, not inspected)
  |
Extract target files:
  - Read -> tool_input.file_path directly
  - Grep -> tool_input.path (file only; if directory -> skip, see Limitations)
  - Bash -> best-effort parse for file paths (see Bash Parsing section)
  |
If no files extracted -> exit 0 (allow)
  |
For each file:
  +-> Run gitleaks on file -> secret findings
  +-> Run PII regex on file -> PII findings
  |
Merge & deduplicate all findings across files
  |
Filter out already-allowed items:
  - For each finding, compute SHA-256 of matched value (trimmed, see Allowlist Hashing)
  - Check exact hash against project allowlist, then global allowlist
  - Check raw matched value against pattern regexes in both allowlists
  - If matched -> remove from findings list
  |
If no remaining findings -> exit 0 (allow)
If findings remain -> interactive prompt
  |
User chooses per-item:
  [p] Pass once    -> allow, continue
  [a] Always allow -> add to project allowlist
  [g] Global allow -> add to global allowlist
  [b] Block        -> exit 2, tool call rejected
  |
If any item blocked -> exit 2 (block entire tool call)
If all items passed/allowed -> exit 0 (allow)
```

**Exit codes:**
- `0` — allow tool call
- `2` — block tool call (Claude Code shows the hook's stderr message to the user)
- `1` — hook error (Claude Code treats as block for safety)

## Tool Routing

| Tool | How to extract files |
|------|---------------------|
| `Read` | `tool_input.file_path` directly |
| `Grep` | `tool_input.path` — scan if it's a file. If directory, skip (see Limitations: findings in matched content won't be caught pre-execution). |
| `Bash` | Best-effort file path extraction (see Bash Parsing section below). |
| `Edit` | Not inspected — file already in conversation from prior Read. Can be added to `config.tools` if needed. |
| `Glob` | Not inspected — returns paths only, no content. |

### Bash Parsing

Best-effort regex extraction of file paths from Bash commands. Recognized patterns:

- Direct file arguments: `cat`, `less`, `head`, `tail`, `source`, `.`, `grep ... <file>`
- Input redirection: `< file`
- Multi-line commands: each line parsed separately
- Chained commands (`&&`, `;`): each segment parsed separately
- Resolvable variables: `$HOME`, `$PWD`, `~` are expanded; other variables (`$VAR`) are skipped

**Explicitly out of scope:** dynamic paths (`cat "$COMPUTED_VAR"`), piped output (`curl | jq`), subshell results (`$(find ...)`), script execution (`python script.py` — the script itself is not scanned).

When multiple files are found in one command, all are scanned independently.

## Gitleaks Invocation

```bash
gitleaks detect --no-git -f json --source="$file_path" 2>/dev/null
```

Returns JSON array of findings with rule ID, match, line number.

Dependency check on first run — if `gitleaks` not in PATH:
```
  Install options:
    macOS:   brew install gitleaks
    Linux:   https://github.com/gitleaks/gitleaks/releases
    Any OS:  go install github.com/gitleaks/gitleaks/v8@latest
  Or disable: set gitleaks.enabled=false in config
```

**Fallback when gitleaks not installed:** If `gitleaks.enabled` is true but binary is not found, the plugin logs a warning to stderr and proceeds with PII-only scanning. It does NOT block tool calls due to missing gitleaks — that would be disruptive. Warning is shown once per session via a marker file (`/tmp/sensitive-guard-gitleaks-warned-$USER`), deleted on session end or system reboot.

## Default PII Patterns

```json
[
  { "id": "email", "regex": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}", "description": "Email address" },
  { "id": "ssn", "regex": "\\b\\d{3}-\\d{2}-\\d{4}\\b", "description": "US SSN" },
  { "id": "credit_card", "regex": "\\b(?:4\\d{3}|5[1-5]\\d{2}|3[47]\\d{2}|6(?:011|5\\d{2}))[-\\s]?\\d{4}[-\\s]?\\d{4}[-\\s]?\\d{4}\\b", "description": "Credit card" },
  { "id": "phone", "regex": "(?:\\+[1-9]\\d{0,2}[-\\s])?(?:\\(?\\d{1,4}\\)[-\\s])?\\d[\\d-\\s]{4,14}\\d", "enabled": false, "description": "Phone number (disabled by default — high false positive rate with numeric data)" },
  { "id": "ipv4", "regex": "\\b(?:(?:25[0-5]|2[0-4]\\d|[01]?\\d\\d?)\\.){3}(?:25[0-5]|2[0-4]\\d|[01]?\\d\\d?)\\b", "enabled": false, "description": "IPv4 address (disabled by default — high false positive rate with version strings)" },
  { "id": "iban", "regex": "\\b[A-Z]{2}\\d{2}[A-Z0-9]{4}\\d{7}(?:[A-Z0-9]?){0,16}\\b", "description": "IBAN" }
]
```

## Interactive Prompt

Output to stderr:
```
  sensitive-guard: 3 findings in /Users/me/project/.env

  1. [aws-access-key] AKIA3E...F7Q2  (line 4)
  2. [email] john.d...@corp.com       (line 12)
  3. [credit_card] 4532-****-****-8901 (line 15)

Action per item: [p]ass once  [a]llow project  [g]lobal allow  [b]lock
(1): _
```

Sensitive values are truncated/masked in the prompt — user sees enough to identify but not the full value.

## Allowlist

Two scopes: project (`.claude/sensitive-guard-allowlist.json`) and global (`~/.claude/sensitive-guard-allowlist.json`).

Structure:
```json
{
  "exact": [
    { "value": "sha256:<hashed>", "type": "aws-key", "note": "test key", "added": "2026-03-10" }
  ],
  "patterns": [
    { "regex": ".*@mycompany\\.com", "type": "email", "note": "work emails ok" }
  ]
}
```

Values stored as SHA-256 hashes — allowlist itself does not contain plaintext secrets.

### Allowlist Hashing

For `exact` entries, the hash input is determined by detection engine:

- **Gitleaks findings:** SHA-256 of the `Secret` field from gitleaks JSON output (the actual secret value, not the surrounding match context). Trimmed of leading/trailing whitespace before hashing.
- **PII findings:** SHA-256 of the full regex match, trimmed of leading/trailing whitespace.

For `patterns` entries, the raw matched value (not hashed) is tested against the regex at runtime. Pattern entries never store sensitive data — they describe shapes (e.g., `.*@mycompany\.com`).

**Matching order:** exact hash check first (fast O(1) lookup), then pattern regex check (linear scan). Project allowlist checked before global.

## Configuration

Plugin config at `~/.claude/sensitive-guard.json`:
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
  "allowlist": {
    "global": "~/.claude/sensitive-guard-allowlist.json",
    "project": ".claude/sensitive-guard-allowlist.json"
  },
  "display": {
    "maxValuePreview": 12
  }
}
```

**Customization:**

| What | How |
|------|-----|
| Add tool to inspect | Add to `tools` array |
| Disable PII detection entirely | `pii.enabled: false` |
| Disable specific PII pattern | Add pattern ID to `pii.disabled`: `["ipv4", "phone"]`. Overrides the `enabled` field in default patterns — a pattern is active only if its default `enabled` is true AND its ID is NOT in `pii.disabled` |
| Add custom PII pattern | Append to `pii.custom`: `{ "id": "internal_id", "regex": "EMP-\\d{6}", "description": "Employee ID" }` |
| Use custom gitleaks rules | Set `gitleaks.configPath` to `.gitleaks.toml` |
| Disable gitleaks | `gitleaks.enabled: false` |
| Change preview length | `display.maxValuePreview` |

**Project-level override:** `.claude/sensitive-guard.json` in project root merges on top of global config.

**Merge strategy:** Deep merge with these rules:
- **Arrays** (`tools`, `pii.disabled`, `pii.custom`): project values **append** to global values (union)
- **Scalars** (`pii.enabled`, `gitleaks.enabled`, `display.maxValuePreview`): project value **replaces** global value
- **Objects** (`allowlist`, `gitleaks`): deep merge recursively

**Missing config files:** Treated as empty — all defaults apply.

**Non-interactive mode:** If stdin is not a TTY (e.g., CI environment), the default action is `block` — all findings are rejected. This ensures the plugin fails safe in headless contexts.

## Edge Cases & Limitations

| Case | Behavior |
|------|----------|
| `Bash` with dynamic paths (`cat "$VAR"`) | Cannot resolve — skipped, documented |
| `Bash` piped commands (`curl ... \| jq`) | Not scanning local files — skipped |
| Large files (>10MB) | Gitleaks handles fine, PII regex may be slow — 5s timeout. On timeout: file treated as clean (allow), warning logged to stderr |
| Binary files | Gitleaks skips, PII regex skips — no false positives |
| Symlinks | Resolve to real path before scanning |
| File doesn't exist yet (Write tool) | Not inspected — data comes from Claude, already on server |
| Glob tool | Returns file paths only, no content — skip |
| Grep with directory path | PreToolUse cannot know which files will match — directory-level Grep is not scanned. Known limitation: findings in matched content won't be caught. |
| Race condition (file changes between scan and read) | Possible but unlikely in practice. Known limitation — scan result may be stale. |

**False positive mitigation:**
- Allowlist is the primary escape hatch
- Common non-sensitive IPs (`127.0.0.1`, `0.0.0.0`) in default allowlist
- Users can disable specific pattern IDs via `pii.disabled` config array
- IPv4 pattern disabled by default due to high false positive rate with version strings

**Performance budget:**
- Gitleaks: ~50-200ms per file
- PII regex: ~10-50ms per file
- Allowlist check: <5ms
- Total target: <500ms per tool call

#!/bin/bash
set -euo pipefail

# sensitive-guard PreToolUse hook
# Reads tool call JSON from stdin, scans target files for sensitive data,
# prompts user, and blocks or allows based on their choice.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source all modules
source "$PLUGIN_ROOT/src/utils.sh"
source "$PLUGIN_ROOT/src/config.sh"
source "$PLUGIN_ROOT/src/pii-detector.sh"
source "$PLUGIN_ROOT/src/gitleaks-runner.sh"
source "$PLUGIN_ROOT/src/allowlist.sh"
source "$PLUGIN_ROOT/src/bash-parser.sh"
source "$PLUGIN_ROOT/src/prompt.sh"
source "$PLUGIN_ROOT/src/scanner.sh"

# Read hook input from stdin
HOOK_INPUT=$(cat)

# Extract tool name and input
TOOL_NAME=$(echo "$HOOK_INPUT" | jq -r '.tool_name // empty')
TOOL_INPUT=$(echo "$HOOK_INPUT" | jq -c '.tool_input // {}')
CWD=$(echo "$HOOK_INPUT" | jq -r '.cwd // empty')

if [[ -z "$TOOL_NAME" ]]; then
  exit 0  # No tool name, allow
fi

# Resolve config paths
GLOBAL_CONFIG="${HOME}/.claude/sensitive-guard.json"
PROJECT_CONFIG="${CWD:-.}/.claude/sensitive-guard.json"

# Load config
CONFIG=$(sg_load_config "$GLOBAL_CONFIG" "$PROJECT_CONFIG" "$PLUGIN_ROOT")

# Resolve allowlist paths
GLOBAL_ALLOWLIST=$(echo "$CONFIG" | jq -r '.allowlist.global // empty')
GLOBAL_ALLOWLIST=$(sg_resolve_path "${GLOBAL_ALLOWLIST:-$HOME/.claude/sensitive-guard-allowlist.json}")

PROJECT_ALLOWLIST=$(echo "$CONFIG" | jq -r '.allowlist.project // empty')
PROJECT_ALLOWLIST="${CWD:-.}/${PROJECT_ALLOWLIST:-.claude/sensitive-guard-allowlist.json}"

# Run scan and prompt
sg_scan_and_prompt "$TOOL_NAME" "$TOOL_INPUT" "$CONFIG" "$PLUGIN_ROOT" "$PROJECT_ALLOWLIST" "$GLOBAL_ALLOWLIST"
exit $?

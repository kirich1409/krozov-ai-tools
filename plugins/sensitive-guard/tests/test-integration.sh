#!/bin/bash
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$SCRIPT_DIR/.."
source "$SCRIPT_DIR/test-utils.sh"

FIXTURES="$SCRIPT_DIR/fixtures"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# Helper: pipe JSON to the hook and return its exit code without tripping pipefail
run_hook() {
  local input="$1"
  local exit_code_file
  exit_code_file=$(mktemp)
  set +o pipefail
  echo "$input" | bash "$PLUGIN_ROOT/hooks/pre-tool-use.sh" 2>/dev/null
  echo $? >"$exit_code_file"
  set -o pipefail
  local code
  code=$(cat "$exit_code_file")
  rm -f "$exit_code_file"
  echo "$code"
}

# Test: hook allows clean file
test_start "hook allows Read of clean file"
HOOK_INPUT=$(jq -n \
  --arg tool "Read" \
  --arg file "$FIXTURES/clean-file.txt" \
  --arg cwd "$TMP_DIR" \
  '{tool_name: $tool, tool_input: {file_path: $file}, cwd: $cwd}')
EXIT_CODE=$(run_hook "$HOOK_INPUT")
assert_exit_code "0" "$EXIT_CODE" "clean file should be allowed"

# Test: hook allows uninspected tool
test_start "hook allows uninspected tool (Write)"
HOOK_INPUT=$(jq -n \
  --arg tool "Write" \
  --arg file "/tmp/out.txt" \
  --arg cwd "$TMP_DIR" \
  '{tool_name: $tool, tool_input: {file_path: $file}, cwd: $cwd}')
EXIT_CODE=$(run_hook "$HOOK_INPUT")
assert_exit_code "0" "$EXIT_CODE" "Write should not be inspected"

# Test: hook blocks file with PII in non-interactive mode
test_start "hook blocks PII file in non-interactive mode"
HOOK_INPUT=$(jq -n \
  --arg tool "Read" \
  --arg file "$FIXTURES/pii-file.txt" \
  --arg cwd "$TMP_DIR" \
  '{tool_name: $tool, tool_input: {file_path: $file}, cwd: $cwd}')
EXIT_CODE=$(run_hook "$HOOK_INPUT")
assert_exit_code "2" "$EXIT_CODE" "PII file should be blocked in non-interactive"

# Test: hook allows file with all findings in allowlist
test_start "hook allows file when all findings are allowlisted"
mkdir -p "$TMP_DIR/.claude"
cat > "$TMP_DIR/.claude/sensitive-guard-allowlist.json" << 'ALEOF'
{
  "exact": [],
  "patterns": [
    { "regex": ".*@.*\\.com", "type": "email", "note": "all .com emails" },
    { "regex": ".*@.*\\.org", "type": "email", "note": "all .org emails" },
    { "regex": ".*", "type": "ssn", "note": "all SSNs" },
    { "regex": ".*", "type": "credit_card", "note": "all cards" },
    { "regex": ".*", "type": "iban", "note": "all IBANs" }
  ]
}
ALEOF
HOOK_INPUT=$(jq -n \
  --arg tool "Read" \
  --arg file "$FIXTURES/pii-file.txt" \
  --arg cwd "$TMP_DIR" \
  '{tool_name: $tool, tool_input: {file_path: $file}, cwd: $cwd}')
EXIT_CODE=$(run_hook "$HOOK_INPUT")
assert_exit_code "0" "$EXIT_CODE" "all-allowlisted file should pass"

# Test: hook handles Bash tool
test_start "hook handles Bash tool with file reference"
# Reset allowlist
rm -f "$TMP_DIR/.claude/sensitive-guard-allowlist.json"
HOOK_INPUT=$(jq -n \
  --arg tool "Bash" \
  --arg cmd "cat $FIXTURES/pii-file.txt" \
  --arg cwd "$TMP_DIR" \
  '{tool_name: $tool, tool_input: {command: $cmd}, cwd: $cwd}')
EXIT_CODE=$(run_hook "$HOOK_INPUT")
assert_exit_code "2" "$EXIT_CODE" "Bash reading PII file should be blocked"

# Test: hook allows empty tool name
test_start "hook allows empty tool name"
EXIT_CODE=$(run_hook '{}')
assert_exit_code "0" "$EXIT_CODE" "empty input should be allowed"

# Test: hook allows nonexistent file
test_start "hook allows Read of nonexistent file"
HOOK_INPUT=$(jq -n \
  --arg tool "Read" \
  --arg file "/nonexistent/does-not-exist.txt" \
  --arg cwd "$TMP_DIR" \
  '{tool_name: $tool, tool_input: {file_path: $file}, cwd: $cwd}')
EXIT_CODE=$(run_hook "$HOOK_INPUT")
assert_exit_code "0" "$EXIT_CODE" "nonexistent file should be allowed"

# Test: all unit tests still pass (run each unit test file directly, skip this file to avoid recursion)
test_start "all unit tests pass"
UNIT_FAILED=0
for f in "$SCRIPT_DIR"/test-*.sh; do
  [[ "$f" == "$SCRIPT_DIR/test-integration.sh" ]] && continue
  bash "$f" >/dev/null 2>&1 || UNIT_FAILED=1
done
assert_exit_code "0" "$UNIT_FAILED" "unit test suite"

test_summary

#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test-utils.sh"
source "$SCRIPT_DIR/../src/utils.sh"
source "$SCRIPT_DIR/../src/config.sh"
source "$SCRIPT_DIR/../src/pii-detector.sh"
source "$SCRIPT_DIR/../src/gitleaks-runner.sh"
source "$SCRIPT_DIR/../src/allowlist.sh"
source "$SCRIPT_DIR/../src/bash-parser.sh"
source "$SCRIPT_DIR/../src/prompt.sh"
source "$SCRIPT_DIR/../src/scanner.sh"

FIXTURES="$SCRIPT_DIR/fixtures"
PLUGIN_ROOT="$SCRIPT_DIR/.."

# Test: scan_file returns findings from PII engine
test_start "scan_file detects PII in file"
CONFIG=$(sg_load_config "/nonexistent" "/nonexistent" "$PLUGIN_ROOT")
FINDINGS=$(sg_scan_file "$FIXTURES/pii-file.txt" "$CONFIG" "$PLUGIN_ROOT")
COUNT=$(echo "$FINDINGS" | jq 'length')
[[ "$COUNT" -ge 4 ]] && test_pass || test_fail "expected >=4 findings, got $COUNT"

test_start "scan_file returns empty for clean file"
FINDINGS=$(sg_scan_file "$FIXTURES/clean-file.txt" "$CONFIG" "$PLUGIN_ROOT")
COUNT=$(echo "$FINDINGS" | jq 'length')
assert_equals "0" "$COUNT"

# Test: extract_target_files for Read tool
test_start "extract_target_files handles Read tool"
TOOL_INPUT='{"file_path":"/tmp/test.txt"}'
FILES=$(sg_extract_target_files "Read" "$TOOL_INPUT")
assert_contains "$FILES" "/tmp/test.txt"

# Test: extract_target_files for Grep tool (file)
test_start "extract_target_files handles Grep with file path"
TOOL_INPUT='{"path":"/tmp/test.txt","pattern":"secret"}'
FILES=$(sg_extract_target_files "Grep" "$TOOL_INPUT")
assert_contains "$FILES" "/tmp/test.txt"

# Test: extract_target_files for Bash tool
test_start "extract_target_files handles Bash tool"
TOOL_INPUT='{"command":"cat /tmp/test.txt"}'
FILES=$(sg_extract_target_files "Bash" "$TOOL_INPUT")
assert_contains "$FILES" "/tmp/test.txt"

# Test: extract_target_files skips Grep with directory
test_start "extract_target_files skips Grep with directory path"
TOOL_INPUT='{"path":"/tmp/","pattern":"secret"}'
FILES=$(sg_extract_target_files "Grep" "$TOOL_INPUT")
[[ -z "$FILES" ]] && test_pass || test_fail "should skip directory"

test_summary

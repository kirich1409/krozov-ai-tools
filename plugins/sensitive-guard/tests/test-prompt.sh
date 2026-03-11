#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test-utils.sh"
source "$SCRIPT_DIR/../src/utils.sh"
source "$SCRIPT_DIR/../src/prompt.sh"

# Test: format_findings_display
test_start "format_findings_display shows type and line info"
FINDINGS='[
  {"type":"aws-access-key","value":"AKIAIOSFODNN7EXAMPLE","file":"/app/.env","line":3,"engine":"gitleaks"},
  {"type":"email","value":"admin@example.com","file":"/app/.env","line":5,"engine":"pii"}
]'
OUTPUT=$(sg_format_findings_display "$FINDINGS" 8)
assert_contains "$OUTPUT" "aws-access-key" "should show type"
assert_contains "$OUTPUT" "line 3" "should show line number"
assert_contains "$OUTPUT" "email" "should show email type"
assert_not_contains "$OUTPUT" "AKIAIOSFODNN7EXAMPLE" "should NOT show full key"

# Test: multi-file display
test_start "format_findings_display shows multiple files"
FINDINGS='[
  {"type":"email","value":"a@test.com","file":"/app/a.txt","line":1,"engine":"pii"},
  {"type":"ssn","value":"123-45-6789","file":"/app/b.txt","line":2,"engine":"pii"}
]'
OUTPUT=$(sg_format_findings_display "$FINDINGS" 12)
assert_contains "$OUTPUT" "/app/a.txt" "should show first file"
assert_contains "$OUTPUT" "/app/b.txt" "should show second file"

# Test: non-interactive mode returns block for all items
test_start "non-interactive mode returns all-block actions"
FINDINGS='[{"type":"email","value":"a@b.com","file":"f.txt","line":1,"engine":"pii"}]'
ACTIONS=$(sg_collect_actions "$FINDINGS" 12 </dev/null 2>/dev/null)
FIRST_ACTION=$(echo "$ACTIONS" | jq -r '.[0].action')
assert_equals "block" "$FIRST_ACTION" "non-TTY should default to block"

test_summary

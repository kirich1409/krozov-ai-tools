#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test-utils.sh"
source "$SCRIPT_DIR/../src/utils.sh"
source "$SCRIPT_DIR/../src/gitleaks-runner.sh"

FIXTURES="$SCRIPT_DIR/fixtures"

# Skip tests if gitleaks not installed
if ! command -v gitleaks &>/dev/null; then
  echo "SKIP: gitleaks not installed"
  exit 0
fi

# Test: detect secrets in file
test_start "detects secrets in file"
FINDINGS=$(sg_run_gitleaks "$FIXTURES/secret-file.env" "")
COUNT=$(echo "$FINDINGS" | jq 'length')
if [[ "$COUNT" -ge 2 ]]; then
  test_pass
else
  test_fail "expected >=2 findings, got $COUNT"
fi

# Test: finding structure
test_start "findings have required fields"
FIRST=$(echo "$FINDINGS" | jq '.[0]')
HAS_TYPE=$(echo "$FIRST" | jq 'has("type")')
assert_equals "true" "$HAS_TYPE" "should have type"

test_start "findings have value field"
HAS_VALUE=$(echo "$FIRST" | jq 'has("value")')
assert_equals "true" "$HAS_VALUE" "should have value"

test_start "findings have file field"
HAS_FILE=$(echo "$FIRST" | jq 'has("file")')
assert_equals "true" "$HAS_FILE" "should have file"

test_start "engine field is gitleaks"
ENGINE=$(echo "$FIRST" | jq -r '.engine')
assert_equals "gitleaks" "$ENGINE" "engine should be gitleaks"

# Test: clean file produces no findings
test_start "clean file produces no findings"
FINDINGS=$(sg_run_gitleaks "$FIXTURES/clean-file.txt" "")
COUNT=$(echo "$FINDINGS" | jq 'length')
assert_equals "0" "$COUNT"

# Test: nonexistent file returns empty
test_start "nonexistent file returns empty array"
FINDINGS=$(sg_run_gitleaks "/nonexistent/file.txt" "")
COUNT=$(echo "$FINDINGS" | jq 'length')
assert_equals "0" "$COUNT"

test_summary

#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test-utils.sh"
source "$SCRIPT_DIR/../src/utils.sh"
source "$SCRIPT_DIR/../src/allowlist.sh"

FIXTURES="$SCRIPT_DIR/fixtures"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# Test: load allowlist
test_start "load existing allowlist"
AL=$(sg_load_allowlist "$FIXTURES/sample-allowlist.json")
EXACT_COUNT=$(echo "$AL" | jq '.exact | length')
assert_equals "1" "$EXACT_COUNT"

test_start "load nonexistent allowlist returns empty structure"
AL=$(sg_load_allowlist "/nonexistent/allowlist.json")
EXACT_COUNT=$(echo "$AL" | jq '.exact | length')
assert_equals "0" "$EXACT_COUNT"
PATTERN_COUNT=$(echo "$AL" | jq '.patterns | length')
assert_equals "0" "$PATTERN_COUNT"

# Test: check finding against allowlist (exact match)
test_start "exact hash match allows finding"
AL=$(sg_load_allowlist "$FIXTURES/sample-allowlist.json")
RESULT=$(sg_is_allowed "$AL" "hello world" "email")
assert_equals "true" "$RESULT" "hello world hash should match"

test_start "non-matching hash is not allowed"
RESULT=$(sg_is_allowed "$AL" "other-value" "email")
assert_equals "false" "$RESULT"

# Test: pattern match
test_start "pattern regex match allows finding"
RESULT=$(sg_is_allowed "$AL" "user@example.com" "email")
assert_equals "true" "$RESULT" "example.com email should match pattern"

test_start "non-matching pattern is not allowed"
RESULT=$(sg_is_allowed "$AL" "user@other.com" "email")
assert_equals "false" "$RESULT"

# Test: add exact entry
test_start "add exact entry to allowlist"
AL_PATH="$TMP_DIR/test-allowlist.json"
sg_add_to_allowlist "$AL_PATH" "exact" "my-secret" "aws-key" "test addition"
AL=$(sg_load_allowlist "$AL_PATH")
EXACT_COUNT=$(echo "$AL" | jq '.exact | length')
assert_equals "1" "$EXACT_COUNT"

test_start "added entry has correct hash"
EXPECTED_HASH="sha256:$(sg_sha256 "my-secret")"
ACTUAL_HASH=$(echo "$AL" | jq -r '.exact[0].value')
assert_equals "$EXPECTED_HASH" "$ACTUAL_HASH"

# Test: filter findings against allowlists
test_start "filter_findings removes allowed items"
FINDINGS='[{"type":"email","value":"user@example.com","file":"f.txt","line":1,"engine":"pii"},{"type":"ssn","value":"123-45-6789","file":"f.txt","line":2,"engine":"pii"}]'
FILTERED=$(sg_filter_findings "$FINDINGS" "$FIXTURES/sample-allowlist.json" "/nonexistent")
COUNT=$(echo "$FILTERED" | jq 'length')
assert_equals "1" "$COUNT" "email should be filtered, ssn remains"
REMAINING_TYPE=$(echo "$FILTERED" | jq -r '.[0].type')
assert_equals "ssn" "$REMAINING_TYPE"

test_summary

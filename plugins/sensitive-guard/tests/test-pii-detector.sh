#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test-utils.sh"
source "$SCRIPT_DIR/../src/utils.sh"
source "$SCRIPT_DIR/../src/config.sh"
source "$SCRIPT_DIR/../src/pii-detector.sh"

FIXTURES="$SCRIPT_DIR/fixtures"
PLUGIN_ROOT="$SCRIPT_DIR/.."

# Load default config to get active patterns
CONFIG=$(sg_load_config "/nonexistent" "/nonexistent" "$PLUGIN_ROOT")
PATTERNS=$(sg_get_active_pii_patterns "$CONFIG" "$PLUGIN_ROOT")

# Test: detect email
test_start "detects email addresses"
FINDINGS=$(sg_detect_pii "$FIXTURES/pii-file.txt" "$PATTERNS")
EMAILS=$(echo "$FINDINGS" | jq '[.[] | select(.type == "email")] | length')
assert_equals "2" "$EMAILS" "should find 2 emails"

# Test: detect SSN
test_start "detects SSN"
SSNS=$(echo "$FINDINGS" | jq '[.[] | select(.type == "ssn")] | length')
assert_equals "1" "$SSNS" "should find 1 SSN"

# Test: detect credit card
test_start "detects credit card numbers"
CCS=$(echo "$FINDINGS" | jq '[.[] | select(.type == "credit_card")] | length')
assert_equals "1" "$CCS" "should find 1 credit card"

# Test: detect IBAN
test_start "detects IBAN"
IBANS=$(echo "$FINDINGS" | jq '[.[] | select(.type == "iban")] | length')
assert_equals "1" "$IBANS" "should find 1 IBAN"

# Test: finding structure
test_start "findings have required fields"
FIRST=$(echo "$FINDINGS" | jq '.[0]')
assert_json_field "$FIRST" '.type' "email" "type field"
assert_json_field "$FIRST" '.file' "$FIXTURES/pii-file.txt" "file field"
HAS_LINE=$(echo "$FIRST" | jq 'has("line")')
assert_equals "true" "$HAS_LINE" "should have line number"
HAS_VALUE=$(echo "$FIRST" | jq 'has("value")')
assert_equals "true" "$HAS_VALUE" "should have matched value"
assert_json_field "$FIRST" '.engine' "pii" "engine field"

# Test: clean file produces no findings
test_start "clean file produces no findings"
FINDINGS=$(sg_detect_pii "$FIXTURES/clean-file.txt" "$PATTERNS")
COUNT=$(echo "$FINDINGS" | jq 'length')
assert_equals "0" "$COUNT" "should find nothing in clean file"

# Test: nonexistent file produces no findings
test_start "nonexistent file returns empty array"
FINDINGS=$(sg_detect_pii "/nonexistent/file.txt" "$PATTERNS")
COUNT=$(echo "$FINDINGS" | jq 'length')
assert_equals "0" "$COUNT"

# Test: binary file produces no findings
test_start "binary file returns empty array"
BINARY=$(mktemp)
printf '\x00\x01\x02admin@test.com' > "$BINARY"
FINDINGS=$(sg_detect_pii "$BINARY" "$PATTERNS")
COUNT=$(echo "$FINDINGS" | jq 'length')
assert_equals "0" "$COUNT" "binary files should be skipped"
rm -f "$BINARY"

# Test: ipv4 is NOT detected (disabled by default)
test_start "ipv4 not detected when disabled"
FINDINGS=$(sg_detect_pii "$FIXTURES/pii-file.txt" "$PATTERNS")
IPV4=$(echo "$FINDINGS" | jq '[.[] | select(.type == "ipv4")] | length')
assert_equals "0" "$IPV4" "ipv4 should not be detected"

test_summary

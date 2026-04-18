#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test-utils.sh"
source "$SCRIPT_DIR/../src/utils.sh"

# Test sha256
test_start "sha256 produces consistent hash"
HASH1=$(sg_sha256 "my-secret-value")
HASH2=$(sg_sha256 "my-secret-value")
assert_equals "$HASH1" "$HASH2" "same input should produce same hash"

test_start "sha256 produces 64-char hex string"
HASH=$(sg_sha256 "test")
assert_equals "64" "${#HASH}" "sha256 hash length"

test_start "sha256 trims whitespace before hashing"
HASH_CLEAN=$(sg_sha256 "secret")
HASH_SPACED=$(sg_sha256 "  secret  ")
assert_equals "$HASH_CLEAN" "$HASH_SPACED" "trimmed values should match"

# Test truncate_value
test_start "truncate_value masks long values"
RESULT=$(sg_truncate_value "AKIA1234567890ABCDEF" 8)
assert_equals "AKIA...CDEF" "$RESULT" "should show prefix(4)...suffix(4)"

test_start "truncate_value keeps short values as-is"
RESULT=$(sg_truncate_value "short" 12)
assert_equals "short" "$RESULT" "short value unchanged"

# Test is_binary
test_start "is_binary detects binary files"
BINARY_FILE=$(mktemp)
printf '\x00\x01\x02' > "$BINARY_FILE"
sg_is_binary "$BINARY_FILE" && test_pass || test_fail "should detect binary"
rm -f "$BINARY_FILE"

test_start "is_binary returns false for text files"
TEXT_FILE=$(mktemp)
echo "hello world" > "$TEXT_FILE"
sg_is_binary "$TEXT_FILE" && test_fail "should not detect text as binary" || test_pass
rm -f "$TEXT_FILE"

# Test log_warn
test_start "log_warn outputs to stderr with prefix"
OUTPUT=$(sg_log_warn "test warning" 2>&1 1>/dev/null)
assert_contains "$OUTPUT" "sensitive-guard" "should have plugin prefix"
assert_contains "$OUTPUT" "test warning" "should have message"

test_summary

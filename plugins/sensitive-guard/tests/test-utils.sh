#!/bin/bash
# Minimal test framework for sensitive-guard

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
CURRENT_TEST=""

test_start() {
  CURRENT_TEST="$1"
  TESTS_RUN=$((TESTS_RUN + 1))
}

test_pass() {
  TESTS_PASSED=$((TESTS_PASSED + 1))
  echo "  PASS: $CURRENT_TEST"
}

test_fail() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  echo "  FAIL: $CURRENT_TEST — $1" >&2
}

assert_equals() {
  local expected="$1" actual="$2" msg="${3:-}"
  if [[ "$expected" == "$actual" ]]; then
    test_pass
  else
    test_fail "${msg:+$msg: }expected '$expected', got '$actual'"
  fi
}

assert_contains() {
  local haystack="$1" needle="$2" msg="${3:-}"
  if echo "$haystack" | grep -qF "$needle"; then
    test_pass
  else
    test_fail "${msg:+$msg: }'$needle' not found in output"
  fi
}

assert_not_contains() {
  local haystack="$1" needle="$2" msg="${3:-}"
  if echo "$haystack" | grep -qF "$needle"; then
    test_fail "${msg:+$msg: }'$needle' unexpectedly found in output"
  else
    test_pass
  fi
}

assert_exit_code() {
  local expected="$1" actual="$2" msg="${3:-}"
  if [[ "$expected" == "$actual" ]]; then
    test_pass
  else
    test_fail "${msg:+$msg: }expected exit code $expected, got $actual"
  fi
}

assert_json_field() {
  local json="$1" field="$2" expected="$3" msg="${4:-}"
  local actual
  actual=$(echo "$json" | jq -r "$field")
  assert_equals "$expected" "$actual" "$msg"
}

test_summary() {
  echo ""
  echo "Results: $TESTS_PASSED/$TESTS_RUN passed, $TESTS_FAILED failed"
  [[ $TESTS_FAILED -eq 0 ]]
}

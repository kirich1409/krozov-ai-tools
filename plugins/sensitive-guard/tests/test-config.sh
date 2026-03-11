#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test-utils.sh"
source "$SCRIPT_DIR/../src/utils.sh"
source "$SCRIPT_DIR/../src/config.sh"

FIXTURES="$SCRIPT_DIR/fixtures"
PLUGIN_ROOT="$SCRIPT_DIR/.."

# Test: load defaults when no config files exist
test_start "load_config returns defaults when no config files"
CONFIG=$(sg_load_config "/nonexistent/global.json" "/nonexistent/project.json" "$PLUGIN_ROOT")
TOOLS=$(echo "$CONFIG" | jq -r '.tools | join(",")')
assert_equals "Read,Grep,Bash" "$TOOLS" "default tools"

test_start "default config has pii enabled"
PII_ENABLED=$(echo "$CONFIG" | jq -r '.pii.enabled')
assert_equals "true" "$PII_ENABLED"

# Test: global config overrides defaults (scalars replace)
test_start "global config replaces scalar values"
CONFIG=$(sg_load_config "$FIXTURES/sample-config.json" "/nonexistent/project.json" "$PLUGIN_ROOT")
PII_ENABLED=$(echo "$CONFIG" | jq -r '.pii.enabled')
assert_equals "false" "$PII_ENABLED" "pii.enabled replaced"

test_start "global config replaces display.maxValuePreview"
PREVIEW=$(echo "$CONFIG" | jq -r '.display.maxValuePreview')
assert_equals "8" "$PREVIEW"

# Test: global config replaces tools array (not append — global IS the base)
test_start "global config sets tools array"
TOOLS=$(echo "$CONFIG" | jq -r '.tools | join(",")')
assert_equals "Read" "$TOOLS" "global replaces default tools"

# Test: project config appends arrays to global
test_start "project config appends tools to global"
CONFIG=$(sg_load_config "$FIXTURES/sample-config.json" "$FIXTURES/project-config.json" "$PLUGIN_ROOT")
TOOLS=$(echo "$CONFIG" | jq -r '.tools | sort | join(",")')
assert_equals "Edit,Read" "$TOOLS" "project tools appended to global"

test_start "project config appends pii.disabled"
DISABLED=$(echo "$CONFIG" | jq -r '.pii.disabled | join(",")')
assert_equals "email" "$DISABLED" "project pii.disabled appended"

# Test: get_active_pii_patterns filters by enabled + disabled
test_start "get_active_pii_patterns excludes disabled patterns"
CONFIG=$(sg_load_config "/nonexistent/global.json" "/nonexistent/project.json" "$PLUGIN_ROOT")
PATTERNS=$(sg_get_active_pii_patterns "$CONFIG" "$PLUGIN_ROOT")
PATTERN_IDS=$(echo "$PATTERNS" | jq -r '.[].id' | sort | tr '\n' ',')
assert_contains "$PATTERN_IDS" "email" "email should be active"
assert_contains "$PATTERN_IDS" "ssn" "ssn should be active"
assert_not_contains "$PATTERN_IDS" "phone" "phone should be disabled"
assert_not_contains "$PATTERN_IDS" "ipv4" "ipv4 should be disabled"

test_start "get_active_pii_patterns respects pii.disabled from config"
CONFIG=$(sg_load_config "/nonexistent/global.json" "$FIXTURES/project-config.json" "$PLUGIN_ROOT")
PATTERNS=$(sg_get_active_pii_patterns "$CONFIG" "$PLUGIN_ROOT")
PATTERN_IDS=$(echo "$PATTERNS" | jq -r '.[].id' | sort | tr '\n' ',')
assert_not_contains "$PATTERN_IDS" "email" "email disabled by config"

# Test: custom PII patterns are appended
test_start "get_active_pii_patterns includes custom patterns"
CONFIG=$(echo '{"pii":{"enabled":true,"disabled":[],"custom":[{"id":"employee_id","regex":"EMP-[0-9]{6}","description":"Employee ID"}]},"tools":["Read"],"gitleaks":{"enabled":true},"allowlist":{},"display":{"maxValuePreview":12}}')
PATTERNS=$(sg_get_active_pii_patterns "$CONFIG" "$PLUGIN_ROOT")
PATTERN_IDS=$(echo "$PATTERNS" | jq -r '.[].id' | sort | tr '\n' ',')
assert_contains "$PATTERN_IDS" "employee_id" "custom pattern should be included"
assert_contains "$PATTERN_IDS" "email" "default patterns still included"

test_summary

# sensitive-guard Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that prevents sensitive data from reaching AI servers by scanning files before they're read into conversation.

**Architecture:** Standalone Claude Code plugin (shell-based). PreToolUse hook extracts file paths from tool calls, scans them with gitleaks (secrets) and custom regex (PII), prompts the user interactively, and blocks or allows based on their choice. Allowlists (project + global) persist approvals as SHA-256 hashes.

**Tech Stack:** Bash, jq, gitleaks CLI, sha256sum/shasum, grep (PCRE)

**Spec:** `docs/superpowers/specs/2026-03-10-sensitive-guard-design.md`

**Note on plugin structure:** The spec uses `manifest.json` as a placeholder name. The actual Claude Code plugin format uses `plugin.json` for metadata and a separate `hooks/hooks.json` for hook registration (matching the existing maven-mcp plugin conventions in this repo). The plan follows the real format.

---

## File Structure

```
sensitive-guard/
  .claude-plugin/
    plugin.json               # Plugin metadata
  hooks/
    hooks.json                # Hook registration (PreToolUse)
    pre-tool-use.sh           # Entry point: reads stdin JSON, routes to scanner
  src/
    config.sh                 # Load + merge config (global + project)
    pii-detector.sh           # PII regex scanner, outputs JSON findings
    gitleaks-runner.sh        # Wraps gitleaks CLI, outputs normalized JSON findings
    allowlist.sh              # Read/write allowlists, hash checking
    bash-parser.sh            # Extract file paths from Bash commands
    prompt.sh                 # Interactive prompt, collects per-item actions
    scanner.sh                # Orchestrator: ties all modules together
    utils.sh                  # Shared helpers (logging, JSON output, sha256)
  config/
    default-pii-patterns.json # Built-in PII regex patterns
    default-config.json       # Default plugin configuration
  tests/
    run-tests.sh              # Test runner (discovers + runs test-*.sh files)
    test-utils.sh             # Test assertions (assert_equals, assert_contains, etc.)
    test-shared-utils.sh      # Tests for src/utils.sh
    test-pii-detector.sh      # PII detection tests
    test-bash-parser.sh       # Bash file path extraction tests
    test-allowlist.sh         # Allowlist hashing + matching tests
    test-config.sh            # Config loading + merge tests
    test-scanner.sh           # Scanner orchestration tests
    test-prompt.sh            # Prompt formatting tests (non-interactive)
    fixtures/
      secret-file.env         # File with known secrets for testing
      pii-file.txt            # File with known PII for testing
      clean-file.txt          # File with no sensitive data
      sample-allowlist.json   # Pre-populated allowlist for testing
      sample-config.json      # Custom config for testing
      project-config.json     # Project-level config override for merge tests
```

---

## Chunk 1: Foundation (config, utils, test harness)

### Task 1: Project scaffold and test harness

**Files:**
- Create: `sensitive-guard/tests/run-tests.sh`
- Create: `sensitive-guard/tests/test-utils.sh`

- [ ] **Step 1: Create project directory structure**

```bash
mkdir -p sensitive-guard/{.claude-plugin,hooks,src,config,tests/fixtures}
```

- [ ] **Step 2: Write test assertion helpers**

Create `tests/test-utils.sh`:
```bash
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
```

- [ ] **Step 3: Write test runner**

Create `tests/run-tests.sh`:
```bash
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OVERALL_FAILED=0

for test_file in "$SCRIPT_DIR"/test-*.sh; do
  echo "=== $(basename "$test_file") ==="
  if bash "$test_file"; then
    echo ""
  else
    OVERALL_FAILED=1
    echo ""
  fi
done

if [[ $OVERALL_FAILED -eq 0 ]]; then
  echo "All test suites passed."
else
  echo "Some test suites FAILED." >&2
  exit 1
fi
```

- [ ] **Step 4: Make scripts executable and verify runner works**

```bash
chmod +x sensitive-guard/tests/run-tests.sh
chmod +x sensitive-guard/tests/test-utils.sh
bash sensitive-guard/tests/run-tests.sh
```

Expected: `All test suites passed.` (no test files yet)

- [ ] **Step 5: Commit**

```bash
git add sensitive-guard/
git commit -m "feat(sensitive-guard): add project scaffold and test harness"
```

---

### Task 2: Shared utilities

**Files:**
- Create: `sensitive-guard/src/utils.sh`
- Create: `sensitive-guard/tests/test-shared-utils.sh`

- [ ] **Step 1: Write failing test for sha256 helper**

Create `tests/test-shared-utils.sh`:
```bash
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bash sensitive-guard/tests/test-shared-utils.sh
```

Expected: FAIL (source file not found)

- [ ] **Step 3: Write utils.sh implementation**

Create `src/utils.sh`:
```bash
#!/bin/bash
# Shared utilities for sensitive-guard

sg_sha256() {
  local value="$1"
  # Trim leading/trailing whitespace
  value="$(echo "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  # Use shasum (macOS) or sha256sum (Linux)
  if command -v shasum &>/dev/null; then
    printf '%s' "$value" | shasum -a 256 | cut -d' ' -f1
  else
    printf '%s' "$value" | sha256sum | cut -d' ' -f1
  fi
}

sg_truncate_value() {
  local value="$1" max_preview="${2:-12}"
  local len=${#value}
  if [[ $len -le $((max_preview + 6)) ]]; then
    echo "$value"
  else
    local half=$((max_preview / 2))
    echo "${value:0:$half}...${value: -$half}"
  fi
}

sg_log_warn() {
  echo "[sensitive-guard] WARNING: $1" >&2
}

sg_log_error() {
  echo "[sensitive-guard] ERROR: $1" >&2
}

sg_is_file() {
  [[ -f "$1" ]]
}

sg_resolve_path() {
  local path="$1"
  # Expand ~ and known variables
  path="${path/#\~/$HOME}"
  path="${path//\$HOME/$HOME}"
  path="${path//\$PWD/$PWD}"
  # Resolve symlinks if file exists
  if [[ -e "$path" ]]; then
    if command -v realpath &>/dev/null; then
      path=$(realpath "$path")
    elif command -v readlink &>/dev/null; then
      path=$(readlink -f "$path" 2>/dev/null || echo "$path")
    fi
  fi
  echo "$path"
}

sg_is_binary() {
  local file_path="$1"
  # Quick check: if file contains null bytes, it's binary
  if grep -Pql '\x00' "$file_path" 2>/dev/null; then
    return 0  # is binary
  fi
  return 1  # is text
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bash sensitive-guard/tests/test-shared-utils.sh
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add sensitive-guard/src/utils.sh sensitive-guard/tests/test-shared-utils.sh
git commit -m "feat(sensitive-guard): add shared utilities (sha256, truncate, logging)"
```

---

### Task 3: Configuration loading and merging

**Files:**
- Create: `sensitive-guard/src/config.sh`
- Create: `sensitive-guard/config/default-config.json`
- Create: `sensitive-guard/config/default-pii-patterns.json`
- Create: `sensitive-guard/tests/test-config.sh`
- Create: `sensitive-guard/tests/fixtures/sample-config.json`
- Create: `sensitive-guard/tests/fixtures/project-config.json`

- [ ] **Step 1: Create default config files**

Create `config/default-config.json`:
```json
{
  "tools": ["Read", "Grep", "Bash"],
  "pii": {
    "enabled": true,
    "disabled": [],
    "custom": []
  },
  "gitleaks": {
    "enabled": true,
    "configPath": null
  },
  "allowlist": {
    "global": "~/.claude/sensitive-guard-allowlist.json",
    "project": ".claude/sensitive-guard-allowlist.json"
  },
  "display": {
    "maxValuePreview": 12
  }
}
```

Create `config/default-pii-patterns.json`:
```json
[
  { "id": "email", "enabled": true, "regex": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}", "description": "Email address" },
  { "id": "ssn", "enabled": true, "regex": "\\b[0-9]{3}-[0-9]{2}-[0-9]{4}\\b", "description": "US SSN" },
  { "id": "credit_card", "enabled": true, "regex": "\\b(?:4[0-9]{3}|5[1-5][0-9]{2}|3[47][0-9]{2}|6(?:011|5[0-9]{2}))[-\\s]?[0-9]{4}[-\\s]?[0-9]{4}[-\\s]?[0-9]{4}\\b", "description": "Credit card number" },
  { "id": "phone", "enabled": false, "regex": "(?:\\+[1-9][0-9]{0,2}[-\\s])?(?:\\(?[0-9]{1,4}\\)[-\\s])?[0-9][0-9\\-\\s]{4,14}[0-9]", "description": "Phone number (disabled by default)" },
  { "id": "ipv4", "enabled": false, "regex": "\\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\b", "description": "IPv4 address (disabled by default)" },
  { "id": "iban", "enabled": true, "regex": "\\b[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}(?:[A-Z0-9]?){0,16}\\b", "description": "IBAN" }
]
```

- [ ] **Step 2: Write failing test for config loading**

Create `tests/fixtures/sample-config.json`:
```json
{
  "tools": ["Read"],
  "pii": {
    "enabled": false
  },
  "display": {
    "maxValuePreview": 8
  }
}
```

Create `tests/fixtures/project-config.json`:
```json
{
  "tools": ["Edit"],
  "pii": {
    "disabled": ["email"]
  }
}
```

Create `tests/test-config.sh`:
```bash
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
```

- [ ] **Step 3: Run test to verify it fails**

```bash
bash sensitive-guard/tests/test-config.sh
```

Expected: FAIL (config.sh not found)

- [ ] **Step 4: Write config.sh implementation**

Create `src/config.sh`:
```bash
#!/bin/bash
# Configuration loading and merging for sensitive-guard
#
# Merge strategy (spec):
# - Arrays (tools, pii.disabled, pii.custom): project appends to global (union)
# - Scalars (pii.enabled, gitleaks.enabled, display.maxValuePreview): project replaces global
# - Objects (allowlist, gitleaks): deep merge recursively

sg_load_config() {
  local global_config_path="$1"
  local project_config_path="$2"
  local plugin_root="$3"

  local default_config
  default_config=$(cat "$plugin_root/config/default-config.json")

  # Start with defaults
  local merged="$default_config"

  # Apply global config if exists
  if [[ -f "$global_config_path" ]]; then
    local global_config
    global_config=$(cat "$global_config_path")
    merged=$(sg_merge_configs "$merged" "$global_config")
  fi

  # Apply project config if exists (arrays append, scalars replace)
  if [[ -f "$project_config_path" ]]; then
    local project_config
    project_config=$(cat "$project_config_path")
    merged=$(sg_merge_project_config "$merged" "$project_config")
  fi

  echo "$merged"
}

sg_merge_configs() {
  local base="$1" override="$2"
  # For global config: simple deep merge (override replaces)
  echo "$base" "$override" | jq -s '.[0] * .[1]'
}

sg_merge_project_config() {
  local base="$1" project="$2"
  # Project merge: arrays append (union), scalars replace, objects deep merge
  echo "$base" "$project" | jq -s '
    def merge_project(base; proj):
      base as $b | proj as $p |
      ($b | keys) + ($p | keys) | unique | map(. as $k |
        if ($p | has($k) | not) then {($k): $b[$k]}
        elif ($b | has($k) | not) then {($k): $p[$k]}
        elif ($b[$k] | type) == "array" and ($p[$k] | type) == "array" then
          {($k): ($b[$k] + $p[$k] | unique)}
        elif ($b[$k] | type) == "object" and ($p[$k] | type) == "object" then
          {($k): merge_project($b[$k]; $p[$k])}
        else
          {($k): $p[$k]}
        end
      ) | add // {};
    merge_project(.[0]; .[1])
  '
}

sg_get_active_pii_patterns() {
  local config="$1"
  local plugin_root="$2"

  local pii_enabled
  pii_enabled=$(echo "$config" | jq -r '.pii.enabled')
  if [[ "$pii_enabled" != "true" ]]; then
    echo "[]"
    return
  fi

  local disabled_ids
  disabled_ids=$(echo "$config" | jq -c '.pii.disabled // []')

  local custom_patterns
  custom_patterns=$(echo "$config" | jq -c '.pii.custom // []')

  local default_patterns
  default_patterns=$(cat "$plugin_root/config/default-pii-patterns.json")

  # Filter: pattern is active if enabled=true (or enabled not set) AND id not in disabled list
  local active
  active=$(echo "$default_patterns" "$disabled_ids" | jq -s '
    .[0] as $patterns | .[1] as $disabled |
    [$patterns[] | select(
      (.enabled // true) and
      (.id as $id | $disabled | map(select(. == $id)) | length == 0)
    )]
  ')

  # Append custom patterns
  echo "$active" "$custom_patterns" | jq -s '.[0] + .[1]'
}

sg_is_tool_inspected() {
  local config="$1" tool_name="$2"
  echo "$config" | jq -r --arg tool "$tool_name" '.tools | map(select(. == $tool)) | length > 0'
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
bash sensitive-guard/tests/test-config.sh
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add sensitive-guard/config/ sensitive-guard/src/config.sh sensitive-guard/tests/test-config.sh sensitive-guard/tests/fixtures/
git commit -m "feat(sensitive-guard): add config loading with merge strategy"
```

---

## Chunk 2: Detection engines (PII detector, gitleaks runner)

### Task 4: PII detector

**Files:**
- Create: `sensitive-guard/src/pii-detector.sh`
- Create: `sensitive-guard/tests/test-pii-detector.sh`
- Create: `sensitive-guard/tests/fixtures/pii-file.txt`
- Create: `sensitive-guard/tests/fixtures/clean-file.txt`

- [ ] **Step 1: Create test fixtures**

Create `tests/fixtures/pii-file.txt`:
```
# Config file with PII
admin_email=admin@example.com
backup_contact=john.doe@company.org
ssn=123-45-6789
payment_card=4532-1234-5678-8901
iban=DE89370400440532013000
safe_value=hello-world
version=1.2.3.4
```

Create `tests/fixtures/clean-file.txt`:
```
# Just a normal config
app_name=my-service
port=8080
debug=true
log_level=info
```

- [ ] **Step 2: Write failing test**

Create `tests/test-pii-detector.sh`:
```bash
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

# Test: ipv4 is NOT detected (disabled by default)
test_start "ipv4 not detected when disabled"
FINDINGS=$(sg_detect_pii "$FIXTURES/pii-file.txt" "$PATTERNS")
IPV4=$(echo "$FINDINGS" | jq '[.[] | select(.type == "ipv4")] | length')
assert_equals "0" "$IPV4" "ipv4 should not be detected"

test_summary
```

- [ ] **Step 3: Run test to verify it fails**

```bash
bash sensitive-guard/tests/test-pii-detector.sh
```

Expected: FAIL (pii-detector.sh not found)

- [ ] **Step 4: Write pii-detector.sh implementation**

Create `src/pii-detector.sh`:
```bash
#!/bin/bash
# PII detection using regex patterns
# Outputs JSON array of findings

sg_detect_pii() {
  local file_path="$1"
  local patterns_json="$2"

  # Return empty if file doesn't exist or is binary
  if [[ ! -f "$file_path" ]]; then
    echo "[]"
    return
  fi
  if sg_is_binary "$file_path"; then
    echo "[]"
    return
  fi

  local findings="[]"
  local line_num=0
  local start_time=$SECONDS

  while IFS= read -r line || [[ -n "$line" ]]; do
    # 5s timeout for large files
    if (( SECONDS - start_time > 5 )); then
      sg_log_warn "PII scan timeout after 5s on $file_path — treating as clean"
      break
    fi
    line_num=$((line_num + 1))

    # Test each pattern against this line
    while IFS= read -r pattern_entry; do
      local pid pregex
      pid=$(echo "$pattern_entry" | jq -r '.id')
      pregex=$(echo "$pattern_entry" | jq -r '.regex')

      # Use grep -oP for PCRE matching
      local matches
      if matches=$(echo "$line" | grep -oP "$pregex" 2>/dev/null); then
        while IFS= read -r match; do
          findings=$(echo "$findings" | jq \
            --arg type "$pid" \
            --arg value "$match" \
            --arg file "$file_path" \
            --argjson line "$line_num" \
            --arg engine "pii" \
            '. + [{type: $type, value: $value, file: $file, line: $line, engine: $engine}]')
        done <<< "$matches"
      fi
    done < <(echo "$patterns_json" | jq -c '.[]')
  done < "$file_path"

  echo "$findings"
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
bash sensitive-guard/tests/test-pii-detector.sh
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add sensitive-guard/src/pii-detector.sh sensitive-guard/tests/test-pii-detector.sh sensitive-guard/tests/fixtures/pii-file.txt sensitive-guard/tests/fixtures/clean-file.txt
git commit -m "feat(sensitive-guard): add PII detector with regex patterns"
```

---

### Task 5: Gitleaks runner

**Files:**
- Create: `sensitive-guard/src/gitleaks-runner.sh`
- Create: `sensitive-guard/tests/test-gitleaks-runner.sh`
- Create: `sensitive-guard/tests/fixtures/secret-file.env`

- [ ] **Step 1: Create test fixture with known secrets**

Create `tests/fixtures/secret-file.env`:
```
# Test secrets file
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef12
DATABASE_URL=postgresql://user:password@localhost/db
SAFE_VALUE=hello-world
```

- [ ] **Step 2: Write failing test**

Create `tests/test-gitleaks-runner.sh`:
```bash
#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test-utils.sh"
source "$SCRIPT_DIR/../src/utils.sh"
source "$SCRIPT_DIR/../src/gitleaks-runner.sh"

FIXTURES="$SCRIPT_DIR/fixtures"

# Test: check if gitleaks is available (skip tests if not)
if ! command -v gitleaks &>/dev/null; then
  echo "SKIP: gitleaks not installed"
  exit 0
fi

# Test: detect secrets in file
test_start "detects AWS keys in secret file"
FINDINGS=$(sg_run_gitleaks "$FIXTURES/secret-file.env" "")
COUNT=$(echo "$FINDINGS" | jq 'length')
# gitleaks should find at least AWS keys and GitHub token
test_start "finds multiple secrets"
[[ "$COUNT" -ge 2 ]] && test_pass || test_fail "expected >=2 findings, got $COUNT"

# Test: finding structure
test_start "findings have required fields"
FIRST=$(echo "$FINDINGS" | jq '.[0]')
HAS_TYPE=$(echo "$FIRST" | jq 'has("type")')
assert_equals "true" "$HAS_TYPE" "should have type"
HAS_VALUE=$(echo "$FIRST" | jq 'has("value")')
assert_equals "true" "$HAS_VALUE" "should have value"
HAS_FILE=$(echo "$FIRST" | jq 'has("file")')
assert_equals "true" "$HAS_FILE" "should have file"
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
```

- [ ] **Step 3: Run test to verify it fails**

```bash
bash sensitive-guard/tests/test-gitleaks-runner.sh
```

Expected: FAIL (gitleaks-runner.sh not found)

- [ ] **Step 4: Write gitleaks-runner.sh implementation**

Create `src/gitleaks-runner.sh`:
```bash
#!/bin/bash
# Gitleaks wrapper — runs gitleaks and normalizes output to standard finding format

SG_GITLEAKS_WARNED=""

sg_check_gitleaks() {
  if command -v gitleaks &>/dev/null; then
    return 0
  fi

  # Show warning once per session (via temp marker file)
  local marker="/tmp/sensitive-guard-gitleaks-warned-${USER:-unknown}"
  if [[ ! -f "$marker" ]]; then
    sg_log_warn "gitleaks not found in PATH. Secret detection disabled."
    sg_log_warn "Install: brew install gitleaks (macOS) | go install github.com/gitleaks/gitleaks/v8@latest"
    touch "$marker"
  fi
  return 1
}

sg_run_gitleaks() {
  local file_path="$1"
  local config_path="$2"  # optional custom .gitleaks.toml

  # Return empty if file doesn't exist
  if [[ ! -f "$file_path" ]]; then
    echo "[]"
    return
  fi

  # Check gitleaks availability
  if ! sg_check_gitleaks; then
    echo "[]"
    return
  fi

  # Build gitleaks command
  # Use --source with parent dir + --include to target specific file
  local source_dir file_name
  source_dir=$(dirname "$file_path")
  file_name=$(basename "$file_path")

  local cmd=(gitleaks detect --no-git -f json --source="$source_dir" --include="$file_name")
  if [[ -n "$config_path" && -f "$config_path" ]]; then
    cmd+=(--config="$config_path")
  fi

  # Run gitleaks, capture JSON output
  local raw_output
  raw_output=$("${cmd[@]}" 2>/dev/null) || true

  # If empty or not valid JSON, return empty
  if [[ -z "$raw_output" ]] || ! echo "$raw_output" | jq '.' &>/dev/null; then
    echo "[]"
    return
  fi

  # Normalize gitleaks output to standard finding format
  echo "$raw_output" | jq --arg file "$file_path" '
    [.[] | {
      type: .RuleID,
      value: .Secret,
      file: $file,
      line: .StartLine,
      engine: "gitleaks"
    }]
  '
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
bash sensitive-guard/tests/test-gitleaks-runner.sh
```

Expected: All PASS (or SKIP if gitleaks not installed)

- [ ] **Step 6: Commit**

```bash
git add sensitive-guard/src/gitleaks-runner.sh sensitive-guard/tests/test-gitleaks-runner.sh sensitive-guard/tests/fixtures/secret-file.env
git commit -m "feat(sensitive-guard): add gitleaks runner with normalized output"
```

---

## Chunk 3: Allowlist and Bash parser

### Task 6: Allowlist management

**Files:**
- Create: `sensitive-guard/src/allowlist.sh`
- Create: `sensitive-guard/tests/test-allowlist.sh`
- Create: `sensitive-guard/tests/fixtures/sample-allowlist.json`

- [ ] **Step 1: Create test fixture**

Create `tests/fixtures/sample-allowlist.json`:
```json
{
  "exact": [
    { "value": "sha256:b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9", "type": "email", "note": "test value", "added": "2026-03-10" }
  ],
  "patterns": [
    { "regex": ".*@example\\.com", "type": "email", "note": "example domain" }
  ]
}
```

Note: The sha256 hash above is for the string "hello world".

- [ ] **Step 2: Write failing test**

Create `tests/test-allowlist.sh`:
```bash
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
```

- [ ] **Step 3: Run test to verify it fails**

```bash
bash sensitive-guard/tests/test-allowlist.sh
```

Expected: FAIL

- [ ] **Step 4: Write allowlist.sh implementation**

Create `src/allowlist.sh`:
```bash
#!/bin/bash
# Allowlist management — read/write/check allowlists with SHA-256 hashing

sg_load_allowlist() {
  local path="$1"
  if [[ -f "$path" ]]; then
    cat "$path"
  else
    echo '{"exact":[],"patterns":[]}'
  fi
}

sg_is_allowed() {
  local allowlist_json="$1"
  local value="$2"
  local type="$3"

  # Check exact hash match
  local hash
  hash="sha256:$(sg_sha256 "$value")"

  local exact_match
  exact_match=$(echo "$allowlist_json" | jq -r --arg hash "$hash" \
    '[.exact[] | select(.value == $hash)] | length > 0')

  if [[ "$exact_match" == "true" ]]; then
    echo "true"
    return
  fi

  # Check pattern match
  local pattern_match="false"
  while IFS= read -r pattern_entry; do
    local regex
    regex=$(echo "$pattern_entry" | jq -r '.regex')
    if echo "$value" | grep -qP "$regex" 2>/dev/null; then
      pattern_match="true"
      break
    fi
  done < <(echo "$allowlist_json" | jq -c '.patterns[]' 2>/dev/null)

  echo "$pattern_match"
}

sg_add_to_allowlist() {
  local path="$1"
  local entry_type="$2"  # "exact" or "pattern"
  local value="$3"
  local finding_type="$4"
  local note="${5:-}"

  local allowlist
  allowlist=$(sg_load_allowlist "$path")

  local today
  today=$(date +%Y-%m-%d)

  if [[ "$entry_type" == "exact" ]]; then
    local hash="sha256:$(sg_sha256 "$value")"
    allowlist=$(echo "$allowlist" | jq \
      --arg hash "$hash" \
      --arg type "$finding_type" \
      --arg note "$note" \
      --arg added "$today" \
      '.exact += [{"value": $hash, "type": $type, "note": $note, "added": $added}]')
  else
    allowlist=$(echo "$allowlist" | jq \
      --arg regex "$value" \
      --arg type "$finding_type" \
      --arg note "$note" \
      --arg added "$today" \
      '.patterns += [{"regex": $regex, "type": $type, "note": $note, "added": $added}]')
  fi

  # Ensure parent directory exists
  mkdir -p "$(dirname "$path")"
  echo "$allowlist" | jq '.' > "$path"
}

sg_filter_findings() {
  local findings_json="$1"
  local project_allowlist_path="$2"
  local global_allowlist_path="$3"

  local project_al global_al
  project_al=$(sg_load_allowlist "$project_allowlist_path")
  global_al=$(sg_load_allowlist "$global_allowlist_path")

  local filtered="[]"

  while IFS= read -r finding; do
    local value type
    value=$(echo "$finding" | jq -r '.value')
    type=$(echo "$finding" | jq -r '.type')

    # Check project allowlist first, then global
    local allowed
    allowed=$(sg_is_allowed "$project_al" "$value" "$type")
    if [[ "$allowed" != "true" ]]; then
      allowed=$(sg_is_allowed "$global_al" "$value" "$type")
    fi

    if [[ "$allowed" != "true" ]]; then
      filtered=$(echo "$filtered" | jq --argjson f "$finding" '. + [$f]')
    fi
  done < <(echo "$findings_json" | jq -c '.[]')

  echo "$filtered"
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
bash sensitive-guard/tests/test-allowlist.sh
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add sensitive-guard/src/allowlist.sh sensitive-guard/tests/test-allowlist.sh sensitive-guard/tests/fixtures/sample-allowlist.json
git commit -m "feat(sensitive-guard): add allowlist management with SHA-256 hashing"
```

---

### Task 7: Bash command parser

**Files:**
- Create: `sensitive-guard/src/bash-parser.sh`
- Create: `sensitive-guard/tests/test-bash-parser.sh`

- [ ] **Step 1: Write failing test**

Create `tests/test-bash-parser.sh`:
```bash
#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test-utils.sh"
source "$SCRIPT_DIR/../src/utils.sh"
source "$SCRIPT_DIR/../src/bash-parser.sh"

# Test: extract from cat command
test_start "extracts file from 'cat file.txt'"
FILES=$(sg_extract_files_from_bash "cat /etc/hosts")
assert_contains "$FILES" "/etc/hosts"

# Test: extract from head/tail
test_start "extracts file from 'head -n 10 file'"
FILES=$(sg_extract_files_from_bash "head -n 10 /tmp/data.csv")
assert_contains "$FILES" "/tmp/data.csv"

test_start "extracts file from 'tail -f log'"
FILES=$(sg_extract_files_from_bash "tail -f /var/log/app.log")
assert_contains "$FILES" "/var/log/app.log"

# Test: extract from less
test_start "extracts file from 'less file'"
FILES=$(sg_extract_files_from_bash "less /home/user/.env")
assert_contains "$FILES" "/home/user/.env"

# Test: extract from source / dot command
test_start "extracts file from 'source file'"
FILES=$(sg_extract_files_from_bash "source /home/user/.bashrc")
assert_contains "$FILES" "/home/user/.bashrc"

test_start "extracts file from '. file'"
FILES=$(sg_extract_files_from_bash ". /home/user/.profile")
assert_contains "$FILES" "/home/user/.profile"

# Test: input redirection
test_start "extracts file from '< file'"
FILES=$(sg_extract_files_from_bash "wc -l < /tmp/data.txt")
assert_contains "$FILES" "/tmp/data.txt"

# Test: chained commands
test_start "extracts files from chained commands (&&)"
FILES=$(sg_extract_files_from_bash "cat /tmp/a.txt && cat /tmp/b.txt")
assert_contains "$FILES" "/tmp/a.txt"
assert_contains "$FILES" "/tmp/b.txt"

test_start "extracts files from chained commands (;)"
FILES=$(sg_extract_files_from_bash "cat /tmp/a.txt; head /tmp/b.txt")
assert_contains "$FILES" "/tmp/a.txt"
assert_contains "$FILES" "/tmp/b.txt"

# Test: ~ expansion
test_start "expands ~ to HOME"
FILES=$(sg_extract_files_from_bash "cat ~/.env")
assert_contains "$FILES" "$HOME/.env"

# Test: $HOME expansion
test_start "expands \$HOME"
FILES=$(sg_extract_files_from_bash 'cat $HOME/.env')
assert_contains "$FILES" "$HOME/.env"

# Test: dynamic variables are skipped
test_start "skips unresolvable variables"
FILES=$(sg_extract_files_from_bash 'cat "$SOME_VAR/file.txt"')
[[ -z "$FILES" ]] && test_pass || test_fail "should return empty for dynamic vars"

# Test: piped commands don't extract
test_start "skips piped output (curl | jq)"
FILES=$(sg_extract_files_from_bash "curl https://example.com | jq '.'")
assert_not_contains "$FILES" "https://example.com" "URLs not extracted"

# Test: empty/no files
test_start "returns empty for command with no files"
FILES=$(sg_extract_files_from_bash "echo hello")
[[ -z "$FILES" ]] && test_pass || test_fail "should return empty"

test_summary
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bash sensitive-guard/tests/test-bash-parser.sh
```

Expected: FAIL

- [ ] **Step 3: Write bash-parser.sh implementation**

Create `src/bash-parser.sh`:
```bash
#!/bin/bash
# Best-effort file path extraction from Bash commands
# Recognized: cat, less, head, tail, source, ., grep, input redirection
# Expands: ~, $HOME, $PWD
# Skips: dynamic variables, piped output, subshells

sg_extract_files_from_bash() {
  local command="$1"
  local files=""

  # Split on && and ; to handle chained commands
  local segments
  segments=$(echo "$command" | sed 's/&&/\n/g; s/;/\n/g')

  while IFS= read -r segment; do
    # Skip empty segments
    [[ -z "${segment// /}" ]] && continue

    # Extract files from each segment
    local extracted
    extracted=$(sg_extract_from_segment "$segment")
    if [[ -n "$extracted" ]]; then
      files="${files:+$files$'\n'}$extracted"
    fi
  done <<< "$segments"

  echo "$files"
}

sg_extract_from_segment() {
  local segment="$1"
  segment="$(echo "$segment" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

  local files=""

  # Input redirection: < file
  local redir_file
  if redir_file=$(echo "$segment" | grep -oP '<\s*\K[^\s|&;]+' 2>/dev/null); then
    local resolved
    resolved=$(sg_resolve_extracted_path "$redir_file")
    [[ -n "$resolved" ]] && files="${files:+$files$'\n'}$resolved"
  fi

  # Commands that take file arguments: cat, less, head, tail, source, .
  # Pattern: command [flags] file [file...]
  local cmd_word
  cmd_word=$(echo "$segment" | awk '{print $1}')

  case "$cmd_word" in
    cat|less|more)
      # Extract all non-flag arguments
      local args
      args=$(echo "$segment" | awk '{for(i=2;i<=NF;i++) if(substr($i,1,1)!="-") print $i}')
      while IFS= read -r arg; do
        [[ -z "$arg" ]] && continue
        local resolved
        resolved=$(sg_resolve_extracted_path "$arg")
        [[ -n "$resolved" ]] && files="${files:+$files$'\n'}$resolved"
      done <<< "$args"
      ;;
    head|tail)
      # Skip flags like -n 10 -f, take last non-flag arg
      local last_arg
      last_arg=$(echo "$segment" | awk '{
        skip_next=0
        last=""
        for(i=2;i<=NF;i++) {
          if(skip_next) { skip_next=0; continue }
          if($i ~ /^-/) { if($i ~ /^-[ncq]$/) skip_next=1; continue }
          last=$i
        }
        print last
      }')
      if [[ -n "$last_arg" ]]; then
        local resolved
        resolved=$(sg_resolve_extracted_path "$last_arg")
        [[ -n "$resolved" ]] && files="${files:+$files$'\n'}$resolved"
      fi
      ;;
    source|.)
      # source file or . file
      local file_arg
      file_arg=$(echo "$segment" | awk '{print $2}')
      if [[ -n "$file_arg" ]]; then
        local resolved
        resolved=$(sg_resolve_extracted_path "$file_arg")
        [[ -n "$resolved" ]] && files="${files:+$files$'\n'}$resolved"
      fi
      ;;
    grep|rg)
      # grep [flags] pattern file — last arg if not a flag
      local last_arg
      last_arg=$(echo "$segment" | awk '{print $NF}')
      if [[ "$last_arg" != "$cmd_word" && "${last_arg:0:1}" != "-" ]]; then
        # Skip if it looks like just a pattern (no path separators)
        if [[ "$last_arg" == */* || "$last_arg" == *.* ]]; then
          local resolved
          resolved=$(sg_resolve_extracted_path "$last_arg")
          [[ -n "$resolved" ]] && files="${files:+$files$'\n'}$resolved"
        fi
      fi
      ;;
  esac

  echo "$files"
}

sg_resolve_extracted_path() {
  local path="$1"

  # Remove surrounding quotes
  path="${path%\"}"
  path="${path#\"}"
  path="${path%\'}"
  path="${path#\'}"

  # Skip if contains unresolvable variables
  if echo "$path" | grep -qP '\$(?!HOME|PWD)[A-Za-z_]' 2>/dev/null; then
    return
  fi

  # Expand ~ and known variables
  path=$(sg_resolve_path "$path")

  echo "$path"
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bash sensitive-guard/tests/test-bash-parser.sh
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add sensitive-guard/src/bash-parser.sh sensitive-guard/tests/test-bash-parser.sh
git commit -m "feat(sensitive-guard): add Bash command file path extractor"
```

---

## Chunk 4: Interactive prompt and scanner orchestrator

### Task 8: Interactive prompt

**Files:**
- Create: `sensitive-guard/src/prompt.sh`
- Create: `sensitive-guard/tests/test-prompt.sh`

- [ ] **Step 1: Write failing test**

Create `tests/test-prompt.sh`:
```bash
#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test-utils.sh"
source "$SCRIPT_DIR/../src/utils.sh"
source "$SCRIPT_DIR/../src/prompt.sh"

# Test: format_findings_display
test_start "format_findings_display shows truncated values"
FINDINGS='[
  {"type":"aws-access-key","value":"AKIAIOSFODNN7EXAMPLE","file":"/app/.env","line":3,"engine":"gitleaks"},
  {"type":"email","value":"admin@example.com","file":"/app/.env","line":5,"engine":"pii"}
]'
OUTPUT=$(sg_format_findings_display "$FINDINGS" 8)
assert_contains "$OUTPUT" "aws-access-key" "should show type"
assert_contains "$OUTPUT" "line 3" "should show line number"
assert_contains "$OUTPUT" "email" "should show email type"
assert_not_contains "$OUTPUT" "AKIAIOSFODNN7EXAMPLE" "should NOT show full key"

# Test: non-interactive mode returns block
test_start "non-interactive mode returns all-block"
ACTIONS=$(echo "" | sg_collect_actions "$FINDINGS" 8 </dev/null 2>/dev/null || true)
# In non-interactive mode, all items should be blocked
# We test this by checking the function detects non-TTY

test_summary
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bash sensitive-guard/tests/test-prompt.sh
```

Expected: FAIL

- [ ] **Step 3: Write prompt.sh implementation**

Create `src/prompt.sh`:
```bash
#!/bin/bash
# Interactive prompt for sensitive-guard findings
# Outputs to stderr (prompt), reads from stdin (user input)
# Returns JSON array of {index, action} pairs

sg_format_findings_display() {
  local findings_json="$1"
  local max_preview="${2:-12}"

  local count
  count=$(echo "$findings_json" | jq 'length')

  local files
  files=$(echo "$findings_json" | jq -r '[.[].file] | unique | join(", ")')

  local output=""
  output+="$(printf '\n  \033[1;33m⚠ sensitive-guard: %d finding(s) in %s\033[0m\n\n' "$count" "$files")"

  local i=0
  while IFS= read -r finding; do
    i=$((i + 1))
    local type value line
    type=$(echo "$finding" | jq -r '.type')
    value=$(echo "$finding" | jq -r '.value')
    line=$(echo "$finding" | jq -r '.line')

    local preview
    preview=$(sg_truncate_value "$value" "$max_preview")

    output+="$(printf '  %d. [%s] %s  (line %s)\n' "$i" "$type" "$preview" "$line")"
  done < <(echo "$findings_json" | jq -c '.[]')

  echo "$output"
}

sg_collect_actions() {
  local findings_json="$1"
  local max_preview="${2:-12}"

  local count
  count=$(echo "$findings_json" | jq 'length')

  # Check if stdin is a TTY
  if [[ ! -t 0 ]]; then
    # Non-interactive mode: block all
    local actions="[]"
    for ((i=0; i<count; i++)); do
      actions=$(echo "$actions" | jq --argjson idx "$i" '. + [{"index": $idx, "action": "block"}]')
    done
    echo "$actions"
    return
  fi

  # Show findings
  sg_format_findings_display "$findings_json" "$max_preview" >&2

  echo "" >&2
  echo "  Action per item: [p]ass once  [a]llow project  [g]lobal allow  [b]lock" >&2

  local actions="[]"
  for ((i=0; i<count; i++)); do
    local idx=$((i + 1))
    local action=""
    while [[ -z "$action" ]]; do
      printf '  (%d): ' "$idx" >&2
      read -r input
      case "${input,,}" in
        p) action="pass" ;;
        a) action="allow_project" ;;
        g) action="allow_global" ;;
        b) action="block" ;;
        *) echo "  Invalid choice. Use p/a/g/b" >&2 ;;
      esac
    done
    actions=$(echo "$actions" | jq --argjson idx "$i" --arg act "$action" \
      '. + [{"index": $idx, "action": $act}]')
  done

  echo "$actions"
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bash sensitive-guard/tests/test-prompt.sh
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add sensitive-guard/src/prompt.sh sensitive-guard/tests/test-prompt.sh
git commit -m "feat(sensitive-guard): add interactive prompt for findings"
```

---

### Task 9: Scanner orchestrator

**Files:**
- Create: `sensitive-guard/src/scanner.sh`
- Create: `sensitive-guard/tests/test-scanner.sh`

- [ ] **Step 1: Write failing test**

Create `tests/test-scanner.sh`:
```bash
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
source "$SCRIPT_DIR/../src/scanner.sh"

FIXTURES="$SCRIPT_DIR/fixtures"
PLUGIN_ROOT="$SCRIPT_DIR/.."

# Test: scan_file returns merged findings from both engines
test_start "scan_file detects PII in file"
CONFIG=$(sg_load_config "/nonexistent" "/nonexistent" "$PLUGIN_ROOT")
FINDINGS=$(sg_scan_file "$FIXTURES/pii-file.txt" "$CONFIG" "$PLUGIN_ROOT")
COUNT=$(echo "$FINDINGS" | jq 'length')
# Should find email, ssn, credit_card, iban at minimum
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
test_start "extract_target_files skips Grep with directory"
TOOL_INPUT='{"path":"/tmp/","pattern":"secret"}'
FILES=$(sg_extract_target_files "Grep" "$TOOL_INPUT")
[[ -z "$FILES" ]] && test_pass || test_fail "should skip directory"

test_summary
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bash sensitive-guard/tests/test-scanner.sh
```

Expected: FAIL

- [ ] **Step 3: Write scanner.sh implementation**

Create `src/scanner.sh`:
```bash
#!/bin/bash
# Scanner orchestrator — ties detection engines, allowlist, and file extraction together

sg_extract_target_files() {
  local tool_name="$1"
  local tool_input_json="$2"

  case "$tool_name" in
    Read)
      echo "$tool_input_json" | jq -r '.file_path // empty'
      ;;
    Grep)
      local path
      path=$(echo "$tool_input_json" | jq -r '.path // empty')
      # Skip if path is a directory (ends with / or is a directory)
      if [[ -n "$path" && ! "$path" =~ /$ ]] && [[ -f "$path" || ! -d "$path" ]]; then
        echo "$path"
      fi
      ;;
    Bash)
      local command
      command=$(echo "$tool_input_json" | jq -r '.command // empty')
      if [[ -n "$command" ]]; then
        sg_extract_files_from_bash "$command"
      fi
      ;;
  esac
}

sg_scan_file() {
  local file_path="$1"
  local config="$2"
  local plugin_root="$3"

  local all_findings="[]"

  # Run PII detection if enabled
  local pii_enabled
  pii_enabled=$(echo "$config" | jq -r '.pii.enabled')
  if [[ "$pii_enabled" == "true" ]]; then
    local patterns
    patterns=$(sg_get_active_pii_patterns "$config" "$plugin_root")
    local pii_findings
    pii_findings=$(sg_detect_pii "$file_path" "$patterns")
    all_findings=$(echo "$all_findings" "$pii_findings" | jq -s '.[0] + .[1]')
  fi

  # Run gitleaks if enabled
  local gitleaks_enabled
  gitleaks_enabled=$(echo "$config" | jq -r '.gitleaks.enabled')
  if [[ "$gitleaks_enabled" == "true" ]]; then
    local gitleaks_config
    gitleaks_config=$(echo "$config" | jq -r '.gitleaks.configPath // empty')
    local gitleaks_findings
    gitleaks_findings=$(sg_run_gitleaks "$file_path" "$gitleaks_config")
    all_findings=$(echo "$all_findings" "$gitleaks_findings" | jq -s '.[0] + .[1]')
  fi

  # Deduplicate by value+line (same secret caught by both engines)
  all_findings=$(echo "$all_findings" | jq '[group_by(.value + (.line | tostring)) | .[] | .[0]]')

  echo "$all_findings"
}

sg_scan_and_prompt() {
  local tool_name="$1"
  local tool_input_json="$2"
  local config="$3"
  local plugin_root="$4"
  local project_allowlist_path="$5"
  local global_allowlist_path="$6"

  # Check if tool should be inspected
  local should_inspect
  should_inspect=$(sg_is_tool_inspected "$config" "$tool_name")
  if [[ "$should_inspect" != "true" ]]; then
    return 0  # Allow
  fi

  # Extract target files
  local files
  files=$(sg_extract_target_files "$tool_name" "$tool_input_json")

  if [[ -z "$files" ]]; then
    return 0  # No files to scan, allow
  fi

  # Scan each file and collect all findings
  local all_findings="[]"
  while IFS= read -r file_path; do
    [[ -z "$file_path" ]] && continue
    # Resolve path
    file_path=$(sg_resolve_path "$file_path")
    # Only scan existing files
    if [[ -f "$file_path" ]]; then
      local file_findings
      file_findings=$(sg_scan_file "$file_path" "$config" "$plugin_root")
      all_findings=$(echo "$all_findings" "$file_findings" | jq -s '.[0] + .[1]')
    fi
  done <<< "$files"

  # Filter against allowlists
  local filtered
  filtered=$(sg_filter_findings "$all_findings" "$project_allowlist_path" "$global_allowlist_path")

  local count
  count=$(echo "$filtered" | jq 'length')

  if [[ "$count" -eq 0 ]]; then
    return 0  # All findings allowed, proceed
  fi

  # Prompt user for actions
  local max_preview
  max_preview=$(echo "$config" | jq -r '.display.maxValuePreview // 12')

  local actions
  actions=$(sg_collect_actions "$filtered" "$max_preview")

  # Process actions
  local has_block=false
  while IFS= read -r action_entry; do
    local idx action
    idx=$(echo "$action_entry" | jq -r '.index')
    action=$(echo "$action_entry" | jq -r '.action')

    local finding
    finding=$(echo "$filtered" | jq ".[$idx]")
    local value type
    value=$(echo "$finding" | jq -r '.value')
    type=$(echo "$finding" | jq -r '.type')

    case "$action" in
      allow_project)
        sg_add_to_allowlist "$project_allowlist_path" "exact" "$value" "$type" "approved by user"
        ;;
      allow_global)
        sg_add_to_allowlist "$global_allowlist_path" "exact" "$value" "$type" "approved by user"
        ;;
      block)
        has_block=true
        ;;
      pass)
        # One-time pass, do nothing
        ;;
    esac
  done < <(echo "$actions" | jq -c '.[]')

  if [[ "$has_block" == "true" ]]; then
    sg_log_error "Tool call blocked: sensitive data detected"
    return 2  # Block
  fi

  return 0  # Allow
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bash sensitive-guard/tests/test-scanner.sh
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add sensitive-guard/src/scanner.sh sensitive-guard/tests/test-scanner.sh
git commit -m "feat(sensitive-guard): add scanner orchestrator"
```

---

## Chunk 5: Hook entry point and plugin manifest

### Task 10: PreToolUse hook entry point

**Files:**
- Create: `sensitive-guard/hooks/pre-tool-use.sh`

- [ ] **Step 1: Write the hook script**

Create `hooks/pre-tool-use.sh`:
```bash
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
```

- [ ] **Step 2: Make executable**

```bash
chmod +x sensitive-guard/hooks/pre-tool-use.sh
```

- [ ] **Step 3: Commit**

```bash
git add sensitive-guard/hooks/pre-tool-use.sh
git commit -m "feat(sensitive-guard): add PreToolUse hook entry point"
```

---

### Task 11: Plugin manifest and hook registration

**Files:**
- Create: `sensitive-guard/.claude-plugin/plugin.json`
- Create: `sensitive-guard/hooks/hooks.json`

- [ ] **Step 1: Create plugin.json**

Create `.claude-plugin/plugin.json`:
```json
{
  "name": "sensitive-guard",
  "version": "0.1.0",
  "description": "Prevents sensitive data (secrets, PII) from reaching AI servers by scanning files before they are read into conversation"
}
```

- [ ] **Step 2: Create hooks.json**

Create `hooks/hooks.json`:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read|Grep|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/pre-tool-use.sh"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add sensitive-guard/.claude-plugin/plugin.json sensitive-guard/hooks/hooks.json
git commit -m "feat(sensitive-guard): add plugin manifest and hook registration"
```

---

### Task 12: Integration test

**Files:**
- Create: `sensitive-guard/tests/test-integration.sh`

- [ ] **Step 1: Write integration test**

Create `tests/test-integration.sh`:
```bash
#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$SCRIPT_DIR/.."
source "$SCRIPT_DIR/test-utils.sh"

FIXTURES="$SCRIPT_DIR/fixtures"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# Test: hook allows clean file (simulated stdin)
test_start "hook allows Read of clean file"
HOOK_INPUT=$(jq -n \
  --arg tool "Read" \
  --arg file "$FIXTURES/clean-file.txt" \
  --arg cwd "$TMP_DIR" \
  '{tool_name: $tool, tool_input: {file_path: $file}, cwd: $cwd}')
echo "$HOOK_INPUT" | bash "$PLUGIN_ROOT/hooks/pre-tool-use.sh"
EXIT_CODE=$?
assert_exit_code "0" "$EXIT_CODE" "clean file should be allowed"

# Test: hook allows uninspected tool
test_start "hook allows uninspected tool (Write)"
HOOK_INPUT=$(jq -n \
  --arg tool "Write" \
  --arg file "/tmp/out.txt" \
  --arg cwd "$TMP_DIR" \
  '{tool_name: $tool, tool_input: {file_path: $file}, cwd: $cwd}')
echo "$HOOK_INPUT" | bash "$PLUGIN_ROOT/hooks/pre-tool-use.sh"
EXIT_CODE=$?
assert_exit_code "0" "$EXIT_CODE" "Write should not be inspected"

# Test: hook blocks file with PII in non-interactive mode (stdin is not TTY)
test_start "hook blocks PII file in non-interactive mode"
HOOK_INPUT=$(jq -n \
  --arg tool "Read" \
  --arg file "$FIXTURES/pii-file.txt" \
  --arg cwd "$TMP_DIR" \
  '{tool_name: $tool, tool_input: {file_path: $file}, cwd: $cwd}')
echo "$HOOK_INPUT" | bash "$PLUGIN_ROOT/hooks/pre-tool-use.sh" 2>/dev/null
EXIT_CODE=$?
assert_exit_code "2" "$EXIT_CODE" "PII file should be blocked in non-interactive"

# Test: hook allows file with all findings in allowlist
test_start "hook allows file when all findings are allowlisted"
# Create an allowlist that allows the email in pii-file.txt
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
echo "$HOOK_INPUT" | bash "$PLUGIN_ROOT/hooks/pre-tool-use.sh" 2>/dev/null
EXIT_CODE=$?
assert_exit_code "0" "$EXIT_CODE" "all-allowlisted file should pass"

# Test: hook handles Bash tool
test_start "hook handles Bash tool with file reference"
HOOK_INPUT=$(jq -n \
  --arg tool "Bash" \
  --arg cmd "cat $FIXTURES/pii-file.txt" \
  --arg cwd "$TMP_DIR" \
  '{tool_name: $tool, tool_input: {command: $cmd}, cwd: $cwd}')
echo "$HOOK_INPUT" | bash "$PLUGIN_ROOT/hooks/pre-tool-use.sh" 2>/dev/null
EXIT_CODE=$?
assert_exit_code "2" "$EXIT_CODE" "Bash reading PII file should be blocked"

# Test: run all unit tests
test_start "all unit tests pass"
bash "$SCRIPT_DIR/run-tests.sh" >/dev/null 2>&1
EXIT_CODE=$?
assert_exit_code "0" "$EXIT_CODE" "unit test suite"

test_summary
```

- [ ] **Step 2: Run integration test**

```bash
bash sensitive-guard/tests/test-integration.sh
```

Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add sensitive-guard/tests/test-integration.sh
git commit -m "test(sensitive-guard): add integration tests"
```

---

### Task 13: Final cleanup and README

**Files:**
- Create: `sensitive-guard/README.md`

- [ ] **Step 1: Write README with installation and usage instructions**

Create `sensitive-guard/README.md` with:
- One-line description
- Installation: `claude plugin add /path/to/sensitive-guard`
- Prerequisites: `jq` (required), `gitleaks` (optional but recommended)
- Configuration section (reference config structure from spec)
- Allowlist management
- Supported tools

- [ ] **Step 2: Run full test suite one final time**

```bash
bash sensitive-guard/tests/run-tests.sh && bash sensitive-guard/tests/test-integration.sh
```

Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add sensitive-guard/README.md
git commit -m "docs(sensitive-guard): add README with installation and usage"
```

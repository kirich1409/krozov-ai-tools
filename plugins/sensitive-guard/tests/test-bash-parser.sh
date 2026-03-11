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

# Test: piped commands don't extract URLs
test_start "skips piped output (curl | jq)"
FILES=$(sg_extract_files_from_bash "curl https://example.com | jq '.'")
assert_not_contains "${FILES:-empty}" "https://example.com" "URLs not extracted"

# Test: empty/no files
test_start "returns empty for command with no files"
FILES=$(sg_extract_files_from_bash "echo hello")
[[ -z "$FILES" ]] && test_pass || test_fail "should return empty"

test_summary

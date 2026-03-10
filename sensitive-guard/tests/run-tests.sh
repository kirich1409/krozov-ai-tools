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

#!/bin/bash
set -euo pipefail

# Dependencies
command -v jq >/dev/null 2>&1 || exit 0

# Read hook input from stdin
HOOK_INPUT=$(cat)

# Extract tool name and file path
TOOL_NAME=$(echo "$HOOK_INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$HOOK_INPUT" | jq -r '.tool_input.file_path // empty')

# Only care about Edit and Write tools
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
  exit 0
fi

# Check if the file is a build dependency file
BASENAME=$(basename "$FILE_PATH")
case "$BASENAME" in
  build.gradle|build.gradle.kts|settings.gradle|settings.gradle.kts|pom.xml|libs.versions.toml)
    ;;
  *)
    exit 0
    ;;
esac

# Output reminder as JSON systemMessage
cat <<'EOF'
{"systemMessage":"Build dependency file was modified. Consider running /check-deps to verify dependency versions are up to date."}
EOF

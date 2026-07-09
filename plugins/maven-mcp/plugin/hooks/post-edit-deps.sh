#!/usr/bin/env bash
# post-edit-deps.sh — PostToolUse /check-deps reminder for maven-mcp.
#
# After Edit/Write/MultiEdit on a build file, emit a systemMessage nudge to run
# /check-deps — but only when the changed content looks coordinate-shaped
# (avoids nagging on comment/formatting-only edits).
#
# Fail-open is structural: trap 'exit 0' EXIT immediately after set -euo
# pipefail. Malformed stdin, jq failure, or any other error exits 0 with no
# reminder (never surfaces a hook error for a best-effort nudge).
set -euo pipefail
trap 'exit 0' EXIT

# ── Dependency check ─────────────────────────────────────────────────────────
command -v jq >/dev/null 2>&1 || exit 0

# ── Read stdin once; fail-open on any jq parse error ─────────────────────────
HOOK_INPUT=""
HOOK_INPUT=$(cat) || HOOK_INPUT=""

TOOL_NAME=""
TOOL_NAME=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_name // empty' 2>/dev/null) || TOOL_NAME=""

# ── Fast gate: only Edit, Write, MultiEdit on build files ────────────────────
case "$TOOL_NAME" in
  Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

FILE_PATH=""
FILE_PATH=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || FILE_PATH=""
BASENAME=""
BASENAME=$(basename "$FILE_PATH" 2>/dev/null) || BASENAME=""

case "$BASENAME" in
  build.gradle|build.gradle.kts|settings.gradle|settings.gradle.kts|pom.xml|libs.versions.toml) ;;
  *) exit 0 ;;
esac

# ── Extract new content from the tool payload ─────────────────────────────────
# Edit → new_string; Write → content; MultiEdit → concatenate edits[].new_string
NEW_CONTENT=""
case "$TOOL_NAME" in
  Edit)
    NEW_CONTENT=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.new_string // empty' 2>/dev/null) || NEW_CONTENT=""
    ;;
  Write)
    NEW_CONTENT=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.content // empty' 2>/dev/null) || NEW_CONTENT=""
    ;;
  MultiEdit)
    NEW_CONTENT=$(printf '%s' "$HOOK_INPUT" | jq -r '[.tool_input.edits[]?.new_string // empty] | join("\n")' 2>/dev/null) || NEW_CONTENT=""
    ;;
esac

[ -n "$NEW_CONTENT" ] || exit 0

# ── Coordinate-shaped gate (noise reduction) ──────────────────────────────────
# Emit only when the changed content contains dependency-coordinate shapes.
# Missed coordinates → no reminder (fail-open for a nudge is correct).
_Q="'"
HAS_COORDS=0
case "$BASENAME" in
  build.gradle|build.gradle.kts|settings.gradle|settings.gradle.kts)
    # Quoted Gradle notation: "g:a" / "g:a:v" or 'g:a' / 'g:a:v'
    if printf '%s\n' "$NEW_CONTENT" | grep -qE '"[A-Za-z0-9._-]+:[A-Za-z0-9._-]+(:[^"]+)?"' 2>/dev/null; then
      HAS_COORDS=1
    elif printf '%s\n' "$NEW_CONTENT" | grep -qE "${_Q}[A-Za-z0-9._-]+:[A-Za-z0-9._-]+(:[^${_Q}]+)?${_Q}" 2>/dev/null; then
      HAS_COORDS=1
    fi
    ;;
  pom.xml)
    # Any dependency GAV tag in the changed span
    if printf '%s\n' "$NEW_CONTENT" | grep -qE '<(groupId|artifactId|dependency)>' 2>/dev/null; then
      HAS_COORDS=1
    fi
    ;;
  libs.versions.toml)
    if printf '%s\n' "$NEW_CONTENT" | grep -qE 'module[[:space:]]*=[[:space:]]*"[A-Za-z0-9._-]+:[A-Za-z0-9._-]+"' 2>/dev/null; then
      HAS_COORDS=1
    elif printf '%s\n' "$NEW_CONTENT" | grep -qE '"[A-Za-z0-9._-]+:[A-Za-z0-9._-]+:[^"]+"' 2>/dev/null; then
      HAS_COORDS=1
    fi
    ;;
esac

[ "$HAS_COORDS" -eq 1 ] || exit 0

# ── Emit reminder ─────────────────────────────────────────────────────────────
printf '%s\n' '{"systemMessage":"Build dependency file was modified. Consider running /check-deps to verify dependency versions are up to date."}'

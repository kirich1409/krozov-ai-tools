#!/bin/bash
# Shared utilities for sensitive-guard

# Cache tool detection at source time (avoid repeated command -v in loops)
if command -v shasum &>/dev/null; then
  _SG_SHA_CMD="shasum -a 256"
else
  _SG_SHA_CMD="sha256sum"
fi

if command -v realpath &>/dev/null; then
  _SG_REALPATH_CMD="realpath"
elif command -v readlink &>/dev/null; then
  _SG_REALPATH_CMD="readlink"
else
  _SG_REALPATH_CMD=""
fi

sg_sha256() {
  local value="$1"
  # Trim leading/trailing whitespace using bash parameter expansion (safe, no subprocess, no escape interpretation)
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value" | $_SG_SHA_CMD | cut -d' ' -f1
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
  if [[ -e "$path" && -n "$_SG_REALPATH_CMD" ]]; then
    if [[ "$_SG_REALPATH_CMD" == "realpath" ]]; then
      path=$(realpath "$path")
    else
      path=$(readlink -f "$path" 2>/dev/null || echo "$path")
    fi
  fi
  echo "$path"
}

sg_is_binary() {
  local file_path="$1"
  # Check first 8KB for null bytes — if present, file is binary
  # perl -0777 slurps all input; exits 0 if null byte found (binary), 1 if not (text)
  if head -c 8192 "$file_path" 2>/dev/null | perl -0777 -ne 'exit(/\x00/ ? 0 : 1)' 2>/dev/null; then
    return 0  # is binary (null byte found)
  fi
  return 1  # is text
}

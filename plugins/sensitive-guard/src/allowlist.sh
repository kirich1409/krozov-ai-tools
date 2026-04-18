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

  # Check pattern match (use perl for macOS compatibility)
  local pattern_match="false"
  while IFS= read -r pattern_entry; do
    local regex
    regex=$(echo "$pattern_entry" | jq -r '.regex')
    if echo "$value" | perl -sne 'exit(/$regex/ ? 0 : 1)' -- -regex="$regex" 2>/dev/null; then
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

  # Collect indices of non-allowed findings, then extract in one jq call
  local keep_indices=""
  local idx=0

  while IFS= read -r finding; do
    local value type
    # Extract both fields in one jq call (no eval)
    value=$(echo "$finding" | jq -r '.value')
    type=$(echo "$finding" | jq -r '.type')

    local allowed
    allowed=$(sg_is_allowed "$project_al" "$value" "$type")
    if [[ "$allowed" != "true" ]]; then
      allowed=$(sg_is_allowed "$global_al" "$value" "$type")
    fi

    if [[ "$allowed" != "true" ]]; then
      keep_indices+="${keep_indices:+,}$idx"
    fi
    idx=$((idx + 1))
  done < <(echo "$findings_json" | jq -c '.[]')

  if [[ -z "$keep_indices" ]]; then
    echo "[]"
  else
    echo "$findings_json" | jq "[.[$keep_indices]]"
  fi
}

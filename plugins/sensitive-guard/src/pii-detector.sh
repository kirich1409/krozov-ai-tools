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

  # Pre-extract pattern IDs and regexes into arrays (one jq call, not per-line)
  # Use null-byte delimiter to avoid @tsv backslash escaping
  local pattern_ids=() pattern_regexes=()
  while IFS= read -r pid && IFS= read -r pregex; do
    pattern_ids+=("$pid")
    pattern_regexes+=("$pregex")
  done < <(echo "$patterns_json" | jq -r '.[] | .id, .regex')

  local pattern_count=${#pattern_ids[@]}
  if [[ "$pattern_count" -eq 0 ]]; then
    echo "[]"
    return
  fi

  # Collect findings as TSV lines in temp file, then build JSON in one pass
  local findings_file
  findings_file=$(mktemp)
  trap "rm -f '$findings_file'" RETURN

  local line_num=0
  local start_time=$SECONDS

  while IFS= read -r line || [[ -n "$line" ]]; do
    # 5s timeout for large files
    if (( SECONDS - start_time > 5 )); then
      sg_log_warn "PII scan timeout after 5s on $file_path — treating as clean"
      break
    fi

    line_num=$((line_num + 1))

    # Test each pattern against this line (no subprocess for pattern extraction)
    for ((p=0; p<pattern_count; p++)); do
      local pid="${pattern_ids[$p]}"
      local pregex="${pattern_regexes[$p]}"

      # Use perl -sne with variable passing to prevent regex injection
      local matches
      if matches=$(echo "$line" | perl -sne 'print "$&\n" while /$regex/g' -- -regex="$pregex" 2>/dev/null) && [[ -n "$matches" ]]; then
        while IFS= read -r match; do
          [[ -z "$match" ]] && continue
          # Write as newline-triplet: type, value, line (one per line)
          printf '%s\n%s\n%d\n' "$pid" "$match" "$line_num" >> "$findings_file"
        done <<< "$matches"
      fi
    done
  done < "$file_path"

  # Build JSON array from collected findings in one jq call
  if [[ ! -s "$findings_file" ]]; then
    echo "[]"
    return
  fi

  # Convert newline-triplet findings (type\nvalue\nline) to JSON array
  jq -Rn --arg file "$file_path" '[
    [inputs] | _nwise(3) | {type: .[0], value: .[1], file: $file, line: (.[2] | tonumber), engine: "pii"}
  ]' < "$findings_file"
}

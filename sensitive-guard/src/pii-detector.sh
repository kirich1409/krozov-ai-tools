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

      # Use perl for PCRE matching (portable: macOS grep lacks -P)
      local matches
      if matches=$(echo "$line" | perl -nle "print \$& while /$pregex/g" 2>/dev/null) && [[ -n "$matches" ]]; then
        while IFS= read -r match; do
          [[ -z "$match" ]] && continue
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

#!/bin/bash
# Interactive prompt for sensitive-guard findings
# Shows findings to stderr, reads actions from stdin
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

  # Extract all fields in one jq call
  local i=0
  while IFS=$'\t' read -r type value line_no; do
    i=$((i + 1))
    local preview
    preview=$(sg_truncate_value "$value" "$max_preview")
    output+="$(printf '  %d. [%s] %s  (line %s)\n' "$i" "$type" "$preview" "$line_no")"
  done < <(echo "$findings_json" | jq -r '.[] | [.type, .value, (.line | tostring)] | @tsv')

  echo "$output"
}

sg_collect_actions() {
  local findings_json="$1"
  local max_preview="${2:-12}"

  local count
  count=$(echo "$findings_json" | jq 'length')

  # Non-interactive (stdin not a TTY): block all in one jq call
  if [[ ! -t 0 ]]; then
    echo "$findings_json" | jq '[range(length) | {index: ., action: "block"}]'
    return
  fi

  # Show findings
  sg_format_findings_display "$findings_json" "$max_preview" >&2

  echo "" >&2
  echo "  Action per item: [p]ass once  [a]llow project  [g]lobal allow  [b]lock" >&2

  # Collect actions as TSV, build JSON at end
  local actions_tsv=""
  for ((i=0; i<count; i++)); do
    local idx=$((i + 1))
    local action=""
    while [[ -z "$action" ]]; do
      printf '  (%d): ' "$idx" >&2
      read -r input
      case "$input" in
        p|P) action="pass" ;;
        a|A) action="allow_project" ;;
        g|G) action="allow_global" ;;
        b|B) action="block" ;;
        *) echo "  Invalid choice. Use p/a/g/b" >&2 ;;
      esac
    done
    actions_tsv+="${i}\t${action}\n"
  done

  # Build JSON array in one jq call
  printf "$actions_tsv" | jq -R '[split("\t") | select(length == 2) | {index: (.[0] | tonumber), action: .[1]}]'
}

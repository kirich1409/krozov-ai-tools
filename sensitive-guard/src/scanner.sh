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
      # Skip if path ends with / (explicit directory) or is an actual directory on disk
      if [[ -n "$path" && ! "$path" =~ /$ ]] && [[ ! -d "$path" ]]; then
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

  # Deduplicate by value+line
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
    return 0
  fi

  # Extract target files
  local files
  files=$(sg_extract_target_files "$tool_name" "$tool_input_json")

  if [[ -z "$files" ]]; then
    return 0
  fi

  # Scan each file
  local all_findings="[]"
  while IFS= read -r file_path; do
    [[ -z "$file_path" ]] && continue
    file_path=$(sg_resolve_path "$file_path")
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
    return 0
  fi

  # Prompt user
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
        ;;
    esac
  done < <(echo "$actions" | jq -c '.[]')

  if [[ "$has_block" == "true" ]]; then
    sg_log_error "Tool call blocked: sensitive data detected"
    return 2
  fi

  return 0
}

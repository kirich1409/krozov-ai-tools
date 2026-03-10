#!/bin/bash
# Gitleaks wrapper — runs gitleaks and normalizes output to standard finding format

sg_check_gitleaks() {
  if command -v gitleaks &>/dev/null; then
    return 0
  fi
  # Show warning once per session via temp marker file
  local marker="/tmp/sensitive-guard-gitleaks-warned-${USER:-unknown}"
  if [[ ! -f "$marker" ]]; then
    sg_log_warn "gitleaks not found in PATH. Secret detection disabled."
    sg_log_warn "Install: brew install gitleaks (macOS) | go install github.com/gitleaks/gitleaks/v8@latest"
    touch "$marker"
  fi
  return 1
}

sg_run_gitleaks() {
  local file_path="$1"
  local config_path="$2"

  if [[ ! -f "$file_path" ]]; then
    echo "[]"
    return
  fi

  if ! sg_check_gitleaks; then
    echo "[]"
    return
  fi

  # Create temporary directory with copy of the file to scan
  local temp_dir temp_file temp_output
  temp_dir=$(mktemp -d)
  temp_file="$temp_dir/$(basename "$file_path")"
  temp_output="$temp_dir/output.json"
  trap "rm -rf '$temp_dir'" RETURN

  # Copy the file to the temporary directory
  cp "$file_path" "$temp_file"

  local cmd=(gitleaks detect --no-git -f json --source="$temp_dir" -r "$temp_output")
  if [[ -n "$config_path" && -f "$config_path" ]]; then
    cmd+=(--config="$config_path")
  fi

  # Run gitleaks, suppress all output
  "${cmd[@]}" >/dev/null 2>&1 || true

  # Check if output file was created and contains JSON
  if [[ ! -f "$temp_output" ]]; then
    echo "[]"
    return
  fi

  local raw_output
  raw_output=$(cat "$temp_output")

  if [[ -z "$raw_output" ]] || ! echo "$raw_output" | jq '.' &>/dev/null; then
    echo "[]"
    return
  fi

  echo "$raw_output" | jq --arg file "$file_path" '
    [.[] | {
      type: .RuleID,
      value: .Secret,
      file: $file,
      line: .StartLine,
      engine: "gitleaks"
    }]
  '
}

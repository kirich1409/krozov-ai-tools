#!/bin/bash
# Configuration loading and merging for sensitive-guard
#
# Merge strategy (spec):
# - Global config: simple deep merge over defaults (override replaces)
# - Project config on top of global: arrays append (union), scalars replace, objects deep merge

sg_load_config() {
  local global_config_path="$1"
  local project_config_path="$2"
  local plugin_root="$3"

  local default_config
  default_config=$(cat "$plugin_root/config/default-config.json")

  # Start with defaults
  local merged="$default_config"

  # Apply global config if exists (simple deep merge — override replaces)
  if [[ -f "$global_config_path" ]]; then
    local global_config
    global_config=$(cat "$global_config_path")
    merged=$(sg_merge_configs "$merged" "$global_config")
  fi

  # Apply project config if exists (arrays append, scalars replace)
  if [[ -f "$project_config_path" ]]; then
    local project_config
    project_config=$(cat "$project_config_path")
    merged=$(sg_merge_project_config "$merged" "$project_config")
  fi

  echo "$merged"
}

sg_merge_configs() {
  local base="$1" override="$2"
  echo "$base" "$override" | jq -s '.[0] * .[1]'
}

sg_merge_project_config() {
  local base="$1" project="$2"
  echo "$base" "$project" | jq -s '
    def merge_project(base; proj):
      base as $b | proj as $p |
      ($b | keys) + ($p | keys) | unique | map(. as $k |
        if ($p | has($k) | not) then {($k): $b[$k]}
        elif ($b | has($k) | not) then {($k): $p[$k]}
        elif ($b[$k] | type) == "array" and ($p[$k] | type) == "array" then
          {($k): ($b[$k] + $p[$k] | unique)}
        elif ($b[$k] | type) == "object" and ($p[$k] | type) == "object" then
          {($k): merge_project($b[$k]; $p[$k])}
        else
          {($k): $p[$k]}
        end
      ) | add // {};
    merge_project(.[0]; .[1])
  '
}

sg_get_active_pii_patterns() {
  local config="$1"
  local plugin_root="$2"

  local pii_enabled
  pii_enabled=$(echo "$config" | jq -r '.pii.enabled')
  if [[ "$pii_enabled" != "true" ]]; then
    echo "[]"
    return
  fi

  local disabled_ids
  disabled_ids=$(echo "$config" | jq -c '.pii.disabled // []')

  local custom_patterns
  custom_patterns=$(echo "$config" | jq -c '.pii.custom // []')

  local default_patterns
  default_patterns=$(cat "$plugin_root/config/default-pii-patterns.json")

  # Filter: active if enabled != false (true or missing) AND id not in disabled list
  local active
  active=$(echo "$default_patterns" "$disabled_ids" | jq -s '
    .[0] as $patterns | .[1] as $disabled |
    [$patterns[] | select(
      (.enabled != false) and
      (.id as $id | $disabled | map(select(. == $id)) | length == 0)
    )]
  ')

  # Append custom patterns
  echo "$active" "$custom_patterns" | jq -s '.[0] + .[1]'
}

sg_is_tool_inspected() {
  local config="$1" tool_name="$2"
  echo "$config" | jq -r --arg tool "$tool_name" '.tools | map(select(. == $tool)) | length > 0'
}

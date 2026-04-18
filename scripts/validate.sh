#!/usr/bin/env bash
# Validates marketplace and plugin configurations.
#
# Usage:
#   bash scripts/validate.sh                    # full validation
#   bash scripts/validate.sh --check-tag 1.2.3  # + verify all versions match tag
#
# Exit code: 0 if all checks pass, 1 if any error found.
set -uo pipefail

# Require jq
if ! command -v jq &> /dev/null; then
  echo "ERROR: jq is required but not installed" &>\set -uo pipefail2
  exit 1
fi

MARKETPLACE=".claude-plugin/marketplace.json"
ERRORS=0

fail() { echo "ERROR: $*" >&2; ERRORS=$((ERRORS + 1)); }
ok()   { echo "OK: $*"; }

# ---------- L1: JSON syntax ----------

check_json_syntax() {
  echo "--- L1: JSON syntax ---"
  if ! jq empty "$MARKETPLACE" 2>/dev/null; then
    fail "$MARKETPLACE is not valid JSON"
    return
  fi
  ok "$MARKETPLACE is valid JSON"

  while IFS=$'\t' read -r name source; do
    plugin_json="${source}/.claude-plugin/plugin.json"
    [ -f "$plugin_json" ] || continue
    if ! jq empty "$plugin_json" 2>/dev/null; then
      fail "$plugin_json ('$name') is not valid JSON"
    else
      ok "$plugin_json ('$name') is valid JSON"
    fi
  done < <(jq -r '.plugins[] | [.name, .source] | @tsv' "$MARKETPLACE")
}

# ---------- L2: Structure ----------

check_no_duplicates() {
  echo "--- L2: No duplicate plugin names ---"
  DUPES=$(jq -r '[.plugins[].name] | sort | group_by(.) | map(select(length > 1) | .[0]) | .[]' "$MARKETPLACE")
  if [ -n "$DUPES" ]; then
    fail "Duplicate plugin names in marketplace.json: $DUPES"
  else
    ok "no duplicate names"
  fi
}

check_all_dirs_registered() {
  echo "--- L2: All plugins/ directories registered in marketplace.json ---"
  REGISTERED=$(jq -r '.plugins[].name' "$MARKETPLACE")
  for dir in plugins/*/; do
    name=$(basename "$dir")
    if ! echo "$REGISTERED" | grep -Fxq "$name"; then
      fail "'$name' is in plugins/ but missing from marketplace.json"
    fi
  done
}

# ---------- L3: Consistency ----------

check_marketplace_entries_have_dirs() {
  echo "--- L3: marketplace.json entries have plugins/ directories ---"
  while IFS= read -r name; do
    if [ ! -d "plugins/$name" ]; then
      fail "marketplace.json has '$name' but plugins/$name/ does not exist"
    else
      ok "plugins/$name/"
    fi
  done < <(jq -r '.plugins[].name' "$MARKETPLACE")
}

check_source_paths_and_plugin_json() {
  echo "--- L3: Source paths exist and contain plugin.json ---"
  while IFS=$'\t' read -r name source; do
    if [ ! -d "$source" ]; then
      fail "'$name' source path does not exist: $source"
      continue
    fi
    ok "'$name' source $source"

    plugin_json="${source}/.claude-plugin/plugin.json"
    if [ ! -f "$plugin_json" ]; then
      fail "'$name' plugin.json not found at $plugin_json"
    else
      ok "'$name' plugin.json found"
    fi
  done < <(jq -r '.plugins[] | [.name, .source] | @tsv' "$MARKETPLACE")
}

check_name_consistency() {
  echo "--- L3: plugin.json name matches marketplace.json ---"
  while IFS=$'\t' read -r name source; do
    plugin_json="${source}/.claude-plugin/plugin.json"
    [ -f "$plugin_json" ] || continue
    plugin_name=$(jq -r '.name' "$plugin_json")
    if [ "$name" != "$plugin_name" ]; then
      fail "'$name' name mismatch: marketplace.json=$name, plugin.json=$plugin_name"
    else
      ok "'$name' name consistent"
    fi
  done < <(jq -r '.plugins[] | [.name, .source] | @tsv' "$MARKETPLACE")
}

# ---------- L4: Unified versioning ----------

check_version_consistency() {
  echo "--- L4: Versions consistent (marketplace.json ↔ plugin.json) ---"
  while IFS=$'\t' read -r name version source; do
    plugin_json="${source}/.claude-plugin/plugin.json"
    if [ ! -f "$plugin_json" ]; then
      fail "'$name' plugin.json not found — cannot check version"
      continue
    fi
    plugin_version=$(jq -r '.version' "$plugin_json")
    if [ "$version" != "$plugin_version" ]; then
      fail "'$name' version mismatch: marketplace.json=$version, plugin.json=$plugin_version"
    else
      ok "'$name' version $version"
    fi
  done < <(jq -r '.plugins[] | [.name, .version, .source] | @tsv' "$MARKETPLACE")
}

check_semver() {
  echo "--- L4: Semver format (x.y.z) ---"
  SEMVER='^[0-9]+\.[0-9]+\.[0-9]+$'
  while IFS=$'\t' read -r name version source; do
    if ! echo "$version" | grep -qE "$SEMVER"; then
      fail "'$name' marketplace.json version is not semver: $version"
    fi
    plugin_json="${source}/.claude-plugin/plugin.json"
    if [ -f "$plugin_json" ]; then
      plugin_version=$(jq -r '.version' "$plugin_json")
      if ! echo "$plugin_version" | grep -qE "$SEMVER"; then
        fail "'$name' plugin.json version is not semver: $plugin_version"
      fi
    fi
  done < <(jq -r '.plugins[] | [.name, .version, .source] | @tsv' "$MARKETPLACE")
}

check_tag_versions() {
  local version="$1"
  echo "--- L4: All versions match tag v${version} ---"
  SEMVER='^[0-9]+\.[0-9]+\.[0-9]+$'
  if ! echo "$version" | grep -qE "$SEMVER"; then
    fail "Tag version is not semver: $version"
    return
  fi

  # maven-mcp: also check package.json (npm package)
  PKG_JSON="plugins/maven-mcp/package.json"
  if [ -f "$PKG_JSON" ]; then
    pkg_version=$(jq -r '.version' "$PKG_JSON")
    if [ "$pkg_version" != "$version" ]; then
      fail "$PKG_JSON version \"$pkg_version\" does not match tag v${version}"
    else
      ok "$PKG_JSON version $pkg_version"
    fi
  fi

  # All plugin.json files — data-driven from marketplace.json
  while IFS=$'\t' read -r name source; do
    plugin_json="${source}/.claude-plugin/plugin.json"
    if [ ! -f "$plugin_json" ]; then
      fail "'$name' plugin.json not found at $plugin_json"
      continue
    fi
    plugin_version=$(jq -r '.version' "$plugin_json")
    if [ "$plugin_version" != "$version" ]; then
      fail "'$name' plugin.json version \"$plugin_version\" does not match tag v${version}"
    else
      ok "'$name' plugin.json version $plugin_version"
    fi
  done < <(jq -r '.plugins[] | [.name, .source] | @tsv' "$MARKETPLACE")

  # marketplace.json plugin versions
  while IFS=$'\t' read -r name mkt_version; do
    if [ "$mkt_version" != "$version" ]; then
      fail "marketplace.json plugin '$name' version \"$mkt_version\" does not match tag v${version}"
    else
      ok "marketplace.json '$name' version $mkt_version"
    fi
  done < <(jq -r '.plugins[] | [.name, .version] | @tsv' "$MARKETPLACE")
}

# ---------- L5: Skills / agents directories ----------

check_skills_dirs() {
  echo "--- L5: Skills directories exist ---"
  while IFS=$'\t' read -r name source; do
    plugin_json="${source}/.claude-plugin/plugin.json"
    [ -f "$plugin_json" ] || continue
    skills_rel=$(jq -r '.skills // empty' "$plugin_json")
    [ -n "$skills_rel" ] || continue
    skills_path=$(python3 -c "import os; print(os.path.normpath(os.path.join('${source}/.claude-plugin', '${skills_rel}')))")
    if [ ! -d "$skills_path" ]; then
      fail "'$name' skills path does not exist: $skills_path"
    else
      ok "'$name' skills at $skills_path"
    fi
  done < <(jq -r '.plugins[] | [.name, .source] | @tsv' "$MARKETPLACE")
}

check_agents_dirs() {
  echo "--- L5: Agents directories exist ---"
  while IFS=$'\t' read -r name source; do
    plugin_json="${source}/.claude-plugin/plugin.json"
    [ -f "$plugin_json" ] || continue
    agents_rel=$(jq -r '.agents // empty' "$plugin_json")
    [ -n "$agents_rel" ] || continue
    agents_path=$(python3 -c "import os; print(os.path.normpath(os.path.join('${source}/.claude-plugin', '${agents_rel}')))")
    if [ ! -d "$agents_path" ]; then
      fail "'$name' agents path does not exist: $agents_path"
    else
      ok "'$name' agents at $agents_path"
    fi
  done < <(jq -r '.plugins[] | [.name, .source] | @tsv' "$MARKETPLACE")
}

# ---------- L6: Hook scripts ----------

check_hook_scripts() {
  echo "--- L6: Hook scripts executable ---"
  while IFS=$'\t' read -r name source; do
    hooks_dir="${source}/hooks"
    [ -d "$hooks_dir" ] || continue
    while IFS= read -r script; do
      if [ ! -x "$script" ]; then
        fail "'$name' hook script is not executable: $script"
      else
        ok "'$name' $(basename "$script") is executable"
      fi
    done < <(find "$hooks_dir" -type f -name "*.sh")
  done < <(jq -r '.plugins[] | [.name, .source] | @tsv' "$MARKETPLACE")
}

# ---------- L7: Skill/agent frontmatter ----------
#
# Delegated to scripts/check_frontmatter.py — parses YAML frontmatter,
# enforces Anthropic rules (description ≤ 1024 chars, name matches dir/file,
# no forbidden fields in agent frontmatter).

check_frontmatter() {
  echo "--- L7: Skill/agent frontmatter ---"
  if ! output=$(python3 scripts/check_frontmatter.py "$MARKETPLACE" 2>&1); then
    echo "$output"
    # each non-OK line increments ERRORS
    while IFS= read -r line; do
      case "$line" in
        ERROR:*) ERRORS=$((ERRORS + 1)) ;;
      esac
    done <<< "$output"
  else
    echo "$output"
  fi
}

# ---------- Entry point ----------

main() {
  CHECK_TAG=""
  if [ "${1-}" = "--check-tag" ]; then
    CHECK_TAG="${2-}"
    if [ -z "$CHECK_TAG" ]; then
      echo "Usage: $0 --check-tag VERSION" >&2
      exit 1
    fi
  fi

  echo "=== Marketplace & Plugin Validation ==="
  echo "Marketplace: $MARKETPLACE"

  check_json_syntax
  check_no_duplicates
  check_all_dirs_registered
  check_marketplace_entries_have_dirs
  check_source_paths_and_plugin_json
  check_name_consistency
  check_version_consistency
  check_semver
  check_skills_dirs
  check_agents_dirs
  check_hook_scripts
  check_frontmatter

  if [ -n "$CHECK_TAG" ]; then
    check_tag_versions "$CHECK_TAG"
  fi

  echo ""
  if [ "$ERRORS" -eq 0 ]; then
    echo "=== All checks passed ==="
  else
    echo "=== $ERRORS error(s) found ===" >&2
    exit 1
  fi
}

main "$@"

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
  echo "ERROR: jq is required but not installed" >&2
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

# ---------- L5: plugin.json component paths ----------
#
# Claude Code schema rules for component-path fields:
#   - Path is resolved from the plugin ROOT (not from .claude-plugin/)
#   - Must start with "./"
#   - Must not contain "../" — path traversal outside plugin root is rejected
#     by the manifest validator ("Validation errors: <field>: Invalid input").
#   - For standard directories (skills/, agents/, commands/, hooks/,
#     output-styles/, monitors/), auto-discovery works when the field is
#     omitted entirely; that is the preferred form.

PATH_FIELDS=(skills agents commands outputStyles hooks mcpServers lspServers monitors)

# Validates a single path string against the schema rules.
# Args: plugin_name field path_value
_check_path_shape() {
  local name="$1" field="$2" p="$3"
  case "$p" in
    ../*|*/../*|*/..)
      fail "'$name' $field path contains '../' — Claude Code rejects path traversal: $p"
      return 1
      ;;
  esac
  case "$p" in
    ./*) return 0 ;;
    *)
      fail "'$name' $field path must start with './' (got: $p)"
      return 1
      ;;
  esac
}

# Emits each path string from a plugin.json field. Accepts string or array.
# Inline objects (hooks/mcpServers/lspServers configs) emit nothing.
_emit_paths() {
  local plugin_json="$1" field="$2"
  jq -r --arg f "$field" '
    .[$f] as $v
    | if   $v == null             then empty
      elif ($v | type) == "string" then $v
      elif ($v | type) == "array"  then $v[] | select(type == "string")
      else empty
      end
  ' "$plugin_json"
}

check_component_paths() {
  echo "--- L5: plugin.json component paths (shape + existence) ---"
  while IFS=$'\t' read -r name source; do
    plugin_json="${source}/.claude-plugin/plugin.json"
    [ -f "$plugin_json" ] || continue

    for field in "${PATH_FIELDS[@]}"; do
      while IFS= read -r p; do
        [ -n "$p" ] || continue
        _check_path_shape "$name" "$field" "$p" || continue
        abs=$(python3 -c "import os; print(os.path.normpath(os.path.join('${source}', '${p}')))")
        if [ ! -e "$abs" ]; then
          fail "'$name' $field path does not exist: $abs"
        else
          ok "'$name' $field -> $abs"
        fi
      done < <(_emit_paths "$plugin_json" "$field")
    done
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
# Delegated to scripts/check_frontmatter.py. The helper prints its own
# ERROR:/OK:/WARN: lines and exits non-zero on failure. We trust the exit
# code as the single source of truth for pass/fail.

check_frontmatter() {
  echo "--- L7: Skill/agent frontmatter ---"
  if python3 scripts/check_frontmatter.py "$MARKETPLACE"; then
    return 0
  fi
  fail "frontmatter validation failed (see output above)"
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
  check_component_paths
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

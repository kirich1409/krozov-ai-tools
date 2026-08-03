#!/usr/bin/env bash
# Validates marketplace and plugin configurations.
#
# Usage:
#   bash scripts/validate.sh                    # full validation
#   bash scripts/validate.sh --check-tag 1.2.3  # + verify the plugins released by
#                                               #   tag v1.2.3 (those standing on
#                                               #   that version) are consistent
#   bash scripts/validate.sh --check-tag youtube-transcript--v1.2.3
#                                               # + verify that ONE named plugin's
#                                               #   three version locations are at
#                                               #   1.2.3
#
# The per-plugin form is what release.yml passes: with a per-plugin tag the
# released plugin is named, so validation must assert that plugin specifically —
# otherwise a tag naming one plugin passes on another plugin's version
# coincidence. The argument is matched against two anchored patterns and nothing
# else; a value matching neither is a hard error, never a prefix strip.
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

# ---------- L4: Versioning ----------

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

# The three version locations of one plugin, factored out so the bare-version
# form (check_tag_versions) and the per-plugin-tag form
# (check_plugin_tag_versions) assert exactly the same things. $tag_label is only
# used in messages: "v1.2.3" for the bare form, "plugin--v1.2.3" for the other.

# Location 2: plugin.json.
_check_tag_plugin_json() {
  local name="$1" source="$2" version="$3" tag_label="$4"
  local plugin_json="${source}/.claude-plugin/plugin.json"
  if [ ! -f "$plugin_json" ]; then
    fail "'$name' plugin.json not found at $plugin_json"
    return
  fi
  local plugin_version
  plugin_version=$(jq -r '.version' "$plugin_json")
  if [ "$plugin_version" != "$version" ]; then
    fail "'$name' plugin.json version \"$plugin_version\" does not match tag ${tag_label}"
  else
    ok "'$name' plugin.json version $plugin_version"
  fi
}

# Location 3: bundled MCP server scripts — version constants must track the tag.
# The script path is derived from each plugin.json mcpServers entry
# (${CLAUDE_PLUGIN_ROOT} resolves to the plugin source dir). This is the
# runtime that actually ships, so a stale SERVER_VERSION/USER_AGENT here is
# silent version skew that the manifest checks cannot catch.
_check_tag_server_constants() {
  local name="$1" source="$2" version="$3" tag_label="$4"
  local plugin_json="${source}/.claude-plugin/plugin.json"
  [ -f "$plugin_json" ] || return
  local arg script found sver
  while IFS= read -r arg; do
    [ -n "$arg" ] || continue
    script=$(printf '%s' "$arg" | sed "s|\${CLAUDE_PLUGIN_ROOT}|${source}|g")
    [ -f "$script" ] || continue
    found=0
    while IFS= read -r sver; do
      found=1
      if [ "$sver" != "$version" ]; then
        fail "'$name' $script version constant \"$sver\" does not match tag ${tag_label}"
      else
        ok "'$name' $script version constant $sver"
      fi
    done < <(grep -oE '(SERVER_VERSION|USER_AGENT)[[:space:]]*=[[:space:]]*"[^"]*"' "$script" \
               | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
    if [ "$found" -eq 0 ]; then
      fail "'$name' $script has no SERVER_VERSION/USER_AGENT version constant to verify against tag ${tag_label}"
    fi
  done < <(jq -r '
    .mcpServers // {}
    | to_entries[]
    | select(.value.command | test("^python"))
    | .value.args[]? | select(test("\\.py$"))
  ' "$plugin_json")
}

# Per-plugin tag `<plugin>--v<version>` (the release trigger). Exactly one plugin
# is named, so exactly that plugin is validated: a tag naming plugin A must not
# pass because plugin B happens to stand on the same version. Three distinct
# error classes, each with its own message: unknown plugin (raised here),
# version mismatch (per location), unparseable tag (raised by the caller before
# this function is reached — the name is never used to build a path until it has
# matched the anchored pattern AND been found in marketplace.json).
check_plugin_tag_versions() {
  local plugin="$1" version="$2"
  local tag="${plugin}--v${version}"
  echo "--- L4: Plugin released by tag ${tag} ---"

  local entry
  entry=$(jq -r --arg n "$plugin" '.plugins[] | select(.name == $n) | [.version, .source] | @tsv' "$MARKETPLACE")
  if [ -z "$entry" ]; then
    fail "tag ${tag} names plugin '$plugin', which is not in $MARKETPLACE"
    return
  fi

  local mkt_version source
  IFS=$'\t' read -r mkt_version source <<< "$entry"

  # Location 1: marketplace.json.
  if [ "$mkt_version" != "$version" ]; then
    fail "'$plugin' marketplace.json version \"$mkt_version\" does not match tag ${tag}"
  else
    ok "marketplace.json '$plugin' version $mkt_version"
  fi

  _check_tag_plugin_json "$plugin" "$source" "$version" "$tag"
  _check_tag_server_constants "$plugin" "$source" "$version" "$tag"
}

# Plugin versions are independent: a tag vX.Y.Z releases exactly those plugins
# whose marketplace.json version equals X.Y.Z. Plugins on another version are
# not part of this release and are skipped -- loudly, because a silent skip is
# indistinguishable from a forgotten version bump. A tag matching no plugin at
# all releases nothing and is treated as a typo in the tag.
check_tag_versions() {
  local version="$1"
  echo "--- L4: Plugins released by tag v${version} ---"
  SEMVER='^[0-9]+\.[0-9]+\.[0-9]+$'
  if ! echo "$version" | grep -qE "$SEMVER"; then
    fail "Tag version is not semver: $version"
    return
  fi

  local matched=0
  while IFS=$'\t' read -r name mkt_version; do
    if [ "$mkt_version" != "$version" ]; then
      echo "SKIP: '$name' not part of this release (version $mkt_version)"
      continue
    fi
    matched=$((matched + 1))
    ok "marketplace.json '$name' version $mkt_version"
  done < <(jq -r '.plugins[] | [.name, .version] | @tsv' "$MARKETPLACE")

  if [ "$matched" -eq 0 ]; then
    fail "tag v${version} matches no plugin in $MARKETPLACE — it would release nothing"
    return
  fi

  # plugin.json and the bundled server constants of the released plugins —
  # data-driven from marketplace.json, same two checks the per-plugin-tag form
  # runs (see the helpers above).
  while IFS=$'\t' read -r name source; do
    _check_tag_plugin_json "$name" "$source" "$version" "v${version}"
  done < <(jq -r --arg v "$version" '.plugins[] | select(.version == $v) | [.name, .source] | @tsv' "$MARKETPLACE")

  while IFS=$'\t' read -r name source; do
    _check_tag_server_constants "$name" "$source" "$version" "v${version}"
  done < <(jq -r --arg v "$version" '.plugins[] | select(.version == $v) | [.name, .source] | @tsv' "$MARKETPLACE")
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

# ---------- L8: plugin.json scalar field types ----------
#
# Claude Code's plugin.json schema requires these fields to be plain strings.
# npm's package.json allows object forms for some (notably
# "repository": {"type","url"}), which Claude Code rejects with
# "Validation errors: <field>: Invalid input: expected string, received object".
# Catch that here so it never reaches a release.

STRING_FIELDS=(name version description homepage repository license)

check_field_types() {
  echo "--- L8: plugin.json scalar field types ---"
  while IFS=$'\t' read -r name source; do
    plugin_json="${source}/.claude-plugin/plugin.json"
    [ -f "$plugin_json" ] || continue
    local plugin_ok=1
    for field in "${STRING_FIELDS[@]}"; do
      ftype=$(jq -r --arg f "$field" 'if has($f) then (.[$f] | type) else "absent" end' "$plugin_json")
      case "$ftype" in
        absent|string) ;;
        *)
          fail "'$name' plugin.json field '$field' must be a string, got $ftype (Claude Code rejects npm-style $ftype)"
          plugin_ok=0
          ;;
      esac
    done
    [ "$plugin_ok" -eq 1 ] && ok "'$name' scalar field types"
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

# ---------- L9: Workflow permissions ----------
#
# Every workflow must declare a `permissions:` key somewhere (top-level,
# applying to all its jobs, or per-job, like release.yml's publish job and
# codeql.yml's analyze job) rather than relying on the GITHUB_TOKEN default
# permissions (broad, repo-setting-dependent, and easy to widen by accident).
# This is deliberately a presence check, not a least-privilege audit: it
# catches a workflow that omits the key entirely, not one whose declared
# scopes are too broad -- that judgment call stays a human/code-review
# concern.

check_workflow_permissions() {
  echo "--- L9: Workflow files declare a permissions: key ---"
  local dir=".github/workflows"
  [ -d "$dir" ] || return
  for wf in "$dir"/*.yml "$dir"/*.yaml; do
    [ -f "$wf" ] || continue
    if grep -qE '^[[:space:]]*permissions:' "$wf"; then
      ok "$wf declares permissions:"
    else
      fail "$wf is missing a permissions: key (top-level or per-job) -- relies on default GITHUB_TOKEN permissions"
    fi
  done
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
  check_field_types
  check_workflow_permissions

  # Two anchored patterns, tried in order; anything else is a hard error. Never
  # a prefix strip: `${TAG#v}` on an attacker-chosen tag name yields whatever is
  # left over, and the leftover then reaches jq and the filesystem. The
  # per-plugin pattern is tried first because a bare version can never contain
  # "--v", so the two are disjoint.
  if [ -n "$CHECK_TAG" ]; then
    if [[ "$CHECK_TAG" =~ ^([a-z0-9-]+)--v([0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
      check_plugin_tag_versions "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    elif [[ "$CHECK_TAG" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      check_tag_versions "$CHECK_TAG"
    else
      fail "--check-tag value is neither a bare version (X.Y.Z) nor a per-plugin tag (<plugin>--vX.Y.Z): $CHECK_TAG"
    fi
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

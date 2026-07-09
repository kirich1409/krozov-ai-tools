#!/usr/bin/env bash
# pre-edit-deps.sh — PreToolUse write-time dependency guard for maven-mcp.
#
# Checks NEW coordinates being added to a build file for:
#   - Non-existent / likely-hallucinated coords (absent + likelyHallucination)                  → deny
#   - CRITICAL/HIGH CVEs on a pinned version                                                   → ask
# Any uncertainty, failure, or network error → fail-open (edit proceeds).
#
# IMPORTANT — existence guard scope: the guard is Maven-Central-scoped.
# A coordinate that 404s across ALL probed repos is "absent" but may be a
# legitimate private/internal/androidx dependency with no close Central match.
# We therefore only act on "absent" when likelyHallucination==true (similarity
# ≥ HALLUCINATION_THRESHOLD). NEVER deny on bare-absent or on weak Solr hits —
# that would false-block real private dependencies. See plan §Decisions #4 / #352.
#
# Fail-open is structural: trap 'exit 0' EXIT immediately after set -euo pipefail
# (replaced after mktemp to also rm -rf the work dir; still always exits 0).
# The script can only ever reach exit 0 (never exit 2, which would hard-block).
set -euo pipefail
trap 'exit 0' EXIT

# ── Dependency check ─────────────────────────────────────────────────────────
command -v jq >/dev/null 2>&1 || exit 0

# ── Read stdin once; fail-open on any jq parse error ─────────────────────────
HOOK_INPUT=""
HOOK_INPUT=$(cat) || HOOK_INPUT=""

TOOL_NAME=""
TOOL_NAME=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_name // empty' 2>/dev/null) || TOOL_NAME=""

# ── Fast gate: only Edit, Write, MultiEdit on build files ────────────────────
case "$TOOL_NAME" in
  Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

FILE_PATH=""
FILE_PATH=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || FILE_PATH=""
BASENAME=""
BASENAME=$(basename "$FILE_PATH" 2>/dev/null) || BASENAME=""

# *.versions.toml covers libs.versions.toml and custom catalog filenames
# declared via versionCatalogs { create("x") { from(files(...)) } } (#359).
case "$BASENAME" in
  build.gradle|build.gradle.kts|settings.gradle|settings.gradle.kts|pom.xml|*.versions.toml) ;;
  *) exit 0 ;;
esac

# ── Extract new content from the tool payload ─────────────────────────────────
# Edit → new_string; Write → content; MultiEdit → concatenate edits[].new_string
NEW_CONTENT=""
case "$TOOL_NAME" in
  Edit)
    NEW_CONTENT=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.new_string // empty' 2>/dev/null) || NEW_CONTENT=""
    ;;
  Write)
    NEW_CONTENT=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.content // empty' 2>/dev/null) || NEW_CONTENT=""
    ;;
  MultiEdit)
    NEW_CONTENT=$(printf '%s' "$HOOK_INPUT" | jq -r '[.tool_input.edits[]?.new_string // empty] | join("\n")' 2>/dev/null) || NEW_CONTENT=""
    ;;
esac

[ -n "$NEW_CONTENT" ] || exit 0

# ── Coordinate extraction ─────────────────────────────────────────────────────
# Best-effort heuristic; a missed coordinate is fail-open (no wrong block).
# Charset: [A-Za-z0-9._-] for each component; version may be empty (GA-only).
# Bash-3.2-safe: no declare -A, no ${var,,}, no mapfile/readarray.

MAX_COORDS=8

# Temporary files are cleaned up by the EXIT trap (exit 0 always fires).
TMPDIR_WORK=""
TMPDIR_WORK=$(mktemp -d 2>/dev/null) || TMPDIR_WORK=""
# Replace the fail-open EXIT trap so it also removes the work dir. Still exits 0.
trap 'rm -rf "$TMPDIR_WORK" 2>/dev/null || true; exit 0' EXIT
COORDS_FILE=""
[ -n "$TMPDIR_WORK" ] && COORDS_FILE="${TMPDIR_WORK}/coords.txt"

# Write extracted coords (g:a:v or g:a) one per line.
if [ -n "$COORDS_FILE" ]; then
  : > "$COORDS_FILE"

  # _Q holds a literal single-quote character; used to build grep patterns without
  # embedding single quotes inside single-quoted shell strings (avoids SC2016).
  _Q="'"

  case "$BASENAME" in
    build.gradle|build.gradle.kts|settings.gradle|settings.gradle.kts)
      # Match "g:a[:v]" (double-quoted) and 'g:a[:v]' (single-quoted) Gradle notation.
      # Version part allows any non-quote chars; sanitize step below strips non-literal
      # versions (those containing '$') and enforces the charset on each component.
      GRADLE_TMP="${TMPDIR_WORK}/gradle_input.txt"
      printf '%s\n' "$NEW_CONTENT" > "$GRADLE_TMP" 2>/dev/null || true
      # Double-quoted form: "g:a" or "g:a:v"
      grep -oE '"[A-Za-z0-9._-]+:[A-Za-z0-9._-]+(:[^"]+)?"' "$GRADLE_TMP" 2>/dev/null | \
        tr -d '"' >> "$COORDS_FILE" || true
      # Single-quoted form: 'g:a' or 'g:a:v' — pattern built via variable to avoid quoting hell
      grep -oE "${_Q}[A-Za-z0-9._-]+:[A-Za-z0-9._-]+(:[^${_Q}]+)?${_Q}" "$GRADLE_TMP" 2>/dev/null | \
        tr -d "${_Q}" >> "$COORDS_FILE" || true

      # Plugins DSL (#359): id("com.foo") [version "1.0"] → marker
      # com.foo:com.foo.gradle.plugin[:1.0]. Parenthesised and Groovy space forms;
      # double- and single-quoted ids/versions.
      _emit_plugin_marker() {
        _pid="$1"
        _pver="$2"
        [ -n "$_pid" ] || return 0
        if [ -n "$_pver" ]; then
          printf '%s:%s.gradle.plugin:%s\n' "$_pid" "$_pid" "$_pver" >> "$COORDS_FILE" || true
        else
          printf '%s:%s.gradle.plugin\n' "$_pid" "$_pid" >> "$COORDS_FILE" || true
        fi
      }
      # id("…") / id('…') with optional version "…" / '…' on the same line
      grep -oE 'id[[:space:]]*\([[:space:]]*"[A-Za-z0-9._-]+"[[:space:]]*\)([[:space:]]+version[[:space:]]+"[^"]+")?' "$GRADLE_TMP" 2>/dev/null | while IFS= read -r _pline; do
        _pid=$(printf '%s' "$_pline" | sed -nE 's/.*id[[:space:]]*\([[:space:]]*"([^"]+)".*/\1/p') || _pid=""
        _pver=$(printf '%s' "$_pline" | sed -nE 's/.*version[[:space:]]+"([^"]+)".*/\1/p') || _pver=""
        _emit_plugin_marker "$_pid" "$_pver"
      done || true
      grep -oE "id[[:space:]]*\\([[:space:]]*${_Q}[A-Za-z0-9._-]+${_Q}[[:space:]]*\\)([[:space:]]+version[[:space:]]+${_Q}[^${_Q}]+${_Q})?" "$GRADLE_TMP" 2>/dev/null | while IFS= read -r _pline; do
        _pid=$(printf '%s' "$_pline" | sed -nE "s/.*id[[:space:]]*\\([[:space:]]*${_Q}([^${_Q}]+)${_Q}.*/\\1/p") || _pid=""
        _pver=$(printf '%s' "$_pline" | sed -nE "s/.*version[[:space:]]+${_Q}([^${_Q}]+)${_Q}.*/\\1/p") || _pver=""
        _emit_plugin_marker "$_pid" "$_pver"
      done || true
      # Groovy: id '…' version '…' (no parentheses)
      grep -oE 'id[[:space:]]+"[A-Za-z0-9._-]+"([[:space:]]+version[[:space:]]+"[^"]+")?' "$GRADLE_TMP" 2>/dev/null | while IFS= read -r _pline; do
        _pid=$(printf '%s' "$_pline" | sed -nE 's/.*id[[:space:]]+"([^"]+)".*/\1/p') || _pid=""
        _pver=$(printf '%s' "$_pline" | sed -nE 's/.*version[[:space:]]+"([^"]+)".*/\1/p') || _pver=""
        _emit_plugin_marker "$_pid" "$_pver"
      done || true
      grep -oE "id[[:space:]]+${_Q}[A-Za-z0-9._-]+${_Q}([[:space:]]+version[[:space:]]+${_Q}[^${_Q}]+${_Q})?" "$GRADLE_TMP" 2>/dev/null | while IFS= read -r _pline; do
        _pid=$(printf '%s' "$_pline" | sed -nE "s/.*id[[:space:]]+${_Q}([^${_Q}]+)${_Q}.*/\\1/p") || _pid=""
        _pver=$(printf '%s' "$_pline" | sed -nE "s/.*version[[:space:]]+${_Q}([^${_Q}]+)${_Q}.*/\\1/p") || _pver=""
        _emit_plugin_marker "$_pid" "$_pver"
      done || true

      # Map / named-arg form (#359): group = "g", name = "a"[, version = "v"]
      # Also Groovy colon form: group: 'g', name: 'a'. Either key order.
      _emit_map_dep() {
        _mg="$1"; _ma="$2"; _mv="$3"
        [ -n "$_mg" ] && [ -n "$_ma" ] || return 0
        if [ -n "$_mv" ]; then
          printf '%s:%s:%s\n' "$_mg" "$_ma" "$_mv" >> "$COORDS_FILE" || true
        else
          printf '%s:%s\n' "$_mg" "$_ma" >> "$COORDS_FILE" || true
        fi
      }
      # group then name (double-quoted, = or :)
      grep -oE 'group[[:space:]]*[=:][[:space:]]*"[A-Za-z0-9._-]+"[[:space:]]*,[[:space:]]*name[[:space:]]*[=:][[:space:]]*"[A-Za-z0-9._-]+"([[:space:]]*,[[:space:]]*version[[:space:]]*[=:][[:space:]]*"[^"]+")?' "$GRADLE_TMP" 2>/dev/null | while IFS= read -r _mline; do
        _mg=$(printf '%s' "$_mline" | sed -nE 's/.*group[[:space:]]*[=:][[:space:]]*"([^"]+)".*/\1/p') || _mg=""
        _ma=$(printf '%s' "$_mline" | sed -nE 's/.*name[[:space:]]*[=:][[:space:]]*"([^"]+)".*/\1/p') || _ma=""
        _mv=$(printf '%s' "$_mline" | sed -nE 's/.*version[[:space:]]*[=:][[:space:]]*"([^"]+)".*/\1/p') || _mv=""
        _emit_map_dep "$_mg" "$_ma" "$_mv"
      done || true
      # name then group (double-quoted)
      grep -oE 'name[[:space:]]*[=:][[:space:]]*"[A-Za-z0-9._-]+"[[:space:]]*,[[:space:]]*group[[:space:]]*[=:][[:space:]]*"[A-Za-z0-9._-]+"([[:space:]]*,[[:space:]]*version[[:space:]]*[=:][[:space:]]*"[^"]+")?' "$GRADLE_TMP" 2>/dev/null | while IFS= read -r _mline; do
        _mg=$(printf '%s' "$_mline" | sed -nE 's/.*group[[:space:]]*[=:][[:space:]]*"([^"]+)".*/\1/p') || _mg=""
        _ma=$(printf '%s' "$_mline" | sed -nE 's/.*name[[:space:]]*[=:][[:space:]]*"([^"]+)".*/\1/p') || _ma=""
        _mv=$(printf '%s' "$_mline" | sed -nE 's/.*version[[:space:]]*[=:][[:space:]]*"([^"]+)".*/\1/p') || _mv=""
        _emit_map_dep "$_mg" "$_ma" "$_mv"
      done || true
      # group then name (single-quoted)
      grep -oE "group[[:space:]]*[=:][[:space:]]*${_Q}[A-Za-z0-9._-]+${_Q}[[:space:]]*,[[:space:]]*name[[:space:]]*[=:][[:space:]]*${_Q}[A-Za-z0-9._-]+${_Q}([[:space:]]*,[[:space:]]*version[[:space:]]*[=:][[:space:]]*${_Q}[^${_Q}]+${_Q})?" "$GRADLE_TMP" 2>/dev/null | while IFS= read -r _mline; do
        _mg=$(printf '%s' "$_mline" | sed -nE "s/.*group[[:space:]]*[=:][[:space:]]*${_Q}([^${_Q}]+)${_Q}.*/\\1/p") || _mg=""
        _ma=$(printf '%s' "$_mline" | sed -nE "s/.*name[[:space:]]*[=:][[:space:]]*${_Q}([^${_Q}]+)${_Q}.*/\\1/p") || _ma=""
        _mv=$(printf '%s' "$_mline" | sed -nE "s/.*version[[:space:]]*[=:][[:space:]]*${_Q}([^${_Q}]+)${_Q}.*/\\1/p") || _mv=""
        _emit_map_dep "$_mg" "$_ma" "$_mv"
      done || true
      ;;

    pom.xml)
      # Per-<dependency> block extraction (#351): never pair global parallel
      # groupId/artifactId/version lists — a version-less dependency would shift
      # later versions onto earlier coordinates. Only <dependency>…</dependency>
      # spans are walked, so project/parent/plugin GAVs are skipped.
      REST=""
      REST=$(printf '%s\n' "$NEW_CONTENT") || REST=""
      while :; do
        case "$REST" in *"<dependency>"*) ;; *) break ;; esac
        AFTER="${REST#*<dependency>}"
        case "$AFTER" in *"</dependency>"*) ;; *) break ;; esac
        # %% peels through the first </dependency> (longest suffix match).
        DEP_BODY="${AFTER%%</dependency>*}"
        REST="${AFTER#*</dependency>}"
        GV=$(printf '%s' "$DEP_BODY" | grep -oE '<groupId>[A-Za-z0-9._-]+</groupId>' 2>/dev/null | head -n1 | sed 's|<groupId>||;s|</groupId>||') || GV=""
        AV=$(printf '%s' "$DEP_BODY" | grep -oE '<artifactId>[A-Za-z0-9._-]+</artifactId>' 2>/dev/null | head -n1 | sed 's|<artifactId>||;s|</artifactId>||') || AV=""
        # Version: any non-'<' chars (sanitize step strips non-literal/interpolated values)
        VV=$(printf '%s' "$DEP_BODY" | grep -oE '<version>[^<]+</version>' 2>/dev/null | head -n1 | sed 's|<version>||;s|</version>||') || VV=""
        if [ -n "$GV" ] && [ -n "$AV" ]; then
          if [ -n "$VV" ]; then
            printf '%s:%s:%s\n' "$GV" "$AV" "$VV" >> "$COORDS_FILE" || true
          else
            printf '%s:%s\n' "$GV" "$AV" >> "$COORDS_FILE" || true
          fi
        fi
      done
      ;;

    *.versions.toml)
      # TOML [libraries] tables use double-quoted strings only (single-quote strings
      # are not valid TOML syntax for these values).
      # module = "g:a" (most common form; [[:space:]] for POSIX ERE portability)
      printf '%s\n' "$NEW_CONTENT" | \
        grep -oE 'module[[:space:]]*=[[:space:]]*"[A-Za-z0-9._-]+:[A-Za-z0-9._-]+"' 2>/dev/null | \
        grep -oE '"[A-Za-z0-9._-]+:[A-Za-z0-9._-]+"' 2>/dev/null | \
        tr -d '"' >> "$COORDS_FILE" || true
      # "g:a:v" triples — version may be any non-quote chars; sanitize drops non-literals
      printf '%s\n' "$NEW_CONTENT" | \
        grep -oE '"[A-Za-z0-9._-]+:[A-Za-z0-9._-]+:[^"]+"' 2>/dev/null | \
        tr -d '"' >> "$COORDS_FILE" || true
      # [plugins] id = "com.foo" → marker com.foo:com.foo.gradle.plugin (#359)
      printf '%s\n' "$NEW_CONTENT" | \
        grep -oE 'id[[:space:]]*=[[:space:]]*"[A-Za-z0-9._-]+"' 2>/dev/null | while IFS= read -r _tid; do
          _pid=$(printf '%s' "$_tid" | sed -nE 's/.*id[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p') || _pid=""
          [ -n "$_pid" ] || continue
          printf '%s:%s.gradle.plugin\n' "$_pid" "$_pid" >> "$COORDS_FILE" || true
        done || true
      # [plugins] shorthand alias = "id:version" where version starts with a digit
      # (distinguishes from library "group:artifact" two-part shorthand).
      printf '%s\n' "$NEW_CONTENT" | \
        grep -oE '"[A-Za-z0-9._-]+:[0-9][^"]*"' 2>/dev/null | tr -d '"' | while IFS= read -r _tsh; do
          # Exactly two colon-separated components (id:version), not g:a:v
          case "$_tsh" in
            *:*:*) continue ;;
          esac
          _pid=$(printf '%s' "$_tsh" | cut -d: -f1) || _pid=""
          _pver=$(printf '%s' "$_tsh" | cut -d: -f2) || _pver=""
          [ -n "$_pid" ] && [ -n "$_pver" ] || continue
          printf '%s:%s.gradle.plugin:%s\n' "$_pid" "$_pid" "$_pver" >> "$COORDS_FILE" || true
        done || true
      ;;
  esac
fi

[ -n "$COORDS_FILE" ] || exit 0
[ -s "$COORDS_FILE" ] || exit 0

# ── Sanitize: charset filter, deduplicate, drop non-literal version → GA-only ─
# "Non-literal" means version contains $ (interpolation) → treat as GA-only.
# Charset: each component must be [A-Za-z0-9._-].
CLEAN_FILE="${TMPDIR_WORK}/clean.txt"
: > "$CLEAN_FILE"
while IFS= read -r COORD; do
  [ -n "$COORD" ] || continue
  # Split on ':'
  G=$(printf '%s' "$COORD" | cut -d: -f1) || G=""
  A=$(printf '%s' "$COORD" | cut -d: -f2) || A=""
  V=$(printf '%s' "$COORD" | cut -d: -f3) || V=""

  # Validate g and a with charset check
  G_CLEAN=$(printf '%s' "$G" | tr -cd 'A-Za-z0-9._-') || G_CLEAN=""
  A_CLEAN=$(printf '%s' "$A" | tr -cd 'A-Za-z0-9._-') || A_CLEAN=""

  [ -n "$G" ] || continue
  [ "$G_CLEAN" = "$G" ] || continue
  [ -n "$A" ] || continue
  [ "$A_CLEAN" = "$A" ] || continue

  # Version: if empty, contains $, or has chars outside [A-Za-z0-9._-] → GA-only
  if [ -n "$V" ]; then
    case "$V" in
      *\$*) V="" ;;
      *)
        V_CLEAN=$(printf '%s' "$V" | tr -cd 'A-Za-z0-9._-') || V_CLEAN=""
        [ "$V_CLEAN" = "$V" ] || V=""
        ;;
    esac
  fi

  if [ -n "$V" ]; then
    printf '%s:%s:%s\n' "$G" "$A" "$V" >> "$CLEAN_FILE" || true
  else
    printf '%s:%s\n' "$G" "$A" >> "$CLEAN_FILE" || true
  fi
done < "$COORDS_FILE"

[ -s "$CLEAN_FILE" ] || exit 0

# Deduplicate, cap at MAX_COORDS
DEDUP_FILE="${TMPDIR_WORK}/dedup.txt"
sort -u "$CLEAN_FILE" 2>/dev/null | head -n "$MAX_COORDS" > "$DEDUP_FILE" || exit 0

[ -s "$DEDUP_FILE" ] || exit 0

# ── Resolve timeout command ────────────────────────────────────────────────────
TIMEOUT_CMD=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_CMD="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_CMD="gtimeout"
fi
# No timeout available → fail-open: skip the python call entirely.
[ -n "$TIMEOUT_CMD" ] || exit 0

# python3 must be present
command -v python3 >/dev/null 2>&1 || exit 0

# ── Build JSON-RPC requests ───────────────────────────────────────────────────
# CWD from hook input for projectPath
CWD=""
CWD=$(printf '%s' "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null) || CWD=""

# Build dependency array for verify_coordinates (all coords, GA or versioned)
DEPS_VERIFY=""
DEPS_VERIFY=$(
  while IFS= read -r COORD; do
    [ -n "$COORD" ] || continue
    G=$(printf '%s' "$COORD" | cut -d: -f1)
    A=$(printf '%s' "$COORD" | cut -d: -f2)
    V=$(printf '%s' "$COORD" | cut -d: -f3)
    if [ -n "$V" ]; then
      jq -c -n --arg g "$G" --arg a "$A" --arg v "$V" \
        '{groupId:$g,artifactId:$a,version:$v}' 2>/dev/null || true
    else
      jq -c -n --arg g "$G" --arg a "$A" \
        '{groupId:$g,artifactId:$a}' 2>/dev/null || true
    fi
  done < "$DEDUP_FILE"
) || DEPS_VERIFY=""

[ -n "$DEPS_VERIFY" ] || exit 0

# Wrap into array
DEPS_VERIFY_ARR=""
DEPS_VERIFY_ARR=$(printf '%s\n' "$DEPS_VERIFY" | jq -sc '.' 2>/dev/null) || DEPS_VERIFY_ARR=""
[ -n "$DEPS_VERIFY_ARR" ] || exit 0

# Build verify_coordinates request (id:1)
REQ1=""
if [ -n "$CWD" ]; then
  REQ1=$(jq -c -n \
    --argjson deps "$DEPS_VERIFY_ARR" \
    --arg cwd "$CWD" \
    '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"verify_coordinates","arguments":{"dependencies":$deps,"projectPath":$cwd}}}' \
    2>/dev/null) || REQ1=""
else
  REQ1=$(jq -c -n \
    --argjson deps "$DEPS_VERIFY_ARR" \
    '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"verify_coordinates","arguments":{"dependencies":$deps}}}' \
    2>/dev/null) || REQ1=""
fi
[ -n "$REQ1" ] || exit 0

# Build versioned-only dependency array for get_dependency_vulnerabilities (id:2)
# Only versioned coords; handle_get_dependency_vulnerabilities does hard args["dependencies"].
DEPS_VULN=""
DEPS_VULN=$(
  while IFS= read -r COORD; do
    [ -n "$COORD" ] || continue
    V=$(printf '%s' "$COORD" | cut -d: -f3)
    [ -n "$V" ] || continue
    G=$(printf '%s' "$COORD" | cut -d: -f1)
    A=$(printf '%s' "$COORD" | cut -d: -f2)
    jq -c -n --arg g "$G" --arg a "$A" --arg v "$V" \
      '{groupId:$g,artifactId:$a,version:$v}' 2>/dev/null || true
  done < "$DEDUP_FILE"
) || DEPS_VULN=""

DEPS_VULN_ARR=""
REQ2=""
if [ -n "$DEPS_VULN" ]; then
  DEPS_VULN_ARR=$(printf '%s\n' "$DEPS_VULN" | jq -sc '.' 2>/dev/null) || DEPS_VULN_ARR=""
  if [ -n "$DEPS_VULN_ARR" ]; then
    if [ -n "$CWD" ]; then
      REQ2=$(jq -c -n \
        --argjson deps "$DEPS_VULN_ARR" \
        --arg cwd "$CWD" \
        '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_dependency_vulnerabilities","arguments":{"dependencies":$deps,"projectPath":$cwd}}}' \
        2>/dev/null) || REQ2=""
    else
      REQ2=$(jq -c -n \
        --argjson deps "$DEPS_VULN_ARR" \
        '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_dependency_vulnerabilities","arguments":{"dependencies":$deps}}}' \
        2>/dev/null) || REQ2=""
    fi
  fi
fi

# ── Invoke server; scrub GITHUB_TOKEN from spawned env ───────────────────────
REQUESTS="${REQ1}"
[ -n "$REQ2" ] && REQUESTS="${REQ1}
${REQ2}"

SERVER_OUTPUT=""
SERVER_OUTPUT=$(
  printf '%s\n' "$REQUESTS" | \
    env -u GITHUB_TOKEN \
    "$TIMEOUT_CMD" 8 python3 "${CLAUDE_PLUGIN_ROOT}/server/server.py" 2>/dev/null
) || SERVER_OUTPUT=""

[ -n "$SERVER_OUTPUT" ] || exit 0

# ── Unwrap responses by id-matching (not line order) ─────────────────────────
RESP1=""
RESP1=$(printf '%s\n' "$SERVER_OUTPUT" | \
  jq -c 'select(.id==1)' 2>/dev/null | head -n1) || RESP1=""

RESP2=""
if [ -n "$REQ2" ]; then
  RESP2=$(printf '%s\n' "$SERVER_OUTPUT" | \
    jq -c 'select(.id==2)' 2>/dev/null | head -n1) || RESP2=""
fi

# Extract tool result payload; .error or missing .result → fail-open for that tool
VERIFY_RESULT=""
if [ -n "$RESP1" ]; then
  VERIFY_RESULT=$(printf '%s' "$RESP1" | \
    jq -r 'if .error or (.result==null) then empty else .result.content[0].text end' 2>/dev/null | \
    jq '.' 2>/dev/null) || VERIFY_RESULT=""
fi

VULN_RESULT=""
if [ -n "$RESP2" ]; then
  VULN_RESULT=$(printf '%s' "$RESP2" | \
    jq -r 'if .error or (.result==null) then empty else .result.content[0].text end' 2>/dev/null | \
    jq '.' 2>/dev/null) || VULN_RESULT=""
fi

# ── Decision assembly ──────────────────────────────────────────────────────────
# Accumulate findings. deny wins over ask.
DECISION=""
REASONS_FILE="${TMPDIR_WORK}/reasons.txt"
: > "$REASONS_FILE"

# ── Check existence results ───────────────────────────────────────────────────
# Act only on absent AND likelyHallucination==true (score ≥ HALLUCINATION_THRESHOLD).
# Non-empty suggestions alone must NOT deny — verify_coordinates historically
# populated suggestions for every Solr hit regardless of score, which made this
# branch de-facto bare-absent denial for private/new coords (#352). Suggestions
# are still shown in the reason when present (server now threshold-filters them).
# NEVER act on "exists" or "unknown". See plan §Decisions #4 / #352.
if [ -n "$VERIFY_RESULT" ]; then
  COUNT=0
  COUNT=$(printf '%s' "$VERIFY_RESULT" | jq '.results | length' 2>/dev/null) || COUNT=0
  IDX=0
  while [ "$IDX" -lt "$COUNT" ] 2>/dev/null; do
    ITEM=""
    ITEM=$(printf '%s' "$VERIFY_RESULT" | jq -c ".results[$IDX]" 2>/dev/null) || ITEM=""
    [ -n "$ITEM" ] || { IDX=$((IDX+1)); continue; }

    STATUS=""
    STATUS=$(printf '%s' "$ITEM" | jq -r '.existenceStatus // empty' 2>/dev/null) || STATUS=""

    if [ "$STATUS" = "absent" ]; then
      HALLUC=""
      HALLUC=$(printf '%s' "$ITEM" | jq -r '.likelyHallucination // "false"' 2>/dev/null) || HALLUC="false"

      if [ "$HALLUC" = "true" ]; then
        # Build reason — only structured fields, no raw network text
        GA=""
        GA=$(printf '%s' "$ITEM" | jq -r '"\(.groupId // ""):\(.artifactId // "")"' 2>/dev/null) || GA=""
        GA=$(printf '%s' "$GA" | tr -cd 'A-Za-z0-9._:-') || GA=""

        SUGG_TEXT=""
        SUGG_COUNT=0
        SUGG_COUNT=$(printf '%s' "$ITEM" | jq '.suggestions | length // 0' 2>/dev/null) || SUGG_COUNT=0
        if [ "$SUGG_COUNT" -gt 0 ] 2>/dev/null; then
          # Charset-filter suggestion coordinates before embedding
          SUGG_TEXT=$(printf '%s' "$ITEM" | jq -r \
            '.suggestions[0:3][] | "\(.groupId // ""):\(.artifactId // "") (versionCount=\(.versionCount // 0))"' \
            2>/dev/null | tr -cd 'A-Za-z0-9._:=()\n -') || SUGG_TEXT=""
        fi

        REASON_LINE=""
        if [ -n "$SUGG_TEXT" ]; then
          REASON_LINE=$(printf '%s not found in resolved repositories. If you intended a real package, verify candidates before use:\n%s' "$GA" "$SUGG_TEXT")
        else
          REASON_LINE=$(printf '%s not found in resolved repositories; likely hallucinated coordinate.' "$GA")
        fi
        printf '%s\n' "$REASON_LINE" >> "$REASONS_FILE" || true
        DECISION="deny"
      fi
    elif [ "$STATUS" = "exists" ]; then
      # ── typosquatRisk heuristic (#322 Layer 2) — advisory `ask` only ───────
      # Lives in the SAME per-coordinate loop as the absent+hallucination deny
      # check above: the guard below is what prevents a LATER coordinate's
      # heuristic ask from silently downgrading an EARLIER coordinate's deny
      # within this same batch.
      TR_SIGNAL=""
      TR_SIGNAL=$(printf '%s' "$ITEM" | jq -r '.typosquatRisk.signal // "false"' 2>/dev/null) || TR_SIGNAL="false"

      if [ "$TR_SIGNAL" = "true" ]; then
        GA=""
        GA=$(printf '%s' "$ITEM" | jq -r '"\(.groupId // ""):\(.artifactId // "")"' 2>/dev/null) || GA=""
        GA=$(printf '%s' "$GA" | tr -cd 'A-Za-z0-9._:-') || GA=""

        TR_REASONS=""
        TR_REASONS=$(printf '%s' "$ITEM" | jq -r '(.typosquatRisk.reasons // []) | join(", ")' 2>/dev/null) || TR_REASONS=""
        TR_REASONS=$(printf '%s' "$TR_REASONS" | tr -cd 'A-Za-z0-9._, ') || TR_REASONS=""

        # popularMatch originates from the same Solr search results as
        # `suggestions` and is equally attacker-influenceable in principle —
        # REQUIRED identical charset filter before it enters the reason text.
        POPULAR_TEXT=""
        HAS_POPULAR=""
        HAS_POPULAR=$(printf '%s' "$ITEM" | jq -r 'if .typosquatRisk.popularMatch then "yes" else empty end' 2>/dev/null) || HAS_POPULAR=""
        if [ -n "$HAS_POPULAR" ]; then
          POPULAR_TEXT=$(printf '%s' "$ITEM" | jq -r \
            '"\(.typosquatRisk.popularMatch.groupId // ""):\(.typosquatRisk.popularMatch.artifactId // "")"' \
            2>/dev/null) || POPULAR_TEXT=""
          POPULAR_TEXT=$(printf '%s' "$POPULAR_TEXT" | tr -cd 'A-Za-z0-9._:-') || POPULAR_TEXT=""
        fi

        REASON_LINE=""
        if [ -n "$POPULAR_TEXT" ]; then
          REASON_LINE=$(printf '%s exists but shows a typosquat/popularity risk signal (%s); a more popular candidate under a different group is %s. Verify this is the package you intended before use.' \
            "$GA" "$TR_REASONS" "$POPULAR_TEXT")
        else
          REASON_LINE=$(printf '%s exists but shows a typosquat/popularity risk signal (%s). Verify this is the package you intended before use.' \
            "$GA" "$TR_REASONS")
        fi
        printf '%s\n' "$REASON_LINE" >> "$REASONS_FILE" || true

        # deny wins over ask; only set ask if decision not already deny —
        # SAME guard the existing CRITICAL/HIGH branch uses.
        [ "$DECISION" = "deny" ] || DECISION="ask"
      fi
    fi
    IDX=$((IDX+1))
  done
fi

# ── Check vulnerability results ───────────────────────────────────────────────
# Only CRITICAL/HIGH → ask (deny wins if already set from existence check)
if [ -n "$VULN_RESULT" ]; then
  COUNT=0
  COUNT=$(printf '%s' "$VULN_RESULT" | jq '.results | length' 2>/dev/null) || COUNT=0
  IDX=0
  while [ "$IDX" -lt "$COUNT" ] 2>/dev/null; do
    ITEM=""
    ITEM=$(printf '%s' "$VULN_RESULT" | jq -c ".results[$IDX]" 2>/dev/null) || ITEM=""
    [ -n "$ITEM" ] || { IDX=$((IDX+1)); continue; }

    # ── Malicious-package check (#322 Layer 1) — UNCONDITIONAL deny ──────────
    # Runs independent of, and regardless of ordering relative to, the
    # severity-based CRITICAL/HIGH scan below: MAL- entries carry no CVSS
    # severity (querybatch never hydrates it), so the severity branch alone
    # would never catch this even once its own hydration gap is fixed.
    # UNCONDITIONAL (never behind a `[ -z "$DECISION" ]`-style guard) is what
    # correctly upgrades a prior `ask` (from the CRITICAL/HIGH branch below, or
    # from the typosquatRisk branch above) to `deny` when both fire for the
    # same coordinate.
    MAL_COUNT=0
    MAL_COUNT=$(printf '%s' "$ITEM" | jq -r \
      '[.vulnerabilities[]? | select(.malicious == true)] | length' \
      2>/dev/null) || MAL_COUNT=0

    if [ "$MAL_COUNT" -gt 0 ] 2>/dev/null; then
      GA=""
      GA=$(printf '%s' "$ITEM" | jq -r '"\(.groupId // ""):\(.artifactId // ""):\(.version // "")"' 2>/dev/null) || GA=""
      GA=$(printf '%s' "$GA" | tr -cd 'A-Za-z0-9._:-') || GA=""

      MAL_ID=""
      MAL_ID=$(printf '%s' "$ITEM" | jq -r \
        '[.vulnerabilities[]? | select(.malicious == true)][0].id // ""' \
        2>/dev/null) || MAL_ID=""
      MAL_ID=$(printf '%s' "$MAL_ID" | tr -cd 'A-Za-z0-9._:-') || MAL_ID=""

      REASON_LINE=""
      REASON_LINE=$(printf '%s is flagged as a malicious package (%s) by OSSF Malicious Packages. Do not use this dependency.' \
        "$GA" "$MAL_ID")
      printf '%s\n' "$REASON_LINE" >> "$REASONS_FILE" || true

      DECISION="deny"
    fi

    # Find CRITICAL or HIGH vulns
    SEVS=""
    SEVS=$(printf '%s' "$ITEM" | jq -r \
      '[.vulnerabilities[]? | select(.severity=="CRITICAL" or .severity=="HIGH")] | length' \
      2>/dev/null) || SEVS=0

    if [ "$SEVS" -gt 0 ] 2>/dev/null; then
      GA=""
      GA=$(printf '%s' "$ITEM" | jq -r '"\(.groupId // ""):\(.artifactId // ""):\(.version // "")"' 2>/dev/null) || GA=""
      GA=$(printf '%s' "$GA" | tr -cd 'A-Za-z0-9._:-') || GA=""

      # First CRITICAL/HIGH vuln info (id + fixedVersion)
      VULN_ID=""
      VULN_ID=$(printf '%s' "$ITEM" | jq -r \
        '[.vulnerabilities[]? | select(.severity=="CRITICAL" or .severity=="HIGH")][0].id // ""' \
        2>/dev/null) || VULN_ID=""
      VULN_ID=$(printf '%s' "$VULN_ID" | tr -cd 'A-Za-z0-9._:-') || VULN_ID=""

      SEV_LABEL=""
      SEV_LABEL=$(printf '%s' "$ITEM" | jq -r \
        '[.vulnerabilities[]? | select(.severity=="CRITICAL" or .severity=="HIGH")][0].severity // ""' \
        2>/dev/null) || SEV_LABEL=""
      SEV_LABEL=$(printf '%s' "$SEV_LABEL" | tr -cd 'A-Za-z0-9') || SEV_LABEL=""

      FIXED=""
      FIXED=$(printf '%s' "$ITEM" | jq -r \
        '[.vulnerabilities[]? | select(.severity=="CRITICAL" or .severity=="HIGH")][0].fixedVersion // ""' \
        2>/dev/null) || FIXED=""
      FIXED=$(printf '%s' "$FIXED" | tr -cd 'A-Za-z0-9._-') || FIXED=""

      REASON_LINE=""
      if [ -n "$FIXED" ]; then
        REASON_LINE=$(printf '%s has a %s vulnerability (%s); fixed in %s. Verify whether this version is intentional.' \
          "$GA" "$SEV_LABEL" "$VULN_ID" "$FIXED")
      else
        REASON_LINE=$(printf '%s has a %s vulnerability (%s); no known fix version. Verify whether this version is intentional.' \
          "$GA" "$SEV_LABEL" "$VULN_ID")
      fi
      printf '%s\n' "$REASON_LINE" >> "$REASONS_FILE" || true

      # deny wins over ask; only set ask if decision not already deny
      [ "$DECISION" = "deny" ] || DECISION="ask"
    fi
    IDX=$((IDX+1))
  done
fi

# ── Emit result ───────────────────────────────────────────────────────────────
# If no actionable finding → exit 0 with no stdout (normal allow flow).
[ -n "$DECISION" ] || exit 0
[ -s "$REASONS_FILE" ] || exit 0

# Build combined reason string from all findings
COMBINED_REASON=""
COMBINED_REASON=$(jq -Rs '.' "$REASONS_FILE" 2>/dev/null) || COMBINED_REASON='""'

# Emit hook decision JSON (single printf, nothing else to stdout)
printf '%s' "$(jq -c -n \
  --arg decision "$DECISION" \
  --argjson reason "$COMBINED_REASON" \
  '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":$decision,"permissionDecisionReason":$reason}}' \
  2>/dev/null)"

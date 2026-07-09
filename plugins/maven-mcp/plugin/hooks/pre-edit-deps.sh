#!/usr/bin/env bash
# pre-edit-deps.sh — PreToolUse write-time dependency guard for maven-mcp.
#
# Checks NEW coordinates being added to a build file for:
#   - Non-existent / likely-hallucinated coords (absent + likelyHallucination or suggestion)  → deny
#   - CRITICAL/HIGH CVEs on a pinned version                                                   → ask
# Any uncertainty, failure, or network error → fail-open (edit proceeds).
#
# IMPORTANT — existence guard scope: the guard is Maven-Central-scoped.
# A coordinate that 404s across ALL probed repos is "absent" but may be a
# legitimate private/internal/androidx dependency with no Central suggestion.
# We therefore only act on "absent" when likelyHallucination==true OR
# non-empty suggestions exist. NEVER tighten this to bare-absent denial —
# that would false-block real private dependencies. See plan §Decisions #4.
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

case "$BASENAME" in
  build.gradle|build.gradle.kts|settings.gradle|settings.gradle.kts|pom.xml|libs.versions.toml) ;;
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
      ;;

    pom.xml)
      # Match groupId+artifactId pairs; require both present in the fragment.
      # Extract groupId and artifactId separately, then pair them.
      G_FILE="${TMPDIR_WORK}/pom_g.txt"
      A_FILE="${TMPDIR_WORK}/pom_a.txt"
      V_FILE="${TMPDIR_WORK}/pom_v.txt"
      printf '%s\n' "$NEW_CONTENT" | grep -oE '<groupId>[A-Za-z0-9._-]+</groupId>' 2>/dev/null | sed 's|<groupId>||;s|</groupId>||' > "$G_FILE" || true
      printf '%s\n' "$NEW_CONTENT" | grep -oE '<artifactId>[A-Za-z0-9._-]+</artifactId>' 2>/dev/null | sed 's|<artifactId>||;s|</artifactId>||' > "$A_FILE" || true
      # Version: any non-'<' chars (sanitize step strips non-literal/interpolated values)
      printf '%s\n' "$NEW_CONTENT" | grep -oE '<version>[^<]+</version>' 2>/dev/null | sed 's|<version>||;s|</version>||' > "$V_FILE" || true
      # Pair line-by-line: requires same count (g, a, [v]).
      G_COUNT=0
      A_COUNT=0
      G_COUNT=$(wc -l < "$G_FILE" 2>/dev/null || printf '0') || G_COUNT=0
      A_COUNT=$(wc -l < "$A_FILE" 2>/dev/null || printf '0') || A_COUNT=0
      G_COUNT=$(printf '%s' "$G_COUNT" | tr -d ' \n') || G_COUNT=0
      A_COUNT=$(printf '%s' "$A_COUNT" | tr -d ' \n') || A_COUNT=0
      if [ "$G_COUNT" -eq "$A_COUNT" ] && [ "$G_COUNT" -gt 0 ] 2>/dev/null; then
        IDX=1
        while [ "$IDX" -le "$G_COUNT" ]; do
          GV=$(sed -n "${IDX}p" "$G_FILE" 2>/dev/null) || GV=""
          AV=$(sed -n "${IDX}p" "$A_FILE" 2>/dev/null) || AV=""
          VV=$(sed -n "${IDX}p" "$V_FILE" 2>/dev/null) || VV=""
          if [ -n "$GV" ] && [ -n "$AV" ]; then
            if [ -n "$VV" ]; then
              printf '%s:%s:%s\n' "$GV" "$AV" "$VV" >> "$COORDS_FILE" || true
            else
              printf '%s:%s\n' "$GV" "$AV" >> "$COORDS_FILE" || true
            fi
          fi
          IDX=$((IDX + 1))
        done
      fi
      ;;

    libs.versions.toml)
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
# Act only on absent AND (likelyHallucination==true OR non-empty suggestions).
# NEVER act on "exists" or "unknown". See plan §Decisions #4.
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
      SUGG_COUNT=0
      SUGG_COUNT=$(printf '%s' "$ITEM" | jq '.suggestions | length // 0' 2>/dev/null) || SUGG_COUNT=0

      if [ "$HALLUC" = "true" ] || [ "$SUGG_COUNT" -gt 0 ] 2>/dev/null; then
        # Build reason — only structured fields, no raw network text
        GA=""
        GA=$(printf '%s' "$ITEM" | jq -r '"\(.groupId // ""):\(.artifactId // "")"' 2>/dev/null) || GA=""
        GA=$(printf '%s' "$GA" | tr -cd 'A-Za-z0-9._:-') || GA=""

        SUGG_TEXT=""
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

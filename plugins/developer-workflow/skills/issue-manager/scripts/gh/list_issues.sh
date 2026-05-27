#!/bin/bash
# list_issues.sh — list GitHub issues with optional filters and output a JSON array.
#
# USAGE:
#   list_issues.sh [OPTIONS] [-R <owner/repo>]
#
# OPTIONS (all optional; defaults: state=open, limit=30):
#   --state <open|closed|all>      Filter by state (default: open)
#   --label <name>                 Filter by label name (repeatable)
#   --limit <n>                    Max number of issues to return (default: 30)
#   --numbers <n1,n2,...>          Fetch only these specific issue numbers (overrides other filters)
#   -R <owner/repo>                Target repository (default: current repo from git)
#
# OUTPUT (stdout, JSON):
#   Success: JSON array of issue objects. Each object:
#     {
#       "number":  <int>,
#       "title":   <string>,
#       "state":   "OPEN"|"CLOSED",
#       "labels":  [{"id":<string>,"name":<string>,"color":<string>},...],
#       "url":     <string>,
#       "node_id": <string>
#     }
#   Note: body is omitted for list output to keep payloads compact.
#         Use fetch_issue.sh to retrieve the full body of a specific issue.
#
#   Error:
#     {"error":<string>,"code":<string>}
#   Exit code is non-zero on error.

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

im_error() {
  local msg="$1" code="${2:-unknown}"
  printf '{"error":%s,"code":%s}\n' "$(printf '%s' "$msg" | jq -Rs .)" "$(printf '%s' "$code" | jq -Rs .)"
}

im_resolve_repo() {
  out=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>&1); rc=$?
  if [[ $rc -ne 0 ]]; then
    im_error "Cannot resolve repo: $out" "repo_resolve_failed"
    exit 1
  fi
  printf '%s' "$out"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

REPO=""
STATE="open"
LIMIT="30"
LABELS=()
NUMBERS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -R)          REPO="$2"; shift 2 ;;
    --state)     STATE="$2"; shift 2 ;;
    --label)     LABELS+=("$2"); shift 2 ;;
    --limit)     LIMIT="$2"; shift 2 ;;
    --numbers)   NUMBERS="$2"; shift 2 ;;
    *)           im_error "Unknown flag: $1" "usage"; exit 1 ;;
  esac
done

if [[ -z "$REPO" ]]; then
  REPO=$(im_resolve_repo)
fi

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

if [[ -n "$NUMBERS" ]]; then
  # Fetch each numbered issue individually and merge into array.
  IFS=',' read -ra NUMLIST <<< "$NUMBERS"
  results="[]"
  for n in "${NUMLIST[@]}"; do
    n="${n// /}"
    [[ -z "$n" ]] && continue
    if [[ ! "$n" =~ ^[0-9]+$ ]]; then
      im_error "Invalid issue number: $n" "invalid_ref"
      exit 1
    fi
    out=$(gh issue view "$n" -R "$REPO" \
      --json id,number,title,state,labels,url 2>&1); rc=$?
    if [[ $rc -ne 0 ]]; then
      im_error "$out" "gh_failed"
      exit 1
    fi
    item=$(printf '%s' "$out" | jq '{
      number:  .number,
      title:   .title,
      state:   .state,
      labels:  [.labels[] | {id: .id, name: .name, color: .color}],
      url:     .url,
      node_id: .id
    }')
    results=$(printf '%s' "$results" | jq --argjson item "$item" '. + [$item]')
  done
  printf '%s\n' "$results"
  exit 0
fi

# Build label flags
LABEL_FLAGS=()
for lbl in "${LABELS[@]+"${LABELS[@]}"}"; do
  LABEL_FLAGS+=("--label" "$lbl")
done

out=$(gh issue list -R "$REPO" \
  --state "$STATE" \
  --limit "$LIMIT" \
  "${LABEL_FLAGS[@]+"${LABEL_FLAGS[@]}"}" \
  --json id,number,title,state,labels,url 2>&1); rc=$?

if [[ $rc -ne 0 ]]; then
  im_error "$out" "gh_failed"
  exit 1
fi

printf '%s' "$out" | jq '[.[] | {
  number:  .number,
  title:   .title,
  state:   .state,
  labels:  [.labels[] | {id: .id, name: .name, color: .color}],
  url:     .url,
  node_id: .id
}]'

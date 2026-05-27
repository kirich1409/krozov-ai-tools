#!/bin/bash
# fetch_issue.sh — fetch a single GitHub issue by ref and output JSON.
#
# USAGE:
#   fetch_issue.sh <issue-ref> [-R <owner/repo>]
#
# <issue-ref> accepts:
#   - plain number:              206
#   - owner/repo#number:         kirich1409/krozov-ai-tools#206
#   - full URL:                  https://github.com/kirich1409/krozov-ai-tools/issues/206
#
# -R <owner/repo>  Override repository (takes precedence over ref-embedded repo).
#                  If omitted, resolved from ref or from `gh repo view`.
#
# OUTPUT (stdout, JSON):
#   Success:
#     {
#       "number":   <int>,
#       "title":    <string>,
#       "state":    "OPEN"|"CLOSED",
#       "body":     <string>,
#       "labels":   [{"id":<string>,"name":<string>,"color":<string>},...],
#       "url":      <string>,
#       "node_id":  <string>   -- GraphQL global node id (e.g. "I_kwDO...")
#     }
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

im_parse_ref() {
  # Sets globals: IM_NUMBER, IM_REPO (may be empty)
  local ref="$1"
  IM_NUMBER=""
  IM_REPO=""

  if [[ "$ref" =~ ^https?://github\.com/([^/]+/[^/]+)/issues/([0-9]+) ]]; then
    IM_REPO="${BASH_REMATCH[1]}"
    IM_NUMBER="${BASH_REMATCH[2]}"
  elif [[ "$ref" =~ ^([^#]+)#([0-9]+)$ ]]; then
    IM_REPO="${BASH_REMATCH[1]}"
    IM_NUMBER="${BASH_REMATCH[2]}"
  elif [[ "$ref" =~ ^([0-9]+)$ ]]; then
    IM_NUMBER="${BASH_REMATCH[1]}"
  else
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
  im_error "Usage: fetch_issue.sh <issue-ref> [-R <owner/repo>]" "usage"
  exit 1
fi

RAW_REF="$1"
shift
REPO_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -R) REPO_OVERRIDE="$2"; shift 2 ;;
    *)  im_error "Unknown flag: $1" "usage"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Resolve repo and number
# ---------------------------------------------------------------------------

if ! im_parse_ref "$RAW_REF"; then
  im_error "Cannot parse issue ref: $RAW_REF" "invalid_ref"
  exit 1
fi

if [[ -n "$REPO_OVERRIDE" ]]; then
  IM_REPO="$REPO_OVERRIDE"
fi

if [[ -z "$IM_REPO" ]]; then
  out=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>&1); rc=$?
  if [[ $rc -ne 0 ]]; then
    im_error "Cannot resolve repo: $out" "repo_resolve_failed"
    exit 1
  fi
  IM_REPO="$out"
fi

if [[ -z "$IM_NUMBER" ]]; then
  im_error "No issue number in ref: $RAW_REF" "invalid_ref"
  exit 1
fi

REPO_OWNER="${IM_REPO%%/*}"
REPO_NAME="${IM_REPO##*/}"

# ---------------------------------------------------------------------------
# Fetch via REST (gh issue view)
# ---------------------------------------------------------------------------

out=$(gh issue view "$IM_NUMBER" -R "$IM_REPO" \
  --json id,number,title,state,body,labels,url 2>&1); rc=$?

if [[ $rc -ne 0 ]]; then
  im_error "$out" "gh_failed"
  exit 1
fi

# Remap: gh uses "id" for the GraphQL node id; expose as "node_id" for clarity.
result=$(printf '%s' "$out" | jq '{
  number:  .number,
  title:   .title,
  state:   .state,
  body:    .body,
  labels:  [.labels[] | {id: .id, name: .name, color: .color}],
  url:     .url,
  node_id: .id
}')

printf '%s\n' "$result"

#!/bin/bash
# get_dependencies.sh — derive dependency edges for a GitHub issue.
#
# USAGE:
#   get_dependencies.sh <issue-ref> [-R <owner/repo>]
#
# <issue-ref> accepts: plain number, owner/repo#number, or full URL.
# -R <owner/repo>  Override repository.
#
# SOURCES (both are always queried and merged):
#   A. GitHub sub-issues via GraphQL `subIssues` field (uses issue global node id).
#      Note: no special GraphQL-Features header required — field is GA.
#   B. Regex parse of issue body + all comments for:
#        "blocked by #N"   (case-insensitive)
#        "depends on #N"   (case-insensitive)
#      Both imply: issue <this> is blocked by issue <N>.
#
# EDGE DIRECTION:
#   from = the issue that is blocked / depends on another
#   to   = the blocker / dependency
#   A "from" issue cannot proceed until "to" is done.
#
# OUTPUT (stdout, JSON):
#   Success:
#     [
#       {
#         "from":   <int>,   -- blocked issue number
#         "to":     <int>,   -- blocker issue number
#         "source": "sub-issue" | "blocked-by" | "depends-on"
#       },
#       ...
#     ]
#   Empty result when no edges found: []
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

im_parse_ref() {
  IM_NUMBER=""
  IM_REPO=""
  local ref="$1"
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

im_check_graphql_errors() {
  local response="$1"
  if printf '%s' "$response" | jq -e '.errors' >/dev/null 2>&1; then
    local errmsg
    errmsg=$(printf '%s' "$response" | jq -r '.errors[0].message // "GraphQL error"')
    im_error "$errmsg" "graphql_error"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
  im_error "Usage: get_dependencies.sh <issue-ref> [-R <owner/repo>]" "usage"
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
THIS_NUMBER="$IM_NUMBER"

# ---------------------------------------------------------------------------
# Fetch issue data (node_id, body, comments)
# ---------------------------------------------------------------------------

out=$(gh issue view "$THIS_NUMBER" -R "$IM_REPO" \
  --json id,body,comments 2>&1); rc=$?
if [[ $rc -ne 0 ]]; then
  im_error "$out" "gh_failed"
  exit 1
fi

NODE_ID=$(printf '%s' "$out" | jq -r '.id')
BODY=$(printf '%s' "$out" | jq -r '.body // ""')
COMMENTS_TEXT=$(printf '%s' "$out" | jq -r '[.comments[].body] | join("\n")' 2>/dev/null || echo "")

# ---------------------------------------------------------------------------
# Source A: sub-issues via GraphQL
# Note: subIssues returns issues that are children of this issue.
# A sub-issue's parent is the blocker/dependency; the sub-issue depends on its parent
# completing context — but in GitHub sub-issues model, parent contains sub-issues.
# We emit: sub-issue depends-on (is a child of) parent. Direction: from=sub to=parent.
# However the spec requests: from=blocked, to=blocker.
# GitHub sub-issues: parent CONTAINS sub-issues. Sub-issues are tasks within parent.
# We represent: parent blocks sub-issues? No — the conventional reading is sub-issues
# must be done for parent to complete. So sub-issue -> parent would be "enables", not "blocks".
# Per spec the direction chosen: sub-issue IS a dependency edge where THIS issue has sub-issues
# that must be completed. We emit: from=sub-issue-number, to=THIS (meaning sub blocks parent).
# ---------------------------------------------------------------------------

graphql_query='query($nodeId:ID!){
  node(id:$nodeId){
    ... on Issue {
      subIssues(first:50){
        nodes{ number }
      }
    }
  }
}'

gql_out=$(gh api graphql \
  -f query="$graphql_query" \
  -F nodeId="$NODE_ID" 2>&1); rc=$?

if [[ $rc -ne 0 ]]; then
  im_error "$gql_out" "graphql_failed"
  exit 1
fi

im_check_graphql_errors "$gql_out"

# Build sub-issue edges: sub-issue depends on (from=sub, to=parent)
SUBISSUE_EDGES=$(printf '%s' "$gql_out" | jq --argjson parent "$THIS_NUMBER" \
  '[.data.node.subIssues.nodes[]? | {from: .number, to: $parent, source: "sub-issue"}]')

# ---------------------------------------------------------------------------
# Source B: regex parse — "blocked by #N" and "depends on #N"
# Both patterns in body and comments mean THIS issue is blocked by issue N.
# Edge: from=THIS, to=N
# ---------------------------------------------------------------------------

# Combine body + comments into one text blob for scanning
ALL_TEXT="${BODY}
${COMMENTS_TEXT}"

BLOCKED_BY_NUMS=$(printf '%s' "$ALL_TEXT" | \
  { grep -ioE 'blocked[[:space:]]+by[[:space:]]+#([0-9]+)' || true; } | \
  { grep -oE '[0-9]+$' || true; } | sort -un)

DEPENDS_ON_NUMS=$(printf '%s' "$ALL_TEXT" | \
  { grep -ioE 'depends[[:space:]]+on[[:space:]]+#([0-9]+)' || true; } | \
  { grep -oE '[0-9]+$' || true; } | sort -un)

# Build blocked-by edges
BLOCKED_EDGES="[]"
while IFS= read -r n; do
  [[ -z "$n" ]] && continue
  edge=$(jq -n --argjson from "$THIS_NUMBER" --argjson to "$n" \
    '{from:$from,to:$to,source:"blocked-by"}')
  BLOCKED_EDGES=$(printf '%s' "$BLOCKED_EDGES" | jq --argjson e "$edge" '. + [$e]')
done <<< "$BLOCKED_BY_NUMS"

# Build depends-on edges
DEPENDS_EDGES="[]"
while IFS= read -r n; do
  [[ -z "$n" ]] && continue
  edge=$(jq -n --argjson from "$THIS_NUMBER" --argjson to "$n" \
    '{from:$from,to:$to,source:"depends-on"}')
  DEPENDS_EDGES=$(printf '%s' "$DEPENDS_EDGES" | jq --argjson e "$edge" '. + [$e]')
done <<< "$DEPENDS_ON_NUMS"

# ---------------------------------------------------------------------------
# Merge all edges and deduplicate by (from,to,source)
# ---------------------------------------------------------------------------

MERGED=$(jq -n \
  --argjson a "$SUBISSUE_EDGES" \
  --argjson b "$BLOCKED_EDGES" \
  --argjson c "$DEPENDS_EDGES" \
  '($a + $b + $c) | unique_by({from,to,source})')

printf '%s\n' "$MERGED"

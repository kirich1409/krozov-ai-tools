#!/bin/bash
# get_completion_signal.sh — derive the completion signal for a GitHub issue
#                            based on its linked/cross-referenced pull requests.
#
# USAGE:
#   get_completion_signal.sh <issue-ref> [-R <owner/repo>]
#
# <issue-ref> accepts: plain number, owner/repo#number, or full URL.
# -R <owner/repo>  Override repository.
#
# LOGIC:
#   Uses `gh issue view --json closedByPullRequestsReferences` to get PRs that
#   closed this issue, plus cross-referenced PRs from the timeline.
#
#   Signal derivation (first matching rule wins):
#     done     — at least one linked PR is merged (MERGED state)
#     pr-open  — at least one linked PR is open (OPEN state) and none merged
#     none     — no linked PRs found (or issue is closed but no PR reference)
#
# OUTPUT (stdout, JSON):
#   Success:
#     {
#       "signal":   "done" | "pr-open" | "none",
#       "pr_url":   <string|null>,    -- URL of the most relevant PR (merged>open>null)
#       "pr_state": <string|null>,    -- "MERGED" | "OPEN" | "CLOSED" | null
#       "pr_number": <int|null>
#     }
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
  im_error "Usage: get_completion_signal.sh <issue-ref> [-R <owner/repo>]" "usage"
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
  if ! out=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>&1); then
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
# Source A: closedByPullRequestsReferences (REST via gh)
# Returns PRs that closed this issue via "Closes #N" or "Fixes #N" keywords.
# ---------------------------------------------------------------------------

if ! out=$(gh issue view "$IM_NUMBER" -R "$IM_REPO" \
  --json closedByPullRequestsReferences,state,stateReason 2>&1); then
  im_error "$out" "gh_failed"
  exit 1
fi

CLOSED_BY_PRS=$(printf '%s' "$out" | jq '.closedByPullRequestsReferences // []')
ISSUE_STATE=$(printf '%s' "$out" | jq -r '.state // "OPEN"')
ISSUE_STATE_REASON=$(printf '%s' "$out" | jq -r '.stateReason // ""')

# ---------------------------------------------------------------------------
# Source B: cross-referenced PRs from timeline via GraphQL
# Captures PRs that mention this issue in their body or commits but do not
# use the auto-close keywords.
# ---------------------------------------------------------------------------

graphql_query='query($owner:String!,$repo:String!,$number:Int!){
  repository(owner:$owner,name:$repo){
    issue(number:$number){
      timelineItems(first:50 itemTypes:[CROSS_REFERENCED_EVENT,CONNECTED_EVENT]){
        nodes{
          __typename
          ... on CrossReferencedEvent {
            source {
              __typename
              ... on PullRequest {
                number
                state
                url
                merged
                title
              }
            }
          }
          ... on ConnectedEvent {
            subject {
              __typename
              ... on PullRequest {
                number
                state
                url
                merged
                title
              }
            }
          }
        }
      }
    }
  }
}'

if ! gql_out=$(gh api graphql \
  -f query="$graphql_query" \
  -f owner="$REPO_OWNER" \
  -f repo="$REPO_NAME" \
  -F number="$IM_NUMBER" 2>&1); then
  im_error "$gql_out" "graphql_failed"
  exit 1
fi

im_check_graphql_errors "$gql_out"

# Extract PRs from timeline (both CrossReferencedEvent and ConnectedEvent)
TIMELINE_PRS=$(printf '%s' "$gql_out" | jq '
  [.data.repository.issue.timelineItems.nodes[]
   | (
       if .__typename == "CrossReferencedEvent" then .source
       elif .__typename == "ConnectedEvent" then .subject
       else null
       end
     )
   | select(. != null and .__typename == "PullRequest")
   | {
       number: .number,
       state:  (if .merged then "MERGED" elif .state == "OPEN" then "OPEN" else "CLOSED" end),
       url:    .url
     }
  ]')

# ---------------------------------------------------------------------------
# Merge all PR references and derive signal
# ---------------------------------------------------------------------------

# Normalize closedByPullRequestsReferences to same shape
CLOSED_BY_NORMALIZED=$(printf '%s' "$CLOSED_BY_PRS" | jq '
  [.[] | {
    number: .number,
    state:  (if .mergedAt != null then "MERGED" elif .state == "OPEN" then "OPEN" else "CLOSED" end),
    url:    .url
  }]')

ALL_PRS=$(jq -n \
  --argjson a "$CLOSED_BY_NORMALIZED" \
  --argjson b "$TIMELINE_PRS" \
  '($a + $b) | unique_by(.number)')

# Derive signal (merged PR > open PR > closed-as-done > none)
RESULT=$(jq -n \
  --argjson prs "$ALL_PRS" \
  --arg issue_state "$ISSUE_STATE" \
  --arg issue_state_reason "$ISSUE_STATE_REASON" '
  if ($prs | map(select(.state == "MERGED")) | length) > 0
  then
    ($prs | map(select(.state == "MERGED")) | first) as $pr |
    {signal: "done", pr_url: $pr.url, pr_state: "MERGED", pr_number: $pr.number}
  elif ($prs | map(select(.state == "OPEN")) | length) > 0
  then
    ($prs | map(select(.state == "OPEN")) | first) as $pr |
    {signal: "pr-open", pr_url: $pr.url, pr_state: "OPEN", pr_number: $pr.number}
  elif ($issue_state == "CLOSED" and $issue_state_reason == "COMPLETED")
  then
    {signal: "done", pr_url: null, pr_state: null, pr_number: null}
  else
    {signal: "none", pr_url: null, pr_state: null, pr_number: null}
  end
')

printf '%s\n' "$RESULT"

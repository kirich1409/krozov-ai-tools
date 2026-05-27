#!/bin/bash
# link_pr.sh — associate a PR with a GitHub issue via a comment, idempotently.
#
# USAGE:
#   link_pr.sh <issue-ref> <pr-ref> [OPTIONS]
#
# <issue-ref>  Plain number, owner/repo#number, or full URL (issue).
# <pr-ref>     PR number (int) or full PR URL.
#
# OPTIONS:
#   -R <owner/repo>   Target repository (default: current repo from git)
#   --dry-run         Print what would be posted, without writing.
#
# IDEMPOTENCY:
#   Uses a hidden HTML comment marker: <!-- issue-manager:link-pr:<pr-number> -->
#   If any existing comment on the issue already contains this marker, the script
#   exits with action "noop" and does NOT create a duplicate comment.
#
# OUTPUT (stdout, JSON):
#   {
#     "action":     "linked" | "noop",
#     "issue":      <int>,
#     "pr":         <int>,
#     "comment_id": <int|null>,   -- new comment id (null on noop or dry-run)
#     "dry_run":    <bool>
#   }
#
#   Error: {"error":<string>,"code":<string>}
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

im_parse_pr_ref() {
  # Sets IM_PR_NUMBER
  IM_PR_NUMBER=""
  local ref="$1"
  if [[ "$ref" =~ ^https?://github\.com/[^/]+/[^/]+/pull/([0-9]+) ]]; then
    IM_PR_NUMBER="${BASH_REMATCH[1]}"
  elif [[ "$ref" =~ ^([0-9]+)$ ]]; then
    IM_PR_NUMBER="$ref"
  else
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

if [[ $# -lt 2 ]]; then
  im_error "Usage: link_pr.sh <issue-ref> <pr-ref> [-R <owner/repo>] [--dry-run]" "usage"
  exit 1
fi

RAW_ISSUE_REF="$1"
RAW_PR_REF="$2"
shift 2

REPO_OVERRIDE=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -R)        REPO_OVERRIDE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *)         im_error "Unknown flag: $1" "usage"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Resolve refs
# ---------------------------------------------------------------------------

if ! im_parse_ref "$RAW_ISSUE_REF"; then
  im_error "Cannot parse issue ref: $RAW_ISSUE_REF" "invalid_ref"
  exit 1
fi

if ! im_parse_pr_ref "$RAW_PR_REF"; then
  im_error "Cannot parse PR ref: $RAW_PR_REF (expected: number or https://github.com/.../pull/N)" "invalid_ref"
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

ISSUE_NUMBER="$IM_NUMBER"
PR_NUMBER="$IM_PR_NUMBER"
MARKER="<!-- issue-manager:link-pr:${PR_NUMBER} -->"

# ---------------------------------------------------------------------------
# Idempotency check — scan existing comments for marker
# ---------------------------------------------------------------------------

out=$(gh issue view "$ISSUE_NUMBER" -R "$IM_REPO" \
  --json comments 2>&1); rc=$?
if [[ $rc -ne 0 ]]; then
  im_error "$out" "gh_failed"
  exit 1
fi

EXISTING=$(printf '%s' "$out" | jq -r --arg marker "$MARKER" \
  '.comments[] | select(.body | contains($marker)) | .id' 2>/dev/null | head -1) || {
  im_error "Failed to parse comments while checking idempotency marker" "parse_failed"
  exit 1
}

if [[ -n "$EXISTING" ]]; then
  jq -n \
    --argjson issue "$ISSUE_NUMBER" \
    --argjson pr "$PR_NUMBER" \
    --argjson dry_run "$DRY_RUN" \
    '{action:"noop",issue:$issue,pr:$pr,comment_id:null,dry_run:$dry_run}'
  exit 0
fi

# ---------------------------------------------------------------------------
# Build comment body
# ---------------------------------------------------------------------------

PR_URL="https://github.com/${IM_REPO}/pull/${PR_NUMBER}"
COMMENT_BODY="${MARKER}
Linked PR: ${PR_URL}"

if [[ "$DRY_RUN" == true ]]; then
  jq -n \
    --argjson issue "$ISSUE_NUMBER" \
    --argjson pr "$PR_NUMBER" \
    --arg body "$COMMENT_BODY" \
    '{action:"linked",issue:$issue,pr:$pr,comment_id:null,dry_run:true,would_post:$body}'
  exit 0
fi

# ---------------------------------------------------------------------------
# Post comment
# ---------------------------------------------------------------------------

new_out=$(gh issue comment "$ISSUE_NUMBER" -R "$IM_REPO" \
  --body "$COMMENT_BODY" 2>&1); rc=$?
if [[ $rc -ne 0 ]]; then
  im_error "$new_out" "gh_failed"
  exit 1
fi

# Fetch the new comment id by rescanning (gh issue comment doesn't return JSON)
out2=$(gh issue view "$ISSUE_NUMBER" -R "$IM_REPO" \
  --json comments 2>&1); rc=$?
if [[ $rc -ne 0 ]]; then
  im_error "$out2" "gh_failed"
  exit 1
fi

NEW_COMMENT_ID=$(printf '%s' "$out2" | jq -r --arg marker "$MARKER" \
  '.comments[] | select(.body | contains($marker)) | .id' 2>/dev/null | tail -1) || {
  im_error "Failed to parse comments after posting (id rescan)" "parse_failed"
  exit 1
}

jq -n \
  --argjson issue "$ISSUE_NUMBER" \
  --argjson pr "$PR_NUMBER" \
  --arg cid "$NEW_COMMENT_ID" \
  '{action:"linked",issue:$issue,pr:$pr,comment_id:($cid | if . == "" then null else . end),dry_run:false}'

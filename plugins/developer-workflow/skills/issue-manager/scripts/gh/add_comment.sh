#!/bin/bash
# add_comment.sh — add a comment to a GitHub issue, idempotently.
#
# USAGE:
#   add_comment.sh <issue-ref> --key <marker-key> --body <text> [OPTIONS]
#
# <issue-ref>         Plain number, owner/repo#number, or full URL.
# --key <marker-key>  Unique marker key for idempotency. Must be non-empty.
#                     The marker embedded in the comment is:
#                       <!-- issue-manager:<marker-key> -->
#                     If any existing comment already contains this marker, the
#                     script exits with action "noop" (no duplicate).
# --body <text>       Comment body text. Required.
#
# OPTIONS:
#   -R <owner/repo>   Target repository (default: current repo from git)
#   --dry-run         Print what would be posted, without writing.
#
# IDEMPOTENCY:
#   Scans existing issue comments for <!-- issue-manager:<marker-key> -->.
#   If found → noop. If not found → post once.
#   On resume the comment will already exist → noop, no duplicate.
#
# OUTPUT (stdout, JSON):
#   {
#     "action":     "commented" | "noop",
#     "issue":      <int>,
#     "key":        <string>,
#     "comment_id": <string|null>,   -- new comment id (null on noop or dry-run)
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

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
  im_error "Usage: add_comment.sh <issue-ref> --key <marker-key> --body <text> [-R <owner/repo>] [--dry-run]" "usage"
  exit 1
fi

RAW_REF="$1"
shift

REPO_OVERRIDE=""
DRY_RUN=false
MARKER_KEY=""
BODY_TEXT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -R)        REPO_OVERRIDE="$2"; shift 2 ;;
    --key)     MARKER_KEY="$2"; shift 2 ;;
    --body)    BODY_TEXT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *)         im_error "Unknown flag: $1" "usage"; exit 1 ;;
  esac
done

if [[ -z "$MARKER_KEY" ]]; then
  im_error "--key is required" "usage"
  exit 1
fi

if [[ ! "$MARKER_KEY" =~ ^[A-Za-z0-9:_.-]+$ ]]; then
  im_error "--key must match [A-Za-z0-9:_.-]+" "usage"
  exit 1
fi

if [[ -z "$BODY_TEXT" ]]; then
  im_error "--body is required" "usage"
  exit 1
fi

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

ISSUE_NUMBER="$IM_NUMBER"
MARKER="<!-- issue-manager:${MARKER_KEY} -->"

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
    --arg key "$MARKER_KEY" \
    --argjson dry_run "$DRY_RUN" \
    '{action:"noop",issue:$issue,key:$key,comment_id:null,dry_run:$dry_run}'
  exit 0
fi

# ---------------------------------------------------------------------------
# Build comment body (marker appended as last line)
# ---------------------------------------------------------------------------

FULL_BODY="${BODY_TEXT}

${MARKER}"

if [[ "$DRY_RUN" == true ]]; then
  jq -n \
    --argjson issue "$ISSUE_NUMBER" \
    --arg key "$MARKER_KEY" \
    --arg body "$FULL_BODY" \
    '{action:"commented",issue:$issue,key:$key,comment_id:null,dry_run:true,would_post:$body}'
  exit 0
fi

# ---------------------------------------------------------------------------
# Post comment
# ---------------------------------------------------------------------------

new_out=$(gh issue comment "$ISSUE_NUMBER" -R "$IM_REPO" \
  --body "$FULL_BODY" 2>&1); rc=$?
if [[ $rc -ne 0 ]]; then
  im_error "$new_out" "gh_failed"
  exit 1
fi

# Fetch the new comment id by rescanning
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
  --arg key "$MARKER_KEY" \
  --arg cid "$NEW_COMMENT_ID" \
  '{action:"commented",issue:$issue,key:$key,comment_id:($cid | if . == "" then null else . end),dry_run:false}'

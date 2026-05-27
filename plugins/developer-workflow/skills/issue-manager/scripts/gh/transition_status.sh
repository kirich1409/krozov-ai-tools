#!/bin/bash
# transition_status.sh — idempotent issue status transition.
#
# USAGE:
#   transition_status.sh <issue-ref> <target-status> [OPTIONS]
#
# <issue-ref>      Plain number, owner/repo#number, or full URL.
# <target-status>  One of: todo | in-progress | blocked | done | open | closed
#                  Canonical form is lowercase-with-hyphens.
#                  Aliases accepted: "in_progress" → "in-progress", "In Progress" → "in-progress", etc.
#
# OPTIONS:
#   -R <owner/repo>   Target repository (default: current repo from git)
#   --project-id <id> Force use of a specific Project v2 node id (skips auto-detect)
#   --dry-run         Resolve current state and planned action, then EXIT without writing.
#                     Prints the resolved payload it WOULD send. Safe to run against live issues.
#
# MECHANISM:
#   1. Detect GitHub Project v2 (via `gh project list --owner <owner>`).
#      If a project is found for this repo's owner AND the issue is linked to the project,
#      uses GraphQL to set the Status single-select field.
#   2. Fallback: open/closed state + labels (status:in-progress, status:blocked).
#
# READ-BEFORE-WRITE (AC-5):
#   Always reads current status before writing. Writes ONLY if current != target.
#
# STATUS MAPPING:
#   target          Project v2 option    Open/closed + label
#   todo            Todo                 open (no status label)
#   in-progress     In Progress          open + label "status:in-progress"
#   blocked         (none — label only)  open + label "status:blocked"
#   done            Done                 closed
#   open            (→ todo)             open
#   closed          (→ done)             closed
#
# OUTPUT (stdout, JSON):
#   {
#     "action":     "transition" | "noop",
#     "from":       <string|null>,   -- current status (normalized)
#     "to":         <string>,        -- target status (normalized)
#     "mechanism":  "project-v2" | "labels",
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

im_check_graphql_errors() {
  local response="$1"
  if printf '%s' "$response" | jq -e '.errors' >/dev/null 2>&1; then
    local errmsg
    errmsg=$(printf '%s' "$response" | jq -r '.errors[0].message // "GraphQL error"')
    im_error "$errmsg" "graphql_error"
    exit 1
  fi
}

im_normalize_status() {
  # Normalize status to lowercase-with-hyphens canonical form
  local raw
  raw=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[_ ]/-/g')
  case "$raw" in
    todo|open)         printf 'todo' ;;
    in-progress)       printf 'in-progress' ;;
    blocked)           printf 'blocked' ;;
    done|closed)       printf 'done' ;;
    *)                 printf '%s' "$raw" ;;
  esac
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

if [[ $# -lt 2 ]]; then
  im_error "Usage: transition_status.sh <issue-ref> <target-status> [-R <owner/repo>] [--dry-run]" "usage"
  exit 1
fi

RAW_REF="$1"
RAW_TARGET="$2"
shift 2

REPO_OVERRIDE=""
DRY_RUN=false
FORCED_PROJECT_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -R)            REPO_OVERRIDE="$2"; shift 2 ;;
    --project-id)  FORCED_PROJECT_ID="$2"; shift 2 ;;
    --dry-run)     DRY_RUN=true; shift ;;
    *)             im_error "Unknown flag: $1" "usage"; exit 1 ;;
  esac
done

TARGET_STATUS=$(im_normalize_status "$RAW_TARGET")

# Validate target
case "$TARGET_STATUS" in
  todo|in-progress|blocked|done) ;;
  *) im_error "Unknown target status: $RAW_TARGET (accepted: todo|in-progress|blocked|done)" "invalid_status"; exit 1 ;;
esac

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
# Read current issue state (always — part of read-before-write and dry-run output)
# ---------------------------------------------------------------------------

out=$(gh issue view "$IM_NUMBER" -R "$IM_REPO" \
  --json id,number,state,labels 2>&1); rc=$?
if [[ $rc -ne 0 ]]; then
  im_error "$out" "gh_failed"
  exit 1
fi

ISSUE_NODE_ID=$(printf '%s' "$out" | jq -r '.id')
ISSUE_STATE=$(printf '%s' "$out" | jq -r '.state') # OPEN or CLOSED
ISSUE_LABELS=$(printf '%s' "$out" | jq -r '[.labels[].name] | join(",")')

# Derive current status from labels + state (labels-mechanism baseline)
if [[ "$ISSUE_STATE" == "CLOSED" ]]; then
  CURRENT_LABELS_STATUS="done"
elif printf '%s' "$ISSUE_LABELS" | grep -qi 'status:in-progress'; then
  CURRENT_LABELS_STATUS="in-progress"
elif printf '%s' "$ISSUE_LABELS" | grep -qi 'status:blocked'; then
  CURRENT_LABELS_STATUS="blocked"
else
  CURRENT_LABELS_STATUS="todo"
fi

# ---------------------------------------------------------------------------
# Detect Project v2 and check if issue is linked
# ---------------------------------------------------------------------------

MECHANISM="labels"
PROJECT_ID=""
PROJECT_ITEM_ID=""
PROJECT_STATUS_FIELD_ID=""
PROJECT_CURRENT_STATUS=""
PROJECT_TARGET_OPTION_ID=""

detect_project() {
  local project_id_to_use="$1"

  # Query project fields to find Status field id
  local fields_out
  fields_out=$(gh api graphql \
    -f query='query($projId:ID!){node(id:$projId){... on ProjectV2{fields(first:30){nodes{... on ProjectV2FieldCommon{id name} ... on ProjectV2SingleSelectField{id name options{id name}}}}}}}' \
    -f projId="$project_id_to_use" 2>&1); local rc=$?
  if [[ $rc -ne 0 ]]; then return 1; fi
  im_check_graphql_errors "$fields_out" 2>/dev/null || return 1

  local status_field_id
  status_field_id=$(printf '%s' "$fields_out" | jq -r \
    '.data.node.fields.nodes[] | select(.name=="Status") | .id' 2>/dev/null || true)
  [[ -z "$status_field_id" ]] && return 1

  # Map target_status to option id
  local option_name
  case "$TARGET_STATUS" in
    todo)        option_name="Todo" ;;
    in-progress) option_name="In Progress" ;;
    blocked)     option_name="Todo" ;; # no Blocked option in project; fall through to labels
    done)        option_name="Done" ;;
  esac

  local option_id
  option_id=$(printf '%s' "$fields_out" | jq -r \
    --arg name "$option_name" \
    '.data.node.fields.nodes[] | select(.name=="Status") | .options[]? | select(.name==$name) | .id' \
    2>/dev/null || true)

  # Check if issue is linked to this project
  local items_out
  items_out=$(gh api graphql \
    -f query='query($nodeId:ID!){node(id:$nodeId){... on Issue{projectItems(first:10){nodes{id project{id} fieldValues(first:20){nodes{... on ProjectV2ItemFieldSingleSelectValue{name optionId field{... on ProjectV2FieldCommon{name}}}}}}}}}}}' \
    -f nodeId="$ISSUE_NODE_ID" 2>&1); local rc2=$?
  if [[ $rc2 -ne 0 ]]; then return 1; fi
  im_check_graphql_errors "$items_out" 2>/dev/null || return 1

  local item_id
  item_id=$(printf '%s' "$items_out" | jq -r \
    --arg projId "$project_id_to_use" \
    '.data.node.projectItems.nodes[] | select(.project.id==$projId) | .id' 2>/dev/null || true)

  [[ -z "$item_id" ]] && return 1  # issue not in this project

  local current_option
  current_option=$(printf '%s' "$items_out" | jq -r \
    --arg projId "$project_id_to_use" \
    '.data.node.projectItems.nodes[] | select(.project.id==$projId) | .fieldValues.nodes[] | select(.field.name=="Status") | .name' \
    2>/dev/null || true)

  PROJECT_STATUS_FIELD_ID="$status_field_id"
  PROJECT_ITEM_ID="$item_id"
  PROJECT_CURRENT_STATUS=$(im_normalize_status "${current_option:-todo}")
  PROJECT_TARGET_OPTION_ID="$option_id"
  PROJECT_ID="$project_id_to_use"
  return 0
}

# Try to find a project — use forced id if provided, else scan owner's projects
USE_PROJECT=false

if [[ -n "$FORCED_PROJECT_ID" ]]; then
  if detect_project "$FORCED_PROJECT_ID" 2>/dev/null; then
    USE_PROJECT=true
  fi
else
  # Scan owner's projects
  proj_list_out=$(gh project list --owner "$REPO_OWNER" --format json 2>&1); proj_rc=$?
  if [[ $proj_rc -eq 0 ]]; then
    proj_ids=$(printf '%s' "$proj_list_out" | jq -r '.projects[].id' 2>/dev/null || true)
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      if detect_project "$pid" 2>/dev/null; then
        USE_PROJECT=true
        break
      fi
    done <<< "$proj_ids"
  fi
  # Scope/permission errors from gh project list degrade to labels silently
fi

# Determine current status and mechanism
CURRENT_STATUS="$CURRENT_LABELS_STATUS"
if [[ "$USE_PROJECT" == true && -n "$PROJECT_TARGET_OPTION_ID" && "$TARGET_STATUS" != "blocked" ]]; then
  MECHANISM="project-v2"
  CURRENT_STATUS="$PROJECT_CURRENT_STATUS"
fi

# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------

if [[ "$CURRENT_STATUS" == "$TARGET_STATUS" ]]; then
  jq -n \
    --arg from "$CURRENT_STATUS" \
    --arg to "$TARGET_STATUS" \
    --arg mechanism "$MECHANISM" \
    --argjson dry_run "$DRY_RUN" \
    '{action:"noop",from:$from,to:$to,mechanism:$mechanism,dry_run:$dry_run}'
  exit 0
fi

# ---------------------------------------------------------------------------
# Build dry-run or real transition
# ---------------------------------------------------------------------------

if [[ "$MECHANISM" == "project-v2" ]]; then
  DRY_PAYLOAD=$(jq -n \
    --arg projectId "$PROJECT_ID" \
    --arg itemId "$PROJECT_ITEM_ID" \
    --arg fieldId "$PROJECT_STATUS_FIELD_ID" \
    --arg optionId "$PROJECT_TARGET_OPTION_ID" \
    '{mutation:"updateProjectV2ItemFieldValue",projectId:$projectId,itemId:$itemId,fieldId:$fieldId,singleSelectOptionId:$optionId}')
else
  # Labels mechanism — determine state change and label changes
  TARGET_OPEN="true"
  TARGET_ADD_LABELS=()
  TARGET_REMOVE_LABELS=("status:in-progress" "status:blocked")
  case "$TARGET_STATUS" in
    todo)        TARGET_OPEN="true" ;;
    in-progress) TARGET_OPEN="true"; TARGET_ADD_LABELS+=("status:in-progress") ;;
    blocked)     TARGET_OPEN="true"; TARGET_ADD_LABELS+=("status:blocked") ;;
    done)        TARGET_OPEN="false" ;;
  esac
  DRY_PAYLOAD=$(jq -n \
    --argjson open "$TARGET_OPEN" \
    --argjson add_labels "$(printf '%s\n' "${TARGET_ADD_LABELS[@]+"${TARGET_ADD_LABELS[@]}"}" | jq -Rs 'split("\n") | map(select(length>0))')" \
    --argjson remove_labels "$(printf '%s\n' "${TARGET_REMOVE_LABELS[@]}" | jq -Rs 'split("\n") | map(select(length>0))')" \
    '{open:$open,add_labels:$add_labels,remove_labels:$remove_labels}')
fi

if [[ "$DRY_RUN" == true ]]; then
  jq -n \
    --arg from "$CURRENT_STATUS" \
    --arg to "$TARGET_STATUS" \
    --arg mechanism "$MECHANISM" \
    --argjson payload "$DRY_PAYLOAD" \
    '{action:"transition",from:$from,to:$to,mechanism:$mechanism,dry_run:true,resolved_payload:$payload}'
  exit 0
fi

# ---------------------------------------------------------------------------
# Execute transition
# ---------------------------------------------------------------------------

if [[ "$MECHANISM" == "project-v2" ]]; then
  mut_out=$(gh api graphql \
    -f query='mutation($projId:ID!,$itemId:ID!,$fieldId:ID!,$optId:String!){updateProjectV2ItemFieldValue(input:{projectId:$projId,itemId:$itemId,fieldId:$fieldId,value:{singleSelectOptionId:$optId}}){projectV2Item{id}}}' \
    -f projId="$PROJECT_ID" \
    -f itemId="$PROJECT_ITEM_ID" \
    -f fieldId="$PROJECT_STATUS_FIELD_ID" \
    -f optId="$PROJECT_TARGET_OPTION_ID" 2>&1); rc=$?
  if [[ $rc -ne 0 ]]; then
    im_error "$mut_out" "graphql_failed"
    exit 1
  fi
  im_check_graphql_errors "$mut_out"
else
  # Apply label changes and state changes
  # Remove old status labels first
  for lbl in "status:in-progress" "status:blocked"; do
    if printf '%s' "$ISSUE_LABELS" | grep -qF "$lbl"; then
      gh issue edit "$IM_NUMBER" -R "$IM_REPO" --remove-label "$lbl" >/dev/null 2>&1 || true
    fi
  done

  # Add new status label if needed
  for lbl in "${TARGET_ADD_LABELS[@]+"${TARGET_ADD_LABELS[@]}"}"; do
    # Ensure label exists
    gh label create "$lbl" -R "$IM_REPO" --color "ededed" --description "Issue status: $lbl" 2>/dev/null || true
    gh issue edit "$IM_NUMBER" -R "$IM_REPO" --add-label "$lbl" >/dev/null 2>&1
  done

  # Apply open/closed state
  if [[ "$TARGET_OPEN" == "false" && "$ISSUE_STATE" == "OPEN" ]]; then
    gh issue close "$IM_NUMBER" -R "$IM_REPO" >/dev/null 2>&1
  elif [[ "$TARGET_OPEN" == "true" && "$ISSUE_STATE" == "CLOSED" ]]; then
    gh issue reopen "$IM_NUMBER" -R "$IM_REPO" >/dev/null 2>&1
  fi
fi

jq -n \
  --arg from "$CURRENT_STATUS" \
  --arg to "$TARGET_STATUS" \
  --arg mechanism "$MECHANISM" \
  '{action:"transition",from:$from,to:$to,mechanism:$mechanism,dry_run:false}'

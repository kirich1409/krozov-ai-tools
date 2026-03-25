---
name: pr-drive-to-merge
description: Use when a PR/MR already exists and needs to be driven to merge — monitors CI/CD, handles multi-round code review, responds to and resolves reviewer comments, and loops until all merge requirements are met.
---

# PR Drive to Merge

## Overview

Takes an existing PR/MR and drives it to merge autonomously. Loops through CI/CD monitoring and code review cycles until all requirements are satisfied.

**Core principle:** Fix only what belongs to the current PR. Ask the user only when a problem is outside the current PR scope and the fix isn't obvious.

## Setup

Before starting, detect the PR and platform:

```bash
# GitHub — detect PR number and base branch
PR_NUMBER=$(gh pr view --json number -q .number)
BASE=$(gh pr view --json baseRefName -q .baseRefName)
IS_DRAFT=$(gh pr view --json isDraft -q .isDraft)

# GitLab — detect MR number and base branch
MR_NUMBER=$(glab mr view --output json | jq .iid)
BASE=$(glab mr view --output json | jq -r .target_branch)
IS_DRAFT=$(glab mr view --output json | jq .draft)
```

**Platform detection:** check `git remote get-url origin`.
- Contains `github.com` (HTTPS: `https://github.com/...` or SSH: `git@github.com:...`) → use `gh`
- Contains `gitlab` → use `glab`

## Phase 1: CI/CD Monitoring

```dot
digraph cicd {
    rankdir=TB;

    start [label="PR/MR exists", shape=doublecircle];
    fetch_status [label="Fetch current CI/CD status\n+ check if draft", shape=box];
    has_ci [label="CI/CD configured?", shape=diamond];
    ci_state [label="Current state?", shape=diamond];
    wait [label="Poll checks every ~2 min\nuntil complete", shape=box];
    passing [label="All required checks passing?", shape=diamond];
    investigate [label="Investigate failure logs", shape=box];
    our_fault [label="Caused by current changes?", shape=diamond];
    fix [label="Fix → invoke prepare-for-pr\n→ push", shape=box];
    ask [label="Ask user", shape=box];
    undraft [label="Undraft PR/MR\nif still draft", shape=box];
    review [label="Proceed to Code Review", shape=box];

    start -> fetch_status;
    fetch_status -> has_ci;
    has_ci -> ci_state [label="yes"];
    has_ci -> undraft [label="no CI"];
    ci_state -> wait [label="pending/running"];
    ci_state -> passing [label="complete"];
    wait -> passing;
    passing -> undraft [label="yes"];
    passing -> investigate [label="no"];
    investigate -> our_fault;
    our_fault -> fix [label="yes"];
    our_fault -> ask [label="no — pause\nuntil user decides"];
    fix -> wait;
    undraft -> review;
}
```

**Invoking `prepare-for-pr` for fixes:** invoke it as a sub-skill. It runs its own quality loop, commits fixes, and exits when clean. If it pauses for user input, this skill also pauses. After it exits, push: `git push`.

## Phase 2: Code Review Cycle

```dot
digraph review {
    rankdir=TB;

    start [label="CI/CD passing", shape=doublecircle];
    reviewers [label="Reviewers assigned?", shape=diamond];
    approvals_req [label="Approvals required\nby repo rules?", shape=diamond];
    ask_assign [label="Notify user: approvals required\nbut no reviewers assigned.\nPause until user assigns.", shape=box];
    wait [label="Poll for new reviews/comments\nevery ~5 min", shape=box];
    stale_check [label="No activity for\n>4 hours?", shape=diamond];
    notify_stale [label="Notify user, ask\nhow to proceed.\nPause.", shape=box];
    read_all [label="Read ALL comments\n(reviews + inline review comments)", shape=box];
    any_comments [label="Unaddressed comments?", shape=diamond];
    categorize [label="Categorize + show table\n(BLOCKING/IMPORTANT/OPTIONAL\n/INVALID/OUT OF SCOPE)", shape=box];
    oos [label="OUT OF SCOPE\ncomments?", shape=diamond];
    ask_oos [label="Ask user for each\nOUT OF SCOPE comment.\nPause until resolved.", shape=box];
    any_fix [label="Any BLOCKING or\nIMPORTANT comments?", shape=diamond];
    fix [label="Fix → prepare-for-pr → push", shape=box];
    respond [label="Respond to every comment\nindividually (in PR language)\nReference pushed commit hash", shape=box];
    resolve [label="Resolve threads", shape=box];
    fixes_made [label="Fixes were made?", shape=diamond];
    rereview [label="Request re-review", shape=box];
    ci_loop [label="Back to CI/CD monitoring", shape=box];
    merge_check [label="Merge requirements met?", shape=diamond];
    done [label="MERGE", shape=doublecircle];

    start -> reviewers;
    reviewers -> approvals_req [label="no"];
    approvals_req -> ask_assign [label="yes — stop"];
    approvals_req -> merge_check [label="no"];
    ask_assign -> wait [label="user assigns reviewers"];
    reviewers -> wait [label="yes"];
    wait -> stale_check;
    stale_check -> notify_stale [label="yes"];
    stale_check -> read_all [label="no"];
    read_all -> any_comments;
    any_comments -> categorize [label="yes"];
    any_comments -> merge_check [label="no, approved"];
    categorize -> oos;
    oos -> ask_oos [label="yes — pause\nuntil resolved"];
    oos -> any_fix [label="no"];
    ask_oos -> any_fix [label="user decided"];
    any_fix -> fix [label="yes"];
    any_fix -> respond [label="no — skip fix"];
    fix -> respond;
    respond -> resolve;
    resolve -> fixes_made;
    fixes_made -> rereview [label="yes"];
    fixes_made -> merge_check [label="no"];
    rereview -> ci_loop -> wait;
    merge_check -> done [label="yes"];
    merge_check -> wait [label="no — keep polling"];
}
```

**Reading comments:** `gh pr view <N> --comments` does not return inline review comments. Fetch them separately:

```bash
# GitHub — inline review comments
gh api repos/{owner}/{repo}/pulls/{number}/comments

# GitLab — all discussions (includes inline)
glab api /projects/:fullpath/merge_requests/:iid/discussions
```

## Comment Categories

Assign ONE category per comment. Show full table before acting. Proceed without waiting for approval except for OUT OF SCOPE.

| Category | When to use | Action |
|----------|-------------|--------|
| **BLOCKING** | Security issues, critical bugs, compliance violations | Fix → respond → Resolve |
| **IMPORTANT** | Bugs, missing error handling, missing tests | Fix → respond → Resolve |
| **OPTIONAL** | Style, naming preference, refactoring suggestion, nitpick | Respond acknowledging → Resolve without fixing |
| **INVALID** | Already fixed, no longer applies, praise | Respond acknowledging → Resolve |
| **OUT OF SCOPE** | Requires changes outside this PR | Ask user before acting |

**Show table format:**

```markdown
## PR Review Comments

| # | Author | Location | Summary | Category | Action |
|---|--------|----------|---------|----------|--------|
| 1 | @dev | auth.ts:23 | Password in plaintext | BLOCKING | Will fix |
| 2 | @dev | auth.ts:12 | Rename doAuth | OPTIONAL | Will acknowledge |
| 3 | @qa | auth.ts:45 | Missing error handling | IMPORTANT | Will fix |
| 4 | @dev | auth.ts:67 | Nice work! | INVALID | Will acknowledge |
| 5 | @dev | utils.ts:10 | Whole file needs refactor | OUT OF SCOPE | Need your input |

Proceeding with BLOCKING + IMPORTANT fixes. Waiting on your input for OUT OF SCOPE (#5).
```

## Responding to Comments

**Always respond in the same language as the PR and review comments.**
**Respond after pushing fixes** — reference the actual commit hash.
**Respond to every comment individually — never a single summary.**

| Category | Response template |
|----------|------------------|
| BLOCKING/IMPORTANT (fixed) | `Fixed in [commit hash]. [What changed and why.]` |
| OPTIONAL | `Good point. Not addressing in this PR to keep it focused on [goal].` *(If genuinely useful: "Logged as [issue link] for follow-up.")* |
| INVALID (outdated) | `This was addressed in [commit]. [File/code] now [does X].` |
| INVALID (praise) | `Thank you!` |
| OUT OF SCOPE | Per user's instruction |

## Resolving Threads

After responding, resolve threads where the issue is closed. Do NOT resolve if discussion is ongoing or awaiting reviewer confirmation.

```bash
# GitHub — resolve review thread via GraphQL
# 1. Get thread node IDs:
gh api graphql -f query='
  query($owner:String!,$repo:String!,$number:Int!) {
    repository(owner:$owner,name:$repo) {
      pullRequest(number:$number) {
        reviewThreads(first:100) { nodes { id isResolved } }
      }
    }
  }
' -f owner=OWNER -f repo=REPO -F number=N

# 2. Resolve a thread:
gh api graphql -f query='
  mutation($id:ID!) { resolveReviewThread(input:{threadId:$id}) { thread { isResolved } } }
' -f id=THREAD_NODE_ID

# GitLab — resolve a discussion:
glab api /projects/:fullpath/merge_requests/:iid/discussions/:discussion_id \
  --method PUT -f resolved=true
```

## Re-Review

Request re-review only from reviewers whose BLOCKING or IMPORTANT comments were fixed:

```bash
# GitHub — re-request review (use API, not --add-reviewer which only adds new reviewers)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh api --method POST /repos/$REPO/pulls/$PR_NUMBER/requested_reviewers \
  -f "reviewers[]=username1" -f "reviewers[]=username2"

# GitLab — re-request review via REST API (glab mr update has no --reviewer flag)
glab api /projects/:fullpath/merge_requests/:iid \
  --method PUT -f "reviewer_ids[]=<user_id1>" -f "reviewer_ids[]=<user_id2>"
# Get user IDs: glab api /users?username=<username> | jq '.[0].id'
```

## Merge Requirements Checklist

Before merging, verify all of:
- [ ] All required CI/CD checks pass
- [ ] Required approvals received
- [ ] No unresolved blocking threads
- [ ] Branch up to date with base branch

**Branch behind base — update and handle conflicts:**
```bash
# GitHub
gh pr update-branch <PR_NUMBER>
# or: git fetch origin $BASE && git rebase origin/$BASE
# If rebase produces conflicts:
#   resolve manually → git add <resolved files> → git rebase --continue
#   if conflicts touch files outside this PR scope → ask user before proceeding
git push --force-with-lease

# GitLab
glab mr rebase <MR_NUMBER>
# If conflict: resolve manually, then git push --force-with-lease
```

## Tools Priority

**GitHub/GitLab CLI → REST API → MCP**

| Platform | Remote URL pattern | CLI |
|----------|-------------------|-----|
| GitHub | `github.com` (HTTPS or SSH `git@github.com:...`) | `gh` |
| GitLab | `gitlab` in URL | `glab` |

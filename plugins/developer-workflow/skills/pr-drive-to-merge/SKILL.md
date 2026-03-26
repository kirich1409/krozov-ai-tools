---
name: pr-drive-to-merge
description: Use when a PR/MR already exists and needs to be driven to merge — monitors CI/CD, handles multi-round code review, responds to and resolves reviewer comments, and loops until all merge requirements are met.
---

# PR Drive to Merge

## Overview

Takes an existing PR/MR and drives it to merge autonomously. Loops through CI/CD monitoring and code review cycles until all requirements are satisfied.

**Core principle:** Fix only what belongs to the current PR. Verify suggestions before implementing. Ask the user only when a problem is outside the current PR scope and the fix isn't obvious.

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
    ask -> fetch_status [label="user decides"];
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
    clarify [label="Any comment unclear?", shape=diamond];
    ask_clarify [label="Ask user, await\nclarification", shape=box];
    categorize [label="Categorize + show table\n(BLOCKING/IMPORTANT/OPTIONAL\n/INVALID/OUT OF SCOPE)", shape=box];
    oos [label="OUT OF SCOPE\ncomments?", shape=diamond];
    ask_oos [label="Ask user for each\nOUT OF SCOPE comment.\nPause until resolved.", shape=box];
    any_fix [label="Any BLOCKING or\nIMPORTANT comments?", shape=diamond];
    verify [label="Verify ALL BLOCKING/IMPORTANT\nsuggestions before fixing any\n(see Verification section)", shape=box];
    fix [label="Fix → prepare-for-pr → push", shape=box];
    respond [label="Respond to every comment\nindividually in thread\n(in PR language)\nReference pushed commit hash", shape=box];
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
    notify_stale -> wait [label="user responds"];
    stale_check -> read_all [label="no"];
    read_all -> any_comments;
    any_comments -> clarify [label="yes"];
    any_comments -> merge_check [label="no, approved"];
    clarify -> categorize [label="no"];
    clarify -> ask_clarify [label="yes"];
    ask_clarify -> categorize;
    categorize -> oos;
    oos -> ask_oos [label="yes — pause\nuntil resolved"];
    oos -> any_fix [label="no"];
    ask_oos -> any_fix [label="user decided"];
    any_fix -> verify [label="yes"];
    any_fix -> respond [label="no — skip fix"];
    verify -> fix [label="technically correct"];
    verify -> respond [label="push back — no fix"];
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

## Handling Unclear Feedback

Ask for clarification on ALL unclear items at once — not one at a time. **Example:**
```
Reviewer: "Fix 1-6"
You understand 1,2,3,6. Unclear on 4,5.

Wrong: Implement 1,2,3,6 now, ask about 4,5 later
Right: "I understand items 1,2,3,6. Need clarification on 4 and 5 before proceeding."
```

## Verifying Suggestions Before Implementing

Before implementing any BLOCKING or IMPORTANT suggestion from an external reviewer:

```
1. Check: Technically correct for THIS codebase?
2. Check: Would it break existing functionality?
3. Check: Is there a reason the current code is written this way?
4. Check: Works on all platforms/versions targeted by this PR?
5. Check: Does the reviewer have full context?

IF suggestion seems wrong:
  Push back with technical reasoning (see Push Back section below)

IF can't easily verify:
  Say so: "I can't verify this without [X]. Should I [investigate/ask/proceed]?"

IF conflicts with prior decisions made for this PR:
  Discuss with user first
```

**YAGNI check** — if a reviewer suggests "implementing it properly" or adding infrastructure:

```
Search codebase for actual usage.

IF unused: push back — "This isn't called anywhere. Remove it?"
IF used:   implement properly
```

## Comment Categories

Assign ONE category per comment. Show full table before acting. Proceed without waiting for approval except for OUT OF SCOPE.

| Category | When to use | Action |
|----------|-------------|--------|
| **BLOCKING** | Security issues, critical bugs, compliance violations | Verify → Fix → respond → Resolve |
| **IMPORTANT** | Bugs, missing error handling, missing tests | Verify → Fix → respond → Resolve |
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

**Reply in the comment thread, not as a top-level PR comment.** For fixed comments: respond after pushing, referencing the commit hash. For all others: respond inline immediately.

```bash
# GitHub — reply in an inline review comment thread
gh api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies \
  --method POST -f body="Your reply here"
```

**No performative agreement.** Never write "You're absolutely right!", "Great point!", "Excellent feedback!", or thank the reviewer. Actions speak — just fix it and show what changed.

| Category | Response template |
|----------|------------------|
| BLOCKING/IMPORTANT (fixed) | `Fixed in [commit hash]. [What changed and why.]` |
| BLOCKING/IMPORTANT (pushed back, then verified correct) | `Checked [X] — confirmed it does [Y]. Fixed in [commit hash].` |
| BLOCKING/IMPORTANT (pushing back) | `[Technical reasoning]. [Evidence from codebase.] Leaving as-is.` |
| OPTIONAL | `Not addressing in this PR to keep it focused on [goal].` *(If genuinely useful: "Logged as [issue link] for follow-up.")* |
| INVALID (outdated) | `This was addressed in [commit]. [File/code] now [does X].` |
| INVALID (praise) | *(no response needed — just resolve)* |
| OUT OF SCOPE | Per user's instruction |

## When to Push Back

Trigger conditions are the same as the verification checklist above — push back when any check fails. See "Verifying Suggestions Before Implementing".

**How to push back:**
- Use technical reasoning, not defensiveness
- Ask specific questions
- Reference working tests or existing code as evidence
- Involve the user if the disagreement is architectural

Use the response table template for the correction — state it factually, no apology, no over-explaining.

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

# GitLab — re-request review (replace reviewers, which triggers re-review notification)
glab mr update <MR_NUMBER> --reviewer username1,username2
# To add without removing existing: --reviewer +username1,+username2
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

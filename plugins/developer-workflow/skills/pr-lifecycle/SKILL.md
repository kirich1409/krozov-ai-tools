---
name: pr-lifecycle
description: Use when a PR/MR already exists and needs to be driven to merge — monitors CI/CD, handles multi-round code review, responds to and resolves reviewer comments, and loops until all merge requirements are met.
---

# PR Lifecycle

## Overview

Takes an existing PR/MR and drives it to merge autonomously. Loops through CI/CD monitoring and code review cycles until all requirements are satisfied.

**Core principle:** Fix only what belongs to the current PR. Ask the user only when a problem is outside the current PR scope and the fix isn't obvious.

## Setup

Before starting, detect the PR and platform:

```bash
# GitHub — detect PR number from current branch
PR_NUMBER=$(gh pr view --json number -q .number)
BASE=$(gh pr view --json baseRefName -q .baseRefName)

# GitLab — detect MR number from current branch
MR_NUMBER=$(glab mr view --output json | jq .iid)
BASE=$(glab mr view --output json | jq -r .target_branch)

# Check if PR is still in draft — undraft before proceeding if CI/CD passed
# GitHub: gh pr ready <PR_NUMBER>
# GitLab: glab mr update <MR_NUMBER> --draft=false
```

Detect platform from remote URL (`github.com` → `gh`, `gitlab` → `glab`).

## Phase 1: CI/CD Monitoring

```dot
digraph cicd {
    rankdir=TB;

    start [label="PR/MR exists", shape=doublecircle];
    has_ci [label="CI/CD configured?", shape=diamond];
    draft [label="PR in draft?", shape=diamond];
    undraft [label="Undraft PR", shape=box];
    wait [label="Poll checks every ~2 min\nuntil complete", shape=box];
    passing [label="All required checks passing?", shape=diamond];
    investigate [label="Investigate failure logs", shape=box];
    our_fault [label="Caused by current changes?", shape=diamond];
    fix [label="Fix → invoke prepare-for-pr\n→ commit → push", shape=box];
    ask [label="Ask user", shape=box];
    review [label="Proceed to Code Review", shape=box];

    start -> has_ci;
    has_ci -> draft [label="yes, all passing"];
    has_ci -> wait [label="yes, pending"];
    has_ci -> review [label="no CI"];
    draft -> undraft [label="yes"];
    draft -> review [label="no"];
    undraft -> review;
    wait -> passing;
    passing -> draft [label="yes"];
    passing -> investigate [label="no"];
    investigate -> our_fault;
    our_fault -> fix [label="yes"];
    our_fault -> ask [label="no — stop"];
    fix -> wait;
}
```

**Invoking prepare-for-pr for fixes:** run the `prepare-for-pr` skill as a sub-skill. It runs its own loop and commits fixes. If it pauses for user input, this skill also pauses. After it exits, push the branch (`git push`).

## Phase 2: Code Review Cycle

```dot
digraph review {
    rankdir=TB;

    start [label="CI/CD passing", shape=doublecircle];
    reviewers [label="Reviewers assigned?", shape=diamond];
    approvals_required [label="Approvals required\nby repo rules?", shape=diamond];
    notify_user [label="Notify user:\nno reviewers but\napprovals required", shape=box];
    wait [label="Poll for new reviews\nevery ~5 min", shape=box];
    read_all [label="Read ALL comments\n(incl. on approved reviews)", shape=box];
    any_comments [label="Unaddressed\ncomments?", shape=diamond];
    categorize [label="Categorize + show table\n(BLOCKING/IMPORTANT/OPTIONAL\n/INVALID/OUT OF SCOPE)", shape=box];
    oos [label="OUT OF SCOPE\ncomments?", shape=diamond];
    ask_oos [label="Ask user for each\nOUT OF SCOPE", shape=box];
    fix [label="Fix BLOCKING + IMPORTANT\n→ prepare-for-pr → push", shape=box];
    respond [label="Respond to every comment\nindividually (in PR language)\nReference push commit hash", shape=box];
    resolve [label="Resolve threads\n(see Resolving Threads)", shape=box];
    fixes_made [label="Fixes were made?", shape=diamond];
    rereview [label="Request re-review", shape=box];
    ci_loop [label="Back to CI/CD monitoring", shape=box];
    merge_check [label="Merge requirements met?", shape=diamond];
    done [label="MERGE", shape=doublecircle];

    start -> reviewers;
    reviewers -> approvals_required [label="no"];
    approvals_required -> notify_user [label="yes"];
    approvals_required -> merge_check [label="no"];
    notify_user -> merge_check;
    reviewers -> wait [label="yes"];
    wait -> read_all;
    read_all -> any_comments;
    any_comments -> categorize [label="yes"];
    any_comments -> merge_check [label="no, approved"];
    categorize -> oos;
    oos -> ask_oos [label="yes — pause\nuntil resolved"];
    oos -> fix [label="no"];
    ask_oos -> fix [label="user decided"];
    fix -> respond;
    respond -> resolve;
    resolve -> fixes_made;
    fixes_made -> rereview [label="yes"];
    fixes_made -> merge_check [label="no"];
    rereview -> ci_loop -> wait;
    merge_check -> done [label="yes"];
    merge_check -> wait [label="no — poll"];
}
```

**Reading comments:** always read ALL comments including inline on approved reviews — `gh pr view <N> --comments` does not return inline review comments. Use:

```bash
# GitHub — get all review comments (inline)
gh api repos/{owner}/{repo}/pulls/{number}/comments

# GitLab — get all discussions
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
| BLOCKING/IMPORTANT (fixed) | `✅ Fixed in [commit hash]. [What changed and why.]` |
| OPTIONAL | `Good suggestion. Acknowledging — keeping this PR focused on [goal].` |
| INVALID (outdated) | `This was addressed in [commit]. [File/code] now [does X].` |
| INVALID (praise) | `Thank you!` |
| OUT OF SCOPE | Per user's instruction |

## Resolving Threads

After responding, resolve threads where the issue is closed. Do NOT resolve if discussion is ongoing or awaiting reviewer confirmation.

```bash
# GitHub — resolve review thread via GraphQL
# 1. Get thread IDs:
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
# GitHub — re-request review (NOT --add-reviewer, which only adds new reviewers)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh api --method POST /repos/$REPO/pulls/$PR_NUMBER/requested_reviewers \
  -f "reviewers[]=username1" -f "reviewers[]=username2"

# GitLab
glab mr update <MR_NUMBER> --reviewer @username1,@username2
```

Do not request re-review for OPTIONAL or INVALID comments.

## Merge Requirements Checklist

Before merging, verify all of:
- [ ] All required CI/CD checks pass
- [ ] Required approvals received
- [ ] No unresolved blocking threads
- [ ] Branch up to date with base branch

**Branch behind base:**
```bash
# GitHub
gh pr update-branch <PR_NUMBER>
# or: git fetch origin <base> && git rebase origin/<base> && git push --force-with-lease

# GitLab
glab mr rebase <MR_NUMBER>
```

## Tools Priority

**GitHub/GitLab CLI → REST API → MCP**

| Platform | Detect from remote | CLI |
|----------|-------------------|-----|
| GitHub | `github.com` in remote URL | `gh` |
| GitLab | `gitlab` in remote URL | `glab` |

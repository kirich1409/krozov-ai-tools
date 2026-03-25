---
name: pr-lifecycle
description: Use when a PR/MR already exists and needs to be driven to merge — monitors CI/CD, handles multi-round code review, responds to and resolves reviewer comments, and loops until all merge requirements are met.
---

# PR Lifecycle

## Overview

Takes an existing PR/MR and drives it to merge autonomously. Loops through CI/CD monitoring and code review cycles until all requirements are satisfied.

**Core principle:** Fix only what belongs to the current PR. Ask the user when a problem is outside the current scope and the fix isn't obvious.

## Phase 1: CI/CD Monitoring

```dot
digraph cicd {
    rankdir=TB;

    start [label="PR/MR exists", shape=doublecircle];
    has_ci [label="CI/CD configured?", shape=diamond];
    wait [label="Wait for checks", shape=box];
    passing [label="All checks passing?", shape=diamond];
    investigate [label="Investigate\nfailure logs", shape=box];
    our_fault [label="Caused by\ncurrent changes?", shape=diamond];
    fix [label="Fix →\nprepare-for-pr →\npush", shape=box];
    ask [label="Ask user", shape=box];
    review [label="Proceed to\nCode Review", shape=box];

    start -> has_ci;
    has_ci -> wait [label="yes"];
    has_ci -> review [label="no"];
    wait -> passing;
    passing -> review [label="yes"];
    passing -> investigate [label="no"];
    investigate -> our_fault;
    our_fault -> fix [label="yes"];
    our_fault -> ask [label="no — stop"];
    fix -> wait;
}
```

## Phase 2: Code Review Cycle

```dot
digraph review {
    rankdir=TB;

    start [label="CI/CD passing", shape=doublecircle];
    reviewers [label="Reviewers assigned?", shape=diamond];
    wait [label="Wait for review", shape=box];
    comments [label="Comments received?", shape=diamond];
    categorize [label="Categorize all comments\n+ show table to user", shape=box];
    out_of_scope [label="OUT OF SCOPE\ncomments?", shape=diamond];
    ask_user [label="Ask user\nfor each OOS", shape=box];
    fix_blocking [label="Fix BLOCKING +\nIMPORTANT", shape=box];
    respond_all [label="Respond to every\ncomment individually\n(in PR language)", shape=box];
    resolve [label="Resolve all threads", shape=box];
    fixes_made [label="Fixes were made?", shape=diamond];
    rereview [label="Request re-review", shape=box];
    ci_again [label="Back to CI/CD", shape=box];
    merge_ok [label="Merge requirements\nmet?", shape=diamond];
    done [label="MERGE", shape=doublecircle];

    start -> reviewers;
    reviewers -> wait [label="yes"];
    reviewers -> merge_ok [label="no"];

    wait -> comments;
    comments -> categorize [label="yes"];
    comments -> merge_ok [label="approved"];
    categorize -> out_of_scope;
    out_of_scope -> ask_user [label="yes — stop\nuntil resolved"];
    out_of_scope -> fix_blocking [label="no"];
    ask_user -> fix_blocking [label="user decided"];
    fix_blocking -> respond_all;
    respond_all -> resolve;
    resolve -> fixes_made;
    fixes_made -> rereview [label="yes"];
    fixes_made -> merge_ok [label="no"];
    rereview -> ci_again;
    ci_again -> wait;
    merge_ok -> done [label="yes"];
    merge_ok -> wait [label="no"];
}
```

## Comment Categories

Assign ONE category per comment. Show the full table to user before acting — then proceed without waiting for approval, except for OUT OF SCOPE.

| Category | When to use | Action |
|----------|-------------|--------|
| **BLOCKING** | Security issues, critical bugs, compliance violations | Fix → respond with explanation → Resolve |
| **IMPORTANT** | Bugs, missing error handling, missing tests | Fix → respond with explanation → Resolve |
| **OPTIONAL** | Style, naming preference, refactor suggestions, nitpicks | Respond acknowledging → Resolve without fixing |
| **INVALID** | Already fixed, no longer applies, praise | Respond acknowledging → Resolve |
| **OUT OF SCOPE** | Requires changes outside this PR's scope | Ask user before acting |

**Show before acting:**

```markdown
## PR Review Comments

| # | Author | Location | Comment | Category | Action |
|---|--------|----------|---------|----------|--------|
| 1 | @dev | auth.ts:23 | "Password in plaintext" | BLOCKING | Will fix |
| 2 | @dev | auth.ts:12 | "Rename doAuth" | OPTIONAL | Will acknowledge |
| 3 | @qa | auth.ts:45 | "Missing error handling" | IMPORTANT | Will fix |
| 4 | @dev | auth.ts:67 | "Nice work!" | INVALID | Will acknowledge |
| 5 | @dev | utils.ts:10 | "This whole file needs refactor" | OUT OF SCOPE | Need your input |

Proceeding with BLOCKING + IMPORTANT fixes. OUT OF SCOPE items need your decision first.
```

## Responding to Comments

**Always respond in the same language as the PR and review comments.**

Respond to **every** comment individually — never a single summary.

| Category | Response template |
|----------|------------------|
| BLOCKING/IMPORTANT (fixed) | `✅ Fixed in [commit]. [What changed and why.]` |
| OPTIONAL (deferred) | `Good suggestion. Deferring to keep this PR focused — created [issue] to track.` |
| INVALID (outdated) | `This was addressed in [commit]. [File/code] now [does X].` |
| INVALID (praise) | `Thank you!` |
| OUT OF SCOPE (after user decision) | Per user's instruction |

## Resolving Threads

After responding, mark as Resolved if:
- Fix was implemented
- Question was answered
- Comment no longer applies

Do NOT resolve if discussion is ongoing or waiting for reviewer confirmation.

Use GitHub web UI for resolving ("Resolve conversation" button) — `gh` CLI doesn't support it directly.

## Re-Review

Request re-review only from reviewers whose BLOCKING or IMPORTANT comments were fixed:

```bash
# GitHub
gh pr edit <PR_NUMBER> --add-reviewer @username1,@username2
# GitLab
glab mr update <MR_NUMBER> --reviewer @username1,@username2
```

Do not request re-review for OPTIONAL deferred items or INVALID comments.

## Merge Requirements Checklist

- [ ] All required CI/CD checks pass
- [ ] Required approvals received (or no reviewers)
- [ ] No unresolved blocking threads
- [ ] Branch up to date with base branch

## Tools Priority

**GitHub/GitLab CLI → REST API → MCP**

Detect platform from remote URL and use the matching CLI:

| Platform | CLI | Read comments | Reply | Re-review |
|----------|-----|---------------|-------|-----------|
| GitHub | `gh` | `gh pr view <N> --comments` | `gh pr comment <N> --body "…"` | `gh pr edit <N> --add-reviewer @user` |
| GitLab | `glab` | `glab mr view <N> --comments` | `glab mr note <N> --message "…"` | `glab mr update <N> --reviewer @user` |

Fall back to REST API if CLI unavailable, then MCP as last resort.

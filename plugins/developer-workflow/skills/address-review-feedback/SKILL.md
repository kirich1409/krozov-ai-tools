---
name: address-review-feedback
description: >
  Use when the user has received review comments on a GitHub PR or GitLab MR and needs
  to process them — analyze, triage, coordinate fixes, respond, and resolve threads. This is THE skill
  for any post-review work on a PR/MR. Triggers on: "разберись с комментариями",
  "address review comments", "handle review feedback", "respond to reviewers",
  "fix review comments", "deal with PR/MR comments", "reply to review",
  "resolve review threads", "go through the feedback", "комментарии к PR/MR",
  "ревьюер оставил комментарии", "пройдись по комментариям", "тредов после ревью",
  "reviewer left comments", "got a review", "review feedback on my MR/PR",
  or any mention of processing, triaging, or responding to existing review comments
  on a pull request or merge request. Do NOT use for writing new reviews, creating PRs,
  or CI/CD monitoring — those are separate skills.
---

# Address Review Feedback

An orchestrator skill. Analyzes all review comments, categorizes them, detects
cross-diff patterns, presents an action plan for user confirmation, then coordinates
fixes, answers, and thread responses. Does NOT implement code changes itself — it
produces task descriptions for implementation agents.

**Core principle:** Fix what belongs to this PR. Push back when a suggestion is wrong.
Never perform agreement — just act and show evidence.

---

## Phase 1: Fetch & Parse

### Platform detection

```bash
REMOTE_URL=$(git remote get-url origin)
# Contains github.com → GitHub (gh)
# Contains gitlab     → GitLab (glab)
```

### Fetch PR/MR metadata and context

Fetch both technical metadata and the PR/MR context — description, linked issues, labels,
milestone. This context is essential for Phase 2: understanding the intent behind changes
lets you judge whether a comment is in scope, whether a suggestion aligns with the goal,
and what trade-offs matter.

```bash
# GitHub — metadata + context in one call
PR_INFO=$(gh pr view --json number,baseRefName,headRefName,title,body,labels,milestone,closingIssuesReferences)
PR_NUMBER=$(echo "$PR_INFO" | jq -r .number)
BASE=$(echo "$PR_INFO" | jq -r .baseRefName)
PR_BODY=$(echo "$PR_INFO" | jq -r .body)
PR_LABELS=$(echo "$PR_INFO" | jq -r '[.labels[].name] | join(", ")')
PR_MILESTONE=$(echo "$PR_INFO" | jq -r '.milestone.title // empty')
LINKED_ISSUES=$(echo "$PR_INFO" | jq -r '[.closingIssuesReferences[].number] | join(", ")')
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
OWNER=$(echo "$REPO" | cut -d/ -f1)
REPO_NAME=$(echo "$REPO" | cut -d/ -f2)

# GitHub — if linked issues exist, fetch their bodies for context
# (issue description often contains acceptance criteria and requirements)
for ISSUE_NUM in $(echo "$PR_INFO" | jq -r '.closingIssuesReferences[].number'); do
  gh issue view "$ISSUE_NUM" --json title,body --jq '"\(.title): \(.body)"'
done

# GitLab — metadata + context
MR_INFO=$(glab mr view --output json)
MR_IID=$(echo "$MR_INFO" | jq -r .iid)
MR_BODY=$(echo "$MR_INFO" | jq -r .description)
MR_LABELS=$(echo "$MR_INFO" | jq -r '[.labels[]] | join(", ")')
MR_MILESTONE=$(echo "$MR_INFO" | jq -r '.milestone.title // empty')
PROJECT=$(glab repo view --output json | jq -r '.path_with_namespace')
BASE=$(echo "$MR_INFO" | jq -r .target_branch)

# GitLab — fetch linked issues (closing pattern in description: "Closes #123")
# Extract issue IIDs from description, then fetch each
echo "$MR_BODY" | grep -Eo '(Closes?|Fixes?|Resolves?) #[0-9]+' | sed 's/.*#//' | while read ISSUE_IID; do
  glab api "/projects/$PROJECT/issues/$ISSUE_IID" --jq '"\(.title): \(.description)"'
done
```

### Build the change context

Before analyzing comments, summarize what this PR/MR is about:

- **Goal** — from the PR/MR description and linked issue titles
- **Scope** — from labels, milestone, and the list of changed files
- **Requirements** — from linked issue bodies (acceptance criteria, constraints)

Use this context throughout Phase 2 to decide scope, priority, and whether to push back.

### Fetch all comments

Fetch every comment type separately — each endpoint returns different data.

```bash
# GitHub — inline review comments (attached to specific lines)
gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/comments" \
  --jq '[.[] | {id, in_reply_to_id, user:.user.login, path, line, body, created_at}]'

# GitHub — review summaries (top-level review objects with body text)
gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/reviews" \
  --jq '[.[] | {id, user:.user.login, state, body, submitted_at}]'

# GitHub — PR-level issue comments (not inline, not review summaries)
gh api "repos/$OWNER/$REPO_NAME/issues/$PR_NUMBER/comments" \
  --jq '[.[] | {id, user:.user.login, body, created_at}]'

# GitLab — all discussions (inline, review summaries, and general notes in one call)
glab api "/projects/$PROJECT/merge_requests/$MR_IID/discussions" \
  --jq '[.[] | {id, notes: [.notes[] | {id, author:.author.username, body, position:.position, resolved, created_at}]}]'
```

### Parse each comment

For each comment record, extract:
- **author** — reviewer username
- **location** — `file:line` for inline comments; `(review summary)` for top-level reviews; `(PR comment)` for issue comments
- **body** — full text
- **thread_state** — resolved / unresolved (GitHub: check `resolvedAt` on the thread node via GraphQL; GitLab: `notes[0].resolved`)
- **in_reply_to** — whether this is a reply in an existing thread (skip root analysis — reply context is part of the thread)

Skip already-resolved threads unless the resolution seems premature (e.g., reviewer resolved their own open question without getting an answer).

---

## Phase 2: Analyze & Categorize

### Read the diff

```bash
git diff "$BASE"...HEAD
```

Use the diff for two purposes: verifying suggestions are technically valid, and detecting repeated patterns.

### Assign one category per comment

| Category | When to assign |
|----------|---------------|
| **BLOCKING** | Security vulnerability, critical bug, compliance violation, data loss risk |
| **IMPORTANT** | Non-critical bug, missing error handling, logic error, missing test for a broken case |
| **SUGGESTION** | Refactoring opportunity, architectural improvement, better approach — no correctness risk |
| **NIT** | Naming, formatting, style, minor preferences with no functional impact |
| **QUESTION** | Reviewer asking for clarification — needs an answer, may or may not need a code change |
| **PRAISE** | Compliment or approval — no action needed |
| **OUT_OF_SCOPE** | Valid concern, but requires changes outside this PR's scope |

### Assess actionability per comment

| Actionability | Meaning |
|--------------|---------|
| **FIXABLE** | Clear what to change — can be delegated directly |
| **NEEDS_CLARIFICATION** | Comment is ambiguous — must ask reviewer before acting |
| **DISCUSSION** | No single right answer — needs conversation with reviewer and/or user |
| **NO_ACTION** | Praise, already fixed, or demonstrably invalid |

### Verify before accepting

Before labeling a BLOCKING or IMPORTANT comment as FIXABLE, verify the suggestion:

1. Is it technically correct for this codebase?
2. Would it break existing functionality or tests?
3. Is there a documented reason the current code is written this way?
4. Does it apply to all platforms/versions targeted by this PR?

If any check fails → category stays, but actionability becomes DISCUSSION with a note on what's wrong with the suggestion.

### Detect patterns

For each BLOCKING, IMPORTANT, or SUGGESTION comment that points to a specific code pattern
(null check, error handling, naming convention, etc.):

1. Extract the problematic pattern from the diff at the referenced location
2. Search the rest of the diff for the same pattern in other files or lines
3. If found → note: `Pattern also at: file:line, file:line`

This prevents fixes that address the reported location but leave identical problems elsewhere.

### Group related comments

- Comments from different reviewers about the same logical issue → one group, one action item
- Multiple comments from the same reviewer about closely related concerns → one group if a single fix addresses all

Each group produces one action item in the plan.

---

## Phase 3: Present Plan

Show the full analysis before doing anything. Wait for user confirmation.

```markdown
## Review Feedback Analysis

### Summary
- X comments total across Y reviewers
- Z BLOCKING, A IMPORTANT, B SUGGESTION, C NIT, D QUESTION, E PRAISE, F OUT_OF_SCOPE
- G patterns detected (same issue in multiple locations)
- H comments need clarification before acting

### Action Plan

#### BLOCKING (must fix)
| # | Author | Location | Issue | Pattern? | Action |
|---|--------|----------|-------|----------|--------|
| 1 | @alice | auth.kt:45 | SQL injection via raw query | +2 locations | Fix in 3 files |

#### IMPORTANT (should fix)
| # | Author | Location | Issue | Pattern? | Action |
|---|--------|----------|-------|----------|--------|
| 2 | @bob | session.kt:12 | Missing null check on token | none | Fix |

#### SUGGESTION (consider)
| # | Author | Location | Issue | Actionability | Action |
|---|--------|----------|-------|--------------|--------|
| 3 | @alice | order.kt:88 | Extract to separate function | FIXABLE | Fix (or decline — your call) |

#### QUESTION (answer needed)
| # | Author | Location | Question | Action |
|---|--------|----------|----------|--------|
| 4 | @carol | README.md | Why not use X approach here? | Answer in thread |

#### NIT (acknowledge only)
| # | Author | Location | Comment |
|---|--------|----------|---------|
| 5 | @bob | util.kt:3 | Trailing whitespace |

#### PRAISE (no action)
| # | Author | Comment |
|---|--------|---------|
| 6 | @alice | Looks clean! |

#### OUT_OF_SCOPE (your decision)
| # | Author | Issue | Recommendation |
|---|--------|-------|---------------|
| 7 | @carol | Entire auth module needs rework | Decline with note; log as follow-up issue if agreed |

### Proposed execution order
1. Seek clarification on NEEDS_CLARIFICATION items — pause until resolved
2. Fix BLOCKING #1 (3 files) — implementation agent task
3. Fix IMPORTANT #2 — implementation agent task
4. Address SUGGESTION #3 — awaiting your call (fix or decline)
5. Answer QUESTION #4 — reply in thread
6. Acknowledge NITs #5 — reply and resolve
7. OUT_OF_SCOPE #7 — awaiting your decision
```

**Wait for user response.** The user may:
- Approve as-is → proceed
- Re-categorize specific comments → update and proceed
- Skip specific items → remove from plan
- Add context or notes for specific items → incorporate into task descriptions or responses

---

## Phase 4: Execute

Execute in the order below. Do not proceed to the next step until the current one is complete.

### Step 1: Clarifications (if any NEEDS_CLARIFICATION items)

Reply to those threads asking for specifics. Ask all clarification questions in a single
round — one reply per ambiguous thread, all at once. Then pause and wait for reviewer
responses before proceeding with affected items.

```bash
# GitHub — reply to an inline review comment
gh api "repos/$OWNER/$REPO_NAME/pulls/comments/$COMMENT_ID/replies" \
  --method POST -f body="<question text>"

# GitHub — reply to a top-level PR comment or review summary
gh pr comment "$PR_NUMBER" --body "<question text>"

# GitLab — reply to a discussion note
glab api "/projects/$PROJECT/merge_requests/$MR_IID/discussions/$DISCUSSION_ID/notes" \
  --method POST -f body="<question text>"
```

### Step 2: Delegate fixes

For each approved fix group (BLOCKING / IMPORTANT / accepted SUGGESTION), produce a task
description for an implementation agent. Include:

- **What to fix** — exact issue as described by the reviewer
- **Where** — primary file:line + all pattern locations detected in Phase 2
- **Why** — reviewer's reasoning (quote directly where it adds clarity)
- **Constraints** — do not change code outside the listed locations; do not alter unrelated logic

Output these task descriptions. The main session orchestrator spawns the implementation
agents — this skill does not call agents directly.

### Step 3: Answer questions

For each QUESTION thread, derive the answer from code context (read the relevant file
and surrounding logic). Reply directly in the thread.

```bash
# Same reply commands as Step 1
```

### Step 4: Respond to all addressed comments

After fixes are committed, post responses. For declined suggestions, respond immediately
(no commit needed).

**Response rules — no performative agreement.** Never write "Great point!", "You're right!",
"Thanks for catching that!". State what changed and why, or state disagreement with evidence.

| Category | Response |
|----------|----------|
| BLOCKING / IMPORTANT (fixed) | `Fixed in <commit hash>. <One sentence: what changed and where.>` |
| BLOCKING / IMPORTANT (pushed back — suggestion is incorrect) | `<Technical reasoning with evidence from codebase. Reference file:line or test.> Keeping as-is.` |
| SUGGESTION (accepted, fixed) | `Addressed in <commit hash>. <What changed.>` |
| SUGGESTION (declined) | `Keeping as-is — <brief reason>. <Optional: "Logged as <issue> for follow-up.">` |
| NIT | `Noted. Not addressing in this PR to keep scope focused.` |
| QUESTION | The answer itself — complete, no fluff |
| PRAISE | *(no response — resolve silently)* |
| OUT_OF_SCOPE | Per user's decision from Phase 3 |

```bash
# GitHub — reply to inline review comment
gh api "repos/$OWNER/$REPO_NAME/pulls/comments/$COMMENT_ID/replies" \
  --method POST -f body="<response>"

# GitHub — reply to top-level comment or review summary
gh pr comment "$PR_NUMBER" --body "<response>"

# GitLab — reply to discussion
glab api "/projects/$PROJECT/merge_requests/$MR_IID/discussions/$DISCUSSION_ID/notes" \
  --method POST -f body="<response>"
```

### Step 5: Resolve threads

Resolve threads where the issue is fully closed. Do NOT resolve if:
- Awaiting reviewer confirmation after a pushback
- The thread is marked DISCUSSION and no consensus has been reached
- NEEDS_CLARIFICATION items still awaiting reviewer reply

```bash
# GitHub — get thread node IDs (needed for GraphQL resolve mutation)
gh api graphql -f query='
  query($owner:String!,$repo:String!,$number:Int!) {
    repository(owner:$owner,name:$repo) {
      pullRequest(number:$number) {
        reviewThreads(first:100) {
          nodes {
            id
            isResolved
            comments(first:1) { nodes { body databaseId } }
          }
        }
      }
    }
  }
' -f owner="$OWNER" -f repo="$REPO_NAME" -F number="$PR_NUMBER"

# GitHub — resolve a thread by node ID
gh api graphql -f query='
  mutation($id:ID!) {
    resolveReviewThread(input:{threadId:$id}) { thread { isResolved } }
  }
' -f id="<THREAD_NODE_ID>"

# GitLab — resolve a discussion
glab api "/projects/$PROJECT/merge_requests/$MR_IID/discussions/$DISCUSSION_ID" \
  --method PUT -f resolved=true
```

---

## Principles

**Push back when a suggestion is wrong.** If a reviewer's recommendation would introduce
a bug, violate a project pattern, or doesn't apply to this codebase — say so. Use technical
evidence: reference the file, the test, the documented behavior. Involve the user if the
disagreement is architectural.

**Pattern completeness.** A fix that addresses only the reported location while leaving
identical problems elsewhere is incomplete. Always check the full diff before marking
a comment resolved.

**One clarification round.** Batch all ambiguous items and ask in a single pass. Never
send clarification requests one at a time as they get resolved — wait until you have
all questions ready.

**Scope discipline.** OUT_OF_SCOPE comments are valid concerns — don't dismiss them.
Surface them clearly to the user with a recommendation (decline with note, or log as
a follow-up issue). The user decides; you execute that decision.

**Tools priority:** CLI (gh / glab) → REST API → MCP.

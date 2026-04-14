---
name: pr-drive-to-merge
description: >
  Use when a PR/MR already exists and needs to be driven to merge — monitors CI/CD,
  handles multi-round code review, responds to and resolves reviewer comments, and
  loops until all merge requirements are met.
  Triggers on: "merge this PR", "drive to merge", "get this merged", "monitor CI",
  "watch CI and merge", "довести до мержа", "замержь этот PR", "drive this to merge",
  "finish this PR", "get it merged", "land this PR", "ship this PR",
  "доведи PR до мержа", "следи за CI и мержь".
  Do NOT use for: creating new PRs (use create-pr), writing code or implementing features
  (use implement), reviewing code (use code-reviewer agent), addressing a single
  round of review comments without merge intent (use address-review-feedback directly).
  Cross-references: invokes address-review-feedback for review handling. Invoked by
  the orchestrator as the final pipeline stage.
---

# PR Drive to Merge

Autonomous orchestrator that takes an existing PR/MR from its current state to a
successful merge. Monitors CI/CD pipelines, handles review feedback across multiple
rounds, and merges when all requirements are satisfied.

**Core principle:** keep the PR moving. Every stall — CI failure, pending review,
merge conflict — is an obstacle to identify, fix or escalate, and move past. The loop
exits only when the PR is merged or escalation is required.

---

## Phase 1: Setup

### 1.1 Detect platform

```bash
REMOTE_URL=$(git remote get-url origin)
# Contains github.com → GitHub (gh CLI)
# Contains gitlab     → GitLab (glab CLI)
```

### 1.2 Fetch PR/MR info

```bash
# GitHub
PR_INFO=$(gh pr view --json number,baseRefName,headRefName,title,isDraft,state,statusCheckRollup,reviewDecision,mergeable,mergeStateStatus,reviews,url)
PR_NUMBER=$(echo "$PR_INFO" | jq -r .number)
PR_URL=$(echo "$PR_INFO" | jq -r .url)
IS_DRAFT=$(echo "$PR_INFO" | jq -r .isDraft)
BASE=$(echo "$PR_INFO" | jq -r .baseRefName)
HEAD=$(echo "$PR_INFO" | jq -r .headRefName)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
OWNER=$(echo "$REPO" | cut -d/ -f1)
REPO_NAME=$(echo "$REPO" | cut -d/ -f2)

# GitLab
MR_INFO=$(glab mr view --output json)
MR_IID=$(echo "$MR_INFO" | jq -r .iid)
MR_URL=$(echo "$MR_INFO" | jq -r .web_url)
IS_DRAFT=$(echo "$MR_INFO" | jq -r '.title | startswith("Draft:")')
BASE=$(echo "$MR_INFO" | jq -r .target_branch)
PROJECT=$(glab repo view --output json | jq -r '.path_with_namespace | @uri')
# Note: path_with_namespace contains '/' (e.g. "group/repo") which must be
# URL-encoded to "%2F" for GitLab REST API path segments. @uri in jq handles this.
```

### 1.3 Validate preconditions

Before entering the loop, verify:
- PR/MR exists and is open (not already merged or closed)
- Current branch matches the PR head branch
- Local branch is up to date with remote (`git fetch origin && git diff HEAD..origin/$HEAD --stat`)

If any check fails — report the issue and stop.

### 1.4 Create state file

Create `swarm-report/<slug>-drive-to-merge-state.md` to track progress across
potential context compaction:

```markdown
# Drive to Merge: <PR title>

PR: <url>
Platform: GitHub | GitLab
Number: <number>
Base: <base branch>
Started: <date>
Status: in-progress

## Phase Progress
- [x] Setup — completed
- [ ] CI/CD Monitoring
- [ ] Code Review Handling
- [ ] Merge

## CI History
| Run | Status | Failed jobs | Action taken |
|-----|--------|-------------|--------------|

## Review Rounds
| Round | Reviewer | Comments | Outcome |
|-------|----------|----------|---------|

## Escalations
(none yet)
```

**Slug derivation:** reuse the branch name in kebab-case, stripped of the prefix
(`feature/`, `fix/`, etc.). Example: `feature/user-avatar-upload` -> `user-avatar-upload`.

---

## Phase 2: CI/CD Monitoring

### 2.1 Wait for CI checks

```bash
# GitHub — watch checks until they complete (blocks until done)
gh pr checks "$PR_NUMBER" --watch --fail-fast

# GitLab — poll pipeline status
glab ci status --live
```

If `gh pr checks --watch` is unavailable or times out, fall back to a manual poll loop:

```bash
while true; do
  STATUS=$(gh pr checks "$PR_NUMBER" --json name,state,conclusion \
    --jq '[.[] | select(.state != "COMPLETED" or (.conclusion | test("FAILURE|CANCELLED|TIMED_OUT|ACTION_REQUIRED|STARTUP_FAILURE|STALE")))]')
  PENDING=$(echo "$STATUS" | jq '[.[] | select(.state != "COMPLETED")] | length')
  FAILED=$(echo "$STATUS" | jq '[.[] | select(.conclusion | test("FAILURE|CANCELLED|TIMED_OUT|ACTION_REQUIRED|STARTUP_FAILURE|STALE"))] | length')

  if [ "$PENDING" -eq 0 ] && [ "$FAILED" -eq 0 ]; then
    break  # All green
  elif [ "$PENDING" -eq 0 ] && [ "$FAILED" -gt 0 ]; then
    break  # Failures to investigate
  fi
  sleep 60
done
```

### 2.2 Handle CI failures

When a check fails:

1. **Get the failure details:**

```bash
# GitHub — find the failed run and get logs
FAILED_RUN=$(gh run list --branch "$HEAD" --status failure --limit 1 --json databaseId -q '.[0].databaseId')
gh run view "$FAILED_RUN" --log-failed
```

2. **Cross-reference with PR diff:**

```bash
git diff "$BASE"..."$HEAD"
```

Compare the failed log output against the changed files. Determine:
- **Our fault** — the failure is caused by changes in this PR
- **Not our fault** — pre-existing failure, flaky test, infra issue

3. **If our fault — fix it:**
   - Identify the root cause from the log
   - Fix the code
   - Run the relevant quality gates locally before pushing:
     - Build: `./gradlew build` (or project-equivalent)
     - Tests: `./gradlew test` (or the specific failing test)
     - Lint: `./gradlew lint` (if applicable)
   - Commit with a descriptive message referencing the CI failure
   - Push and return to step 2.1 (wait for CI again)

4. **If not our fault — escalate:**
   - Log the failure details in the state file under Escalations
   - Report to the user: what failed, why it's not related to PR changes, evidence
   - Ask whether to retry, ignore, or wait

5. **Fix attempt limit:** if 3 fix attempts for the same CI failure have been made
   and it still fails — stop and escalate. Something deeper is wrong.

### 2.3 Undraft when CI passes

If the PR is a draft and all CI checks pass:

```bash
# GitHub
gh pr ready "$PR_NUMBER"

# GitLab
glab mr update "$MR_IID" --remove-draft
```

Update the state file: mark CI/CD Monitoring as complete.

---

## Phase 3: Code Review Handling

### 3.1 Outer review loop

This phase runs in a loop until there are no more unaddressed review comments and
the PR has the required approvals.

```
while (unaddressed comments exist OR approvals insufficient):
    3.2 Detect unaddressed comments
    3.3 Invoke address-review-feedback
    3.4 Verify fixes were pushed
    3.5 Re-request review
    3.6 Wait for reviewer response
```

### 3.2 Detect unaddressed comments

```bash
# GitHub — check for pending reviews and unresolved threads
REVIEW_DECISION=$(gh pr view "$PR_NUMBER" --json reviewDecision -q .reviewDecision)
# APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED, or empty

# GitHub — count unresolved threads
UNRESOLVED=$(gh api graphql -f query='
  query($owner:String!,$repo:String!,$number:Int!) {
    repository(owner:$owner,name:$repo) {
      pullRequest(number:$number) {
        reviewThreads(first:100) {
          nodes { isResolved }
        }
      }
    }
  }
' -f owner="$OWNER" -f repo="$REPO_NAME" -F number="$PR_NUMBER" \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length')

# GitLab — check unresolved discussions
UNRESOLVED=$(glab api "/projects/$PROJECT/merge_requests/$MR_IID/discussions" \
  --jq '[.[] | select(.notes[0].resolved == false and .notes[0].system == false)] | length')
```

If `REVIEW_DECISION` is `APPROVED` and `UNRESOLVED` is 0 — skip to Phase 4 (Merge).

### 3.3 Invoke address-review-feedback

Delegate review comment handling to the `developer-workflow:address-review-feedback` skill.
This skill will:
- Fetch and categorize all comments
- Present an action plan
- Coordinate fixes via implementation agents
- Respond to reviewers and resolve threads

Include the state file path in the delegation context so the skill can update it.

### 3.4 Verify fixes were pushed

After address-review-feedback completes:

```bash
# Check that new commits exist after the review round
LATEST_COMMIT=$(git log -1 --format=%H)
REMOTE_COMMIT=$(git ls-remote origin "$HEAD" | cut -f1)
# If they differ → push is needed
[ "$LATEST_COMMIT" != "$REMOTE_COMMIT" ] && git push
```

### 3.5 Re-request review

After pushing fixes, re-request review from the reviewers who requested changes:

```bash
# GitHub — get reviewers who requested changes
REVIEWERS=$(gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/reviews" \
  --jq '[.[] | select(.state == "CHANGES_REQUESTED") | .user.login] | unique | join(",")')

# GitHub — re-request review (only if there are reviewers to re-request)
if [ -n "$REVIEWERS" ]; then
  gh pr edit "$PR_NUMBER" --add-reviewer "$REVIEWERS"
fi

# GitLab — no explicit re-request; pushing new commits notifies reviewers
```

### 3.6 Wait for reviewer response

Distinguish between **bot reviews** (CI, automated checks) and **human reviews**:

**Bot reviews** (review author is a bot or CI system) — wait and poll:
```bash
# Poll for bot review activity (short cycle — bots respond in minutes)
# Timeout: 15 minutes. If bots haven't responded — escalate.
BASELINE_REVIEWS=$(gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/reviews" \
  --jq '[.[] | select(.user.type == "Bot")] | length')
TIMEOUT=900
ELAPSED=0
while true; do
  sleep 60
  ELAPSED=$((ELAPSED + 60))
  CURRENT_REVIEWS=$(gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/reviews" \
    --jq '[.[] | select(.user.type == "Bot")] | length')
  if [ "$CURRENT_REVIEWS" -gt "$BASELINE_REVIEWS" ]; then
    break  # New bot review detected — re-enter the loop at 3.2
  fi
  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    break  # Bot timeout — report and stop
  fi
done
```
If bots don't respond within 15 minutes — report the stall and stop. This likely indicates
a CI infrastructure issue, not something the skill can fix.

**Human reviews** — **do NOT poll**. Human reviews can take hours or days.
Instead, stop and report to the user:

1. Log current state in the state file
2. Report:
   - PR URL and current status
   - Which reviewers were requested
   - What bot checks remain (if any)
   - All automated work is complete — waiting for human review
3. **Stop the skill.** The user resumes when a reviewer responds (e.g., "check PR",
   "reviewer responded", "continue with PR")

On resume:
1. Re-read the state file at `swarm-report/<slug>-drive-to-merge-state.md`
2. Fetch current PR state (new reviews, comments, CI status)
3. If new review comments → re-enter at step 3.2
4. If approved → proceed to Phase 4 (Merge)
5. If no new activity → report and stop again

### 3.8 Update state

After each review round, update the state file:

```markdown
## Review Rounds
| Round | Reviewer | Comments | Outcome |
|-------|----------|----------|---------|
| 1     | @alice   | 3 (2 fixed, 1 declined) | Changes pushed, re-requested |
| 2     | @alice   | 1 (acknowledged) | Approved |
```

---

## Phase 4: Merge

### 4.1 Pre-merge checklist

Before merging, verify all requirements are met:

```bash
# GitHub — check mergeable state
MERGE_STATE=$(gh pr view "$PR_NUMBER" --json mergeable,mergeStateStatus,reviewDecision,statusCheckRollup \
  --jq '{mergeable, mergeStateStatus, reviewDecision, checks: [.statusCheckRollup[] | .conclusion] | unique}')
```

All of these must be true:
- CI checks: all green (no FAILURE or PENDING)
- Review: `APPROVED` (or no review required per repo settings)
- Unresolved threads: 0
- Merge conflicts: none (`mergeable` is `MERGEABLE`)
- PR is not a draft

### 4.2 Update branch if behind

If the PR branch is behind the base branch:

```bash
# GitHub — try the API merge-upstream first (no local rebase needed)
gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/update-branch" \
  --method PUT -f expected_head_oid="$(git rev-parse HEAD)"

# If that fails (conflicts) — rebase locally
git fetch origin "$BASE"
git rebase "origin/$BASE"
# If rebase conflicts are within PR scope → resolve, push, return to Phase 2
# If conflicts are outside PR scope → escalate to user
```

After updating the branch, return to Phase 2 (CI/CD Monitoring) — the updated branch
needs fresh CI checks before merging.

### 4.3 Request merge confirmation

**Always ask the user for confirmation before merging** unless the user explicitly
pre-approved merging at the start of the session (e.g., "merge it when ready",
"drive to merge, no need to ask").

Present the merge summary:

```markdown
## Ready to merge

**PR:** <title> (<url>)
**CI:** all checks passing
**Reviews:** approved by <reviewers>
**Unresolved threads:** 0
**Branch:** up to date with <base>

Merge method: squash (default)

Proceed with merge?
```

### 4.4 Execute merge

```bash
# GitHub — squash merge and delete the branch
gh pr merge "$PR_NUMBER" --squash --delete-branch

# GitLab — squash merge and delete the branch
glab mr merge "$MR_IID" --squash --remove-source-branch --yes
```

### 4.5 Post-merge cleanup

After successful merge:

1. Update the state file status to `done`
2. Switch to the base branch and pull:
   ```bash
   git checkout "$BASE"
   git pull origin "$BASE"
   ```
3. If working in a worktree — exit and clean up:
   ```bash
   # From the main worktree
   git worktree remove ".worktrees/$HEAD" 2>/dev/null
   git branch -d "$HEAD" 2>/dev/null
   ```

---

## State Persistence

The state file at `swarm-report/<slug>-drive-to-merge-state.md` ensures the skill
survives context compaction. Before every action in any phase:

1. Re-read the state file via Read tool
2. Check completed steps (`[x]`) — do not repeat them
3. Resume from the first incomplete step (`[ ]`)
4. Update the state file after completing each significant step

### State file structure

```markdown
# Drive to Merge: <PR title>

PR: <url>
Platform: GitHub | GitLab
Number: <number>
Base: <base branch>
Started: <date>
Status: in-progress | done | blocked

## Phase Progress
- [x] Setup — completed
- [x] CI/CD Monitoring — all checks green
- [ ] Code Review Handling — round 2 in progress
- [ ] Merge

## CI History
| Run | Status | Failed jobs | Action taken |
|-----|--------|-------------|--------------|
| #1  | FAIL   | lint        | Fixed import ordering, pushed |
| #2  | PASS   | —           | —            |

## Review Rounds
| Round | Reviewer | Comments | Outcome |
|-------|----------|----------|---------|
| 1     | @alice   | 5 (3 fixed, 1 declined, 1 answered) | Re-requested |

## Escalations
- 2026-04-11 14:30: Review stale >4h, notified user
```

---

## Escalation Policy

Stop and ask the user when:

| Condition | Action |
|-----------|--------|
| CI failure is not caused by PR changes | Report evidence, ask: retry / ignore / wait |
| 3 failed fix attempts for the same CI issue | Report attempts, ask for help |
| No reviewer response for >4 hours | Report stall, ask: ping / reassign / wait |
| Merge confirmation required | Present summary, wait for approval |
| Rebase conflicts outside PR scope | Report conflicting files, ask for resolution |
| PR is blocked by branch protection rules | Report which rule blocks, ask how to proceed |

**Never silently wait.** Every stall must be surfaced within its timeout window.

---

## Integration

This skill operates both standalone and as a phase in larger workflows:

- **Standalone:** user has an existing PR and wants it merged — invoke directly
- **Pipeline phase:** the orchestrator invokes this skill after implementation, quality loop,
  after the quality loop (Phase 2) and PR creation (Phase 3) are complete

In both cases, the skill takes ownership from the current PR state and drives
forward until merge or escalation.

---

## Decision Guide

| Ask the user | Decide autonomously |
|---|---|
| Merge confirmation (unless pre-approved) | Fix CI failures caused by PR changes |
| CI failures not caused by PR changes | Undraft PR when CI passes |
| Review stale >4 hours | Re-request review after pushing fixes |
| Rebase conflicts outside PR scope | Update branch when behind base |
| Reviewer disagrees with a pushback | Resolve threads after fixes are confirmed |

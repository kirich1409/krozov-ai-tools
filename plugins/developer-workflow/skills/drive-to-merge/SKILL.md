---
name: drive-to-merge
description: >
  Autonomous orchestrator that takes an existing PR/MR from its current state to merge. Monitors
  CI/CD, diagnoses failures, fetches review comments, categorizes them inline, proposes concrete
  fixes (snippet or delegation), delegates to implement/debug, posts replies, resolves threads,
  re-requests review (Copilot + humans), polls via ScheduleWakeup, loops until merged. Decision
  tables rendered in-session — no user-editable manifest. Default mode waits for "approve" per
  round; `--auto` proceeds without waiting; `--dry-run` stops after the first table. Final merge
  always requires explicit user confirmation. Triggers: "drive this PR to merge", "get this PR
  merged", "monitor CI and reviews", "ship this PR", "land this PR", "доведи PR до мержа",
  "веди PR", "замержь этот PR". Do NOT use for creating new PRs (use create-pr) or code
  written from scratch (use implement).
---

# Drive to Merge

Autonomous end-to-end PR driver. Takes the currently open PR/MR from its present state
and loops — diagnose CI, categorize review comments, propose fixes, delegate, push,
re-request review, wait for new activity — until the PR is merged or a true blocker
requires the user.

**Core principle:** keep the PR moving. Every obstacle (CI failure, review comment,
stalled reviewer) is a loop iteration, not a stop. The skill stops only for: the final
merge (requires user confirmation), true disagreements with a reviewer that need a
human judgement call, or mechanical dead-ends (permission denied, rebase conflict the
skill cannot resolve).

**In-session, not in files.** All analysis, categorization, and proposed actions are
rendered in the conversation as tables. A state file exists only to survive context
compaction — the user never edits it.

---

## Modes

| Mode | What it changes |
|---|---|
| default | Between rounds shows a decision table and waits for `approve` / `skip` / `stop` |
| `--auto` | Same table shown for visibility, then proceeds without waiting; merge step still asks |
| `--dry-run` | Runs analysis and renders the decision table once; makes no edits, pushes, or posts; exits |

Trigger words equivalent to `--auto`: "действуй автономно", "без подтверждений", "auto mode", "не спрашивай". The skill echoes which mode it is running in before Phase 2.

The merge step in Phase 5 **always** asks — `--auto` does not override that.

---

## Phase 1: Setup

### 1.1 Detect platform

```bash
REMOTE_URL=$(git remote get-url origin)
# github.com → gh CLI
# gitlab     → glab CLI
```

### 1.2 Fetch PR/MR metadata

```bash
# GitHub
PR_INFO=$(gh pr view --json number,baseRefName,headRefName,title,body,isDraft,state,url,\
statusCheckRollup,reviewDecision,mergeable,mergeStateStatus,labels,closingIssuesReferences)
PR_NUMBER=$(jq -r .number <<<"$PR_INFO")
PR_URL=$(jq -r .url <<<"$PR_INFO")
IS_DRAFT=$(jq -r .isDraft <<<"$PR_INFO")
BASE=$(jq -r .baseRefName <<<"$PR_INFO")
HEAD=$(jq -r .headRefName <<<"$PR_INFO")
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
OWNER=${REPO%/*}; REPO_NAME=${REPO#*/}

# Node ids — needed later for thread-ownership re-verify and Copilot re-request.
REPO_NODE_ID=$(gh api graphql -f query='query($o:String!,$n:String!){repository(owner:$o,name:$n){id}}' \
  -F o="$OWNER" -F n="$REPO_NAME" --jq '.data.repository.id')
PR_NODE_ID=$(gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER" --jq '.node_id')
# COPILOT_NODE_ID is resolved lazily in Phase 3.6 and cached in the state file header.

# GitLab
MR_INFO=$(glab mr view --output json)
MR_IID=$(jq -r .iid <<<"$MR_INFO")
MR_URL=$(jq -r .web_url <<<"$MR_INFO")
IS_DRAFT=$(jq -r '.title | startswith("Draft:")' <<<"$MR_INFO")
BASE=$(jq -r .target_branch <<<"$MR_INFO")
PROJECT=$(glab repo view --output json | jq -r '.path_with_namespace | @uri')
```

If the PR/MR is already merged or closed — stop and report the final state.

### 1.3 Preconditions

Abort with a clear message if any of these fail:

- Current branch matches the PR head branch. If not — abort with `checkout <head> first; this skill does not auto-switch branches`.
- Local branch is fetched and not behind the remote head (`git fetch origin && git status -sb`).
- `gh auth status` / `glab auth status` — token valid.
- The base branch still exists on the remote.

### 1.4 State file

`swarm-report/<slug>-drive-state.md`. Slug = branch name with `feature/` / `fix/` / `chore/` stripped. Verify `swarm-report/` is gitignored. If absent — abort with a clear message asking the user to add `swarm-report/` to `.gitignore` and rerun. Do not auto-modify `.gitignore`: that creates an unrelated diff inside a PR-driving loop and surprises the user.

Schema (markdown, machine-parseable by the skill on resume):

```markdown
# Drive to Merge — <PR title>

URL: <PR URL>
Platform: github | gitlab
Mode: default | auto | dry-run
Principal: <@actor>            # gh api user --jq .login
Repository node id: <graphql node id of the repository>
PR node id: <graphql node id of the pull request>
Copilot node id: <graphql node id of copilot-pull-request-reviewer or `unavailable`>
Started: <ISO8601>
Status: running | waiting-for-user | merged | blocked

## Rounds
| # | Started | Trigger | CI | New comments | Actions | Outcome |
|---|---------|---------|----|--------------|---------|---------|

## Commitments (open threads this skill owns)
| thread_id | category | delegated_to | fix_commit_sha | replied | resolved |
|-----------|----------|--------------|----------------|---------|----------|

`fix_commit_sha` holds the abbreviated sha of the commit that addressed the thread (empty string if the thread is dismiss-only, no code change).

## Blockers raised
<empty | list of items the skill surfaced to the user>
```

On every resume (new session after context compaction) — re-read this file first; do not re-run analysis that already lives in a "Commitments" row unless the reviewer posted new activity.

**Mode precedence on resume.** The state file `Mode` is the authoritative source. A fresh invocation without a flag inherits the stored mode; a fresh invocation with an explicit flag **overrides** the stored mode and rewrites it. This lets the user downgrade an `auto` run to `default` by re-invoking the skill, but does not silently demote an autonomous run just because the wake-up prompt was edited.

---

## Phase 2: Round loop

One round = one full pass of Phases 2.1 → 2.5. After 2.5, either merge (Phase 5) or sleep (Phase 4) and start a new round.

Each round begins by re-fetching PR state. Nothing is cached across rounds except the state file.

### 2.1 Sync PR state

```bash
# GitHub — single call covers CI rollup, reviews decision, mergeability
PR_STATE=$(gh pr view --json statusCheckRollup,reviewDecision,mergeable,mergeStateStatus,\
isDraft,state,reviews,reviewRequests)
```

Classify:

| PR attribute | Values that matter |
|---|---|
| `state` | OPEN → continue; MERGED / CLOSED → Phase 5 terminal |
| `statusCheckRollup` | Any `FAILURE` / `CANCELLED` / `TIMED_OUT` → 2.2 CI handling; all `SUCCESS` → skip 2.2; mix of `IN_PROGRESS` + no failures → wait (Phase 4) |
| `reviewDecision` | `CHANGES_REQUESTED` → 2.3 must run; `APPROVED` → candidate for merge; `REVIEW_REQUIRED` → 2.4 (request review) |
| `mergeable` + `mergeStateStatus` | `CONFLICTING` → 2.6 rebase; `BLOCKED` (missing approval, failing required check) → identify and loop |

### 2.2 CI handling

For each failed check:

1. Download the job log (GitHub: `gh run view --log-failed <run-id>`; GitLab: `glab ci trace`).
2. Classify the failure:
   - Test failure → symptom + failing test path.
   - Build failure → file + error.
   - Lint / format → specific rule.
   - Infra / runner / network error → retryable without code change.
3. Render a **CI failure table** in session:

   ```
   | Check | Failure | Likely cause | Proposed action | Delegate |
   |-------|---------|--------------|-----------------|----------|
   | build | unresolved reference: Foo | renamed class, import stale | update import at <file:line> | implement |
   | test  | ExpectedFooTest.bar assert | behaviour change in diff | review diff vs test expectation | debug |
   | lint  | ktlint wrapping            | auto-fixable               | run `ktlint --format` | implement |
   | e2e   | network timeout            | flake                      | retry once                | — |
   ```
4. Retry infra flakes once automatically (`gh run rerun <run-id> --failed`). Do not retry actual failures.
5. For code-fix rows — delegate per the **Delegation protocol** (§ Phase 3).
6. After fixes land: push, re-enter Phase 2.1.

**Failure-loop guard.** If the same check name fails 3 rounds in a row with no new commit diagnosis (same error signature), stop and surface as a blocker. Record it in state file's `Blockers raised` and ask the user what to do.

### 2.3 Review handling

Fetch all comments and thread state:

```bash
# GitHub — inline review comments (line-attached)
gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/comments" \
  --jq '[.[] | {id, in_reply_to_id, user:.user.login, path, line, body, created_at}]'

# GitHub — review summaries (top-level)
gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/reviews" \
  --jq '[.[] | {id, user:.user.login, state, body, submitted_at}]'

# GitHub — PR-level issue comments
gh api "repos/$OWNER/$REPO_NAME/issues/$PR_NUMBER/comments" \
  --jq '[.[] | {id, user:.user.login, body, created_at}]'

# GitHub — review threads (for isResolved + node ids used when replying + resolving)
# Paginate 100 per page until hasNextPage == false; accumulate to a temp file
```

For GitLab use `glab api "/projects/$PROJECT/merge_requests/$MR_IID/discussions"` which returns resolution state inline.

Fetch diff:

```bash
git diff "origin/$BASE"...HEAD
```

Filter before categorizing:

- Skip replies in already-resolved threads.
- Skip comments posted by the current principal (the skill's own earlier replies).
- Skip comments already covered by a row in state file `Commitments` with `replied: true`.

#### Categorize each remaining item

Category (one of):

| Category | When |
|---|---|
| `BLOCKING` | Security vuln, correctness bug on main path, crash, data loss risk, compliance violation, inaccurate data in regulated/audit/financial pipelines |
| `IMPORTANT` | Non-critical bug, missing error handling, logic error, edge-case miss, missing test for a broken case |
| `SUGGESTION` | Refactor, alternative approach, architectural improvement — no correctness risk if left as-is |
| `NIT` | Naming, formatting, style with no functional impact |
| `QUESTION` | Reviewer asks for clarification — may or may not imply a change |
| `PRAISE` | Approval, compliment |
| `OUT_OF_SCOPE` | Valid but belongs in a different PR or issue |

Actionability (one of):

| Actionability | Meaning |
|---|---|
| `FIXABLE` | Clear what to change; can be handed off as-is |
| `NEEDS_CLARIFICATION` | Ambiguous comment — must ask reviewer before acting |
| `DISCUSSION` | No single right answer — needs user decision |
| `NO_ACTION` | Already fixed, duplicate, invalid, praise |

Priority (derived, used for ordering in the decision table):

- `P0` = BLOCKING + FIXABLE
- `P1` = IMPORTANT + FIXABLE
- `P2` = SUGGESTION + FIXABLE, or any category + NEEDS_CLARIFICATION on a P0/P1 item
- `P3` = NIT + FIXABLE, SUGGESTION + DISCUSSION
- `P4` = PRAISE, OUT_OF_SCOPE, NO_ACTION

#### Verify the suggestion against the diff

For every BLOCKING / IMPORTANT + FIXABLE item:

1. Is the suggestion correct for this codebase's patterns?
2. Would it break tests that currently pass?
3. Is there a comment / ADR / commit message explaining why the current form exists?
4. Does it apply to all platforms/versions this PR targets?

If any check fails → keep the category but change actionability to `DISCUSSION`, record a short note explaining what's wrong with the suggestion.

#### Pattern match across the diff

For every concrete code pattern mentioned (missing null check, deprecated API, hardcoded string, etc.) — search the rest of the diff for the same shape. Additional locations become part of the same item, not separate ones.

#### Group and dedup

Multiple reviewers pointing at the same issue → one group. Multiple comments from one reviewer covering concerns one fix addresses → one group.

#### Propose a concrete solution per actionable item

For each FIXABLE item, generate a specific proposal — not a category label. The proposal is one of:

- **Edit:** `<file:line>` with before/after snippet (≤15 lines total). Shown inline in the decision table row.
- **Delegate with intent:** a one-paragraph instruction naming the engineer (kotlin-engineer / swift-engineer / …) or skill (`implement` / `debug`) and the exact files to touch, when the change is too big for a snippet.
- **Ask in thread:** the clarifying question the skill will post, verbatim. Used for NEEDS_CLARIFICATION.
- **Dismiss with reply:** the canned template with a 1-sentence context slot, for PRAISE / OUT_OF_SCOPE / NO_ACTION / NIT+NO_ACTION.

Never output only a category without a proposal. The value of this skill is the proposal.

### 2.4 Decision table (the gate)

Render in session:

```
Round N — review decision table

| # | Pri | Cat     | Act      | Author | Location          | Proposal (concrete)                                         | Delegate    |
|---|-----|---------|----------|--------|-------------------|--------------------------------------------------------------|-------------|
| 1 | P0  | BLOCK   | FIX      | @alice | api/User.kt:42    | edit: guard `userId` null, see snippet below                 | implement   |
| 2 | P1  | IMPORT  | FIX      | @bob   | api/Repo.kt:88    | delegate: refactor Flow cancellation, see instruction below  | implement   |
| 3 | P2  | IMPORT  | NEEDS_CL | @bob   | api/Repo.kt:91    | ask thread: "Is this required for initial release, or v2?"   | —           |
| 4 | P3  | NIT     | FIX      | @alice | ui/Screen.kt:12   | edit: rename `tmp` → `pendingUser`                           | implement   |
| 5 | P4  | PRAISE  | NO_ACT   | @alice | —                 | dismiss: "Thanks — appreciated."                             | —           |
| 6 | P4  | OUT_SC  | NO_ACT   | @carol | —                 | dismiss: "Valid concern, out of scope for this PR." + issue? | —           |

Concrete snippets / instructions are listed under the table with their row number.
```

Follow the table with:

1. Inline snippets (for edit rows) and full instructions (for delegate rows).
2. Explicit blockers — DISCUSSION items that need the user to decide.
3. A **summary line:** `Proposing N actions: K edits, L delegates, M dismisses, P clarifications. Q items need your decision (see blockers).`

**Gate behaviour:**

- Default mode: stop here. Tell the user: `reply "approve" to execute all rows, "skip 1,4" to drop rows, or "stop" to end the round without acting.` Wait for input.
- `--auto`: skip waiting; proceed to Phase 3.
- `--dry-run`: print the table and stop for good.

Blockers (DISCUSSION) are always surfaced — `--auto` does not swallow them. If any P0 item is DISCUSSION, stop and ask regardless of mode.

### 2.5 Round outcome

After Phase 3 executes the approved rows: push, update state file (append a row to `Rounds` and to `Commitments`), decide next step:

| Situation | Next |
|---|---|
| New fixes pushed → CI will run → wait for it | Phase 4 poll |
| No code changes, only dismisses/replies posted, review still pending | Phase 4 poll (wait for reviewer) |
| All threads closed, CI green, `reviewDecision == APPROVED`, mergeable | Phase 5 merge |
| `mergeStateStatus == BEHIND` (base moved) | Phase 2.6 rebase, then poll |
| Blocker raised | Stop, update state file, surface to user |

### 2.6 Rebase when base has advanced

When `mergeStateStatus` is `BEHIND` / `OUT_OF_DATE`:

```bash
git fetch origin
git rebase "origin/$BASE"
```

On clean rebase: run local `check` skill (build + lint + tests); on success push with `--force-with-lease`. On conflict: resolve only truly mechanical conflicts (import reshuffle, unrelated whitespace); otherwise surface as a blocker — do not guess merge resolutions that involve logic.

**Expected side effect.** After a `--force-with-lease` push, some repos reset `reviewDecision` from `APPROVED` back to `REVIEW_REQUIRED` (branch-protection "Dismiss stale approvals" setting). Do not treat this as a regression — re-request review per Phase 3.6 and keep looping. Tracking commit sha in `Commitments.fix_commit_sha` identifies which fixes have already been through review versus which are new since the rebase.

---

## Phase 3: Execute approved rows

Execute strictly in table order. Record each row's outcome inline in the session as it runs.

### 3.1 Edit rows

Apply the snippet directly via Edit tool (one file at a time). After all edit rows: run `check` skill (build + lint + tests). If `check` fails, roll the loop to Phase 2.2 with the new errors — do not push broken code.

### 3.2 Delegate rows

For each delegate row: invoke the named skill (`implement` or `debug`) or engineer agent via the Task tool. Prompt includes:

- The reviewer comment quote.
- The proposed approach from the decision table.
- The files to touch.
- "Do not refactor outside the listed files. Report back with diff summary."

Delegates run sequentially, not in parallel, so their edits don't stomp each other. After each delegate returns — spot-check the diff; if it went outside scope, revert and surface as a blocker.

### 3.3 Ask-in-thread rows (NEEDS_CLARIFICATION)

Post the verbatim question as a reply in the thread. Do not resolve. Record in state file `Commitments` with `replied: true, resolved: false`.

### 3.4 Dismiss rows (terminal verdicts)

For PRAISE / OUT_OF_SCOPE / NO_ACTION / NIT+NO_ACTION:

1. Post reply using the canned template + sanitized 1-sentence slot.
2. Resolve the thread.
3. Record in state file `Commitments` with `replied: true, resolved: true`.

**Reply delivery — safety rules:**

- Body always piped through `jq -n --arg b ... --argjson r ...` into `gh api --input -`. Never `-f body="$TEXT"`.
- Rate-limit handling: on `403` / `429`, inspect `x-ratelimit-remaining`, `x-ratelimit-reset`, and `retry-after`. **Primary rate limit** (`x-ratelimit-remaining: 0`) — schedule a `ScheduleWakeup` at `x-ratelimit-reset` (UTC epoch) and exit the round. **Secondary rate limit / abuse detection** (`retry-after: N`) — sleep `N + 5` seconds locally and retry once; if it fails again, surface as a blocker. Never burn the round in a tight retry loop.
- Sanitize slot: NFKC normalize → strip BiDi + format chars → strip HTML → strip shell metacharacters (`` ` ``, `$(`, `${`) → collapse newlines → neutralize `@mention` (remove `@`) and cross-refs (`#123` → `issue-123`) → clamp to 120 chars. Empty after sanitize → drop the slot, use template without it.
- Cap total reply body at 280 chars.
- Pre-POST thread-ownership verify: GraphQL node query → `pullRequest.number` matches + `repository.id` matches header `Repository node id` from state file. Mismatch → skip this row, log `integrity_mismatch`, abort the round (do not continue POSTing other rows).
- Pre-POST race check: if the thread was resolved by someone else since Phase 2.3 fetch, skip (record `already_resolved`).

### 3.5 Commit + push

After code-change rows (edit + delegate): one commit per logical group of reviewer items. Commit message: `Address review: <short summary>`. Push: plain `git push` for fast-forward additions; `git push --force-with-lease` only when history was rewritten (rebase, amend, fixup squash). Plain `--force` is forbidden.

### 3.6 Re-request review after code changes

If any BLOCKING / IMPORTANT row actually changed code — re-request review from all reviewers whose `state` was `CHANGES_REQUESTED` in the current round snapshot.

```bash
# GitHub: request a re-review from a specific user
gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/requested_reviewers" \
  -X POST -F "reviewers[]=<login>"

# Copilot bot — the login is "copilot-pull-request-reviewer[bot]".
# Resolve its node id from the PR's suggestedReviewers / past reviewer pool:
COPILOT_NODE_ID=$(gh api graphql -f query='
  query($owner:String!,$repo:String!,$pr:Int!){
    repository(owner:$owner,name:$repo){
      pullRequest(number:$pr){
        suggestedReviewers { reviewer { login ... on Bot { id } ... on User { id } } }
        reviews(first:50) { nodes { author { login ... on Bot { id } ... on User { id } } } }
      }
    }
  }' -F owner="$OWNER" -F repo="$REPO_NAME" -F pr="$PR_NUMBER" \
  | jq -r '[.data.repository.pullRequest.suggestedReviewers[].reviewer,
            .data.repository.pullRequest.reviews.nodes[].author]
           | map(select(.login=="copilot-pull-request-reviewer"))[0].id // empty')

# Best-effort. If empty — Copilot is not part of this repo's review pool, skip silently.
if [ -n "$COPILOT_NODE_ID" ]; then
  gh api graphql -f query='
    mutation($pr:ID!,$user:ID!){
      requestReviews(input:{pullRequestId:$pr, userIds:[$user]}){
        pullRequest { id }
      }
    }' -f pr="$PR_NODE_ID" -f user="$COPILOT_NODE_ID"
fi
```

Cache `$COPILOT_NODE_ID` in the state file header once resolved (avoid re-querying every round). If the lookup returned empty — record `copilot_unavailable: true` in the header and stop trying.

GitLab: `glab mr update $MR_IID --reviewer <user>` for humans; GitLab has no first-class bot equivalent of Copilot review — skip.

---

## Phase 4: Poll (ScheduleWakeup)

When the round ended with "wait" (CI running or review pending) — schedule the next round. The wake-up prompt is built from the stored `Mode` in the state file (per "Mode precedence on resume" in Phase 1.4) — never hardcoded.

```
WAKEUP_PROMPT="/drive-to-merge"
[ "$STATE_MODE" = "auto" ] && WAKEUP_PROMPT="/drive-to-merge --auto"
# dry-run never reaches Phase 4 — it exits after the first decision table.

ScheduleWakeup(
  delaySeconds: <picked>,
  reason:       "drive-to-merge poll: <what we're waiting on>",
  prompt:       $WAKEUP_PROMPT
)
```

Pick `delaySeconds`:

| Waiting on | delaySeconds |
|---|---|
| CI in progress, fast pipeline known (<5 min) | 270 (stay in cache window) |
| CI in progress, slow pipeline (≥5 min) | 600–1200 |
| Copilot bot review after re-request | 270 (stay in cache window for the first check); if still pending, 600 |
| Human reviewer after re-request | 1800 (30 min) |
| Approved but `mergeStateStatus == BLOCKED` on an unknown reason | 900 |

Avoid the 280–550s range: past 270s the prompt cache TTL expires, but under ~600s the cache miss is not amortized. Pick either ≤270 (stay warm) or ≥600 (commit to a longer wait).

After 6 consecutive polls with no state change — stop, record in state file `Blockers raised`, surface to the user.

On wake-up: re-read the state file, re-enter Phase 2.1.

---

## Phase 5: Merge (always user-confirmed)

Entered when: CI all green + `reviewDecision == APPROVED` + no unresolved threads owned by this skill + `mergeable == MERGEABLE` + `mergeStateStatus == CLEAN`.

Before proposing merge:

1. Re-verify the state file's `Commitments` section — every row with `delegated_to` must have non-empty `fix_commit_sha` and `replied: true`.
2. Re-pull PR state (reviewers may have changed their decision since last round).
3. Confirm the branch has not diverged from origin. If `git status -sb` shows the local branch behind / ahead of `origin/$HEAD` unexpectedly — skip merge, log the delta, return to Phase 2.1 for one more round.

Show the user:

```
PR ready to merge.

URL:     <PR URL>
Branch:  <head> → <base>
Commits: <N since branch point>
Final CI: ✔ all checks passing
Review:  ✔ approved by <reviewers>
Threads: <T> resolved, 0 unresolved

Proposed merge method: squash | merge | rebase   (pick per repo convention)
Proposed commit message:
  <subject>

  <body>

Reply "merge" to execute, or supply a different method / message.
```

Wait for explicit user confirmation. `--auto` does NOT skip this gate — by design, final merge always requires explicit user approval.

On confirmation, re-verify state one last time before invoking merge — between the gate and the API call, CI may have failed or approval may have been dismissed:

```bash
FINAL=$(gh pr view --json statusCheckRollup,reviewDecision,mergeable,mergeStateStatus)
# Abort merge if anything regressed since the gate; loop back to Phase 2.1.
```

If the re-check is still green:

```bash
gh pr merge "$PR_NUMBER" --<method> --subject "<subject>" --body "<body>" --delete-branch
# GitLab
glab mr merge "$MR_IID" --<method-flag> --delete-source-branch
```

After merge:

1. Mark state file `Status: merged`, timestamp the `Rounds` final entry.
2. Report the merged URL + commit sha to the user.
3. Stop. No further polling.

---

## Terminal states

| State | When | What the skill writes |
|---|---|---|
| `merged` | Phase 5 succeeded | state file marked merged, success summary in session |
| `blocked` | A blocker was surfaced (failure-loop guard, integrity mismatch, unresolvable rebase, DISCUSSION requires user, polling exceeded cap) | state file `Blockers raised` filled, session message explains next action |
| `abandoned` | User explicitly says "stop" | state file `Status: blocked` with reason "user stop", no further work |

---

## Defaults for autonomous judgement

The skill decides these without asking, in any mode:

- **NEEDS_CLARIFICATION** — ask the clarifying question in the thread; record and move on. Do not stop the round.
- **OUT_OF_SCOPE** — dismiss with reply. Offer (in the decision table row) to create a follow-up issue; create it only if the user types "create issues" during the approval step.
- **NIT + FIXABLE** — include in the edits batch. Trivial renames and formatting are worth the round.
- **DISCUSSION on P0/P1** — stop, surface as blocker. Never execute guesses on blocking-level disagreements.
- **DISCUSSION on P2/P3** — include as a table row with proposal "ack-in-thread-without-code-change"; a short reply summarizing the skill's counter-view and leaving the thread open for the reviewer.

---

## Principles

**One skill, one loop.** CI, review, rebase, merge — all one loop with shared state. Never hand off mid-round to another skill for orchestration; delegate individual edits, but own the loop.

**All output in the session.** The decision table, proposals, blockers, final merge summary — all rendered as chat messages. The state file is for resumption after compaction, not for user editing.

**Proposals are concrete.** Every actionable row carries a snippet, a delegation instruction, or the exact question text. "BLOCKING / FIXABLE" alone is not a proposal.

**Autonomous by default.** The user should only see decisions that require judgement: true disagreements, unresolvable rebases, final merge. Everything mechanical happens without asking.

**Approval gate ≠ merge gate.** `--auto` removes the round-level approval gate. It does not remove the merge gate — by design, final merge always requires explicit user confirmation.

**Safe by construction.** Replies go through the sanitize pipeline; thread ownership is re-verified before every POST; POST bodies go through stdin, never shell args; force-push uses `--force-with-lease` only.

**Respect the reviewer.** Push back on wrong suggestions (record as DISCUSSION, draft a counter-reply); do not dress a broken suggestion up as FIXABLE and ship the broken fix.

**Pattern completeness.** Fixing one reported instance while identical problems remain elsewhere in the diff gets the thread reopened. Pattern-match at analysis time, fix at apply time.

**Fail loudly, not silently.** Three CI failures on the same signature, an integrity mismatch, a rebase with logic conflicts — stop and surface, do not retry forever.

---

## Tool priority

`gh` / `glab` CLI when available → REST via `gh api` / `glab api` → GraphQL via `gh api graphql` for review threads and node ids → `ScheduleWakeup` for Phase 4 polling → nothing else.

If neither `gh` nor `glab` is installed or authenticated, stop with a clear message: this skill cannot degrade gracefully without a working CLI, because its value is autonomous push + reply + resolve. Ask the user to install and authenticate, then rerun.

`ScheduleWakeup` is required for autonomous polling. If the runtime does not expose it, fall back to a single-shot round: report state, record a "wake me manually" note in the state file, and exit. The user then re-invokes `/drive-to-merge` when they want the next round.

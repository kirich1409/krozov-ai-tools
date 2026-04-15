---
name: comment-analysis
description: >-
  Researcher skill for PR/MR review comments. Analyzes each comment to extract the
  underlying principle it encodes, then searches every changed file in the PR diff for the
  same pattern — not just the one location the reviewer pointed to. Fixes all occurrences,
  including ones the reviewer didn't explicitly name.

  Use when the user wants to process one or more review comments with researcher-level
  depth: "разберись с комментарием", "найди где ещё такое же", "посмотри по всем правкам",
  "проанализируй замечание", "analyze this review comment", "find all similar issues in the PR",
  "apply this feedback everywhere it applies", "look for the same pattern in other changed files",
  "reviewer pointed to one place but there might be more".

  Do NOT use for: full multi-round review orchestration (use address-review-feedback),
  creating PRs (use create-pr), CI/CD monitoring (use pr-drive-to-merge).
  Cross-reference: called by address-review-feedback for pattern propagation on
  BLOCKING/IMPORTANT/SUGGESTION comments.
---

# Comment Analysis

Researcher skill for review comments. A reviewer pointing to one location often means
"this principle is violated here" — not "only fix this one line." This skill extracts
the principle, sweeps the entire PR diff, and fixes every location that violates it.

**Core principle:** fix the problem everywhere it exists in this PR, not just where
it was noticed.

---

## Phase 1: Gather PR Context

### 1.1 Detect platform

```bash
REMOTE_URL=$(git remote get-url origin)
# Contains github.com → GitHub (gh CLI)
# Contains gitlab     → GitLab (glab CLI)
```

### 1.2 Fetch PR/MR info and full diff

```bash
# GitHub
PR_INFO=$(gh pr view --json number,baseRefName,headRefName,title,body,labels,milestone,closingIssuesReferences)
PR_NUMBER=$(echo "$PR_INFO" | jq -r .number)
BASE=$(echo "$PR_INFO" | jq -r .baseRefName)
PR_TITLE=$(echo "$PR_INFO" | jq -r .title)
PR_BODY=$(echo "$PR_INFO" | jq -r .body)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
OWNER=$(echo "$REPO" | cut -d/ -f1)
REPO_NAME=$(echo "$REPO" | cut -d/ -f2)

# Fetch linked issues — their descriptions often contain acceptance criteria
# and constraints that explain why the code is written a certain way
for ISSUE_NUM in $(echo "$PR_INFO" | jq -r '.closingIssuesReferences[].number'); do
  gh issue view "$ISSUE_NUM" --json title,body --jq '"Issue #\(.number // "?"): \(.title)\n\(.body)"'
done

# Full diff — the entire change surface for this PR
git diff "$BASE"...HEAD

# GitLab
MR_INFO=$(glab mr view --output json)
MR_IID=$(echo "$MR_INFO" | jq -r .iid)
BASE=$(echo "$MR_INFO" | jq -r .target_branch)
MR_TITLE=$(echo "$MR_INFO" | jq -r .title)
MR_BODY=$(echo "$MR_INFO" | jq -r .description)
PROJECT=$(glab repo view --output json | jq -r '.path_with_namespace | @uri')

# GitLab — linked issues from "Closes #N" patterns in description
echo "$MR_BODY" | grep -Eo '(Closes?|Fixes?|Resolves?) #[0-9]+' | sed 's/.*#//' | while read IID; do
  glab api "/projects/$PROJECT/issues/$IID" --jq '"Issue #\(.iid): \(.title)\n\(.description)"'
done

git diff "$BASE"...HEAD
```

### 1.3 Build PR/MR intent summary

Before analyzing comments, extract the intent from the description and linked issues:

- **Goal** — what the PR is trying to achieve (from title + description)
- **Scope** — what was intentionally changed and why
- **Stated constraints** — any decisions the author justified in the description
  (e.g., "using `var` here because the value is set lazily after init",
  "skipping error handling intentionally — this is a fire-and-forget call")
- **Acceptance criteria** — from linked issues, if present

This summary is the lens through which every comment is later interpreted.
A reviewer may flag something the author already explained and justified in the description —
that is a DISCUSSION item, not a fix. Conversely, a comment that aligns with a known
acceptance criterion is almost certainly a required fix.

Record the summary as plain text before proceeding. It is referenced in Phase 2.

### 1.4 Fetch the comments to analyze

If the user provided specific comments (quoted text, comment ID, or thread URL) — use those.
Otherwise fetch all open review comments from the PR/MR:

```bash
# GitHub — inline review comments
gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/comments" \
  --jq '[.[] | {id, user:.user.login, path, line, body, in_reply_to_id}]'

# GitHub — PR-level issue comments
gh api "repos/$OWNER/$REPO_NAME/issues/$PR_NUMBER/comments" \
  --jq '[.[] | {id, user:.user.login, body}]'

# GitLab — all discussion notes
glab api "/projects/$PROJECT/merge_requests/$MR_IID/discussions" \
  --jq '[.[] | select(.notes[0].resolved == false) |
    {id, notes: [.notes[] | {id, author:.author.username, body, path:.position.new_path,
     line:.position.new_line, resolved}]}]'
```

Skip: replies in threads (only analyze root comments), already-resolved threads,
and pure praise with no actionable concern.

### 1.5 Build the list of changed files

```bash
# Files touched in this PR — needed for targeted pattern search
git diff "$BASE"...HEAD --name-only
```

---

## Phase 2: Per-Comment Deep Analysis

For each comment, extract two levels of meaning. Use the PR/MR intent summary from
Phase 1.3 as background throughout — it explains what the author was trying to do
and what decisions were already justified.

### 2.1 Surface issue

What the reviewer literally described:
- The specific file and line they referenced
- The exact code they objected to (read the hunk containing that line from the diff)
- What they said should change

Cross-check against the PR description: if the author already explained this exact
choice in the description or linked issue — note it. The comment may be a
DISCUSSION (reviewer unaware of the constraint) rather than a required fix.

### 2.2 Underlying principle

What rule or principle the reviewer is enforcing. Derive this from:
1. The comment body
2. The code context at the referenced location
3. The PR intent summary — does the principle align with the PR's stated goal,
   or does it conflict with a constraint the author described?

Examples:

| Surface complaint | Underlying principle |
|-------------------|---------------------|
| "This variable should be `val`, not `var`" | Prefer immutability — all state in this file/module should use `val` unless mutation is required |
| "Missing null check before accessing `.user.id`" | Never dereference a nullable without guarding — applies to every call site on nullable types |
| "Error is swallowed here" | All caught exceptions must be logged or propagated — applies to every `catch` block in the diff |
| "This string should use the `strings.xml` resource" | No hardcoded user-visible strings — applies to every literal passed to UI components |
| "Use `viewModelScope` instead of `GlobalScope`" | Coroutines must use a lifecycle-aware scope — applies to every coroutine launch in the PR |
| "This function is too long, extract the logic" | Functions should do one thing — applies to other oversized functions added in the diff |

Document the principle explicitly. If the principle cannot be generalized beyond the exact
line (e.g., a one-off typo in a constant name), mark it as **point fix only** and skip
Phase 3 for this comment.

### 2.3 Pattern signature

Translate the principle into a detectable code pattern — a string, regex, or structural
description that can be searched in the diff:

| Principle | Pattern signature |
|-----------|-----------------|
| `val` vs `var` | `var ` declarations in new lines of the diff |
| Nullable dereference without guard | `?.` missing before `.fieldName` on a nullable type; or `!!` usage |
| Swallowed exception | `catch` blocks with empty body or no logging/rethrow |
| Hardcoded UI string | String literals passed to `setText`, `text =`, `contentDescription =`, etc. |
| Wrong coroutine scope | `GlobalScope.launch`, `CoroutineScope(Dispatchers` at call sites |

The signature does not need to be a regex — describe it precisely enough to guide
a systematic diff scan. If the pattern is structural (e.g., "a function body exceeding
50 lines"), describe the detection heuristic.

---

## Phase 3: Pattern Propagation Sweep

For each comment that produced a generalizable principle (not **point fix only**):

### 3.1 Search the diff

Read the full diff. For every hunk (`+` lines — additions only, since existing code is
out of scope for this PR's fixes):

1. Apply the pattern signature from Phase 2.3
2. Collect every line where the pattern is present
3. Record: `file:line — excerpt — matches principle?`

```bash
# Additions only — we only fix what this PR introduced
git diff "$BASE"...HEAD | grep '^+' | grep -v '^+++' > /tmp/pr-additions.txt

# Then search for the pattern in these additions
# (use Grep with the relevant pattern against the changed files)
```

### 3.2 Read full file context for candidates

For each candidate line found:

1. Read the surrounding code in the actual file (not just the diff hunk) to confirm
   the pattern applies — diff context can be misleading
2. Verify that the same fix makes sense in this context
3. If the principle applies → **confirmed location**
4. If context makes it a different situation → note why and exclude

### 3.3 Cross-file sweep

Check all changed files, not just the file where the reviewer commented. A reviewer
commenting on `LoginViewModel.kt` about error handling might be pointing to a pattern
that also exists in `RegistrationViewModel.kt` if both were changed in the same PR.

When evaluating candidates in other files, use the PR intent summary as a filter:
if the description explains why a specific file was intentionally written differently
(e.g., "this module uses a different error strategy — see the linked ADR"), exclude
it from the fix list and note the reason.

---

## Phase 4: Consolidate and Present

Before fixing anything, present the full picture to the user.

```markdown
## Comment Analysis

**PR/MR:** {title}
**Goal:** {one-sentence goal from description}
**Scope constraints from description:** {any decisions the author justified, or "none stated"}

---

### Comment by @{reviewer} at {file}:{line}

**What they said:** "{reviewer's comment text}"

**Underlying principle:** {extracted principle — one sentence}

**Relation to PR description:** {aligns with PR goal | conflicts with stated constraint →
treat as DISCUSSION | author already justified this choice → flagged, not a fix}

**Pattern signature:** {what to look for}

---

#### Locations to fix

| # | File | Line | Code excerpt | Status |
|---|------|------|-------------|--------|
| 1 | {stated file} | {stated line} | `{code snippet}` | Stated in review |
| 2 | {other file} | {line} | `{code snippet}` | Discovered — same pattern |
| 3 | {other file} | {line} | `{code snippet}` | Discovered — same pattern |

**Point fix only:** {file}:{line} — {reason this is a one-off, not part of a pattern}

**Excluded (justified in description):** {file}:{line} — {what the author said in the PR body}

---

### Summary

- {N} comment(s) analyzed
- {M} principles extracted
- {K} stated locations + {L} discovered locations = {total} fixes needed
- {P} point fixes (one-off, no propagation)
- {Q} excluded — author-justified in PR description
```

Wait for user confirmation before proceeding with fixes. The user may:
- Approve all — fix everything
- Exclude specific locations — remove from the fix list and note why
- Override the principle extraction — adjust and re-sweep
- Mark some as out-of-scope for this PR — note for follow-up

---

## Phase 5: Fix Everything

Fix all confirmed locations in the plan — stated and discovered.

### 5.1 Order of fixes

1. Group by file to minimize context switches
2. Within a file, fix from bottom to top (line numbers stay stable)
3. If multiple comments share the same principle, apply all their fixes in one pass per file

### 5.2 Fix discipline

- Fix only the code that violates the identified principle
- Do not refactor surrounding code
- Do not add comments explaining the fix (the commit message does that)
- Do not introduce new patterns or abstractions beyond what the fix requires
- If a fix requires touching logic outside the diff's additions, note it and ask the user

### 5.3 Verify each fix

After applying fixes, confirm:
- The original location is fixed (re-read the changed lines)
- Each discovered location is fixed
- No new instances of the pattern were introduced by the fixes themselves

Run applicable local quality gates before committing:

```bash
# Build check
./gradlew assembleDebug 2>&1 | tail -20

# Tests for affected modules (infer from changed files)
./gradlew :<module>:test 2>&1 | tail -30

# Lint if relevant
./gradlew lint 2>&1 | grep -E 'error|warning' | head -20
```

If any gate fails: diagnose, fix, re-run. Do not commit until gates pass.

### 5.4 Commit

One commit per review comment (or per principle if multiple comments share one):

```
fix: <principle applied, brief>

Reviewer pointed to {stated file}:{stated line}. Same pattern found
in {N} additional location(s): {file:line, ...}.

Fixed all {total} occurrences.
```

Push immediately after each commit. Do not batch commits from different comments.

---

## Phase 6: Report

After all fixes are committed and pushed, summarize:

```markdown
## Fixes Applied

### Comment by @{reviewer}
- **Principle enforced:** {principle}
- **Stated location fixed:** {file}:{line}
- **Additional locations fixed:** {file:line}, {file:line}
- **Commit:** {hash}

### Point fixes (no propagation)
- {file}:{line} — {what was fixed}
- **Commit:** {hash}

### Excluded (not in scope for this PR)
- {file}:{line} — {reason}
```

If thread responses are needed (to inform the reviewer what was done):
use the same response rules as `address-review-feedback` Phase 4, Step 4 —
state what changed and where, no performative agreement.

---

## Decision Guide

| Situation | Action |
|-----------|--------|
| Principle is clear and generalizable | Sweep entire diff, fix all matches |
| Comment is ambiguous — could mean two different things | Ask one clarifying question before extracting pattern |
| PR description explicitly justifies the flagged pattern | Mark as DISCUSSION — present the conflict to the user, do not fix unilaterally |
| PR description is silent on the pattern, reviewer flags it | Treat as a required fix — no justification means the reviewer is correct |
| Linked issue contains acceptance criteria that requires the pattern | The pattern may be intentional — surface the conflict, ask the user |
| Discovered location exists in code NOT added by this PR | Note it, do not fix — out of scope; optionally surface to user as a follow-up issue |
| Fix at a discovered location would require significant refactoring | Note it, ask user before proceeding |
| Reviewer said "fix this here" with no generalizable principle | Point fix only — fix exactly that location |
| Pattern appears in test code as well as production code | Fix both unless the test is intentionally testing the wrong pattern |
| Multiple comments encode the same principle | Merge into one sweep — fix once, reference both comments in the commit message |

---

## Relationship to Other Skills

- **address-review-feedback** — full review orchestrator. Invokes `comment-analysis`
  for BLOCKING/IMPORTANT/SUGGESTION comments where pattern propagation applies.
  `comment-analysis` can be invoked standalone when the user wants researcher-depth
  analysis on specific comments.
- **implement** — executes code changes. `comment-analysis` produces the what-and-where;
  it can delegate complex multi-file changes to an `implement` agent if the fix scope
  is large.
- **research** — investigates technology questions. `comment-analysis` investigates
  code patterns within the PR diff.

---
name: triage-feedback
description: >
  Use when feedback needs to be analyzed, prioritized, categorized, and filtered
  before acting on it — regardless of where the feedback came from. This skill
  produces a structured action plan; it does NOT fix code, reply in threads,
  resolve discussions, or push commits. Sources supported: an existing PR/MR
  (review comments, review summaries, PR-level comments) and user-provided text
  pasted in the chat (bug reports, stacktraces, CI logs, free-form complaints,
  a list of items to triage). The skill auto-detects the source from context
  and asks the user only when detection is ambiguous. Trigger whenever the user
  says "triage feedback", "categorize review comments", "разбери комментарии",
  "просмотри фидбэк", "разбери и приоритизируй", "analyze reviewer feedback",
  "sort these comments by priority", "filter and categorize", "triage this",
  "triage PR comments", "triage these errors", "categorize these findings",
  "что из этого важно", "что блокирующее", "help me prioritize", or any other
  phrasing that asks to understand, sort, group, or prioritize incoming
  feedback without taking action on it. Invoke proactively when the user
  pastes a block of review comments, bug reports, CI logs, or any list of
  issues and asks which to address first or how to split them up. Do NOT use
  this skill when the user wants to fix the issues, respond to reviewers,
  resolve threads, or merge a PR — those are separate workflows.
---

# Triage Feedback

Analyzer. Fetches feedback → categorizes → prioritizes → groups → produces a
structured action plan saved as a markdown artifact. Consumers (the user, or
other skills like `implement-task`, `debug`, `decompose-feature`) decide what
to act on.

**Core principle:** separate analysis from execution. This skill never edits
code, never posts comments, never resolves threads, never merges. Its only
side effect is writing the report file.

**Why separation matters.** Triage and execution have different failure modes:
triage is about judgement (what matters, what's scope creep, what's wrong in
the suggestion). Execution is about correctness (does the fix actually work).
Conflating them in one skill leads to the fixer being biased by its own
categorization, and to premature action on items that should have been
declined or clarified first.

---

## Phase 1: Determine the source

Auto-detect the feedback source from context. Ask a single clarifying question
only when detection is genuinely ambiguous.

### Signals and priority

Evaluate signals in this order; first match wins:

1. **User explicitly named a source** in the current request ("triage the PR
   comments", "triage this log", "triage from <URL>") → use what they said.
2. **User pasted a block of text** in the current or a recent message that
   looks like feedback (numbered list, review comments, stack trace, CI log,
   bullet points with issues) → source is the pasted text.
3. **Current branch has an open PR/MR** (see detection in Phase 2) and the
   user did not paste any feedback block → source is the PR/MR.
4. **User request references a PR/MR URL** but no current branch match → fetch
   that specific PR/MR.
5. **Nothing matches** → ask the user one question: "What do you want me to
   triage — the open PR on this branch, a block of text you want to paste,
   or a specific URL?" Wait for the answer before proceeding.

### Override rule

If the user specifies a source explicitly (signal 1), honor it even when
auto-detection would pick something else. Users know the source; the skill
should not argue.

### Multi-source requests

If the user asks to triage both a PR and pasted text ("triage the PR and also
these bugs I noticed"), treat them as one combined input — merge items after
normalization in Phase 3. Flag the source of each item in the report.

---

## Phase 2: Fetch & parse

### Source A — PR/MR

Detect platform:

```bash
REMOTE_URL=$(git remote get-url origin)
# Contains github.com → GitHub (gh CLI)
# Contains gitlab     → GitLab (glab CLI)
```

Fetch metadata and context (used later for scope and requirement checks):

```bash
# GitHub
PR_INFO=$(gh pr view --json number,baseRefName,headRefName,title,body,labels,milestone,closingIssuesReferences,url)
PR_NUMBER=$(echo "$PR_INFO" | jq -r .number)
PR_URL=$(echo "$PR_INFO" | jq -r .url)
BASE=$(echo "$PR_INFO" | jq -r .baseRefName)
PR_BODY=$(echo "$PR_INFO" | jq -r .body)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
OWNER=$(echo "$REPO" | cut -d/ -f1)
REPO_NAME=$(echo "$REPO" | cut -d/ -f2)

# Linked issues — often contain acceptance criteria worth reading
for ISSUE_NUM in $(echo "$PR_INFO" | jq -r '.closingIssuesReferences[].number'); do
  gh issue view "$ISSUE_NUM" --json title,body --jq '"\(.title): \(.body)"'
done

# GitLab
MR_INFO=$(glab mr view --output json)
MR_IID=$(echo "$MR_INFO" | jq -r .iid)
MR_URL=$(echo "$MR_INFO" | jq -r .web_url)
BASE=$(echo "$MR_INFO" | jq -r .target_branch)
MR_BODY=$(echo "$MR_INFO" | jq -r .description)
PROJECT=$(glab repo view --output json | jq -r '.path_with_namespace | @uri')

echo "$MR_BODY" | grep -Eo '(Closes?|Fixes?|Resolves?) #[0-9]+' | sed 's/.*#//' | while read ISSUE_IID; do
  glab api "/projects/$PROJECT/issues/$ISSUE_IID" --jq '"\(.title): \(.description)"'
done
```

Fetch comments (each endpoint returns different shapes — call all three on
GitHub):

```bash
# GitHub — inline review comments (attached to lines)
gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/comments" \
  --jq '[.[] | {id, in_reply_to_id, user:.user.login, path, line, body, created_at}]'

# GitHub — review summaries (top-level review bodies)
gh api "repos/$OWNER/$REPO_NAME/pulls/$PR_NUMBER/reviews" \
  --jq '[.[] | {id, user:.user.login, state, body, submitted_at}]'

# GitHub — PR-level issue comments (not inline, not review)
gh api "repos/$OWNER/$REPO_NAME/issues/$PR_NUMBER/comments" \
  --jq '[.[] | {id, user:.user.login, body, created_at}]'

# GitHub — thread resolution state (REST doesn't expose this; GraphQL does).
# Build a map from the root comment id to isResolved so inline comments can be
# filtered by thread state below.
gh api graphql -f query='
  query($owner:String!,$repo:String!,$number:Int!) {
    repository(owner:$owner,name:$repo) {
      pullRequest(number:$number) {
        reviewThreads(first:100) {
          nodes {
            isResolved
            comments(first:1) { nodes { databaseId } }
          }
        }
      }
    }
  }
' -f owner="$OWNER" -f repo="$REPO_NAME" -F number="$PR_NUMBER" \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | {rootId: .comments.nodes[0].databaseId, isResolved}]'

# GitLab — all discussions in one call (resolution state already in the response)
glab api "/projects/$PROJECT/merge_requests/$MR_IID/discussions" \
  --jq '[.[] | {id, notes: [.notes[] | {id, author:.author.username, body, position:.position, resolved, created_at}]}]'
```

Join the resolution map into each inline comment by matching the root comment
id (the first node's `databaseId` identifies the thread root). Comments
without a matching thread are PR-level or review-summary items — mark their
`thread_state` as `n/a`.

Fetch the PR diff — used for pattern detection and suggestion verification:

```bash
git diff "$BASE"...HEAD
```

Filter rules:

- Skip replies in threads when analyzing roots — the reply chain is context
  for the root, not a separate item.
- Skip already-resolved threads unless the resolution looks premature (e.g.,
  the reviewer resolved their own open question without receiving an answer).

### Source B — user-provided text

Parse the pasted content based on its structural shape:

- **Numbered or bulleted list** → each top-level item is one feedback item.
- **Stack trace / exception log** → extract the error type, message, and
  location. Each distinct error becomes one item.
- **CI log output** → scan for lines matching common failure markers (`error:`,
  `FAIL`, `✗`, `Exception`, `assertion failed`, `[ERROR]`) and group related
  lines into one item per failure.
- **Free-form prose** → treat the whole block as one item unless paragraphs
  are clearly describing distinct concerns.

If the structure is genuinely ambiguous (mixed content, no clear delimiters),
ask the user: "How should I split this — one item per paragraph, or one
combined item?" before proceeding.

---

## Phase 3: Normalize to a common item shape

Every feedback item, regardless of source, is normalized to the same shape
before categorization:

| Field | Description |
|-------|-------------|
| `id` | Sequential 1..N within this triage run |
| `source` | `pr-review`, `pr-review-summary`, `pr-comment`, `user-text` |
| `source_ref` | GitHub/GitLab comment id, or a line range in the pasted text |
| `author` | Reviewer username, or `user` for pasted text |
| `location` | `file:line` if inline; `N/A` otherwise |
| `body` | Full text of the feedback |
| `thread_state` | `resolved` / `unresolved` / `n/a` |
| `parent_id` | For replies — id of the root this belongs to |

This shape is what Phase 4–8 operate on. Keeping it uniform means the same
logic applies to PR comments and pasted bug reports alike.

---

## Phase 4: Categorize

Assign exactly one category per item.

| Category | When to assign |
|----------|---------------|
| `BLOCKING` | Security vulnerability, critical correctness bug, compliance violation, data loss risk, crash on a main code path, or inaccurate data sent to reporting / regulated / financial pipelines even when the user-facing symptom looks cosmetic (wrong currency in emails, miscoded locale in audit logs, etc.) |
| `IMPORTANT` | Non-critical bug, missing error handling, logic error, missing test for a broken case, incorrect behavior on edge cases |
| `SUGGESTION` | Refactor, architectural improvement, alternative approach — no correctness risk if left as-is |
| `NIT` | Naming, formatting, style, minor preferences with no functional impact |
| `QUESTION` | Reviewer asking for clarification — may or may not imply a code change |
| `PRAISE` | Compliment, approval, positive acknowledgment — no action required |
| `OUT_OF_SCOPE` | Valid concern but addressing it belongs in a different PR, issue, or project |

**Choosing between BLOCKING and IMPORTANT:** ask "if this ships as-is, does it
cause real harm to users, data, or the team's ability to operate?" If yes →
BLOCKING. If it ships as an annoyance, a latent bug in a rare path, or a
quality regression you'd catch in the next iteration → IMPORTANT.

**Choosing between SUGGESTION and NIT:** a SUGGESTION could change the
architecture or approach; a NIT could not. If reading the comment makes you
think "that's a fair design alternative", it's a SUGGESTION. If it makes you
think "sure, I'll rename that", it's a NIT.

---

## Phase 5: Actionability

Independent axis from category. Assign one value.

| Actionability | Meaning |
|--------------|---------|
| `FIXABLE` | Clear what to change; could be handed to an implementation agent as-is |
| `NEEDS_CLARIFICATION` | Ambiguous — must ask the reviewer/user before acting |
| `DISCUSSION` | No single right answer — human decision required |
| `NO_ACTION` | Praise, already fixed, demonstrably invalid, or duplicate of another item |

Actionability is orthogonal to severity: a BLOCKING item can be DISCUSSION
(the vulnerability is real but the reviewer's proposed fix is wrong), and a
NIT can be FIXABLE (trivial renaming).

---

## Phase 6: Verify suggestions (when diff is available)

For every item categorized as `BLOCKING` or `IMPORTANT` and marked `FIXABLE`,
verify the suggestion against the codebase before recommending it:

1. Is the suggestion technically correct for this codebase's patterns?
2. Would it break tests that currently pass?
3. Is there a documented reason the current code is written this way (comment,
   ADR, commit message)?
4. Does it apply to all platforms/versions the PR targets?

If any check fails → keep the category (the concern may still be real), but
change actionability to `DISCUSSION` and record a one-line note explaining
what's wrong with the suggestion. This prevents handing a broken fix to an
implementation agent.

Skip this phase when no diff is available (e.g., user pasted text without a
PR context).

---

## Phase 7: Pattern detection

For every `BLOCKING`, `IMPORTANT`, or `SUGGESTION` item that refers to a
concrete code pattern (missing null check, unused import, deprecated API,
hardcoded string, etc.):

1. Extract the pattern shape from the referenced location in the diff.
2. Search the rest of the diff for the same pattern in other files or lines.
3. If found, attach `pattern_matches` to the item with the list of additional
   locations.

Why this matters: fixing one reported instance and leaving identical problems
elsewhere means the next review round will reopen the thread. Pattern
completeness is cheaper at triage time than after the fix is already pushed.

Skip when no diff is available.

---

## Phase 8: Group and dedup

- Items from different reviewers about the same logical issue → one group.
- Multiple items from the same reviewer about closely related concerns that
  one fix would address → one group.
- In user-pasted text: items repeating the same concern with different wording
  → one group.

Each group becomes one entry in the final report. Preserve all original
`source_ref`s within the group so the downstream user can still find the
specific comment or log line each concern came from.

---

## Phase 9: Write the report

**Slug derivation:** reuse the branch name in kebab-case with common prefixes
stripped (`feature/`, `fix/`, `chore/`). When no branch context exists (pure
user-text source and no git repo), use `feedback-YYYYMMDD-HHMM`.

**Path:** `swarm-report/<slug>-triage.md`

Assume `swarm-report/` is already gitignored — most projects in the
developer-workflow ecosystem ignore it by convention. Do NOT modify
`.gitignore` from this skill; the only side effect of triage is the report
file. If you notice `swarm-report/` is not ignored, warn the user and still
write the report; let the user decide whether to update `.gitignore`.

Report template:

```markdown
# Triage Report: <slug>

**Source:** <PR URL | pasted text | both>
**Date:** <ISO date>
**Change context:** <one-line goal derived from PR description or user input>

## Summary

- **Total items:** N (after grouping)
- **By category:** BLOCKING <a>, IMPORTANT <b>, SUGGESTION <c>, NIT <d>, QUESTION <e>, PRAISE <f>, OUT_OF_SCOPE <g>
- **By actionability:** FIXABLE <h>, NEEDS_CLARIFICATION <i>, DISCUSSION <j>, NO_ACTION <k>
- **Patterns detected:** <count of items with pattern_matches>
- **Needs user decision before execution:** <count of DISCUSSION + NEEDS_CLARIFICATION>

## Items

Sorted by category priority: BLOCKING → IMPORTANT → SUGGESTION → QUESTION → OUT_OF_SCOPE → NIT → PRAISE.

### BLOCKING

#### #1 — <short title>

- **Author:** @reviewer (or `user`)
- **Source:** <source_ref>
- **Location:** <file:line or N/A>
- **Actionability:** FIXABLE / NEEDS_CLARIFICATION / DISCUSSION / NO_ACTION
- **Pattern matches:** <list of file:line if any, else "none">
- **Body:**
  > <verbatim quote of the feedback>
- **Analysis:** <one or two sentences: what the issue is, whether the suggestion is valid, what would need to happen next>

(… repeat per item)

### IMPORTANT
…

### SUGGESTION
…

### QUESTION
…

### OUT_OF_SCOPE
…

### NIT
…

### PRAISE
…

## Recommended next steps

Generic, tool-agnostic — the user decides what to invoke next:

- **FIXABLE BLOCKING / IMPORTANT** → hand to a code-fix workflow with the
  item list as input. Patterns must be fixed at all matched locations, not
  only the reported one.
- **NEEDS_CLARIFICATION** → reply to the reviewer / ask the user before any
  code change.
- **DISCUSSION** → surface to the user for a decision; do not auto-act.
- **OUT_OF_SCOPE** → user chooses: decline with a note, or log as a follow-up
  issue.
- **NO_ACTION** → acknowledge silently (PRAISE) or leave the thread as-is.

## Source index

For each group, full list of original refs:

| Item | Refs |
|------|------|
| #1 | gh-comment-123, gh-comment-145 |
| #2 | user-text:lines 5-8 |
```

The report is the only artifact this skill produces. It does not invoke other
skills or agents.

---

## Principles

**Category is a judgement, not a lookup.** Read the body in the context of the
PR goal and the diff. A "missing test" in a throwaway spike is NIT; the same
text in a release branch for a payment flow is IMPORTANT or BLOCKING.

**Push back on bad suggestions at triage time.** If a proposed fix is wrong,
mark the item DISCUSSION and record why. Do not dress up a broken suggestion
as FIXABLE and let a downstream agent implement a broken fix.

**Pattern completeness matters.** A fix that addresses only the reported
location while leaving identical problems elsewhere is incomplete. Finding
the matching locations at triage time is cheap; finding them after the fix
shipped costs another review round.

**Respect the source.** For PR/MR source, preserve the exact comment ids so
the user can jump back to the thread. For user-text, preserve line ranges
from the paste. Never invent locations.

**One clarification round at triage start.** If the source is ambiguous, ask
once. Do not trickle clarifying questions one by one — batch any ambiguity
into a single question up front.

**Fail loudly on empty input.** If no PR is found and no text was pasted,
stop and ask. Do not guess or fabricate items.

---

## Tool priority

Prefer `gh` / `glab` CLI when available → REST API via `gh api` / `glab api`
when available → MCP as last resort.

For PR/MR sources, `gh` / `glab` are optional capabilities, not hard
requirements. If neither CLI is installed or authenticated, do not dead-end:
ask the user to provide the PR/MR URL together with the relevant review
comments, review summaries, and diff/context pasted into the chat — then
treat it as a user-text source. User-text source has no CLI dependency at
all.

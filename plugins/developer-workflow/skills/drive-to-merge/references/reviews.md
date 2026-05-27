# drive-to-merge — Phase 2.3 Review Handling + 2.4 Decision Table

Build (or refresh) the branch-change model, fetch review activity, categorize each leftover comment against the whole branch diff, verify suggestions, propose a concrete action per item, and render the gate as a diff-grounded plan.

## 2.3.0 Build (or refresh) the branch-change model

Before touching individual comments, understand what the whole branch does. Every leftover comment is reasoned against this model, not just its own line — a reviewer often flags a symptom whose cause or correct fix lives elsewhere in the branch diff.

First entry this session — build the full model from the complete branch diff:

```bash
git diff "origin/$BASE"...HEAD
```

From it, write a short structured understanding (a few lines, not a transcript): what the branch does, which files/areas it touches, and the key behaviors, invariants, and contracts it introduces or changes. Record `analyzed_through_sha` = current `HEAD`.

Subsequent rounds — refresh with the **delta** only, do not re-read the full diff. First guard: if `analyzed_through_sha` is non-empty **and** `git merge-base --is-ancestor "<analyzed_through_sha>" HEAD` succeeds, use the delta:

```bash
git diff "<analyzed_through_sha>"...HEAD   # new commits since last analysis
```

Otherwise (sha empty, or rebase rewrote history so the sha is no longer an ancestor), rebuild from the full diff (`git diff "origin/$BASE"...HEAD`) and reset `analyzed_through_sha` to the current `HEAD`.

Reconcile the result into the cached model and advance `analyzed_through_sha` to the new `HEAD`. Persist the compact model summary and `analyzed_through_sha` to the state file (see [`setup.md`](setup.md) `Branch change model`) so the model survives context compaction; on resume, reuse the cached model and re-read only the delta since the stored sha (same guard applies).

## 2.3.1 Fetch

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

The branch diff is already loaded into the branch-change model (2.3.0) — do not re-fetch it here.

## 2.3.2 Filter before categorizing

- Skip replies in already-resolved threads.
- Skip the skill's own earlier replies — identify by `(author == principal) AND (comment id OR body signature matches a state file Commitments row with replied: true)`. Do NOT skip every comment from the principal unconditionally — the user may also post from the same account, and those comments must be treated as reviewer input.
- Skip comments already covered by a row in state file `Commitments` with `replied: true`.

## 2.3.3 Categorize each remaining item

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

## 2.3.4 Verify the suggestion against the branch-change model

For every BLOCKING / IMPORTANT + FIXABLE item, reason about it against the whole branch (the 2.3.0 model), not just the commented line:

1. Is the suggestion correct for this codebase's patterns?
2. Would it break tests that currently pass?
3. Is there a comment / ADR / commit message explaining why the current form exists?
4. Does it apply to all platforms/versions this PR targets?
5. Does the fix conflict with — or duplicate — something the branch introduces elsewhere, and is the flagged symptom actually caused by a change in another part of the diff? If so, the real fix may live at that other site.

If any check fails → keep the category but change actionability to `DISCUSSION`, record a short note explaining what's wrong with the suggestion.

## 2.3.5 Pattern match across the branch-change model

For every concrete code pattern mentioned (missing null check, deprecated API, hardcoded string, etc.) — search the whole branch diff (all changed files in the 2.3.0 model) for the same shape, not just the local hunk. Additional locations become part of the same item, not separate ones.

## 2.3.6 Group and dedup

Multiple reviewers pointing at the same issue → one group. Multiple comments from one reviewer covering concerns one fix addresses → one group.

## 2.3.7 Propose a concrete solution per actionable item

For each FIXABLE item, generate a specific proposal — not a category label. The proposal is one of:

- **Edit:** `<file:line>` with before/after snippet (≤15 lines total). Shown inline in the decision table row.
- **Delegate with intent:** a one-paragraph instruction naming the engineer (kotlin-engineer / swift-engineer / compose-developer / swiftui-developer) and the exact files to touch, when the change is too big for a snippet.
- **Ask in thread:** the clarifying question the skill will post, verbatim. Used for NEEDS_CLARIFICATION.
- **Dismiss with reply:** the canned template with a 1-sentence context slot, for PRAISE / OUT_OF_SCOPE / NO_ACTION / NIT+NO_ACTION.

Never output only a category without a proposal. The value of this skill is the proposal.

## 2.4 Decision table (the gate)

Render in session as a **prioritized list**, not a table — a plan grounded in the whole branch, not a per-line checklist. Open with a one-line **branch context** drawn from the 2.3.0 model so the plan visibly accounts for the entire change set. Then one section per priority bucket present in the round, ordered most critical first. Each item is one short paragraph: bold headline = the gist; then prose with author, location, brief context, and the action — no bullet labels, no `→` arrows, no `Reviewer:` / `Action:` / `Verdict:` fields. Reads like a human issue note, not a form. Where a fix touches related changes elsewhere in the branch, name those sites in the item.

```
Round N — review proposals

Branch context: adds nullable userId to the auth flow; touches api/User.kt, api/Repo.kt, ui/Screen.kt.

## P0 — Blocking

1. **Crash: userId is nullable, used as non-null on .length.** @alice, api/User.kt:42.
   Reproducible from the diff. Guard with a safe call:

       - val length = userId.length
       + val length = userId?.length ?: 0

## P1 — Important

2. **Flow.collect leaks without a cancellation guard on rotate.** @bob,
   api/Repo.kt:88 (same pattern at :120). Delegate to `kotlin-engineer`: rewrite
   both call sites to `repeatOnLifecycle(STARTED)`, do not touch anything else.

## P2 — Suggestion

3. **Clarify scope for v1 vs v2.** @bob, api/Repo.kt:91. Reviewer asked
   whether this is needed for the initial release. Reply in the thread: "Targeting v2 — opening a
   follow-up issue. Does that work?"

## P3 — Nit

4. **Local variable `tmp` is unclear.** @alice, ui/Screen.kt:12.
   Rename `tmp` → `pendingUser`.

## P4 — Praise / Out-of-scope / NoAction

5. **PRAISE.** @alice. Reply: "Thanks — appreciated." Resolve.

6. **OUT_OF_SCOPE.** @carol, api/Repo.kt:200. Reply: "Valid concern, out of scope
   for this PR. I can open a follow-up issue if you'd like." Resolve.

## Blockers

none.

## Summary

6 items: 2 edits, 1 delegation, 2 dismissals, 1 clarification.
```

### Format rules

- One `Branch context:` line right under the title, drawn from the 2.3.0 model — one sentence on what the branch does plus the areas it touches. This frames the plan as diff-grounded; keep it to a single line.
- When an item's fix touches related changes elsewhere in the branch, name those sites inline (e.g. "same contract at api/Repo.kt:120") so the plan reads as a whole, not a per-line list.
- Sections in order P0 → P1 → P2 → P3 → P4. Skip empty buckets.
- Numbering is **continuous** across sections (1, 2, 3 …) — gate commands (`approve`, `skip 1,4`, `stop`) reference these numbers.
- Each item: `**Bold headline.**` (one sentence on the gist) + `@author, file:line.` + 1–2 sentences of context and action. Snippet inline indented when relevant (≤15 lines).
- Quote the reviewer verbatim only when paraphrase loses meaning. Otherwise paraphrase to the essence and drop the quotes.
- No labels, no `→`, no category/actionability/delegate columns — the priority is already conveyed by the section; what to do is the last sentence.
- `## Blockers` section is always rendered last (one word "none." if empty) — this is what stops the round for the user.
- `## Summary` — one line with the breakdown by action type.

### Gate behaviour

- Default mode: stop here. Tell the user: `reply "approve" to execute all items, "skip 1,4" (or "skip 1 4") to drop items by number, or "stop" to end the round without acting.` Wait for input. Accept both comma-separated and space-separated number lists; strip whitespace around commas. Numbering is global and continuous across sections — no letters, no per-section restart.
- `--auto`: skip waiting; proceed to Phase 3.
- `--dry-run`: print the list and stop for good.

Blockers are always surfaced — `--auto` does not swallow them. If any P0 item is DISCUSSION, stop and ask regardless of mode.

# drive-to-merge — Phase 2.3 Review Handling + 2.4 Decision Table

Fetch review activity, categorize, verify suggestions, propose a concrete action per item, and render the gate.

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

Fetch diff:

```bash
git diff "origin/$BASE"...HEAD
```

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

## 2.3.4 Verify the suggestion against the diff

For every BLOCKING / IMPORTANT + FIXABLE item:

1. Is the suggestion correct for this codebase's patterns?
2. Would it break tests that currently pass?
3. Is there a comment / ADR / commit message explaining why the current form exists?
4. Does it apply to all platforms/versions this PR targets?

If any check fails → keep the category but change actionability to `DISCUSSION`, record a short note explaining what's wrong with the suggestion.

## 2.3.5 Pattern match across the diff

For every concrete code pattern mentioned (missing null check, deprecated API, hardcoded string, etc.) — search the rest of the diff for the same shape. Additional locations become part of the same item, not separate ones.

## 2.3.6 Group and dedup

Multiple reviewers pointing at the same issue → one group. Multiple comments from one reviewer covering concerns one fix addresses → one group.

## 2.3.7 Propose a concrete solution per actionable item

For each FIXABLE item, generate a specific proposal — not a category label. The proposal is one of:

- **Edit:** `<file:line>` with before/after snippet (≤15 lines total). Shown inline in the decision table row.
- **Delegate with intent:** a one-paragraph instruction naming the engineer (kotlin-engineer / swift-engineer / …) or skill (`implement` / `debug`) and the exact files to touch, when the change is too big for a snippet.
- **Ask in thread:** the clarifying question the skill will post, verbatim. Used for NEEDS_CLARIFICATION.
- **Dismiss with reply:** the canned template with a 1-sentence context slot, for PRAISE / OUT_OF_SCOPE / NO_ACTION / NIT+NO_ACTION.

Never output only a category without a proposal. The value of this skill is the proposal.

## 2.4 Decision table (the gate)

Render in session as a **prioritized list**, not a table. One section per priority bucket present in the round, ordered most critical first. Each item is one short paragraph: bold headline = the gist; then prose with author, location, brief context, and the action — no bullet labels, no `→` arrows, no `Reviewer:` / `Action:` / `Verdict:` fields. Reads like a human issue note, not a form.

```
Round N — review proposals

## P0 — Blocking

1. **Crash: userId is nullable, used as non-null on .length.** @alice, api/User.kt:42.
   Reproducible from the diff. Guard with a safe call:

       - val length = userId.length
       + val length = userId?.length ?: 0

## P1 — Important

2. **Flow.collect leaks without a cancellation guard on rotate.** @bob,
   api/Repo.kt:88 (same pattern at :120). Delegate to `implement`: rewrite
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

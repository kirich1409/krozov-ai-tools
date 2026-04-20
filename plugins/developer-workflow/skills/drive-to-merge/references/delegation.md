# drive-to-merge — Phase 3 Execute Approved Rows

Execute strictly in table order. Record each row's outcome inline in the session as it runs.

## 3.1 Edit rows

Apply the snippet directly via Edit tool (one file at a time). After all edit rows: run `check` skill (build + lint + tests). If `check` fails, roll the loop to Phase 2.2 with the new errors — do not push broken code.

## 3.2 Delegate rows

For each delegate row: invoke the named skill (`implement` or `debug`) or engineer agent via the Task tool. Prompt includes:

- The reviewer comment quote.
- The proposed approach from the decision table.
- The files to touch.
- Scope guard: "Touch only the listed files. No new tests, no CI / workflow / build-config edits, no doc rewrites, no dependency changes, no refactors outside the listed files. Report back with a diff summary."

Delegates run sequentially, not in parallel, so their edits don't stomp each other. After each delegate returns — spot-check the diff; if it touched anything outside the listed files (including `.github/`, tests directories not mentioned, `package.json` / `build.gradle`, docs), revert and surface as a blocker.

## 3.3 Ask-in-thread rows (NEEDS_CLARIFICATION)

Post the verbatim question as a reply in the thread. Do not resolve. Record in state file `Commitments` with `replied: true, resolved: false`.

## 3.4 Dismiss rows (terminal verdicts)

For PRAISE / OUT_OF_SCOPE / NO_ACTION / NIT+NO_ACTION:

1. Post reply using the canned template + sanitized 1-sentence slot.
2. Resolve the thread.
3. Record in state file `Commitments` with `replied: true, resolved: true`.

### Reply delivery — safety rules

- Body always piped through `jq -n --arg b ... --argjson r ...` into `gh api --input -`. Never `-f body="$TEXT"`.
- Rate-limit handling: on `403` / `429`, inspect `x-ratelimit-remaining`, `x-ratelimit-reset`, and `retry-after`. **Primary rate limit** (`x-ratelimit-remaining: 0`) — schedule a `ScheduleWakeup` at `x-ratelimit-reset` (UTC epoch) and exit the round. **Secondary rate limit / abuse detection** (`retry-after: N`) — sleep `N + 5` seconds locally and retry once; if it fails again, surface as a blocker. Never burn the round in a tight retry loop.
- Sanitize slot: NFKC normalize → strip BiDi + format chars → strip HTML → strip shell metacharacters (`` ` ``, `$(`, `${`) → collapse newlines → neutralize `@mention` (remove `@`) and cross-refs (`#123` → `issue-123`) → clamp to 120 chars. Empty after sanitize → drop the slot, use template without it.
- Cap total reply body at 280 chars.
- Pre-POST thread-ownership verify: GraphQL node query → `pullRequest.number` matches + `repository.id` matches header `Repository node id` from state file. Mismatch → skip this row, log `integrity_mismatch`, abort the round (do not continue POSTing other rows).
- Pre-POST race check: if the thread was resolved by someone else since Phase 2.3 fetch, skip (record `already_resolved`).

## 3.5 Commit + push

After code-change rows (edit + delegate): one commit per logical group of reviewer items. Commit message: `Address review: <short summary>`. Push: plain `git push` for fast-forward additions; `git push --force-with-lease` only when history was rewritten (rebase, amend, fixup squash). Plain `--force` is forbidden.

## 3.6 Re-request review after code changes

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
  MUTATION_OUT=$(gh api graphql -f query='
    mutation($pr:ID!,$user:ID!){
      requestReviews(input:{pullRequestId:$pr, userIds:[$user]}){
        pullRequest { id }
      }
    }' -f pr="$PR_NODE_ID" -f user="$COPILOT_NODE_ID" 2>&1)
  # Explicit error check — a bot no longer in the review pool returns an `errors` array,
  # not a non-zero exit code. Without this check the failure is silent.
  if jq -e '.errors // empty' <<<"$MUTATION_OUT" >/dev/null 2>&1 || [ -z "$MUTATION_OUT" ]; then
    # Record once, stop trying for the rest of this PR's lifetime.
    # Downgrade state-file header field `Copilot node id:` to the sentinel `unavailable`.
    COPILOT_NODE_ID=""
  fi
fi
```

Cache `$COPILOT_NODE_ID` in the state file header once resolved (avoid re-querying every round). If the lookup returned empty or the mutation returned `errors` — write the sentinel `Copilot node id: unavailable` into the header (the single schema-defined way to flag this; do NOT invent a separate `copilot_unavailable` field) and stop trying for the rest of this PR's lifetime.

GitLab: `glab mr update $MR_IID --reviewer <user>` for humans; GitLab has no first-class bot equivalent of Copilot review — skip.

# drive-to-merge — Phase 5 Merge (always user-confirmed)

Entered when: CI all green + `reviewDecision == APPROVED` + no unresolved threads owned by this skill + `mergeable == MERGEABLE` + `mergeStateStatus == CLEAN`.

## Pre-merge checks

1. Re-verify the state file's `Commitments` section — every row with `delegated_to` must have non-empty `fix_commit_sha` and `replied: true`.
2. Re-pull PR state (reviewers may have changed their decision since last round).
3. Confirm the branch has not diverged from origin. If `git status -sb` shows the local branch behind / ahead of `origin/$HEAD` unexpectedly — skip merge, log the delta, return to Phase 2.1 for one more round.

## Merge confirmation message

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

## Final re-check and execution

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

## After merge

1. Mark state file `Status: merged`, timestamp the `Rounds` final entry.
2. Report the merged URL + commit sha to the user.
3. Stop. No further polling.

## Rebase when base has advanced (Phase 2.6 companion)

When `mergeStateStatus` is `BEHIND` / `OUT_OF_DATE`:

```bash
git fetch origin
git rebase "origin/$BASE"
```

On clean rebase: run local `check` skill (build + lint + tests); on success push with `--force-with-lease`. On conflict: resolve only truly mechanical conflicts (import reshuffle, unrelated whitespace); otherwise surface as a blocker — do not guess merge resolutions that involve logic.

**Expected side effect.** After a `--force-with-lease` push, some repos reset `reviewDecision` from `APPROVED` back to `REVIEW_REQUIRED` (branch-protection "Dismiss stale approvals" setting). Do not treat this as a regression — re-request review per Phase 3.6 and keep looping. Tracking commit sha in `Commitments.fix_commit_sha` identifies which fixes have already been through review versus which are new since the rebase.

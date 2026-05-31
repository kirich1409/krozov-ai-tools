# drive-to-merge — Phase 5 Merge

Entered when: CI all green + `reviewDecision == APPROVED` + no unresolved threads owned by this skill + `mergeable == MERGEABLE` + `mergeStateStatus == CLEAN`.

## Draft promotion (pre-phase)

If `isDraft == true` when Phase 5 conditions are otherwise met:

- **`--auto` mode** — promote automatically and continue:
  ```bash
  # GitHub
  gh pr ready "$PR_NUMBER"
  # GitLab
  glab mr update "$MR_IID" --remove-draft
  ```
  Show one notification line ("Promoting PR from draft to ready") and proceed to pre-merge checks.

- **default mode** — stop and surface: "PR is still a draft. Promote to ready with `gh pr ready` or type `stop`."

## Pre-merge checks

1. Re-verify the state file's `Commitments` section — every row with `delegated_to` must have non-empty `fix_commit_sha` and `replied: true`.
2. Re-pull PR state (reviewers may have changed their decision since last round).
3. Confirm the branch has not diverged from origin. If `git status -sb` shows the local branch behind / ahead of `origin/$HEAD` unexpectedly — skip merge, log the delta, return to Phase 2.1 for one more round.

## Merge summary message

Always show (regardless of mode):

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
```

**default mode** — append "Reply "merge" to execute, or supply a different method / message." and block until the user replies.

**`--auto` mode** — append "Merging automatically (--auto mode)." and proceed immediately without waiting.

## Final re-check and execution

Before invoking the merge API, re-verify state one last time — between the summary and the API call, CI may have failed or approval may have been dismissed:

```bash
FINAL=$(gh pr view --json statusCheckRollup,reviewDecision,mergeable,mergeStateStatus)
# Abort merge if anything regressed; loop back to Phase 2.1.
```

If the re-check is still green:

```bash
gh pr merge "$PR_NUMBER" --<method> --subject "<subject>" --body "<body>" --delete-branch
# GitLab
glab mr merge "$MR_IID" --<method-flag> --delete-source-branch
```

## Native auto-merge path (CI still running, `--auto` mode)

When Phase 2.5 would enter Phase 4 polling because CI is still in progress AND mode is `--auto`:

Instead of scheduling repeated polls, delegate the wait to the platform:

```bash
# GitHub — requires repo auto-merge enabled + branch protection rules
gh pr merge "$PR_NUMBER" --auto --squash
```

For GitLab, use `--when-pipeline-succeeds` **only** when `Merge policy` in the state file is `auto` (personal repo). For `team-strict` repos skip native auto-merge and fall through to normal polling (avoids blocking merge trains or queues without consent):

```bash
# GitLab — personal / auto policy only
glab mr merge "$MR_IID" --when-pipeline-succeeds
```

On success: mark state file `Status: waiting-native-auto-merge`, show "Native auto-merge set — platform will merge when checks pass. Exiting loop.", and stop.

On failure (e.g. GitHub repo has auto-merge disabled):
- Show "Native auto-merge unavailable (repo setting disabled) — falling back to polling."
- Continue to Phase 4 normally.

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

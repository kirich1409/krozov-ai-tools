# drive-to-merge — Phase 2.2 CI Handling

Investigate failing checks, classify, retry infra flakes, and hand off code-fix rows to Phase 3 delegation.

## Resolve the failing workflow run id (GitHub)

`statusCheckRollup` nodes expose `detailsUrl` of the form
`https://<host>/<owner>/<repo>/actions/runs/<RUN_ID>/job/<JOB_ID>` for GitHub
Actions checks. Parse it directly:

```bash
# Pick the first failed check from statusCheckRollup
FAILED_CHECK=$(jq -r '
  .statusCheckRollup[]
  | select(.conclusion=="FAILURE" or .conclusion=="CANCELLED" or .conclusion=="TIMED_OUT")
  | {name, conclusion, detailsUrl}
' <<<"$PR_INFO" | jq -s 'first')

DETAILS_URL=$(jq -r '.detailsUrl // empty' <<<"$FAILED_CHECK")
RUN_ID=$(echo "$DETAILS_URL" | sed -E 's#.*/runs/([0-9]+).*#\1#')

# Fallback when detailsUrl does not match the /actions/runs/ pattern
# (third-party checks via Checks API, or a check whose detailsUrl points elsewhere):
if ! [[ "$RUN_ID" =~ ^[0-9]+$ ]]; then
  RUN_ID=$(gh run list --branch "$HEAD" --limit 20 \
    --json databaseId,headSha,conclusion \
    --jq '[.[] | select(.headSha=="'"$(git rev-parse HEAD)"'") | select(.conclusion=="failure" or .conclusion=="cancelled" or .conclusion=="timed_out")][0].databaseId // empty')
fi

# If still empty — this is a non-Actions check (external status). Surface to the user
# as a blocker; this skill cannot download logs for arbitrary external check providers.
```

For GitLab: `glab ci view` on the pipeline id from `MR_INFO.head_pipeline.id`, or
`glab api "/projects/$PROJECT/pipelines/<pipeline_id>/jobs"` to enumerate jobs and
`glab api "/projects/$PROJECT/jobs/<job_id>/trace"` to pull a specific job log.

## Per-check flow

For each failed check (once `RUN_ID` is resolved):

1. Download the job log:
   - GitHub: `gh run view --log-failed "$RUN_ID"`
   - GitLab: `glab ci trace` on the specific job id
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
4. Retry infra flakes once automatically (`gh run rerun "$RUN_ID" --failed`). Do not retry actual failures.
5. For code-fix rows — delegate per the **Delegation protocol** (see `references/delegation.md`, § Phase 3).
6. After fixes land: push, re-enter Phase 2.1.

## Failure-loop guard

If the same check name fails 3 rounds in a row with no new commit diagnosis (same error signature), stop and surface as a blocker. Record it in state file's `Blockers raised` and ask the user what to do.

# Flow Metrics Schema

Schema for `swarm-report/<slug>-metrics.json`, the post-run telemetry artifact written by `feature-flow` and `bugfix-flow` after every run (success, escalation, or user-interrupted). Local only — never sent off the machine.

## When the file is written

- **Success** — at the end of the run, when the orchestrator transitions `VERIFIED → stage Merged` (outcome: `merged`). Note the case distinction: `Merged` is a stage label in the orchestrator state machine; `merged` (lowercase) is the value of the `outcome` enum.
- **Escalation** — when the orchestrator stops with an escalation reason.
- **User interruption** — best-effort write inside the orchestrator's cleanup hook (`/exit`, `Ctrl+C`, abandoned worktree, etc.). Missing fields are recorded as `null` rather than omitted.

A failure to write the metrics file **does not break the orchestrator**. The run completes as it would have without telemetry; the failure is logged once to the chat output.

## Top-level fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `slug` | string | yes | The run's task slug |
| `flow` | string enum | yes | `feature-flow` \| `bugfix-flow` |
| `started_at` | ISO-8601 string | yes | First stage start |
| `ended_at` | ISO-8601 string | yes | Last stage end (or interruption moment) |
| `wall_clock_seconds` | integer | yes | `ended_at − started_at`, total seconds |
| `outcome` | string enum | yes | `merged` \| `escalated` \| `interrupted` |
| `escalation_reason` | string \| null | yes (null when not escalated) | One short line |
| `stages` | array of stage records | yes | One entry per stage, in execution order |
| `backward_transitions` | array of transition records | yes | Empty array if none |
| `overrides` | array of strings | yes | E.g. `["--skip-test-plan", "--skip-coverage-audit"]` |
| `review_verdicts` | object | yes | Map of review-stage name → `PASS` \| `WARN` \| `FAIL`. Empty object `{}` when no review stages ran (e.g. `bugfix-flow` runs that skip `PlanReview` / `TestPlanReview`). Consumers must treat `{}` as "no review stages executed", not as a schema violation |
| `finalize_rounds` | integer \| null | yes (null when finalize did not run) | Count of rounds executed |
| `acceptance_verdict` | string \| null | yes (null when acceptance did not run) | `VERIFIED` \| `FAILED` \| `PARTIAL` |
| `pr_number` | integer \| null | yes (null when no PR) | GitHub / GitLab PR / MR number |
| `drive_to_merge_rounds` | integer \| null | yes (null when drive-to-merge did not run) | Round count |
| `schema_version` | string | yes | `"1"` for the format described in this document |

## Stage record

```json
{
  "name": "Research",
  "started_at": "2026-04-21T10:00:00Z",
  "ended_at": "2026-04-21T10:02:00Z",
  "duration_seconds": 120,
  "status": "completed",
  "skip_reason": null
}
```

| Field | Type | Notes |
|---|---|---|
| `name` | string | Canonical stage name. Examples (non-exhaustive — orchestrators may add stages over time): `Research`, `Clarify`, `DesignOptions`, `Decompose`, `Plan`, `PlanReview`, `TestPlan`, `TestPlanReview`, `Implement`, `Finalize`, `Acceptance`, `PR`, `DriveToMerge`, `Debug`, `RegressionTest`. Canonical names are owned by the orchestrator definitions in `skills/feature-flow/` and `skills/bugfix-flow/`; aggregation across runs should treat unknown names as opaque labels rather than error out |
| `started_at` | ISO-8601 string | When the orchestrator entered the stage |
| `ended_at` | ISO-8601 string | When the stage produced its receipt or was skipped |
| `duration_seconds` | integer | Convenience precomputation |
| `status` | string enum | `completed` \| `skipped` \| `failed` |
| `skip_reason` | string \| null | Required when `status` is `skipped` |

## Backward-transition record

```json
{
  "from": "Acceptance",
  "to": "Implement",
  "reason": "P1 bug: empty cart triggers infinite spinner",
  "at": "2026-04-21T11:00:00Z"
}
```

`reason` is a short one-liner — full context lives in the relevant artifact (e.g. `<slug>-acceptance.md`). The schema captures only what is needed to count and trace.

## Privacy

- Metrics are **local-only** by default. The file lives under `swarm-report/`, which is gitignored.
- Do not store user names, secrets, or repo-internal identifiers beyond what already lives in `swarm-report/` artifacts.
- `escalation_reason` and stage `skip_reason` are short text strings — keep them factual, not anecdotal.

## Schema versioning

`schema_version` starts at `"1"`. Breaking changes (renaming fields, removing fields) bump to `"2"` and ship behind a release; downstream `jq` examples in the README are versioned alongside.

## jq cookbook (in `developer-workflow/README.md`)

Three baseline examples that any consumer can copy:

1. Average `wall_clock_seconds` over recent runs:
   ```
   jq -s 'map(.wall_clock_seconds) | add/length' swarm-report/*-metrics.json
   ```
2. Top backward-transition pairs by count:
   ```
   jq -r '.backward_transitions[] | "\(.from) -> \(.to)"' swarm-report/*-metrics.json | sort | uniq -c | sort -rn | head
   ```
3. Percentage of runs with at least one override:
   ```
   jq -s '(map(select(.overrides | length > 0)) | length) / length * 100' swarm-report/*-metrics.json
   ```

These examples are reproduced in the plugin README so users can paste them without reading this document first.

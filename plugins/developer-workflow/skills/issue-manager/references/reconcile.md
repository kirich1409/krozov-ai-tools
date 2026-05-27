# Reconcile — Board Advancement and State Management

The RECONCILE phase runs after each backend call and at the start of every resume. It
advances the board using idempotent abstract actions and keeps the state file synchronized
with GitHub ground-truth.

## State File

**Path:** `swarm-report/issue-manager-<batch>-state.md`

`<batch>` slug is determined in Phase 0 — see [`phase0.md`](phase0.md).

**Schema:**

```markdown
# State: issue-manager-<batch>
Goal: <one-line scope description>
Started: <ISO timestamp>
Last verified: <ISO timestamp>

## Issues

| number | phase | pr_url | last_verified_at |
|--------|-------|--------|-----------------|
| 9      | done  | https://github.com/owner/repo/pull/101 | 2026-05-27T14:23:00Z |
| 12     | in-progress | null | 2026-05-27T14:30:00Z |
| 15     | analyzed | null | 2026-05-27T14:00:00Z |

## Blocked List
- #18: blocked by failure in #12 (failed_gate: finalize)

## Execution Order (approved)
9, 12, 15

## Notes
<free text for mid-batch observations>
```

**Phase values** (derived — always recomputable from tracker + GitHub):

| Phase | Meaning |
|---|---|
| `analyzed` | In scope, not yet started |
| `in-progress` | Backend A is running or was running for this issue |
| `pr-open` | Backend A completed; PR is open, ready-for-review |
| `done` | PR merged OR issue closed-as-done |
| `blocked` | Failed or externally blocked; downstream held |

**Rule:** only store fields that can be independently verified against the tracker. No
fields that are only derivable from conversation history.

## Idempotent Write Rules

All abstract actions used in RECONCILE are idempotent:

- `transition_status` — reads current status first; writes only if `current != target`.
- `link_pr` — checks for existing marker comment before posting.
- `add_comment` — checks for existing marker before posting; key must be unique per comment purpose.
- `fetch_issue` / `get_completion_signal` — read-only, safe to repeat.

On any write failure (script exits non-zero): stop with the error message. Do NOT proceed
to the next issue — partial state is better than inconsistent state.

## Post-Task Reconcile (after each backend completion signal)

1. Read completion signal from backend.
2. Based on `signal.status`:

   **`done`** (backend produced an open, ready-for-review PR — AC-9: merge is a human gate):
   - Do NOT call `transition_status`. The issue must stay open until the PR is merged or the
     issue is closed by a human.
   - Call `link_pr(issue_ref, pr_ref)` using `signal.pr_url`
   - Call `add_comment(issue_ref, key="batch-summary-done", body="Batch completed. PR: <pr_url>")`
   - Update state file: phase → `pr-open`, pr_url → `signal.pr_url`
   - Note: `transition_status("done")` is called only during a later reconcile or compaction-resume
     when `get_completion_signal` returns `signal: done` (PR merged or issue closed-as-done).

   **`failed` or `blocked`:**
   - Call `transition_status(issue_ref, "blocked")`
   - Call `add_comment(issue_ref, key="batch-blocked", body="Blocked. Reason: <failed_gate or blocked_reason>")`
   - Update state file: phase → `blocked`
   - **Hold transitive downstream DAG branch** — find all issues that directly or transitively
     depend on this issue (follow `from` edges where `to == blocked_issue`, recursively).
     Add all to the Blocked List in the state file. Do NOT transition them to `in-progress`.
   - Note: `failed_gate` is logged for the user but never branched on — see [`exec-contract.md`](exec-contract.md).

3. Update `last_verified_at` in the state file.

## Batch Summary

After the last issue in the execution order is processed (or all remaining are blocked),
surface a summary to the user:

```
## Issue Manager — Batch Complete

**Processed:** N issues
**Done (PR open):**
  - #9 — <title> → PR #101: <url>
  - #15 — <title> → PR #103: <url>

**Blocked (require attention):**
  - #12 — blocked at gate: finalize (needs user decision on ESCALATE finding)
    ↳ Downstream held: #18, #22

**Skipped (unresolved dependencies):**
  - #25 — depends on #12 (blocked)

Merge is a human action. Review and merge the open PRs above when ready.
```

## Compaction Resume Protocol (AC-7)

When resuming after context compaction:

1. **Re-read the state file** — this is the recovery point.
2. **Re-fetch board ground-truth** from GitHub for every issue in scope:
   - Call `fetch_issue(issue_ref)` for each → current state and labels.
   - Call `get_completion_signal(issue_ref)` for each → PR existence and state.
3. **Reconcile state file against tracker:**
   - For each issue in the state file, compare `phase` against the fetched data:
     - `phase == pr-open` but `get_completion_signal` returns `done` → update to `done`.
     - `phase == in-progress` but issue is closed → update to `done` or `blocked` per signal.
     - `phase == done` but PR URL returns 404 → investigate; mark `blocked`.
   - **On any conflict: trust the tracker, rewrite the state file.**
4. **Resume from the first issue whose `phase` is not `done`** in the approved execution order.
   Do not re-run any issue with `phase == done`.

The state file is a cache; GitHub is the source of truth. The resume protocol enforces this.

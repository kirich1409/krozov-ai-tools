# drive-to-merge — Phase 4 Polling (ScheduleWakeup)

When the round ended with "wait" (CI running or review pending) — decide whether to use
native auto-merge (exit immediately) or schedule the next round via ScheduleWakeup.

## Native auto-merge path (`--auto` mode, CI still running)

When mode is `--auto` **and** `Merge policy` is `auto` **and** CI is still in progress
(no failures, only `IN_PROGRESS` / `PENDING` checks) — delegate the wait to the platform
instead of polling. Procedure in [`references/merge.md`](merge.md) § "Native auto-merge path".

If native auto-merge succeeds: exit the loop (no ScheduleWakeup). If it fails (repo setting
disabled), fall through to normal ScheduleWakeup below.

For `team-strict` policy: skip native auto-merge entirely regardless of mode; proceed to
ScheduleWakeup.

## Proactive autonomy offer (default mode, long waits)

Before scheduling ScheduleWakeup in **default mode**, when the wait will be long:

- **Slow CI** (pipeline ≥5 min, detected on first entry to this wait): show once —
  > "CI is running (slow pipeline). Type `auto-merge` to set native auto-merge and exit now, or I'll keep polling."
- **Human reviewer not responding** (two or more consecutive 1800s polls with no new review
  activity): show once —
  > "No reviewer activity after two rounds. Type `auto-merge` to set native auto-merge and exit, or I'll keep polling."

If the user types `auto-merge`: execute the native auto-merge path from `references/merge.md`
and exit. Do not offer again after the user declines (silently) — offer at most once per
category per run.

In `--auto` mode this offer is unnecessary — native auto-merge is used automatically above.

## ScheduleWakeup

The wake-up prompt is built from the stored `Mode` in the state file (per "Mode precedence on
resume" in `references/setup.md`) — never hardcoded.

```
WAKEUP_PROMPT="/drive-to-merge"
[ "$STATE_MODE" = "auto" ] && WAKEUP_PROMPT="/drive-to-merge --auto"
# dry-run never reaches Phase 4 — it exits after the first decision table.

ScheduleWakeup(
  delaySeconds: <picked>,
  reason:       "drive-to-merge poll: <what we're waiting on>",
  prompt:       $WAKEUP_PROMPT
)
```

## Pick `delaySeconds`

| Waiting on | delaySeconds |
|---|---|
| CI in progress, fast pipeline known (<5 min) | 270 (stay in cache window) |
| CI in progress, slow pipeline (≥5 min) | 600–1200 |
| Copilot bot review after re-request | 270 (stay in cache window for the first check); if still pending, 600 |
| Human reviewer after re-request | 1800 (30 min) |
| Approved but `mergeStateStatus == BLOCKED` on an unknown reason | 900 |

Avoid the 280–550s range: past 270s the prompt cache TTL expires, but under ~600s the cache miss is not amortized. Pick either ≤270 (stay warm) or ≥600 (commit to a longer wait).

After 6 consecutive polls with no state change — stop, record in state file `Blockers raised`, surface to the user.

On wake-up: re-read the state file, re-enter Phase 2.1.

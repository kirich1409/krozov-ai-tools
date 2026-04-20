# drive-to-merge — Phase 4 Polling (ScheduleWakeup)

When the round ended with "wait" (CI running or review pending) — schedule the next round. The wake-up prompt is built from the stored `Mode` in the state file (per "Mode precedence on resume" in `references/setup.md`) — never hardcoded.

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

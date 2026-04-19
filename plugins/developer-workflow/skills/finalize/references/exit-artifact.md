# Finalize exit artifact template

Save the finalize artifact to `swarm-report/<slug>-finalize.md` on exit (PASS or ESCALATE). Use the template below verbatim; fill in the placeholders from the round logs accumulated during the run.

```markdown
# Finalize: <slug>

**Date:** <date>
**Rounds run:** N (of 3 max)
**Exit:** PASS | ESCALATE
**Escalation reason:** <only if ESCALATE>

## Rounds

### Round 1
- Phase A (code-reviewer): verdict, N findings (K BLOCK, M WARN, L NIT). Fixes applied: X.
- Phase B (/simplify): Y files changed, auto-fixed.
- Phase C (pr-review-toolkit): breakdown per agent.
- Phase D (experts): triggered: [security-expert, ...]; findings, fixes.
- `/check` after round: PASS | FAIL (reason)

### Round 2
...

## Unresolved BLOCKs (on ESCALATE only)

Findings that could not be fixed and were NOT downgraded. Populated only when the
finalize stage exits ESCALATE — lists BLOCKs that remain after 3 rounds, or BLOCKs
whose fix broke `/check` and was reverted (per §Mechanical verification). The user
must decide: loop back to `implement`, accept as risk, or re-scope.

| Severity | Confidence | Category | Finding | Phase | Round | File:Line |
|---|---|---|---|---|---|---|
| BLOCK (critical) | 75 | security | Token logged in clear | D | 3 | src/auth/Logger.kt:23 |

## Remaining findings (not auto-fixed)

Non-BLOCK items surfaced for reviewer awareness — they do not block exit with PASS.

| Severity | Confidence | Category | Finding | Phase | File:Line |
|---|---|---|---|---|---|
| WARN | 60 | quality | Inconsistent error logging | A | src/foo/Bar.kt:142 |
| NIT  | 75 | consistency | Unused import of X in new file | B | ... |

## Acknowledged risks

Findings that the user explicitly decided to accept (e.g., during escalation). Not auto-populated — the user marks items here when handing control back for the run to continue. Distinct from "Unresolved BLOCKs" (which the finalize stage could not close).

## Commits added during finalize

- <hash> <message>
```

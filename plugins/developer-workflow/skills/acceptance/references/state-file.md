# Step 2.6 — Fan-out State File

Symmetric to `multiexpert-review`'s state file. The state file carries the acceptance run
across context compaction — it is never a receipt, just operational state.

## When to write

Before issuing the Step 3 fan-out — but **after** the full check plan has been finalized
(Step 3 intro resolves base + all conditional triggers) — save the plan and
compaction-resilient progress to `swarm-report/<slug>-acceptance-state.md`.

Step ordering: 2.5 dedup probe → Step 3 intro resolves conditional triggers → write the
state file here (Step 2.6) with the complete `Planned Checks` list → Step 3 body dispatches
the fan-out.

## Format

```markdown
# Acceptance State: <slug>

Status: planning | running | aggregating | done
Cycle: <N> of 3              # incremented on Re-verification Loop re-entry
Started: <ISO8601>
Base: <base-branch>
Diff hash: <sha256 of git diff <base>...HEAD>
Spec hash: <sha256 of spec file, or null>
Test-plan hash: <sha256 of permanent test plan, or null>

## Planned Checks
- [ ] manual (triggered by has_ui_surface + scenario)
- [ ] code (triggered by dedup miss)
- [ ] ac-coverage (triggered by spec.acceptance_criteria_ids)
- [ ] security (triggered by spec.risk_areas: [auth])
- ...

## Completed Checks
- [x] code — swarm-report/<slug>-acceptance-code.md — PASS
- [x] build — swarm-report/<slug>-acceptance-build.md — PASS
...

## Aggregated Verdict History
### Cycle 1
Verdict: FAILED
Blockers: <copy from aggregated receipt>
```

## Rules

1. Create and populate the file only after the full check plan is finalized — base
   fan-out plus all conditional triggers (spec-driven and diff-driven) — and before any
   agent batch is spawned. The initial `Planned Checks` list must reflect that complete
   plan.
2. Before each major action (spawning an agent batch, aggregating, writing the final
   receipt) — **re-read** the state file via Read tool. Completed checks (`[x]`) are not
   re-spawned on resume after compaction.
3. Mark each check `[x]` with the artifact path and verdict as soon as the per-check file
   is written.
4. On Re-verification Loop re-entry, increment `Cycle`, reset the `Planned Checks` list
   using the new diff/spec/test-plan hashes, move checks to be skipped to a
   **`## Re-used from previous cycle`** section (with artifact pointers), and append a new
   entry under `Aggregated Verdict History` when the cycle completes.
5. When `Status: done` is written, the state file becomes read-only operational history —
   it is not deleted automatically.

## Relation to e2e-scenario file

The state file and the e2e-scenario file (`<slug>-e2e-scenario.md`) are independent — the
latter is `manual-tester`'s internal re-anchor, owned by the agent; the state file is
acceptance's own fan-out cursor, owned by this skill.

---
name: issue-manager
description: >
  Drives a GitHub issue backlog end-to-end: resolves scope, builds a dependency DAG, presents
  an ordered execution plan for one-time user approval, then processes each ready issue
  sequentially — transitioning it to In-Progress, running the full implementation pipeline
  (implement → /check → /finalize → /acceptance → /create-pr), and advancing the board.
  Stops at an open, ready-for-review PR; merge is always a human action.

  Triggers: "process the backlog", "work through these issues", "implement issues #3 #7 #12",
  "drive all open issues", "work the epic", "run the backlog", "implement the milestone".

  Do NOT use for: a single issue with no GitHub board tracking needed (use the pipeline skills individually);
  merging PRs (use /drive-to-merge); code review only (use /finalize); ad-hoc GitHub queries.
disable-model-invocation: true
---

# Issue Manager

Backlog orchestrator. Resolves scope → builds DAG → gets one approval → drives each ready
issue through the full implementation pipeline → advances the board. All GitHub access is
through abstract actions resolved in [`references/adapter-contract.md`](references/adapter-contract.md).

## Prerequisites (fail-fast, before any writes)

Run these checks before ANALYZE. On any failure: stop with a clear message, no partial writes.

1. **Repo access + auth:** call `list_issues --state open --limit 1` via the abstract action.
   A valid JSON array (including `[]`) → auth and repo access are confirmed. An error object
   or non-zero exit → stop with the error message before any writes.
2. **Project v2 detection (optional):** attempt to detect a linked GitHub Project v2 on the
   repo. If detected, `transition_status` will use the project status field; otherwise it falls
   back to open/closed state + label convention (`status:in-progress`, `status:blocked`). Log
   which mechanism will be used.

## ANALYZE Phase

**Goal:** build the board — a structured view of all in-scope issues with their statuses and
dependency edges.

1. **Resolve scope** from the user's input (issue URL / number list / epic ref / "all open")
   — detail in [`references/phase0.md`](references/phase0.md).
2. For each resolved issue: call `fetch_issue` to get title, body, labels, state.
3. For each resolved issue: call `get_dependencies` to retrieve dependency edges.
4. Call `get_completion_signal` for any issue that already has a linked PR (from labels or
   body scan) to check if it is already done.
5. Assemble the board JSON:
   ```
   { issues: [...], edges: [...], ready_set: [...], blocked_set: [...] }
   ```
6. Mark issues that are already `done` (signal == "done") — skip them in Phase 0.

All data access is via abstract actions — no ad-hoc GitHub calls anywhere in this flow.

## Phase 0 — Plan and Approval

Single human gate. Detail in [`references/phase0.md`](references/phase0.md).

**Summary of steps:**
1. Build DAG from edges; detect cycles.
2. On cycle: present members, BLOCK until manually resolved. Do not proceed.
3. Apply scope cap (default **5** ready issues; overridable via `--cap N`).
4. On over-cap: warn + ask user to narrow scope. Do not proceed without confirmation.
5. Present the execution plan: dependency graph, proposed order, blocked issues.
6. Accept user approval or a reordered number list.
7. Initialize the state file at `swarm-report/issue-manager-<batch>-state.md`.

This is the only gate. After approval, EXECUTE runs without additional per-issue confirmation.

## EXECUTE Phase

Processes the approved execution order sequentially. For each ready issue:

1. Call `transition_status(issue_ref, "in-progress")` via abstract action (idempotent).
2. Update state file: phase → `in-progress`.
3. Invoke the execution backend via the interface in
   [`references/exec-contract.md`](references/exec-contract.md).
   - Active backend: Backend A — [`references/exec-single.md`](references/exec-single.md).
   - The core passes `{ task_id, scope, allowed_depth }` and receives a completion signal.
   - The core does NOT know or care which backend executes — it only reads the signal.
4. Pass the completion signal to RECONCILE (below).

**Strictly sequential:** do not start the next issue until the current one's signal is
received and RECONCILE has written its result to the state file.

## RECONCILE Phase

Advances the board after each backend completion. Detail in [`references/reconcile.md`](references/reconcile.md).

**Summary:**
- `status == "done"`: call `link_pr`, `add_comment`; keep issue open (merge is a human gate — AC-9); update state (phase → `pr-open`). Do NOT call `transition_status("done")` — that happens only when a later reconcile observes the PR is merged or the issue is closed-as-done.
- `status == "failed"` or `"blocked"`: call `transition_status("blocked")`, `add_comment`;
  hold the entire transitive downstream DAG branch (all issues that directly or transitively
  depend on this one). Do NOT transition them to `in-progress`. Add all to Blocked List.
- After last issue (or all remaining blocked): surface batch summary to user.

All actions are idempotent — safe to replay on resume.

## Non-Negotiables

These rules are non-negotiable. Violating them is an error, not a judgment call.

- **Never edit or write project source code.** The skill is a supervisor, not an executor.
  All code work is delegated to subagents and skills (Backend A in exec-single.md).
- **Never run checks, tests, or builds directly.** All verification is delegated via
  `/check`, `/finalize`, `/acceptance` (invoked by the backend, not the core).
- **GitHub access exclusively through abstract actions** resolved in adapter-contract.md.
  No ad-hoc `gh` or GraphQL invocations in the skill body or any reference file.
- **Stop at the open, ready-for-review PR.** Never merge. Never promote a draft to ready
  without user confirmation. (Per Backend A: PRs open immediately as ready-for-review —
  see exec-single.md. The human gate is merge, not promotion.)
- **Compaction resume:** on resume, FIRST re-read the state file AND re-fetch board
  ground-truth from GitHub. Trust the tracker on any conflict. Do not use conversation
  memory as the source of truth. See reconcile.md for the full protocol.
- **Blocked propagates transitively:** when an issue is set to `blocked`, every issue that
  directly or transitively depends on it is also held — not transitioned, not dispatched.

## References

Volatile detail lives in references — load on demand:

- [`references/adapter-contract.md`](references/adapter-contract.md) — abstract action → concrete script mapping (the only place script names appear)
- [`references/exec-contract.md`](references/exec-contract.md) — backend interface + completion-signal schema
- [`references/exec-single.md`](references/exec-single.md) — Backend A: per-task flow, subagent routing, skill chaining
- [`references/phase0.md`](references/phase0.md) — DAG build, cycle detection, scope cap, approval format
- [`references/reconcile.md`](references/reconcile.md) — idempotent transitions, state-file schema, compaction-resume protocol

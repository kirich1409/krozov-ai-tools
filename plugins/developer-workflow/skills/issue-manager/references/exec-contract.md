# Execution-Backend Contract

Defines the interface between the issue-manager core and any execution backend. The core
calls backends ONLY through this form — it does not know which backend is active.

## Backend Call Signature

```
input:
  task_id:       string          # issue number (or "owner/repo#N" for cross-repo)
  scope:         object          # { issue_ref, title, body, labels, url }
  allowed_depth: string          # "minimal" | "standard" | "deep"
                                 #   minimal — implement→check→finalize→acceptance→create-pr
                                 #   standard — adds /write-spec if issue lacks implementation detail
                                 #   deep     — adds /research + /write-spec as needed

output:  <completion-signal>     # JSON object, schema below
```

## Completion Signal Schema

```json
{
  "status":         "done | failed | blocked",
  "pr_url":         "<url | null>",
  "failed_gate":    "<string | null>",
  "blocked_reason": "<string | null>"
}
```

Field semantics:

| Field | When set | Value |
|---|---|---|
| `status` | always | `done` — open PR exists, ready-for-review; `failed` — a gate in the pipeline did not pass and was not recoverable; `blocked` — an external blocker was detected (dependency unresolved, environment issue, manual input required) |
| `pr_url` | when `status == "done"` | URL of the open, ready-for-review PR |
| `failed_gate` | when `status == "failed"` | Free-form string identifying which gate failed (see invariant below) |
| `blocked_reason` | when `status == "blocked"` | Human-readable description of the blocker |

## Invariant: `failed_gate` Is Not a Core Enum

`failed_gate` is a **backend-defined free-form string**. The core MUST NEVER interpret or
branch on `failed_gate` as a closed enumeration. Concretely:

- The core MAY log the value for the user.
- The core MUST NOT use `if failed_gate == "check"` or equivalent branching.
- A Backend B that emits a different vocabulary (e.g. `"lint-gate"`, `"e2e-timeout"`) must
  not require any change to the core — if the core branched on `failed_gate` values, Backend B
  would need to "extend the contract" by editing the core, which violates AC-10.

For Backend A (single-session), the recommended (non-binding) vocabulary is:
`check | finalize | acceptance | create-pr`

These are illustrative examples, not an exhaustive closed set. Any string is valid.

## Core-Side Handling

```
signal = call_backend(task_id, scope, allowed_depth)

if signal.status == "done":
    record pr_url in state file
    call transition_status(issue_ref, "done")   # abstract action
    call link_pr(issue_ref, pr_ref)             # abstract action
    call add_comment(issue_ref, key="batch-done", body="PR: " + signal.pr_url)

elif signal.status == "failed":
    log "Gate failed: " + signal.failed_gate    # log only — no branching on the value
    call transition_status(issue_ref, "blocked")
    hold entire transitive downstream DAG branch

elif signal.status == "blocked":
    log "Blocked: " + signal.blocked_reason
    call transition_status(issue_ref, "blocked")
    hold entire transitive downstream DAG branch
```

## Two Distinct Signals: Completion Signal vs Tracker Completion Fact

These two vocabularies share some words but are different concepts — do not conflate them.

**Completion signal** (this file's schema, emitted by the backend to the core):
- `status: done` = the per-task flow finished and produced an **open, ready-for-review PR**. The core never merges.
- `status: failed` = a gate did not pass; `status: blocked` = external blocker.

**Tracker completion fact** (emitted by `get_completion_signal.sh`, used during RECONCILE
and compaction-resume to read GitHub ground-truth):
- `signal: done` = a linked PR is **merged** (or issue closed-as-done).
- `signal: pr-open` = a linked PR exists and is open.
- `signal: none` = no linked PR.

**Mapping during reconcile/resume:** a task whose backend returned `status: done` (open PR)
corresponds to the tracker fact `pr-open` until a human merges it, at which point the tracker
fact becomes `done`. The core MUST NOT assume `signal: done` (merged) just because the backend
returned `status: done` (open PR).

## Field Mutual-Exclusivity Invariants

The following MUST invariants hold for every completion signal:

- `pr_url` is non-null ONLY when `status == "done"`; it MUST be null for `failed` and `blocked`.
- `failed_gate` is non-null ONLY when `status == "failed"`; it MUST be null for `done` and `blocked`.
- `blocked_reason` is non-null ONLY when `status == "blocked"`; it MUST be null for `done` and `failed`.

## Backend Registry

| Backend ID | Reference | Description |
|---|---|---|
| `A` (default) | [`exec-single.md`](exec-single.md) | Single-session; sequential per-task flow via subagents/skills |
| `B` (future) | `exec-team.md` (not yet authored) | Agent Teams; removes Backend A context ceiling |

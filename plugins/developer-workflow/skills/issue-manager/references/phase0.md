# Phase 0 — Board Analysis and Approval Gate

Phase 0 transforms raw GitHub issue data into an ordered execution plan and presents it
to the user for a single approval. It is the only human gate before execution begins.

## Step 1 — Scope Resolution

Resolve the input to a concrete issue list:

| Input form | Resolution |
|---|---|
| Issue URL or `#N` | Single issue: fetch via `fetch_issue`, check it is open |
| Comma-separated list (`#3,#7,#12`) | Multi-issue: `list_issues --numbers 3,7,12` |
| Epic reference (`#N` labeled as epic, or `epic/<name>`) | Fetch epic, then `list_issues` filtered by sub-issues of that epic |
| `"all open"` / no scope | `list_issues --state open` — subject to scope cap (see below) |

For each resolved issue, call `get_dependencies` to retrieve edges.

## Step 2 — DAG Construction

Build a directed acyclic graph from the dependency edges:

```
edge: { from: BLOCKED, to: BLOCKER }
```

- `from` is the issue that cannot start until `to` is done.
- Sub-issue edges (from=parent, to=child) mean the parent is blocked by each child: children
  must complete before the parent can close.

**Ready set** = issues with no unsatisfied BLOCKER dependencies (all `to` nodes in their
edges are either absent from the scope, already Done, or resolved externally).

**Topological order** = a valid execution sequence respecting all edges. Any valid
topological sort is acceptable; prefer ordering by label priority or issue number when
multiple orderings are valid.

## Step 3 — Cycle Detection

Detect cycles using DFS on the dependency graph.

**On cycle detected:**
1. Identify all issues that are members of the cycle.
2. Present to the user:
   ```
   Cycle detected — cannot build a valid execution order.
   Cycle members: #12 → #15 → #18 → #12
   
   Resolution required: remove at least one edge in the cycle before approving.
   Options:
     a) Edit issue body to remove a "blocked by" reference
     b) Close one of the issues as won't-do
     c) Provide a manual order that breaks the cycle (list numbers in execution order)
   
   Phase 0 is blocked until the cycle is resolved.
   ```
3. Wait for user input. Do not proceed until the cycle is eliminated.

## Step 4 — Scope Cap

**Default cap: 5 issues per batch.**

This limit is calibrated against the Backend A context ceiling (~3–6 tasks before
compaction, depending on issue complexity). It should be tuned based on observed behavior
in L5 dry runs on the target repo.

To override: user may specify `--cap N` (e.g. `/issue-manager --cap 8`). Cap applies
to the ready set only — issues that are blocked by unresolved dependencies do not count.

**On cap exceeded:**
```
Scope contains N ready issues, which exceeds the batch cap of 5.
Processing more than 5 issues in a single session risks context compaction mid-batch.

Options:
  a) Narrow scope: provide a comma-separated list of ≤5 issue numbers to process now
  b) Override cap: confirm "proceed with N" (acknowledged risk of mid-batch compaction)
  c) Increase cap: /issue-manager --cap N
```
Do not proceed without user confirmation when over cap.

## Step 5 — Approval Gate Presentation

Present the execution plan in this format:

```
## Issue Manager — Phase 0: Execution Plan

**Scope:** <description of resolved scope>
**Ready issues:** N (of M total in scope)
**Blocked issues:** <list with reason>

### Dependency Graph
<ASCII or text representation of DAG edges>
  #12 → depends on → #9 (open, will be processed first)
  #15 → no dependencies

### Proposed Execution Order
1. #9  — <title>
2. #12 — <title>  (unblocked after #9)
3. #15 — <title>

### Per-Issue Flow (Backend A)
Each issue: transition In-Progress → [research?] → [spec?] → implement → /check → /finalize → /acceptance → /create-pr (ready-for-review)

**Blocked (not in this batch):**
- #18 — blocked by #22 (not in scope / not done)

---
Confirm to proceed, or reply with a reordered number list (e.g. "15, 9, 12").
```

Accept one of:
- `"ok"` / `"yes"` / `"proceed"` / `"confirm"` → proceed with proposed order
- A number list (e.g. `"15, 9, 12"`) → adopt user's order, validate it is a valid
  topological sort (warn if not, but accept if user insists)
- `"stop"` / `"cancel"` → abort with no writes to tracker

This is the ONLY approval gate. Once approved, EXECUTE runs without further confirmation
(except the implicit human merge gate that exists because the skill stops at open PRs).

## State File Initialization

After approval, write the initial state file at:
`swarm-report/issue-manager-<batch>-state.md`

Where `<batch>` is:
- Epic name (kebab-case) if scope is an epic
- SHA-1 hash of the sorted number list (first 8 chars) if scope is a number list
- `all-open-<YYYYMMDD-HHMM>` if scope is "all open"

See [`reconcile.md`](reconcile.md) for the state file schema.

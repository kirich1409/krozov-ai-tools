# Backend A — Single-Session Execution

Implements the exec-contract for a single issue. Called by the EXECUTE phase of the core.
The backend runs entirely within the main session, delegating all code work to subagents
and skills.

## Input

```
task_id:       string   # issue number or "owner/repo#N"
scope:         object   # { issue_ref, title, body, labels, url }
allowed_depth: string   # "minimal" | "standard" | "deep"
```

## Step 1 — Transition to In-Progress

Call abstract action `transition_status(issue_ref, "in-progress")`.

Read-before-write is enforced by the script — if the issue is already in-progress this is
a no-op.

## Step 2 — Adaptive Depth (Research + Spec)

Evaluate whether the issue has enough information for direct implementation:

- Issue body contains clear acceptance criteria, implementation detail, and no open questions
  → skip research and spec (depth = `minimal`)
- Issue body is underspecified (vague "do X", no ACs, no implementation pointers)
  → if `allowed_depth` is `standard` or `deep`: invoke `/write-spec` via the Skill tool
  → if `allowed_depth` is `deep`: first invoke `/research` via the Skill tool, then `/write-spec`

`/research` and `/write-spec` are invoked via the Skill tool (same chaining pattern that
`/finalize` uses when it chains `/simplify` and `/check`). Do not spawn separate agents for
these — they are skills in the same plugin family.

## Step 3 — Implement (Delegate to Engineer Subagent)

`implement` has no skill. Route by detected stack using the Task/Agent tool:

| Detected stack | Subagent |
|---|---|
| Kotlin / Android (ViewModel, UseCase, Repository, DI, mappers, unit tests) | `developer-workflow-kotlin:kotlin-engineer` |
| Compose UI (composables, theme, navigation, modifiers, previews) | `developer-workflow-kotlin:compose-developer` |
| Swift / iOS / macOS | `developer-workflow-swift:swift-engineer` |
| Any other / mixed / unknown | general-purpose (Sonnet) |

Stack detection: check repo file tree (`.kt`, `.swift`, `build.gradle*`, `Package.swift`),
issue labels, and existing code patterns. When ambiguous, prefer general-purpose.

The subagent receives: task description from issue body + spec (if produced in Step 2) +
repo context. It must not be given the issue-manager state file — it works on the code only.

## Step 4 — Check

Invoke `/check` via the Skill tool.

`/check` runs the project's static analysis and build gate. On failure: capture the error
output, emit completion signal `{ "status": "failed", "failed_gate": "check", "pr_url": null,
"blocked_reason": null }` and return.

## Step 5 — Finalize

Invoke `/finalize` via the Skill tool.

`/finalize` runs the full review→fix→simplify loop until no findings above Minor severity
remain. On ESCALATE (user decision required): emit `{ "status": "failed", "failed_gate":
"finalize", "pr_url": null, "blocked_reason": null }` and return.

## Step 6 — Acceptance

Invoke `/acceptance` via the Skill tool.

`/acceptance` verifies the implementation against the source of truth (spec produced in
Step 2, or issue ACs, or behavioral baseline). On failure: emit `{ "status": "failed",
"failed_gate": "acceptance", "pr_url": null, "blocked_reason": null }` and return.

## Step 7 — Create PR (Ready-for-Review)

Invoke `/create-pr` (default mode — ready-for-review) via the Skill tool.

Per the project feedback rule (feedback_pr_ready_immediately): in batch processing, PRs open
immediately as ready-for-review. Do NOT open as draft. Do NOT merge.

On success: capture `pr_url` from the PR creation output.

## Step 8 — Emit Completion Signal

Success path:
```json
{
  "status": "done",
  "pr_url": "<url of the open, ready-for-review PR>",
  "failed_gate": null,
  "blocked_reason": null
}
```

The core (RECONCILE phase) reads this signal, calls `link_pr` + `add_comment`, and keeps the
issue open (phase → `pr-open`). The board advances to `done` only later, when
`get_completion_signal` returns `signal: done` (PR merged or issue closed-as-done).

## Context Ceiling Note

Backend A runs all steps in the main session. Each task consumes the context of Steps 2–7
(research, spec, implement delegation, check, finalize, acceptance, create-pr). The practical
ceiling before context compaction is approximately 3–6 tasks per batch, depending on issue
complexity. Phase0's scope cap (default 5) is calibrated against this ceiling — see
[`phase0.md`](phase0.md).

On compaction mid-batch: the RECONCILE state file + GitHub ground-truth allow resuming from
the first incomplete task — see [`reconcile.md`](reconcile.md).

---
name: drive-to-merge
description: >
  Autonomous orchestrator that takes an existing PR/MR from its current state to merge. Monitors
  CI/CD, diagnoses failures, fetches review comments, categorizes them inline, proposes concrete
  fixes (snippet or delegation), delegates to implement/debug, posts replies, resolves threads,
  re-requests review (Copilot + humans), polls via ScheduleWakeup, loops until merged. Decision
  tables rendered in-session — no user-editable manifest. Default mode waits for "approve" per
  round; `--auto` proceeds without waiting; `--dry-run` stops after the first table. Final merge
  always requires explicit user confirmation. Triggers: "drive this PR to merge", "get this PR
  merged", "monitor CI and reviews", "ship this PR", "land this PR", "доведи PR до мержа",
  "веди PR", "замержь этот PR". Autonomous-mode triggers (equivalent to `--auto`): "действуй
  автономно", "без подтверждений", "auto mode", "не спрашивай", "run autonomously". Do NOT use
  for creating new PRs (use create-pr) or code written from scratch (use implement).
---

# Drive to Merge

Autonomous end-to-end PR driver. Takes the currently open PR/MR from its present state
and loops — diagnose CI, categorize review comments, propose fixes, delegate, push,
re-request review, wait for new activity — until the PR is merged or a true blocker
requires the user.

**Core principle:** keep the PR moving. Every obstacle (CI failure, review comment,
stalled reviewer) is a loop iteration, not a stop. The skill stops only for: the final
merge (requires user confirmation), true disagreements with a reviewer that need a
human judgement call, or mechanical dead-ends (permission denied, rebase conflict the
skill cannot resolve).

**In-session, not in files.** All analysis, categorization, and proposed actions are
rendered in the conversation as tables. A state file exists only to survive context
compaction — the user never edits it.

---

## Modes

| Mode | What it changes |
|---|---|
| default | Between rounds shows a decision table and waits for `approve` / `skip` / `stop` |
| `--auto` | Same table shown for visibility, then proceeds without waiting; merge step still asks |
| `--dry-run` | Runs analysis and renders the decision table once; makes no edits, pushes, or posts; exits |

Trigger words equivalent to `--auto`: "действуй автономно", "без подтверждений", "auto mode", "не спрашивай". The skill echoes which mode it is running in before Phase 2.

The merge step in Phase 5 **always** asks — `--auto` does not override that.

---

## Operational references

Volatile procedural detail — CLI recipes, GraphQL mutations, sanitize pipeline, retry
logic — lives in reference files loaded only when the relevant phase runs. SKILL.md
stays the stable orchestration contract.

| File | Covers |
|---|---|
| [`references/setup.md`](references/setup.md) | Phase 1: platform detect, metadata fetch, preconditions, state-file schema, mode precedence on resume |
| [`references/ci.md`](references/ci.md) | Phase 2.2: run-id extraction from `statusCheckRollup`, log download, classification, CI failure table, infra-flake retry, failure-loop guard |
| [`references/reviews.md`](references/reviews.md) | Phase 2.3 + 2.4: fetch, categorize, verify, pattern-match, group, propose; decision-table format and gate behaviour |
| [`references/delegation.md`](references/delegation.md) | Phase 3: edit / delegate / ask-in-thread / dismiss; reply-delivery safety rules; commit + push; re-request review (humans + Copilot) |
| [`references/polling.md`](references/polling.md) | Phase 4: ScheduleWakeup schedule, delaySeconds matrix, cache-window tuning, poll-cap blocker |
| [`references/merge.md`](references/merge.md) | Phase 5: pre-merge checks, confirmation UX, final re-check, merge commands; Phase 2.6 rebase companion |

---

## Phase 1: Setup

Detect platform, fetch PR/MR metadata, verify preconditions, load or initialise the state
file. Full procedure in [`references/setup.md`](references/setup.md).

If the PR/MR is already merged or closed — stop and report the final state.

---

## Phase 2: Round loop

One round = one full pass of Phases 2.1 → 2.5. After 2.5, either merge (Phase 5) or sleep
(Phase 4) and start a new round.

Each round begins by re-fetching PR state. Nothing is cached across rounds except the state
file.

### 2.1 Sync PR state

```bash
# GitHub — single call covers CI rollup, reviews decision, mergeability
PR_STATE=$(gh pr view --json statusCheckRollup,reviewDecision,mergeable,mergeStateStatus,\
isDraft,state,reviews,reviewRequests)
```

Classify:

| PR attribute | Values that matter |
|---|---|
| `state` | OPEN → continue; MERGED / CLOSED → Phase 5 terminal |
| `isDraft` | `true` → handle review comments and CI, but never enter Phase 5; surface to user with "PR is draft — promote to ready with `gh pr ready` or abort" when everything else would be merge-ready |
| `statusCheckRollup` | Any `FAILURE` / `CANCELLED` / `TIMED_OUT` → 2.2 CI handling; all `SUCCESS` → skip 2.2; mix of `IN_PROGRESS` + no failures → wait (Phase 4) |
| `reviewDecision` | `CHANGES_REQUESTED` → 2.3 must run; `APPROVED` → candidate for merge; `REVIEW_REQUIRED` → 2.4 (request review) |
| `mergeable` + `mergeStateStatus` | `CONFLICTING` → 2.6 rebase; `BLOCKED` (missing approval, failing required check) → identify and loop |

### 2.2 CI handling

Investigate failing checks, retry infra flakes, hand code-fix rows to Phase 3. Procedure
(run-id extraction, classification, failure-loop guard) in [`references/ci.md`](references/ci.md).

### 2.3 Review handling

Fetch comments, filter already-owned threads, categorize (BLOCKING / IMPORTANT /
SUGGESTION / NIT / QUESTION / PRAISE / OUT_OF_SCOPE) crossed with actionability (FIXABLE
/ NEEDS_CLARIFICATION / DISCUSSION / NO_ACTION), verify suggestions against the diff,
pattern-match, group, and generate a concrete proposal per item. Full procedure in
[`references/reviews.md`](references/reviews.md).

### 2.4 Decision table (the gate)

Render in session as a **prioritized list** — sections P0 → P1 → P2 → P3 → P4 with
continuous numbering. Each item is one short paragraph: bold headline, author, location,
action. `## Blockers` section always last. `## Summary` one line with action-type
breakdown. Format and example in [`references/reviews.md`](references/reviews.md).

Gate behaviour:

- **default** — stop, wait for `approve` / `skip N,M` / `stop`. Accept space- and
  comma-separated number lists.
- **`--auto`** — skip waiting, proceed to Phase 3.
- **`--dry-run`** — print the list and stop for good.

Blockers are always surfaced — `--auto` does not swallow them. If any P0 item is
DISCUSSION, stop and ask regardless of mode.

### 2.5 Round outcome

After Phase 3 executes the approved rows: push, update state file (append a row to `Rounds`
and to `Commitments`), decide next step:

| Situation | Next |
|---|---|
| New fixes pushed → CI will run → wait for it | Phase 4 poll |
| No code changes, only dismisses/replies posted, review still pending | Phase 4 poll (wait for reviewer) |
| All threads closed, CI green, `reviewDecision == APPROVED`, mergeable | Phase 5 merge |
| `mergeStateStatus == BEHIND` (base moved) | Phase 2.6 rebase, then poll |
| Blocker raised | Stop, update state file, surface to user |

### 2.6 Rebase when base has advanced

Procedure and "Dismiss stale approvals" side effect in [`references/merge.md`](references/merge.md).

---

## Phase 3: Execute approved rows

Execute strictly in table order. Branches:

- **Edit rows** — apply snippet, run `check`, stop on failure.
- **Delegate rows** — invoke `implement` / `debug` or engineer agent sequentially; scope-guard
  diff after each returns.
- **Ask-in-thread rows** — post verbatim question, do not resolve.
- **Dismiss rows** — canned template + sanitized slot, resolve thread.

Commit with `Address review: …`, push plain or `--force-with-lease` (never plain
`--force`). Re-request review from any reviewer whose state was `CHANGES_REQUESTED` when
code changed; Copilot via GraphQL mutation.

Full procedure, safety rules (stdin-piped bodies, rate-limit handling, pre-POST
thread-ownership verify), and Copilot node-id resolution in
[`references/delegation.md`](references/delegation.md).

---

## Phase 4: Poll (ScheduleWakeup)

Schedule the next round when the round ended in "wait" (CI running or review pending).
Delay is chosen by what we are waiting on; prompt is derived from the stored `Mode` in the
state file, never hardcoded. Cache-window discipline (≤270 or ≥600, avoid 280–550s).

Procedure and delaySeconds matrix in [`references/polling.md`](references/polling.md).

---

## Phase 5: Merge (always user-confirmed)

Pre-merge checks → confirmation message → final re-check → `gh pr merge` / `glab mr merge`.
`--auto` does not skip this gate — by design, final merge always requires explicit user
approval.

Procedure in [`references/merge.md`](references/merge.md).

---

## Terminal states

| State | When | What the skill writes |
|---|---|---|
| `merged` | Phase 5 succeeded | state file marked merged, success summary in session |
| `blocked` | A blocker was surfaced (failure-loop guard, integrity mismatch, unresolvable rebase, DISCUSSION requires user, polling exceeded cap, or user explicitly says "stop") | state file `Blockers raised` filled (including reason `"user stop"` when applicable), session message explains next action |

---

## Defaults for autonomous judgement

The skill decides these without asking, in any mode:

- **NEEDS_CLARIFICATION** — ask the clarifying question in the thread; record and move on. Do not stop the round.
- **OUT_OF_SCOPE** — dismiss with reply. Offer (in the decision table row) to create a follow-up issue; create it only if the user types "create issues" during the approval step.
- **NIT + FIXABLE** — include in the edits batch. Trivial renames and formatting are worth the round.
- **DISCUSSION on P0/P1** — stop, surface as blocker. Never execute guesses on blocking-level disagreements.
- **DISCUSSION on P2/P3** — include as a table row with proposal "ack-in-thread-without-code-change"; a short reply summarizing the skill's counter-view and leaving the thread open for the reviewer.

---

## Principles

**One skill, one loop.** CI, review, rebase, merge — all one loop with shared state. Never hand off mid-round to another skill for orchestration; delegate individual edits, but own the loop.

**All output in the session.** The decision table, proposals, blockers, final merge summary — all rendered as chat messages. The state file is for resumption after compaction, not for user editing.

**Proposals are concrete.** Every actionable row carries a snippet, a delegation instruction, or the exact question text. "BLOCKING / FIXABLE" alone is not a proposal.

**Autonomous by default.** The user should only see decisions that require judgement: true disagreements, unresolvable rebases, final merge. Everything mechanical happens without asking.

**Approval gate ≠ merge gate.** `--auto` removes the round-level approval gate. It does not remove the merge gate — by design, final merge always requires explicit user confirmation.

**Safe by construction.** Replies go through the sanitize pipeline; thread ownership is re-verified before every POST; POST bodies go through stdin, never shell args; force-push uses `--force-with-lease` only.

**Respect the reviewer.** Push back on wrong suggestions (record as DISCUSSION, draft a counter-reply); do not dress a broken suggestion up as FIXABLE and ship the broken fix.

**Pattern completeness.** Fixing one reported instance while identical problems remain elsewhere in the diff gets the thread reopened. Pattern-match at analysis time, fix at apply time.

**Fail loudly, not silently.** Three CI failures on the same signature, an integrity mismatch, a rebase with logic conflicts — stop and surface, do not retry forever.

---

## Tool priority

`gh` / `glab` CLI when available → REST via `gh api` / `glab api` → GraphQL via `gh api graphql` for review threads and node ids → `ScheduleWakeup` for Phase 4 polling → nothing else.

If neither `gh` nor `glab` is installed or authenticated, stop with a clear message: this skill cannot degrade gracefully without a working CLI, because its value is autonomous push + reply + resolve. Ask the user to install and authenticate, then rerun.

`ScheduleWakeup` is required for autonomous polling. If the runtime does not expose it, fall back to a single-shot round: report state, record a "wake me manually" note in the state file, and exit. The user then re-invokes `/drive-to-merge` when they want the next round.

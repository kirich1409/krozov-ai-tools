# Adapter Contract — GitHub Tracker

This is the ONLY file where concrete script names appear. SKILL.md and all other
references use abstract action names only. The adapter-resolver table below maps each
abstract action to its GitHub implementation, making Phase 3 (multi-tracker) possible
without touching the core.

## Adapter-Resolver Table

| Abstract action | Concrete invocation | Notes |
|---|---|---|
| `list_issues` | `bash ${CLAUDE_PLUGIN_ROOT}/skills/issue-manager/scripts/gh/list_issues.sh [--state open\|closed\|all] [--label <name>]... [--limit N] [--numbers n1,n2,...] [-R <owner/repo>]` | `--numbers` bypasses state/label filters |
| `fetch_issue` | `bash ${CLAUDE_PLUGIN_ROOT}/skills/issue-manager/scripts/gh/fetch_issue.sh <issue-ref> [-R <owner/repo>]` | Returns full body + node_id |
| `get_dependencies` | `bash ${CLAUDE_PLUGIN_ROOT}/skills/issue-manager/scripts/gh/get_dependencies.sh <issue-ref> [-R <owner/repo>]` | Returns edge list; empty deps → `[]` |
| `get_completion_signal` | `bash ${CLAUDE_PLUGIN_ROOT}/skills/issue-manager/scripts/gh/get_completion_signal.sh <issue-ref> [-R <owner/repo>]` | Polls tracker-side PR linkage |
| `transition_status` | `bash ${CLAUDE_PLUGIN_ROOT}/skills/issue-manager/scripts/gh/transition_status.sh <issue-ref> <target-status> [-R <owner/repo>] [--project-id <id>] [--dry-run]` | Read-before-write; writes only if current != target |
| `link_pr` | `bash ${CLAUDE_PLUGIN_ROOT}/skills/issue-manager/scripts/gh/link_pr.sh <issue-ref> <pr-ref> [-R <owner/repo>] [--dry-run]` | Idempotent via marker |
| `add_comment` | `bash ${CLAUDE_PLUGIN_ROOT}/skills/issue-manager/scripts/gh/add_comment.sh <issue-ref> --key <marker-key> --body <text> [-R <owner/repo>] [--dry-run]` | Idempotent via marker |

## Output JSON Schemas

All scripts write to stdout. On error: `{"error":"<msg>","code":"<code>"}` + non-zero exit.

### `list_issues`
```json
[
  {
    "number": 42,
    "title": "string",
    "state": "OPEN|CLOSED",
    "labels": [{"id": "string", "name": "string", "color": "string"}],
    "url": "string",
    "node_id": "string"
  }
]
```
Note: `state` is the GitHub-native uppercase value (`"OPEN"` or `"CLOSED"`).

### `fetch_issue`
```json
{
  "number": 42,
  "title": "string",
  "state": "OPEN|CLOSED",
  "body": "string",
  "labels": [{"id": "string", "name": "string", "color": "string"}],
  "url": "string",
  "node_id": "I_kwDORg45R88..."
}
```
`node_id` is the GraphQL global node id, required for Project v2 mutations.
`state` is the GitHub-native uppercase value (`"OPEN"` or `"CLOSED"`).

### `get_dependencies`
```json
[
  {"from": 17, "to": 12, "source": "sub-issue|blocked-by|depends-on"}
]
```
Direction: `from` is the BLOCKED issue, `to` is the BLOCKER. Sub-issue edge: the parent is
blocked by each child (children must complete before the parent can close) — `from` = parent
number, `to` = child number. Empty dependency set → `[]`.

### `get_completion_signal`
```json
{
  "signal": "done|pr-open|none",
  "pr_url": "<string|null>",
  "pr_state": "<string|null>",
  "pr_number": "<int|null>"
}
```
- `done` — associated PR is merged or issue is closed-as-done.
- `pr-open` — associated PR exists and is open (ready-for-review or draft).
- `none` — no associated PR and issue is still open.

### `transition_status`
```json
{
  "action": "transition|noop",
  "from": "todo|in-progress|blocked|done",
  "to": "todo|in-progress|blocked|done",
  "mechanism": "project-v2|labels",
  "dry_run": false
}
```
`from` is always a non-null string (current normalized status). `--dry-run` adds
`resolved_payload` with the write that would be sent. Target statuses accepted: `todo`,
`in-progress`, `blocked`, `done` (also accepts `open`→`todo`, `closed`→`done` for
convenience). Project v2 detected → uses status option; else fallback: open/closed state +
label convention (`status:in-progress`, `status:blocked`).

### `link_pr`
```json
{
  "action": "linked|noop",
  "issue": 42,
  "pr": 99,
  "comment_id": "<string|null>",
  "dry_run": false
}
```
`comment_id` is the GitHub GraphQL node id string (e.g. `IC_kwDO...`) of the newly posted
comment, or `null` on noop or dry-run. On `--dry-run` (non-noop path), a `would_post` field
contains the comment body that would be posted.
Idempotent: checks for marker `<!-- issue-manager:link-pr:<pr-number> -->` before posting.

### `add_comment`
```json
{
  "action": "commented|noop",
  "issue": 42,
  "key": "marker-key",
  "comment_id": "<string|null>",
  "dry_run": false
}
```
`comment_id` is the GitHub GraphQL node id string (e.g. `IC_kwDO...`) of the newly posted
comment, or `null` on noop or dry-run. On `--dry-run` (non-noop path), a `would_post` field
contains the comment body that would be posted.
Idempotent: checks for marker `<!-- issue-manager:<key> -->` before posting.

## Adapter-Resolver Concept

The core references abstract action names (e.g. `transition_status`) only — never concrete
script paths. This file maps each action to its GitHub-specific implementation.

To add a GitLab adapter (Phase 3): create `scripts/gitlab/` with matching scripts and add a
second resolver column or a separate `adapter-contract-gitlab.md`. The core SKILL.md requires
no changes.

No GitHub-specific logic (`gh`, GraphQL) appears anywhere outside this file's resolver table
and the bundled `scripts/gh/` scripts.

---
name: create-pr
description: >
  Manage the pull request (GitHub) / merge request (GitLab) for the current branch through its
  lifecycle. Four modes: `--draft` creates or refreshes a draft PR early in the pipeline,
  `--refresh` updates the body of an existing PR without touching its status, `--promote`
  refreshes body and marks a draft PR ready for review, and default (no flag) creates a new PR
  with a draft-or-ready prompt. Composes description from available swarm-report artifacts
  (research, plan, test-plan, finalize, acceptance) and falls back to git log + diff. Invoke
  when the user says "create PR", "open draft PR", "refresh PR description", "promote to ready",
  "mark PR ready for review", "update the PR", "switch the PR to ready", or when feature-flow /
  bugfix-flow orchestrators call this skill at a lifecycle step.
---

# Create PR

Manage a pull request (GitHub) or merge request (GitLab) across its lifecycle — draft creation, in-flight body refreshes, and final promotion to ready for review. Composes description dynamically from available artifacts.

---

## Modes overview

| Mode | When | What it does | Fails if |
|---|---|---|---|
| `--draft` | After first implement commit in a pipeline | Creates draft PR if none exists; refreshes body if a draft already exists | PR exists and is already ready for review |
| `--refresh` | After major lifecycle steps (finalize round complete, acceptance passed) | Updates body of existing PR (draft or ready) — no status change | No PR exists |
| `--promote` | After all local quality passes (finalize + acceptance) | Refreshes body with final summary, then marks draft PR as ready for review | No PR exists, or PR is already ready |
| default | Manual invocation outside pipeline | Asks draft-or-ready if unclear, then creates | PR already exists |

Mode is passed via arguments: `/create-pr --draft`, `/create-pr --refresh`, `/create-pr --promote`, or `/create-pr` for default.

---

## Step 1: Setup (all modes)

```bash
# Platform detect
git remote get-url origin
# contains github.com → use gh; contains gitlab → use glab

# Base branch
BASE=$(git remote show origin 2>/dev/null | grep "HEAD branch" | awk '{print $NF}')
# Fallback order: main → master → develop

BRANCH=$(git branch --show-current)
CURRENT_EMAIL=$(git config user.email)
CURRENT_NAME=$(git config user.name)
```

---

## Step 2: Check for existing PR (all modes)

Do NOT use `2>/dev/null` here — it silently conflates "no PR exists" (expected) with
"CLI unavailable / auth failed" (a real error). Capture stderr and branch on exit code:

```bash
# GitHub
out=$(gh pr view --json url,isDraft,number,body 2>&1); rc=$?
# Exit code:
#   0              → PR exists; parse $out as JSON
#   1 + stderr contains "no pull requests" / "no open pull requests" → no PR (expected)
#   any other rc or unexpected stderr → real error (CLI missing, unauthenticated, API down)

# GitLab
out=$(glab mr view --output json 2>&1); rc=$?
# Same pattern: rc 0 → MR exists; stderr "no open merge request" → no MR; other → real error.
```

**On real error (non-zero rc that is not the "no PR" case):** abort with the captured
stderr and stop. Do not proceed as if no PR exists — that would try to create a duplicate.
Typical causes: `gh` / `glab` not installed or not authenticated (`gh auth status`,
`glab auth status`), API outage, or a sandbox/proxy environment where the Git provider
token is missing.

Capture on success:
- `PR_EXISTS` — true/false
- `PR_IS_DRAFT` — true/false (if exists)
- `PR_URL` — for output
- `PR_BODY` — current body, used by refresh/promote to preserve manual edits (see Step 7.4)

### Mode preconditions

| Mode | Precondition | On failure |
|---|---|---|
| `--draft` | PR does not exist, or exists AND `isDraft: true` | If PR exists AND not draft: abort with "PR is already ready for review; use `--refresh` to update the body." |
| `--refresh` | PR exists (draft or ready — `--refresh` does not change status) | If no PR: abort with "No PR found for this branch. Use `--draft` or default to create one first." |
| `--promote` | PR exists AND `isDraft: true` | If no PR: abort with "No PR to promote." If already ready: abort with "PR is already ready for review; use `--refresh` if you want to update the body." |
| default | PR does not exist | If PR exists: print URL, abort. Suggest `--refresh` or `--promote`. |

---

## Step 3: Push branch (all modes — if local has new commits)

```bash
# Ensure upstream exists. First push uses -u to set upstream tracking.
git rev-parse --abbrev-ref @{u} 2>/dev/null || git push -u origin "$BRANCH"
# Then sync any local commits that aren't on the remote yet.
# This is a no-op ("Everything up-to-date") if the branch is already in sync,
# which is the common case for --refresh / --promote between commits.
git push
```

Never force-push here. If the push fails due to non-fast-forward — abort and ask the user to resolve.

---

## Step 4: Analyse branch state (all modes — needed for body)

Run in parallel:

```bash
git log $BASE..HEAD --oneline          # commits on the branch
git diff --name-only $BASE...HEAD      # changed files
git diff $BASE...HEAD --stat           # diff stat
git diff $BASE...HEAD                  # full diff (for description reasoning)
```

---

## Step 5: Discover pipeline artifacts

Look for artifacts in `./swarm-report/` that match the current branch/task slug. Read those that exist:

| Artifact | Location | Purpose in body |
|---|---|---|
| research | `swarm-report/<slug>-research.md` | Link + 1-sentence abstract in "Context" section |
| spec | `docs/specs/<YYYY-MM-DD>-<slug>.md` (written by `write-spec`) | Reference as "Specification" |
| plan | `swarm-report/<slug>-plan.md` | Reference as "Plan"; acceptance criteria extracted for "How to test" |
| decomposition | `swarm-report/<slug>-decomposition.md` | Reference as "Task breakdown" when present |
| debug | `swarm-report/<slug>-debug.md` | Root cause + reproduction steps — primary context for bugfix PRs |
| test plan | `swarm-report/<slug>-test-plan.md` | Reference; test cases become checklist in "How to test" |
| implement | `swarm-report/<slug>-implement.md` | Summary of implementation goes into "What changed" |
| quality | `swarm-report/<slug>-quality.md` | Gate pass/fail summary for status table |
| finalize | `swarm-report/<slug>-finalize.md` | Round-by-round summary for status table (available once the `finalize` skill is installed) |
| acceptance | `swarm-report/<slug>-acceptance.md` | Pass/fail + verified scenarios for "Verification" section |

Slug resolution:
1. Prefer slug if orchestrator passed it as argument
2. Fallback to branch name with common prefix stripped: `feature/`, `fix/`, `hotfix/`, `bug/`, `chore/`, `refactor/`, `docs/`

Artifacts are gitignored (in `swarm-report/`), so they won't appear in diff — include them as *references* in the body (e.g., "See `swarm-report/my-slug-plan.md`"), not as inlined content. Reviewers working on the PR locally can read them; CI cannot, but the body remains readable without them.

---

## Step 6: Labels and reviewers (skip for `--refresh`)

Only set labels/reviewers when **creating** (draft or default) or when **promoting** — these rarely need to change mid-flight. `--refresh` does NOT touch labels/reviewers to avoid clobbering user edits.

### 6.1 Labels

Fetch available labels:

- **GitHub:** `gh label list --json name,description --limit 100`
- **GitLab:** `glab label list` (fetches labels for the current project resolved from
  `git remote get-url origin`; do NOT use `glab api /projects/:fullpath/labels` — glab
  does not substitute `:fullpath` and the call will 404)

Select from existing only, based on changed file paths, commit types, and scope. Do not
invent labels.

**Add, don't replace.** When deriving labels during creation (`--draft` or default) or `--promote`, only **add** missing labels computed from the diff; never remove labels set manually by humans. This preserves reviewer / triage / release labels that a maintainer may have applied between draft creation and promote. `--refresh` skips Step 6 entirely (see header), so it never touches labels at all.

### 6.2 Reviewers

For `--draft` **and** `--promote` modes, skip reviewer assignment — reviewers go on only in default mode or when explicitly requested by the caller. Rationale: draft PRs do not need reviewers yet; when promoting to ready, the pipeline normally has already determined reviewers (or the user assigns manually).

For the default mode: top 3 authors who touched the changed files recently, filtered to exclude `$CURRENT_EMAIL`, mapped to platform usernames, presented to the user before adding.

---

## Step 7: Compose body

Body composition is mode-aware.

### 7.1 Section bank

The body is composed from a catalog of optional sections: What changed, Why / motivation, Artifacts, How to test, Status, Screenshots / demo, Checklist, and a trailing Claude Code footer. Include only the sections that apply for the current mode and available artifacts.

See [`references/body-sections.md`](references/body-sections.md) for the full section-bank templates with example content and status-table formatting.

### 7.2 Section selection per mode

| Section | `--draft` | `--refresh` | `--promote` | default |
|---|---|---|---|---|
| What changed | short (plan/task-based, code may be incomplete) | updated from current diff | final, full | full |
| Why / motivation | ✅ | ✅ | ✅ | ✅ |
| Artifacts | ✅ (as they appear) | ✅ (keeps current) | ✅ | ✅ if exist |
| How to test | from plan if exists | from test-plan if exists | full | ✅ |
| Status | "Implement: in progress" | updated from latest artifacts | all PASS | optional |
| Screenshots | placeholder + prompt user | keep as-is | verify filled | prompt |
| Checklist | unchecked | keep user edits | verify items consistent | unchecked |

### 7.3 Detect visual changes

Scan the changed file paths for platform-specific UI markers (Android/Compose, Compose Multiplatform, Web, iOS/SwiftUI). If any match, include the "Screenshots / demo" section and prompt the user for attachments in `--draft` and `--promote` modes; `--refresh` preserves existing Screenshots content verbatim.

See [`references/visual-change-patterns.md`](references/visual-change-patterns.md) for the full glob patterns per platform.

### 7.4 Preserve user edits on refresh/promote

When `--refresh` or `--promote` runs and `PR_BODY` is non-empty:

1. Detect manual-edit markers — any content between `<!-- user-edit-start -->` and `<!-- user-edit-end -->` is preserved verbatim
2. Content in Screenshots / demo section preserved verbatim (users paste images there)
3. Checklist items that are **checked** are preserved as checked — assume the user or reviewer ticked them

Everything else is regenerated from artifacts + git state.

**Edge case: empty or missing `PR_BODY`.** If `PR_BODY` is empty (e.g., freshly created draft with no body), skip the preserve-step entirely and generate the body from scratch. Do not fail — the preserve-step is an enhancement, not a precondition.

---

## Step 8: Generate title

Title generation is mode-aware:

- **`--draft`** — derive from branch name + first commit message; prefix optional `[WIP] ` **only** if the user explicitly asks (draft state itself conveys WIP)
- **`--refresh`** — keep existing title unchanged
- **`--promote`** — keep existing title; if user asks for a new title, use the task description or spec
- **default** — derive from branch + most meaningful commit

Rules (apply on mode creating or changing title):
- Strip prefixes: `feature/`, `fix/`, `chore/`, `refactor/`, `docs/`
- Convert `kebab-case` to sentence case
- Keep under 70 characters
- Do not add "WIP:" or "Draft:" — draft state conveys this

---

## Step 9: Execute per mode

### 9a. Mode `--draft`

If no PR exists:

```bash
# GitHub
gh pr create --draft \
  --title "<title>" \
  --body "<body>" \
  --base "$BASE" \
  --label "<label>" ...
# Labels optional; no reviewers for draft

# GitLab
glab mr create --draft \
  --title "<title>" \
  --description "<body>" \
  --target-branch "$BASE"
```

If draft already exists → edit body:

```bash
gh pr edit --body "<body>"
glab mr update --description "<body>"
```

Output:
> Draft PR created: `<url>`

### 9b. Mode `--refresh`

```bash
# GitHub
gh pr edit --body "<new-body>"
# GitLab
glab mr update --description "<new-body>"
```

Labels, reviewers, title are **not** touched.

Output:
> PR body refreshed: `<url>`

### 9c. Mode `--promote`

Two sequential operations:

```bash
# 1. Refresh body with final summary
gh pr edit --body "<final-body>"      # or glab mr update --description

# 2. Mark ready
gh pr ready                           # GitHub
# GitLab: --ready on current glab (≥1.32); older glab used --unwip.
# Try --ready first; fall back to --unwip ONLY when stderr shows that
# --ready itself is an unknown flag. Any other error is real — surface it.
GLAB_ERR=$(mktemp)
trap 'rm -f "$GLAB_ERR"' EXIT
if ! glab mr update --ready 2>"$GLAB_ERR"; then
  if grep -qE 'unknown flag:? --ready|flag provided but not defined: -?ready' "$GLAB_ERR"; then
    glab mr update --unwip
  else
    cat "$GLAB_ERR" >&2
    exit 1
  fi
fi
```

Output:
> PR promoted to ready for review: `<url>`

### 9d. Default mode

Same as current behaviour: ask draft-or-ready if not inferable from conversation, then create with full body + labels + reviewers.

Output differs by status (see "Output templates" below).

---

## Output templates

**Draft (`--draft` or default → draft):**
> Draft PR created: `<url>`
> Next: complete implementation → `/finalize` → `/acceptance` → `/create-pr --promote` to mark ready.

**Refreshed (`--refresh`):**
> PR body refreshed: `<url>`

**Promoted (`--promote`):**
> PR promoted to ready for review: `<url>`
> Next: invoke `/drive-to-merge` (or `/drive-to-merge --auto`) to autonomously monitor CI, handle review comments, and drive the PR to merge.

**Default ready:**
> PR created: `<url>`
> Next: invoke `/drive-to-merge` to autonomously monitor CI, handle review comments, and drive the PR to merge.

---

## Lifecycle integration (informational)

Orchestrators (`feature-flow`, `bugfix-flow`) invoke this skill at these milestones:

```
implement first pass → push → /create-pr --draft
finalize (runs after implement, before acceptance — multi-round code-quality loop)
acceptance
all local checks PASS → /create-pr --promote
```

Both orchestrators (`feature-flow`, `bugfix-flow`) call `/create-pr --draft` after `implement` and `/create-pr --promote` after `acceptance` passes. Mid-flow `--refresh` calls (e.g., after each finalize round, after fix loops) are not currently wired in — user or orchestrator can invoke `/create-pr --refresh` manually if the PR body should reflect intermediate progress.

The orchestrator owns deciding *when* to invoke; this skill owns *how*.

---

## Scope rules

- **In scope:** PR create/edit/ready status transitions; body composition; labels and reviewers on create/promote; title generation on create.
- **Out of scope:** editing code, running tests, running `/check`, managing commits (caller pushes beforehand), merging.
- **Do not** force-push or rewrite history here. If push fails — report and let caller resolve.
- **Do not** remove labels or reviewers set by humans. Only add missing ones on `--promote` if the pipeline determined additional reviewers.
- **Do not** strip manually-added content when refreshing — respect `<!-- user-edit-start/end -->` markers and Screenshots section.

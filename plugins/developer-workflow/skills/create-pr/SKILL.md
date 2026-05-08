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
  "mark PR ready for review", "update the PR", "switch the PR to ready".
---

# Create PR

Manage a pull request (GitHub) or merge request (GitLab) across its lifecycle — draft creation, in-flight body refreshes, and final promotion to ready for review. Composes description dynamically from available artifacts.

---

## Modes overview

| Mode | When | What it does | Fails if |
|---|---|---|---|
| `--draft` | After the first commit on a feature branch | Creates draft PR if none exists; refreshes body if a draft already exists | PR exists and is already ready for review |
| `--refresh` | After meaningful progress (finalize round complete, acceptance passed) | Updates body of existing PR (draft or ready) — no status change | No PR exists |
| `--promote` | After all local quality passes (finalize + acceptance) | Refreshes body with final summary, then marks draft PR as ready for review | No PR exists, or PR is already ready |
| default | Direct invocation | Asks draft-or-ready if unclear, then creates | PR already exists |

Mode is passed via arguments: `/create-pr --draft`, `/create-pr --refresh`, `/create-pr --promote`, or `/create-pr` for default.

---

## Step 1: Setup (all modes)

```bash
git remote get-url origin                                        # github.com → gh; gitlab → glab
BASE=$(git remote show origin 2>/dev/null | grep "HEAD branch" | awk '{print $NF}')
# Fallback order: main → master → develop
BRANCH=$(git branch --show-current)
CURRENT_EMAIL=$(git config user.email)
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
stderr. Do not proceed as if no PR exists — that would create a duplicate. Typical causes:
`gh` / `glab` not installed or not authenticated, API outage, missing token in sandbox.

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
git rev-parse --abbrev-ref @{u} 2>/dev/null || git push -u origin "$BRANCH"
git push   # no-op if in sync; common for --refresh / --promote
```

If push fails (non-fast-forward) — abort and ask the user. Force-push policy per globals.

---

## Step 4: Analyse branch state (all modes — needed for body)

Run in parallel: `git log $BASE..HEAD --oneline`, `git diff --name-only $BASE...HEAD`, `git diff $BASE...HEAD --stat`, `git diff $BASE...HEAD`.

---

## Step 5: Discover pipeline artifacts

Look for artifacts in `./swarm-report/` that match the current branch/task slug. Read those that exist:

| Artifact | Location | Purpose in body |
|---|---|---|
| research | `swarm-report/<slug>-research.md` | Link + 1-sentence abstract in "Context" section |
| spec | `docs/specs/<YYYY-MM-DD>-<slug>.md` (written by `write-spec`) | Reference as "Specification" |
| plan | `swarm-report/<slug>-plan.md` | Reference as "Plan"; acceptance criteria extracted for "How to test" |
| debug | `swarm-report/<slug>-debug.md` | Root cause + reproduction steps — primary context for bug-fix PRs |
| test plan | `swarm-report/<slug>-test-plan.md` | Reference; test cases become checklist in "How to test" |
| quality | `swarm-report/<slug>-quality.md` | Gate pass/fail summary for status table |
| finalize | `swarm-report/<slug>-finalize.md` | Round-by-round summary for status table |
| acceptance | `swarm-report/<slug>-acceptance.md` | Pass/fail + verified scenarios for "Verification" section |

Slug resolution:
1. Prefer slug if the caller passed it as an argument.
2. Fallback to branch name with common prefix stripped: `feature/`, `fix/`, `hotfix/`, `bug/`, `chore/`, `refactor/`, `docs/`.

Artifacts are gitignored — include them as **references** in the body (e.g., "See `swarm-report/my-slug-plan.md`"), never inline content.

---

## Step 6: Labels and reviewers (skip for `--refresh`)

Only set labels/reviewers when **creating** (draft or default) or when **promoting**. `--refresh` does NOT touch labels/reviewers to avoid clobbering user edits.

### 6.1 Labels

Fetch available labels:

- **GitHub:** `gh label list --json name,description --limit 100`
- **GitLab:** `glab label list` (resolves project from `git remote get-url origin`; do NOT use `glab api /projects/:fullpath/labels` — glab does not substitute `:fullpath` and the call will 404)

Select from existing only, based on changed file paths, commit types, and scope. Do not invent labels.

**Add, don't replace.** Only **add** missing labels computed from the diff; never remove labels set manually by humans. This preserves reviewer / triage / release labels applied between draft creation and promote.

### 6.2 Reviewers

Skip reviewer assignment for `--draft` and `--promote`. Reviewers go on only in default mode or when explicitly requested.

For default mode: top 3 authors who touched the changed files recently, filtered to exclude `$CURRENT_EMAIL`, mapped to platform usernames, presented to the user before adding.

---

## Step 7: Compose body

Body composition is mode-aware.

### 7.1 Section bank

The body is composed from a catalog of optional sections: What changed, Why / motivation, Artifacts, How to test, **Release Notes** (when user-visible changes are detected), Status, Screenshots / demo, Checklist, and a trailing Claude Code footer. Include only the sections that apply for the current mode and available artifacts.

See [`references/body-sections.md`](references/body-sections.md) for the full section-bank templates with example content and status-table formatting.

### 7.2 Section selection per mode

| Section | `--draft` | `--refresh` | `--promote` | default |
|---|---|---|---|---|
| What changed | short (plan/task-based, code may be incomplete) | updated from current diff | final, full | full |
| Why / motivation | ✅ | ✅ | ✅ | ✅ |
| Artifacts | ✅ (as they appear) | ✅ (keeps current) | ✅ | ✅ if exist |
| How to test | from plan if exists | from test-plan if exists | full | ✅ |
| Release Notes | placeholder + open question if user-facing | refresh from spec/test-plan if user-visible signals | final entry per detected changelog format | ✅ when user-visible |
| Status | "Implement: in progress" | updated from latest artifacts | all PASS | optional |
| Screenshots | placeholder + prompt user | keep as-is | verify filled | prompt |
| Checklist | unchecked | keep user edits | verify items consistent | unchecked |

### 7.2.1 Release Notes section (user-visible changes)

Captures what users of the plugin / library / app will see, ready to paste into the project's changelog at release time. Emit when any signal is true:

- Spec/clarify/plan frontmatter declares `user-facing: true`, `prod-bound: true`, `breaking: true`, or a `release_notes:` block (optional add-ons; not part of the canonical `write-spec` template).
- Diff touches a public API surface (`/api/`, public functions, exported types in barrel files, plugin manifests, marketplace metadata) — default auto-detection.
- User passed `--release-notes "..."` (always wins).

Format is detected by file presence in the repo:

| Repo file | Format used in PR body |
|---|---|
| `CHANGELOG.md` | Keep-a-Changelog bullet, classified `Added` / `Changed` / `Fixed` / `Deprecated` / `Removed` / `Security`. Breaking flagged with leading `**Breaking:**` |
| `.changeset/` directory | PR-body shorthand: `type: patch \| minor \| major` + one-line summary. **PR-body representation only, not a valid `.changeset/` entry**; actual file is created at release time per the [Changesets format](https://github.com/changesets/changesets/blob/main/docs/intro-to-using-changesets.md). |
| `RELEASE_NOTES.md` / `docs/CHANGELOG.md` | Same Keep-a-Changelog format as `CHANGELOG.md` |
| None | Plain bullet list under `## Release Notes` |

Text only — `create-pr` does NOT modify changelog files. `--skip-release-notes` opts out (`Release notes: skipped (<reason>)`). The PR receipt records `release_notes: emitted | skipped: <reason> | not-applicable`.

### 7.3 Detect visual changes

Scan changed file paths for platform-specific UI markers (Android/Compose, Compose Multiplatform, Web, iOS/SwiftUI). If any match, include the "Screenshots / demo" section and prompt the user for attachments in `--draft` and `--promote`; `--refresh` preserves existing Screenshots content verbatim.

See [`references/visual-change-patterns.md`](references/visual-change-patterns.md) for the full glob patterns per platform.

### 7.4 Preserve user edits on refresh/promote

When `--refresh` or `--promote` runs and `PR_BODY` is non-empty:

1. Detect manual-edit markers — content between `<!-- user-edit-start -->` and `<!-- user-edit-end -->` is preserved verbatim.
2. Content in Screenshots / demo section preserved verbatim (users paste images there).
3. Checklist items that are **checked** are preserved as checked.

Everything else is regenerated from artifacts + git state.

**Edge case: empty `PR_BODY`** — skip the preserve-step entirely and generate from scratch. Do not fail.

---

## Step 8: Generate title

Mode-aware:

- **`--draft`** — derive from branch + first commit message
- **`--refresh`** — keep existing title unchanged
- **`--promote`** — keep existing title unless user asks otherwise (then use task description or spec)
- **default** — derive from branch + most meaningful commit

Rules when creating/changing the title: strip `feature/` `fix/` `chore/` `refactor/` `docs/` prefixes, convert kebab-case to sentence case, keep under 70 chars, never add "WIP:" or "Draft:" (draft status conveys it).

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

Ask draft-or-ready if not inferable from conversation, then create with full body + labels + reviewers.

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

## Scope rules

- **In scope:** PR create/edit/ready status transitions; body composition; labels and reviewers on create/promote; title generation on create.
- **Out of scope:** editing code, running tests, running `/check`, managing commits (caller pushes beforehand), merging.
- **Do not** force-push or rewrite history. If push fails — report and let caller resolve.
- **Do not** remove labels or reviewers set by humans. Only add missing ones on `--promote`.
- **Do not** strip manually-added content when refreshing — respect `<!-- user-edit-start/end -->` markers and Screenshots section.

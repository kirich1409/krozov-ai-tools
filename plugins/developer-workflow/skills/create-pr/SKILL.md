---
name: create-pr
description: >
  Use when creating a new pull request (GitHub) or merge request (GitLab) for the current branch.
  Handles branch push, draft/ready decision, title and description generation, label selection,
  reviewer suggestions from git history, and PR creation.
  Invoke whenever the user says "create a PR", "open a PR", "make a PR", "create a draft PR",
  "submit for review", "push a PR", "open an MR", or any variation — draft or not.
  Also invoke proactively after prepare-for-pr completes if no PR exists yet.
---

# Create PR

Creates a pull request (GitHub) or merge request (GitLab) for the current branch,
with a rich description, appropriate labels, and reviewers derived from git history.

---

## Step 1: Setup

```bash
# Platform: check remote URL
git remote get-url origin
# Contains github.com → use gh; contains gitlab → use glab

# Base branch
BASE=$(git remote show origin 2>/dev/null | grep "HEAD branch" | awk '{print $NF}')
# Fallback order: main → master → develop

# Current branch and author
BRANCH=$(git branch --show-current)
CURRENT_EMAIL=$(git config user.email)
CURRENT_NAME=$(git config user.name)
```

**Check if a PR already exists** for this branch — if so, show its URL and stop:

```bash
gh pr view --json url,isDraft 2>/dev/null   # GitHub
glab mr view 2>/dev/null                    # GitLab
```

---

## Step 2: Push branch if needed

```bash
git rev-parse --abbrev-ref @{u} 2>/dev/null || git push -u origin "$BRANCH"
```

---

## Step 3: Draft decision

Look for a clear signal in the current conversation:

| Signal | Decision |
|--------|----------|
| User said "draft", "WIP", "work in progress" | **Draft** |
| User said "ready for review", "not draft", "final", "ready" | **Not draft** |
| Invoked right after `prepare-for-pr` completed cleanly | Lean **not draft** — confirm |
| No clear signal | **Ask the user** |

If unclear, ask exactly this — one question, nothing else:

> Draft PR or ready for review?

Wait for the answer before continuing.

---

## Step 4: Analyse the branch

Run these in parallel to gather all the material needed for labels, reviewers, and description:

```bash
# 1. Commits on this branch
git log $BASE..HEAD --oneline

# 2. Changed files
git diff --name-only $BASE...HEAD

# 3. Full diff stat
git diff $BASE...HEAD --stat

# 4. Full diff (for understanding what changed)
git diff $BASE...HEAD
```

---

## Step 5: Labels

Fetch all labels that exist in the remote repo:

```bash
# GitHub
gh label list --json name,description --limit 100

# GitLab
glab api /projects/:fullpath/labels --jq '[.[] | {name, description}]'
```

Read the available labels and select the ones that fit the changes. Base the decision on:
- Changed file paths (e.g. `src/ui/` → ui label, `src/test/` → testing label)
- Commit message types (`feat` → enhancement/feature, `fix` → bug, `docs` → documentation)
- Scope of impact (e.g. `breaking-change` if public API is modified)

Do not invent labels — only pick from what exists. If nothing clearly fits, apply no labels.

---

## Step 6: Reviewers

Find the people most familiar with the changed code by looking at who has touched those files recently:

```bash
# For each changed file, collect recent commit authors (last 20 commits per file)
git diff --name-only $BASE...HEAD | while read file; do
  git log --follow -n 20 --format="%ae %an" -- "$file" 2>/dev/null
done | sort | uniq -c | sort -rn
```

Filter out the current author (`$CURRENT_EMAIL`). Take the top 3 candidates by commit count.

**Map emails to platform usernames:**

```bash
# GitHub — search by email
gh api "/search/users?q=EMAIL+in:email" --jq '.items[0].login' 2>/dev/null

# GitHub — fallback: look up recent commits on the repo by name
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh api /repos/$REPO/commits --jq '.[].author.login' 2>/dev/null | sort | uniq

# GitLab — search by email or name
glab api "/users?search=EMAIL" --jq '.[0].username' 2>/dev/null
```

Present the suggested reviewers to the user before adding them — don't add silently.
The user may accept, change, or skip.

---

## Step 7: Generate title and description

**Title:**
- Derive from branch name + most meaningful commit message
- Strip prefixes: `feat/`, `fix/`, `chore/`, `refactor/`, `docs/`
- Convert `kebab-case` to sentence case
- Keep under 70 characters
- Do not add "WIP:" or "Draft:" — the draft state on the PR conveys this

**Detect visual changes** — look at changed file paths for any of:
- Android/Compose: `*Screen.kt`, `*Composable.kt`, `res/layout/`, `res/drawable/`
- Compose Multiplatform: same Kotlin patterns, plus `commonMain` UI directories
- Web: `*.tsx`, `*.jsx`, `*.css`, `*.scss`, `*.html`
- iOS: `*.swift` (SwiftUI), `*.xib`, `*.storyboard`

If visual changes are detected, the description must include a Screenshots / Demo section (see template below). Prompt the user to provide screenshots or a screen recording if they haven't already — a PR with visual changes but no visuals is hard to review.

**Description template — ready-for-review PR:**

```markdown
## What changed
<!-- Concise technical description of the changes: what was added, removed, or modified -->

## Why / motivation
<!-- Context: the requirement, issue, or problem this solves. Link to ticket if applicable -->

## How to test
<!-- Step-by-step instructions for a reviewer to verify the change works as intended -->
- [ ] Step 1
- [ ] Step 2

## Checklist
- [ ] Tests added or updated
- [ ] No breaking changes (or breaking changes are documented in this PR)
- [ ] Relevant documentation updated

## Screenshots / demo
<!-- For visual changes: before/after screenshots or a short screen recording.
     Delete this section if there are no visual changes. -->

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Fill every section from the diff and commit log — no placeholder comments left in the final text. The description must be self-contained: a reviewer who has no context about the task should be able to understand what changed, why, and how to verify it.

**Description template — draft PR (early, work in progress):**

```markdown
## What this PR is about
<!-- Brief statement of intent — even one line is fine -->

## Status
<!-- What's done, what's still in progress -->

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

A draft description can be minimal. It will be updated when the PR is marked ready.

---

## Step 8: Create

```bash
# GitHub — draft
gh pr create --draft \
  --title "<title>" \
  --body "<body>" \
  --base "$BASE" \
  --label "<label1>" --label "<label2>" \
  --reviewer "<username1>" --reviewer "<username2>"

# GitHub — ready for review
gh pr create \
  --title "<title>" \
  --body "<body>" \
  --base "$BASE" \
  --label "<label1>" --label "<label2>" \
  --reviewer "<username1>" --reviewer "<username2>"

# GitLab — draft
glab mr create --draft \
  --title "<title>" \
  --description "<body>" \
  --target-branch "$BASE" \
  --label "<label1>,<label2>" \
  --reviewer "<username1>"

# GitLab — ready for review
glab mr create \
  --title "<title>" \
  --description "<body>" \
  --target-branch "$BASE" \
  --label "<label1>,<label2>" \
  --reviewer "<username1>"
```

Omit `--label` and `--reviewer` flags entirely if there are no applicable labels or reviewers — don't pass empty values.

---

## Output

Print the PR/MR URL immediately after creation.

**Draft PR:**
> Draft PR created: \<url\>
> When implementation is complete, run `prepare-for-pr` to quality-check the branch, then mark it ready for review.

**Ready-for-review PR:**
> PR created: \<url\>
> Run `pr-drive-to-merge` to monitor CI/CD and handle review.

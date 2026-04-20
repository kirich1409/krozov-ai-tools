# drive-to-merge — Phase 1 Setup

Platform detection, metadata fetch, preconditions, and state file schema. Loaded on demand by SKILL.md.

## 1.1 Detect platform

Extract hostname from the remote URL and probe the matching CLI — do not regex for `github.com` / `gitlab` literals, which miss GitHub Enterprise Server and self-hosted GitLab.

```bash
REMOTE_URL=$(git remote get-url origin)
HOST=$(echo "$REMOTE_URL" | sed -E 's#^(https?://|git@)([^/:]+)[/:].*#\2#')

if gh auth status --hostname "$HOST" >/dev/null 2>&1; then
  PLATFORM=github
elif glab auth status --hostname "$HOST" >/dev/null 2>&1 || glab config get --global gitlab_uri 2>/dev/null | grep -q "$HOST"; then
  PLATFORM=gitlab
else
  echo "Unknown host $HOST — authenticate gh or glab against it and rerun." >&2
  exit 1
fi
```

## 1.2 Fetch PR/MR metadata

```bash
# GitHub
PR_INFO=$(gh pr view --json id,number,baseRefName,headRefName,title,body,isDraft,state,url,\
statusCheckRollup,reviewDecision,mergeable,mergeStateStatus,labels,closingIssuesReferences)
PR_NUMBER=$(jq -r .number <<<"$PR_INFO")
PR_URL=$(jq -r .url <<<"$PR_INFO")
IS_DRAFT=$(jq -r .isDraft <<<"$PR_INFO")
BASE=$(jq -r .baseRefName <<<"$PR_INFO")
HEAD=$(jq -r .headRefName <<<"$PR_INFO")
PR_NODE_ID=$(jq -r .id <<<"$PR_INFO")     # graphql node id from the same call — no extra round-trip
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
OWNER=${REPO%/*}; REPO_NAME=${REPO#*/}

# Repository node id — needed for thread-ownership re-verify before every POST.
REPO_NODE_ID=$(gh api graphql -f query='query($o:String!,$n:String!){repository(owner:$o,name:$n){id}}' \
  -F o="$OWNER" -F n="$REPO_NAME" --jq '.data.repository.id')
# COPILOT_NODE_ID is resolved lazily in Phase 3.6 and cached in the state file header.

# GitLab
MR_INFO=$(glab mr view --output json)
MR_IID=$(jq -r .iid <<<"$MR_INFO")
MR_URL=$(jq -r .web_url <<<"$MR_INFO")
IS_DRAFT=$(jq -r '.title | startswith("Draft:")' <<<"$MR_INFO")
BASE=$(jq -r .target_branch <<<"$MR_INFO")
PROJECT=$(glab repo view --output json | jq -r '.path_with_namespace | @uri')
```

If the PR/MR is already merged or closed — stop and report the final state.

## 1.3 Preconditions

Abort with a clear message if any of these fail:

- Current branch matches the PR head branch. If not — abort with `checkout <head> first; this skill does not auto-switch branches`.
- Local branch is fetched and not behind the remote head (`git fetch origin && git status -sb`).
- `gh auth status` / `glab auth status` — token valid.
- The base branch still exists on the remote.

## 1.4 State file

`swarm-report/<slug>-drive-state.md`. Slug = `<branch-with-prefix-stripped>-pr<PR_NUMBER>` (e.g. `fix/login` on PR 42 → `login-pr42`). The PR number disambiguates parallel branches that would otherwise produce the same slug (e.g. `feature/login` and `fix/login`, or two re-openings of the same branch).

Verify `swarm-report/` is gitignored by running `git check-ignore -q swarm-report/`; exit 0 = ignored, non-zero = not ignored. On non-zero — abort with `swarm-report/ is not ignored by git; add swarm-report/ to .gitignore and rerun`. Do not auto-modify `.gitignore`: that creates an unrelated diff inside a PR-driving loop and surprises the user.

### Schema (markdown, machine-parseable on resume)

```markdown
# Drive to Merge — <PR title>

URL: <PR URL>
Platform: github | gitlab
Mode: default | auto | dry-run
Principal: <@actor>            # gh api user --jq .login
Repository node id: <graphql node id of the repository>
PR node id: <graphql node id of the pull request>
Copilot node id: <graphql node id of copilot-pull-request-reviewer or `unavailable`>
Started: <ISO8601>
Status: running | waiting-for-user | merged | blocked

## Rounds
| # | Started | Trigger | CI | New comments | Actions | Outcome |
|---|---------|---------|----|--------------|---------|---------|

## Commitments (open threads this skill owns)
| thread_id | category | delegated_to | fix_commit_sha | replied | resolved |
|-----------|----------|--------------|----------------|---------|----------|

`fix_commit_sha` holds the abbreviated sha of the commit that addressed the thread (empty string if the thread is dismiss-only, no code change).

## Blockers raised
<empty | list of items the skill surfaced to the user>
```

On every resume (new session after context compaction) — re-read this file first; do not re-run analysis that already lives in a "Commitments" row unless the reviewer posted new activity.

### Mode precedence on resume

The state file `Mode` is the authoritative source. A fresh invocation without a flag inherits the stored mode; a fresh invocation with an explicit flag **overrides** the stored mode and rewrites it. This lets the user downgrade an `auto` run to `default` by re-invoking the skill, but does not silently demote an autonomous run just because the wake-up prompt was edited.

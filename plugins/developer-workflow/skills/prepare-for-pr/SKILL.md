---
name: prepare-for-pr
description: Use when implementation is complete and the branch needs to be quality-checked before creating a PR — runs build, simplify, self-review, and lint/tests in a loop until only minor or no issues remain.
---

# Prepare for PR

## Overview

Runs a quality loop over the current branch changes until the code is clean enough to expose in a PR.

**Core principle:** Fix only what belongs to current changes. Out-of-scope issues with an obvious fix can be handled autonomously; otherwise ask the user.

## Setup

Before the loop, establish the diff base and build tooling:

```bash
# Determine base branch
BASE=$(git remote show origin 2>/dev/null | grep "HEAD branch" | awk '{print $NF}')
# Fallback: try main → master → develop

# Current changes boundary (use throughout for scope decisions)
git diff $BASE...HEAD
```

**Build system detection — use highest-priority match when multiple files present:**

| Priority | File present | Build | Lint | Test |
|----------|---|---|---|---|
| 1 | `Makefile` (with build/lint/test targets) | `make build` | `make lint` | `make test` |
| 2 | `package.json` | `npm run build` | `npm run lint` | `npm test` |
| 3 | `Cargo.toml` | `cargo build` | `cargo clippy` | `cargo test` |
| 4 | `build.gradle(.kts)` | `./gradlew build` | `./gradlew lint` | `./gradlew test` |
| 5 | `pom.xml` | `mvn package -q` | `mvn checkstyle:check` | `mvn test` |
| 6 | `go.mod` | `go build ./...` | `golangci-lint run` | `go test ./...` |
| 7 | `pyproject.toml` / `setup.py` | `pip install -e .` | `ruff check .` | `pytest` |

**Monorepo / subdirectory projects:** if all changed files are under a single subdirectory that has its own build file, prefer that subdirectory's build system over the root. Example: all changes under `plugins/maven-mcp/` which has its own `package.json` → run `npm` commands from that subdirectory, not a root `Makefile`.

## Quality Loop

**Track all issues found and their status (open / fixed / deferred) across iterations.** On re-entry, only report NEW issues. Deferred issues are removed from the fix queue — never re-prompted.

**Stage and commit fixes as you make them** during the loop, grouping related changes together (use specific file paths, not `git add .`). This allows logical commit grouping without having to reconstruct it at the end.

**Simplify runs only on the first iteration.** Self-review and lint/tests run every iteration.

```dot
digraph prepare_for_pr {
    rankdir=TB;

    start [label="Implementation complete", shape=doublecircle];
    setup [label="Detect base branch + build system", shape=box];
    build [label="Build", shape=box];
    build_pass [label="Passes?", shape=diamond];
    scope_build [label="Scope decision\n(see below)", shape=box];
    simplify [label="Simplify (skill: simplify)\n[1st iteration only — skip if unavailable]", shape=box];
    selfrev [label="Self-review: git diff $BASE...HEAD\nCheck logic, security, edge cases", shape=box];
    lint [label="Lint + Tests", shape=box];
    new_issues [label="New non-minor issues?", shape=diamond];
    scope_issues [label="Scope decision\n(see below)", shape=box];
    assess [label="Any non-deferred\nnon-minor issues?", shape=diamond];
    fix [label="Fix + stage changes", shape=box];
    commit [label="Commit staged fixes\n(logical groups)", shape=box];
    done [label="Quality loop complete", shape=doublecircle];

    start -> setup -> build;
    build -> build_pass;
    build_pass -> simplify [label="yes"];
    build_pass -> scope_build [label="no"];
    scope_build -> fix [label="fix decided\n(in scope OR obvious fix)"];
    scope_build -> done [label="user exits"];
    fix -> build;
    simplify -> selfrev -> lint;
    lint -> new_issues;
    new_issues -> scope_issues [label="yes"];
    new_issues -> assess [label="no"];
    scope_issues -> fix [label="fix decided\n(in scope OR obvious fix)"];
    scope_issues -> assess [label="user defers\n(mark deferred, continue)"];
    assess -> fix [label="yes — non-deferred\nnon-minor remain"];
    assess -> commit [label="no"];
    commit -> done;
}
```

## Scope Decision

```dot
digraph scope {
    rankdir=LR;

    check [label="In current changes\n(git diff $BASE...HEAD)?", shape=diamond];
    obvious [label="Fix is obvious?", shape=diamond];
    auto [label="Fix autonomously", shape=box];
    ask [label="Ask user\n(issue + reason + options)", shape=box];
    user_fix [label="User: fix here", shape=box];
    user_defer [label="User: defer/skip\n(mark deferred)", shape=box];

    check -> auto [label="yes"];
    check -> obvious [label="no"];
    obvious -> auto [label="yes"];
    obvious -> ask [label="no"];
    ask -> user_fix -> auto;
    ask -> user_defer;
}
```

**In scope — fix autonomously:** bugs introduced by current changes, tests broken by current changes, lint errors in changed files, logic/security errors in current implementation.

**Out of scope, obvious fix:** missing import clearly needed by new code, typo in a newly added string, test fixture update required by a changed function signature.

**Out of scope, ask user:** pre-existing failures in untouched files, build errors from unrelated dependency changes, failures in files not touched by this branch. When asking, include: what the issue is, why it appears unrelated, and options (fix here / skip / open separate issue). Pause until user responds.

## Self-Review Criteria

Run `git diff $BASE...HEAD` and check for:
- Logic errors or off-by-one mistakes
- Missing error handling for new code paths
- Security issues (exposed secrets, injection risks, missing validation)
- Missing or insufficient tests for new behavior
- Dead code or unreachable branches introduced

## What "Minor" Means

**Minor (exit loop):** style preferences, optional naming improvements, cosmetic suggestions with no correctness impact.

**Non-minor (keep looping):** bugs, broken tests, lint errors, security issues, incorrect logic, missing required tests.

## Output

```markdown
## Quality Loop Result

| Step | Issues found | Fixed | Deferred |
|------|-------------|-------|---------|
| Build | ... | ... | ... |
| Simplify | ... | ... | — |
| Self-review | ... | ... | ... |
| Lint + Tests | ... | ... | ... |

**Quality loop complete.** [If deferred items exist: X items deferred — see above.]
```

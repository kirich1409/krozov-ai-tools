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
git remote show origin | grep "HEAD branch" | awk '{print $NF}'
# Fallback: try main → master → develop

# Current changes boundary (use throughout for scope decisions)
git diff <base>...HEAD
```

**Build system detection:**

| File present | Build | Lint | Test |
|---|---|---|---|
| `package.json` | `npm run build` | `npm run lint` | `npm test` |
| `Cargo.toml` | `cargo build` | `cargo clippy` | `cargo test` |
| `build.gradle(.kts)` | `./gradlew build` | `./gradlew lint` | `./gradlew test` |
| `pom.xml` | `mvn package -q` | `mvn checkstyle:check` | `mvn test` |
| `go.mod` | `go build ./...` | `golangci-lint run` | `go test ./...` |
| `Makefile` | `make build` | `make lint` | `make test` |

## Quality Loop

**Track all issues found across iterations.** On re-entry to any step, only report and fix issues not seen in a previous iteration. Mark issues as resolved when fixed — never re-report them.

**Simplify runs only on the first iteration** (or after a significant rewrite). Self-review and lint/tests run every iteration.

```dot
digraph prepare_for_pr {
    rankdir=TB;

    start [label="Implementation complete", shape=doublecircle];
    setup [label="Detect base branch + build system", shape=box];
    build [label="Build", shape=box];
    build_pass [label="Passes?", shape=diamond];
    scope_build [label="Scope decision\n(see below)", shape=box];
    simplify [label="Simplify\n(skill: simplify)\n[1st iteration only]", shape=box];
    selfrev [label="Self-review\ngit diff <base>...HEAD", shape=box];
    lint [label="Lint + Tests", shape=box];
    new_issues [label="New non-minor issues?", shape=diamond];
    scope_issues [label="Scope decision\n(see below)", shape=box];
    assess [label="Only minor\nor no issues?", shape=diamond];
    fix [label="Fix", shape=box];
    commit [label="Commit fixes\n(logical groups)", shape=box];
    done [label="Code ready for PR", shape=doublecircle];

    start -> setup -> build;
    build -> build_pass;
    build_pass -> simplify [label="yes"];
    build_pass -> scope_build [label="no"];
    scope_build -> fix [label="fix decided"];
    scope_build -> done [label="user exits"];
    fix -> build;
    simplify -> selfrev -> lint;
    lint -> new_issues;
    new_issues -> scope_issues [label="yes"];
    new_issues -> assess [label="no"];
    scope_issues -> fix [label="fix decided"];
    scope_issues -> assess [label="user defers"];
    assess -> fix [label="non-minor remain"];
    assess -> commit [label="only minor or none"];
    commit -> done;
}
```

## Scope Decision

```dot
digraph scope {
    rankdir=LR;

    check [label="In current changes\n(git diff <base>...HEAD)?", shape=diamond];
    obvious [label="Fix is obvious?", shape=diamond];
    auto [label="Fix autonomously", shape=box];
    ask [label="Ask user", shape=box];

    check -> auto [label="yes"];
    check -> obvious [label="no"];
    obvious -> auto [label="yes"];
    obvious -> ask [label="no"];
}
```

**In scope — fix autonomously:** bugs introduced by current changes, tests broken by current changes, lint errors in files touched by this branch, logic/security errors in current implementation.

**Out of scope, obvious fix:** missing import clearly needed by new code, typo in a newly added string, test fixture update required by a changed function signature.

**Out of scope, ask user:** pre-existing failures in untouched files, build errors from unrelated dependency changes, architectural issues not caused by this branch.

When asking, include: what the issue is, why it appears unrelated, and options (fix here / skip / open separate issue). Pause until user responds.

## Self-Review Criteria

Run `git diff <base>...HEAD` and check for:
- Logic errors or off-by-one mistakes
- Missing error handling for new code paths
- Security issues (exposed secrets, injection risks, missing validation)
- Missing or insufficient tests for new behavior
- Dead code or unreachable branches introduced

## What "Minor" Means

**Minor (exit loop):** style preferences, optional naming improvements, cosmetic suggestions with no correctness impact.

**Non-minor (keep looping):** bugs, broken tests, lint errors, security issues, incorrect logic, missing required tests.

## Committing Fixes

After the loop exits, commit all fixes made during the loop:
- Group related fixes into logical commits
- Message format: `fix: <what was fixed>`
- Do not mix unrelated fixes into a single commit

## Output

```markdown
## Prepare for PR — Result

| Step | Issues found | Fixed | Deferred to user |
|------|-------------|-------|-----------------|
| Build | ... | ... | ... |
| Simplify | ... | ... | — |
| Self-review | ... | ... | ... |
| Lint + Tests | ... | ... | ... |

**Code is ready for PR.**
```

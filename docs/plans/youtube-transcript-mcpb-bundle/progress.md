# Progress: MCPB bundle — Stage 1 (build + CI)

Plan: `docs/plans/youtube-transcript-mcpb-bundle/plan.md`
Tasks: `docs/plans/youtube-transcript-mcpb-bundle/tasks.md`
Branch: `feature/youtube-transcript-mcpb-bundle`

Stage 2 (release wiring) is deferred to its own plan — see *Stage 2 handoff* in `plan.md`.

## Tasks

- [ ] T-1 — Bundle manifest template
- [ ] T-2 — Pinned toolchain, audit gate, update channel
- [ ] T-3 — Pack script (after T-1, T-2)
- [ ] T-4 — Smoke script (after T-3)
- [ ] T-4b — Negative tests for the fail-closed assertions (after T-4)
- [ ] T-5 — CI job (after T-4b)
- [ ] T-6 — Documentation (after T-5)

## Handoff notes

- Promoting `youtube-transcript-mcpb` to a **required status check** is a branch-ruleset change outside CI's reach — the maintainer does it after merge.
- L5 is mandatory and performable before merge: open the PR run's Artifacts, download the **zip container**, unzip, `shasum -a 256 -c` inside that directory, then drag the `.mcpb` into Claude Desktop. `upload-artifact` never delivers a bare file.
- No bundle reaches users in Stage 1 — nothing is attached to a Release yet, and `README.md` is intentionally untouched.

## Learned

(implementation notes, surprises, and decisions made while building — appended by the implementer)

- **Do not assert on `serverInfo.version`.** `protocol/dispatch.py:45-53` hardcodes `"version": "1"` and documents the decoupling from `SERVER_VERSION` as deliberate; verified live during planning. The skew check is a static grep of the packed `server.py`.
- **`git ls-files` pathspec.** `git ls-files 'plugins/youtube-transcript/plugin/server/**/*.py'` returns 23 of 25 — `server.py` and `composition.py` are dropped, because a pathspec without `:(glob)` magic needs `**/` to consume a segment. Verified in this repo during planning. Use `git ls-files -- <dir> | grep '\.py$'`.
- **`cp` dereferences symlinks.** Staging enumerates `git ls-files -s` and filters on mode for that reason — a tracked `*.py` symlink would otherwise ship foreign content and pass every name-based assertion. `LICENSE.md` goes through the same check; it is the one staged file outside the server tree.
- **Two shell traps, both verified by running them.** `find … \( ! -type f \)` matches every directory, so that form of the staging guard can never pass. And `! cmd | grep -q .` does **not** abort under `set -euo pipefail` — bash exempts `!`-inverted commands from `set -e`; a probe with a planted symlink ran to completion and exited 0. Guards are written as capture-and-test.
- **`npm audit --json` ignores `--audit-level`** (it changes only the exit code) and omits advisory ids on propagated records. The allowlist is generated from a real run, never transcribed — an earlier revision hardcoded an id that was the wrong advisory.
- **Why Stage 1 stops before `release.yml`.** Three review cycles each found a fresh critical defect in the release restructure, the last being the silent disappearance of the two `Run Python tests` steps. Root cause named by both reviewers: that path cannot be verified before a tag is pushed. Stage 2 builds it behind a `workflow_dispatch` dry-run so it becomes falsifiable first.

# Progress: MCPB bundle — Stage 1 (build + CI)

Plan: `docs/plans/youtube-transcript-mcpb-bundle/plan.md`
Tasks: `docs/plans/youtube-transcript-mcpb-bundle/tasks.md`
Branch: `feature/youtube-transcript-mcpb-bundle`

Stage 2 (release wiring) is deferred to its own plan — see *Stage 2 handoff* in `plan.md`.

## Tasks

- [x] T-1 — Bundle manifest template — `check` green; deep equality on `.server` verified ahead of T-4
- [x] T-2 — Pinned toolchain, audit gate, update channel — allowlist generated from a live run, not transcribed: the single `high` is `GHSA-ph9p-34f9-6g65` (`tmp` path traversal), with a reachability argument showing the CLI never imports the `editor` prompt that consumes it
- [x] T-3 — Pack script — 27 archive entries, version injected, bare-basename checksum verifies in a flat dir, and a planted symlink is rejected with `::error::non-regular entry staged`
- [x] T-4 — Smoke script — all 8 assertions green on a real bundle; each fails with a distinct `assertion N failed: …` message, which is the contract T-4b greps
- [x] T-4b — Negative tests — 9/9 cases rejected by their own assertion, exit 0. The `platform override` case is the one that proves deep equality earns its keep: a field-by-field check would have passed it
- [x] T-5 — CI job — returned `DONE_WITH_CONCERNS`, and the concern was a real defect in the audit-gate body **as written in the plan**: `grep -o 'GHSA-…' audit-allowlist.txt` exits 1 on an empty allowlist, and under `set -e` + `pipefail` that aborted the step before the diagnostic could name the offenders. Reproduced, then fixed with `|| true` on that line; re-verified that an emptied allowlist now fails *with* `::error::unallowlisted advisories: GHSA-ph9p-34f9-6g65`. The agent also caught that every deliverable was still untracked — a fresh CI checkout would have gone red — so all 11 files were staged.
- [x] T-6 — Documentation — §12 added after §11; the two plugin-file notes are byte-identical; §10 checklist deliberately untouched (its bundle item belongs to Stage 2)

## Handoff notes

- Promoting `youtube-transcript-mcpb` to a **required status check** is a branch-ruleset change outside CI's reach — the maintainer does it after merge.
- L5 is mandatory and performable before merge: open the PR run's Artifacts, download the **zip container**, unzip, `shasum -a 256 -c` inside that directory, then drag the `.mcpb` into Claude Desktop. `upload-artifact` never delivers a bare file.
- No bundle reaches users in Stage 1 — nothing is attached to a Release yet, and `README.md` is intentionally untouched.

## Whole-change verification (phase 4)

All declared levels green: L0 pack, L1a (`shellcheck`, `validate.sh` still green, audit gate), L2 (9/9 negatives), L3 (8/8 smoke assertions), plus the plugin's 276 Python tests and a full clean-room cycle (`npm ci` → pack → smoke → negatives from a wiped `dist/` and `node_modules/`).

**One defect found only at this level**, because it lives on the seam between two tasks rather than inside either: the CI job ordered `negatives` before `upload-artifact`, and negative case 9 re-invokes `pack-mcpb.sh`, whose step 4 clears `dist/youtube-transcript-*` before the symlink guard aborts it. Net effect — `dist/` empty at upload time, and `if-no-files-found: error` would have failed the job on **every** run. Reproduced locally, fixed by moving the upload step ahead of the negatives, then re-verified by simulating the job's step order.

L5 (installing the CI artifact into Claude Desktop) remains outstanding — it needs a human and is a separate pass before merge.

## Learned

(implementation notes, surprises, and decisions made while building — appended by the implementer)

- **Do not assert on `serverInfo.version`.** `protocol/dispatch.py:45-53` hardcodes `"version": "1"` and documents the decoupling from `SERVER_VERSION` as deliberate; verified live during planning. The skew check is a static grep of the packed `server.py`.
- **`git ls-files` pathspec.** `git ls-files 'plugins/youtube-transcript/plugin/server/**/*.py'` returns 23 of 25 — `server.py` and `composition.py` are dropped, because a pathspec without `:(glob)` magic needs `**/` to consume a segment. Verified in this repo during planning. Use `git ls-files -- <dir> | grep '\.py$'`.
- **`cp` dereferences symlinks.** Staging enumerates `git ls-files -s` and filters on mode for that reason — a tracked `*.py` symlink would otherwise ship foreign content and pass every name-based assertion. `LICENSE.md` goes through the same check; it is the one staged file outside the server tree.
- **Two shell traps, both verified by running them.** `find … \( ! -type f \)` matches every directory, so that form of the staging guard can never pass. And `! cmd | grep -q .` does **not** abort under `set -euo pipefail` — bash exempts `!`-inverted commands from `set -e`; a probe with a planted symlink ran to completion and exited 0. Guards are written as capture-and-test.
- **`npm audit --json` ignores `--audit-level`** (it changes only the exit code) and omits advisory ids on propagated records. The allowlist is generated from a real run, never transcribed — an earlier revision hardcoded an id that was the wrong advisory.
- **Why Stage 1 stops before `release.yml`.** Three review cycles each found a fresh critical defect in the release restructure, the last being the silent disappearance of the two `Run Python tests` steps. Root cause named by both reviewers: that path cannot be verified before a tag is pushed. Stage 2 builds it behind a `workflow_dispatch` dry-run so it becomes falsifiable first.

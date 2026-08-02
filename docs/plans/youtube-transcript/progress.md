# Progress: youtube-transcript MCP plugin (v1, stdio-only)

> Plan: ./plan.md · Tasks: ./tasks.md

## Status
- [x] T-1 — Package skeleton, pyproject.toml, test harness shim
- [x] T-2 — `domain/` complete
- [x] T-3 — Contracts freeze: session-scoped provider port, `net`/`formats` constants, AST import-boundary test
- [x] T-4 — `providers/video_ref.py`
- [x] T-5 — `formats/{text,srt,vtt}.py`
- [ ] T-6a — `net/client.py` policy: scheme/host allowlist, TLS, redirect handling
- [ ] T-6b — `net/client.py` resource controls: caps, deadline, retry, XML guard
- [ ] T-7 — `protocol/envelope.py` + `schemas.py`
- [ ] T-8 — `tools/cursor.py`
- [ ] T-9 — `tools/resolution.py`
- [ ] T-13a — `protocol/registry.py` + `dispatch.py`
- [ ] T-10 — `providers/innertube.py`
- [ ] T-11 — `tools/list_transcript_tracks.py`
- [ ] T-12 — `tools/get_transcript.py`
- [ ] T-13b — `composition.py` + `server.py`
- [ ] T-14 — Cross-cutting AC tests
- [ ] T-15 — Live canary
- [ ] T-16 — Plugin docs + final `validate.sh`/coverage pass
- [x] T-P1 — Versioning and repo-doc generalization
- [x] T-P2 — CI workflows
- [x] T-P3 — Network spike: allowlist confirmation, canary videos, size/latency/RSS measurement
- [x] T-P4 — Spec addendum: sync remaining plan/spec divergences

## Blocking / Human-owned items (not a task, tracked here so they aren't missed at merge time)
- [ ] Register the four new `youtube-transcript` CI jobs as required branch-protection status checks — repo-settings action, Human-owned, cannot be verified from the working tree by any agent. Blocks release (spec Prerequisites, plan.md Risks).
- [ ] T-P2: one manual `workflow_dispatch` run of `youtube-transcript-live-canary.yml`, exercising the cache-based consecutive-failure counter end-to-end, verified by a human before merge (T-P2's `check` in tasks.md; closes AC-25, contributes to AC-13). An agent cannot do this — it requires actually triggering a workflow run and watching real Actions-tab/cache behavior. Note: until T-15 lands, the canary's own test step (`unittest discover -p test_live_canary.py`) has no matching file and exits 5 ("NO TESTS RAN") by design (see the workflow's comments), so the counter will genuinely increment on a manual dispatch today — the human verifying this should expect that, not a real transcript-fetch failure.

## Learnings
<!-- Дописывать по строке на завершённую задачу: неожиданности, подводные камни, решения,
     принятые по ходу реализации. Это память, переживающая сброс контекста. -->
- T-1: package skeleton + pyproject.toml mirrored from maven-mcp; `[[tool.mypy.overrides]]`/`[tool.ruff.lint.per-file-ignores]` blocks intentionally omitted (empty placeholders would mirror maven-mcp findings that don't exist here) — add only when a real finding needs one.
- T-2: `domain/` complete, 8/8 tests green. Working on `feature/youtube-transcript-plugin` branch (created after T-1/T-2 — retroactively fixes that T-1 had landed directly on `main` uncommitted, per project CLAUDE.md's worktree/branch PR workflow).
- T-P2: 4 new named CI jobs added to `ci.yml` (`youtube-transcript-tests` matrix 3.9/3.13, `-ruff`, `-mypy`, `-coverage`), each with its own path-based change detector, mirroring maven-mcp's job shape exactly (job IDs prefixed to avoid collision, not generalized into a shared workflow — 2 plugins doesn't justify the abstraction cost). `release.yml` gained one new step (`working-directory: .`) running youtube-transcript's suite alongside maven-mcp's; the existing per-plugin-tag loop already reads `marketplace.json` generically so it needed no change. New `youtube-transcript-live-canary.yml` implements a real cache-based consecutive-failure counter (`actions/cache/restore` + `/save`, keyed by `github.run_id` with a `restore-keys` prefix, since cache entries are immutable per exact key) that fails loud only at 3 consecutive failures; `permissions: contents: read` only, so "fails loud" (not an opened issue) was the chosen escalation — an issue would need `issues: write`. It references T-15's not-yet-existing `test_live_canary.py`; verified empirically that `unittest discover -p <missing-pattern>` exits 5 ("NO TESTS RAN"), so the canary correctly fails (and the counter increments) until T-15 lands, rather than silently passing. `validate.sh` gained an L9 check (`check_workflow_permissions`) flagging any workflow file with no `permissions:` key anywhere (top-level or per-job) — a presence check only, not a least-privilege audit. `actionlint` run against all 5 workflow files: exit 0, no findings.
- T-4: `providers/video_ref.py` — exact-hostname allowlist via `urlsplit(...).hostname`, no scheme-less bare-domain support (read AC-6 as full-URL-or-bare-ID only, flagged as a judgment call if product intent differs).
- T-5: `formats/text.py`/`srt.py`/`vtt.py` + `formats/__init__.py` dispatch/`Page`/`FormatOptions`/`estimate_characters`. Added two same-package-only helpers beyond the brief's literal file list — `formats/_paging.py` (one `fit_page()`/`DeadlineStride` shared by every format's `encode()`/`count_pages_to()`, so the two literally cannot disagree on page boundaries by construction) and `formats/_cue.py` (blank-line-collapse then arrow-collapse, AC-21) — both fall under the existing `"formats": {"domain"}` `ALLOWED_EDGES` fallback row, no table edit needed. `Page`/`FormatOptions` live in `formats/__init__.py` (no owning file was named anywhere in tasks.md/plan.md/spec beyond the bare `-> Page` return-type mention); `text.py`/`srt.py`/`vtt.py` import them back from their own still-initializing parent package, which works because they're bound before the `from formats import text/srt/vtt` dispatch-table lines run — order-dependent, documented in the module docstring. Deadline-stride-bound test uses a poison-segment canary (a `.text` property that raises `AssertionError` if ever read) placed exactly at the analytically-derived stride checkpoint, rather than trying to measure "segments processed" from a function that only returns an int or raises. 68/68 tests green, 100% coverage on every new `formats/` file, ruff/mypy clean.
- T-P3: measurements recorded (`swarm-report/research/youtube-transcript-size-measurements.md`). CPU-phase p95=0.431s, ~45x margin under `CPU_PHASE_BUDGET=20s`. **Host allowlist corrected**: no `*.googlevideo.com` host observed for caption delivery — captions serve from `www.youtube.com/api/timedtext`; allowlist is exactly `{www.youtube.com, youtubei.googleapis.com}`, propagated to AC-19/T-6a/plan.md (the suffix-match branch is dropped, not just unused). Gate 4 (MCP host timeout) and 2 live network legs (InnerTube player POST, real caption body) unreproducible in this sandbox today — falls back to `maven-mcp`'s `TOOL_DEADLINE=30s` per the task's own sanctioned fallback; worth a fresh live attempt once T-6a/T-10 are actually being built, since the research report captured these legs working the day before.
- T-3: contracts frozen — `providers/base.py` (port + 10-member `ProviderError`, `trackId` codec), `net/client.py` (constants + exception set + `Transport`/`Response`, no `fetch()` yet), `formats/__init__.py`/`tools/__init__.py` filled in, `_helpers.py` gained `FakeProvider`/`FakeSession`/`mock_urlopen`/`http_error`. `test_import_boundaries.py`'s `ALLOWED_EDGES` table is keyed by dotted module path with a package-level fallback (exact per-file key wins, else top-level package), so `providers/__init__.py`/`protocol/__init__.py` resolve without needing their own row. The 3.13 stdlib-name fixture was generated from a real `/usr/local/bin/python3.13` interpreter (exact, not approximated from this machine's 3.14 default); the 3.9 fixture has no real 3.9 interpreter available, so it was derived from the 3.13 list plus/minus the documented module additions/removals across 3.10–3.13 (cross-checked against official docs.python.org "What's New" removed/new-modules sections per version) — flagged as the one approximation in this task, worth a double-check at a later `/acceptance` pass if a 3.9 interpreter ever becomes available.

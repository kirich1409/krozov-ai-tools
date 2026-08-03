# Progress: youtube-transcript MCP plugin (v1, stdio-only)

> Plan: ./plan.md · Tasks: ./tasks.md

## Status
- [x] T-1 — Package skeleton, pyproject.toml, test harness shim
- [x] T-2 — `domain/` complete
- [x] T-3 — Contracts freeze: session-scoped provider port, `net`/`formats` constants, AST import-boundary test
- [x] T-4 — `providers/video_ref.py`
- [x] T-5 — `formats/{text,srt,vtt}.py`
- [x] T-6a — `net/client.py` policy: scheme/host allowlist, TLS, redirect handling
- [x] T-6b — `net/client.py` resource controls: caps, deadline, retry, XML guard
- [x] T-7 — `protocol/envelope.py` + `schemas.py`
- [x] T-8 — `tools/cursor.py`
- [x] T-9 — `tools/resolution.py`
- [x] T-13a — `protocol/registry.py` + `dispatch.py`
- [x] T-10 — `providers/innertube.py`
- [x] T-11 — `tools/list_transcript_tracks.py`
- [x] T-12 — `tools/get_transcript.py`
- [x] T-13b — `composition.py` + `server.py`
- [x] T-14 — Cross-cutting AC tests
- [x] T-15 — Live canary
- [x] T-16 — Plugin docs + final `validate.sh`/coverage pass
- [x] T-P1 — Versioning and repo-doc generalization
- [x] T-P2 — CI workflows
- [x] T-P3 — Network spike: allowlist confirmation, canary videos, size/latency/RSS measurement
- [x] T-P4 — Spec addendum: sync remaining plan/spec divergences

## Blocking / Human-owned items (not a task, tracked here so they aren't missed at merge time)
- [ ] **T-16: `plugin-dev:plugin-validator` agent run against both `youtube-transcript` and `maven-mcp` — NOT DONE, tool unavailable in this environment.** Checked: the agent is not in this session's available-agent-types list, and `plugin-dev` is not present in either `.claude/settings.json` (project) or `~/.claude/settings.json` (global) `enabledPlugins` — only cached under `~/.claude/plugins/cache/claude-plugins-official/plugin-dev` and `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/plugin-dev`, never enabled. Root `CLAUDE.md`'s Publishing section requires this before every release; it must be run by whoever has a session with `plugin-dev` enabled, or performed manually per `PLUGIN-STANDARDS.md`'s own §10 checklist (which T-16 already walked manually as a partial substitute — see Learnings below — but that walk is not a substitute for the actual agent's deeper checks, only for the parts of §10 a human/agent can verify by hand).
- [ ] **T-16 gate 4 (MCP host tool-call timeout ≥ `TOOL_CALL_DEADLINE(180) + HOST_TIMEOUT_MARGIN(30) = 210s`) — remains UNMEASURED, same status T-P3 left it in.** No sandbox in this session had a way to invoke a real out-of-process MCP host to probe this (would require registering a stub sleep-handler MCP server with a separate live Claude Code/MCP client host and timing from outside it — outside a subagent's safe scope). Falls back to the `maven-mcp` precedent (`TOOL_DEADLINE=30s`) as a documented, conservative starting value per T-P3's own sanctioned fallback. `TOOL_CALL_DEADLINE=180s` remains unverified against any measured external ceiling. Needs a real probe against an actual MCP host before this gate is closed.
- [x] Register the four new `youtube-transcript` CI jobs as required branch-protection status checks. **Done, 2026-08-03**: added all 5 check contexts (`youtube-transcript-tests (3.9)`, `youtube-transcript-tests (3.13)`, `youtube-transcript-ruff`, `youtube-transcript-mypy`, `youtube-transcript-coverage`) to the `Main` ruleset's `required_status_checks` rule (`gh api -X PUT repos/kirich1409/krozov-ai-tools/rulesets/13632214`, run by the user directly per this session's permission classifier blocking repo-settings mutations from the agent), alongside the pre-existing `python-tests (3.9)`, `python-tests (3.13)`, `validate-marketplace`. Confirmed via `gh api repos/.../rules/branches/main` showing all 8 contexts.
- [x] T-P2: one manual `workflow_dispatch` run of `youtube-transcript-live-canary.yml`, exercising the cache-based consecutive-failure counter end-to-end, verified by a human before merge (T-P2's `check` in tasks.md; closes AC-25, contributes to AC-13). **Done, 2026-08-03**: `test_live_canary.py` itself is no longer untested — the orchestrator ran it for real (`YOUTUBE_TRANSCRIPT_LIVE_CANARY=1 python3 -m unittest discover -s plugins/youtube-transcript/tests -p test_live_canary.py`) against real YouTube traffic in this session's own network and all 3 pinned videos pass. **Update, 2026-08-03 (post-merge)**: triggered the actual workflow via `gh workflow run "youtube-transcript live canary" --ref main` (run [30787915416](https://github.com/kirich1409/krozov-ai-tools/actions/runs/30787915416)), watched it complete `success`. Log confirms the full counter mechanics: `actions/cache/restore@v4` correctly reported "Cache not found for input keys" on this first-ever run of the workflow and fell back to `count=0` (the `restore-keys` prefix-fallback path), `python3 -m unittest discover ... -p test_live_canary.py -v` ran all 3 pinned videos and passed (`Ran 3 tests ... OK`), then `actions/cache/save@v4` wrote a fresh counter entry under the run-id key. Restore→read→run→save round-trip is now exercised end-to-end against real Actions infrastructure. The 3rd-consecutive-failure escalation branch specifically still requires two more consecutive failing runs to observe directly — not forced deliberately, since that would mean intentionally breaking a real scheduled workflow — but the counter mechanism it depends on is now proven functional.
- [x] T-6b: `security-expert` review pass on `net/client.py` — **done**. Found 2 medium (uncaught `ValueError` from `urlsplit()`/`.port` on malformed input escaping the closed `NetError` set; `_check_policy`'s `PolicyRejected` rejections never routed through `_log_and_raise`) and 1 low (a non-retryable-status body-read exception could escape unlogged from inside the `HTTPError` except-block). No SSRF/TLS/redirect/opener/gzip-cap/XML-guard bypass found — those mechanisms are sound. All 3 findings fixed (plus one empirically-discovered cascading fix in `domain.redact_url`, which had the same unguarded `urlsplit()`); regression tests added; 161/161 tests green.

## Learnings
<!-- Дописывать по строке на завершённую задачу: неожиданности, подводные камни, решения,
     принятые по ходу реализации. Это память, переживающая сброс контекста. -->
- **End-to-end real-world verification (2026-08-03, orchestrator, session `01YS893YitNmv2bcVrZCXDXm`)**:
  after the live-fix pass below, ran the actual `plugin/server/server.py` process over real stdio
  JSON-RPC (not mocked, not the provider called directly — the full `dispatch → registry → tool handler
  → provider → net → envelope` stack, exactly how a real MCP client invokes this plugin) against the two
  videos a user asked to be able to fetch: `https://youtu.be/So6wfQs5wII` and
  `https://www.youtube.com/live/GMIWm5y90xA?si=9JLjosYYshM4W2dA`. Both resolved correctly:
  `So6wfQs5wII` — `list_transcript_tracks` found 2 real tracks (`ru` manual, `ru` auto),
  `get_transcript` returned `status: "ok"`, 19,053 real characters, `resolvedTrack:
  {languageCode: "ru", kind: "manual"}`, not truncated. `GMIWm5y90xA` (a completed YouTube-owned live
  stream, "Code with Claude 2026: Opening Keynote") — `list_transcript_tracks` correctly returned
  `status: "no_transcript"` with 0 tracks, because this specific video genuinely has no captions
  (manual or auto) published by YouTube — confirmed directly against the real InnerTube response
  (`captions` key absent entirely), not a fetch failure. Also ran the full `test_live_canary.py` suite
  for real (see the T-P2 blocking-item update above) — all 3 pinned videos pass. Transcript content was
  saved to local scratch files, never printed to any log or committed anywhere, per this repo's own
  content-handling posture.
- **Live-fix pass (2026-08-03, found by the orchestrator's own direct live HTTP calls against real
  YouTube, not a sandboxed subagent lacking egress)**: two of `providers/innertube.py`'s previously
  UNVERIFIED wire-protocol choices (T-10) turned out wrong once tested against real traffic, both
  now fixed and confirmed. (1) **`ANDROID`/`IOS` client context at the player-POST leg (leg 2) is
  now blocked** — HTTP 400 `FAILED_PRECONDITION` on every retry, no header/body variation curing
  it. This is a device-integrity/attestation check YouTube added to native-app client endpoints
  as of this date — a real-world upstream change, not a defect in this plugin or in the original
  research (`swarm-report/research/research-youtube-subtitles-plugin.md`'s 47+ live calls predate
  this change). Fixed: leg 2 now uses `context.client.clientName = "WEB"` plus
  `playbackContext.contentPlaybackContext.signatureTimestamp` (an integer `STS` extracted from the
  same leg-1 watch-page HTML already fetched for `INNERTUBE_API_KEY` — no new request), and
  `context.client.clientVersion` is likewise extracted live (`INNERTUBE_CONTEXT_CLIENT_VERSION`)
  rather than hardcoded. `_USER_AGENT` is now a real desktop Chrome UA string. Confirmed working
  against two real videos, no cookies/`Origin`/`Referer` needed. (2) **The timedtext `baseUrl`'s
  unparameterized default format changed** — a live fetch with no `fmt` query param now returns
  `<transcript><text start=".." dur="..">` (decimal seconds), not the `<timedtext format="3"><body>
  <p t=".." d="..">` (integer milliseconds) shape `_decode_segments()` expects; the module's prior
  docstring inference ("format=3 is the server's default when omitted") was reasonable at the time
  it was written but is empirically wrong as of this date. Fixed: `fmt=srv3` is now appended
  explicitly (via `urlsplit`/`parse_qsl`/`urlencode`, not string concatenation), still through
  `net/client.py`'s full host/scheme/port allowlist re-check (unskipped, per plan.md's own prior
  anticipation of this exact scenario). AC-23's exact-request-count budget unaffected — still 3
  requests for `get_transcript`, 2 for `list_transcript_tracks`, since `STS`/client version come
  from the same leg-1 GET. See `swarm-report/youtube-transcript-report-live-fix.md` for the full
  diff, live end-to-end verification output (real video IDs, metadata-only, no caption text
  logged), and test/lint/type-check results.
- Acceptance-fix pass (2026-08-02): `/acceptance` found `select_track()`'s tier-2 `languages`
  fallthrough violated AC-3 ("does NOT silently fall back to another language") — a supplied,
  non-empty `languages` list matching no track fell through to tiers 3/4/5 instead of returning
  `None`. Fixed: tier 2 is now a hard stop (match returns immediately, non-match returns `None`
  immediately, no fallthrough). **Corrects T-14's Learnings entry below**, which described this
  as intentional ("`select_track`'s tier-5 fallback means an 11-entry (or any non-matching)
  `languages` list ALONE can never produce `language_unavailable`") — that claim is no longer
  true for a genuinely non-matching, well-formed `languages` list (now hard-stops correctly);
  it remains true only for the separate, still-open `validate_languages()` cap-collapse case
  (an 11+-entry or over-length-entry list is normalized to `[]` *before* reaching `select_track`,
  which cannot distinguish "cap violated" from "no `languages` supplied" — code-reviewer's
  literal Issue 1 finding, out of scope for this fix pass, left as a follow-up). Also fixed in
  the same pass: `outcome_from_error()` dropped `RateLimited.retry_after` before it reached
  `envelope.build()`'s AC-22 clamp (now threaded through via the payload's `retry_after_seconds`
  key). See `swarm-report/youtube-transcript-report-acceptance-fix.md` for the full receipt.
- T-16: plugin docs (`plugins/youtube-transcript/CLAUDE.md`/`AGENTS.md`/`README.md`) written mirroring `maven-mcp`'s shape. `bash scripts/validate.sh --check-tag 0.27.0` — **green, all checks passed** (real output, see report file), confirming `server.py`'s `SERVER_VERSION`/`USER_AGENT` (0.27.0) now that T-13b has created the file (`--check-tag` was deliberately deferred here from T-P1, per tasks.md). Full test suite: 243 tests, OK (skipped=3, the gated live canary) — up from T-14's 240 (the +3 are T-15's `test_live_canary.py` cases, landed after T-14's count was taken; this task's own changes are doc-only, no test files touched). Coverage: **97%** (`TOTAL 1119 stmts, 35 miss`), `fail_under=75` satisfied with large margin, confirmed unchanged after doc-only edits. `ruff check` and `mypy` both clean (real runs, this pass).
  - **`plugin-dev:plugin-validator` — confirmed NOT AVAILABLE in this environment.** Checked available agent types (not listed) and both `.claude/settings.json`/`~/.claude/settings.json` `enabledPlugins` (plugin-dev present only in the marketplace cache, never enabled). Recorded as a blocking human-owned item above — do not read this task as having silently skipped it.
  - **`docs/PLUGIN-STANDARDS.md` §10 pre-release checklist, walked manually for both plugins** (real checks run, this pass, not asserted from memory):
    | Item | maven-mcp | youtube-transcript |
    |---|---|---|
    | `bash validate.sh` green | ✓ (part of the same run above) | ✓ |
    | `plugin-dev:plugin-validator` PASS/Minor-only | **not run — tool unavailable, see blocking item above** | **not run — tool unavailable, see blocking item above** |
    | plugin.json/marketplace.json versions synced | ✓ (0.27.0, `validate.sh` L4) | ✓ (0.27.0, `validate.sh` L4) |
    | No `.DS_Store`/`*-workspace/` in commits | ✓ (`git ls-files` grep, none found) | ✓ (`git ls-files` grep, none found) |
    | All `*.sh` executable | ✓ (`find plugins -name "*.sh" ! -perm -u+x` empty) | ✓ (no `.sh` files at all — no hooks in this plugin) |
    | Skill `description` ≤1024 chars | ✓ (`validate.sh` L7, max observed 538ch) | N/A — no skills in v1 (plan.md Decisions Made: "Skill layer: None in v1") |
    | SKILL.md ≤500 lines or has `references/` | ✓ (all 21 skills checked, max 126 lines) | N/A — no skills |
    | No `hooks`/`mcpServers`/`permissionMode` in agent frontmatter | N/A — no agent files in this plugin (`find plugins -path "*/plugin/agents/*.md"` empty for both plugins) | N/A — same |
    | `plugin.json` paths start with `./`, no `../`, auto-discovery preferred | ✓ (`validate.sh` L5, no errors; hooks/skills use auto-discovery, no explicit path fields) | ✓ (`plugin.json` declares only `mcpServers` as an inline object — no path-string fields at all; `plugin/` dir contains only `server/`, no `skills`/`agents`/`hooks`/`commands` dirs to auto-discover) |
    | All referenced files exist | ✓ (`validate.sh` L3/L5) | ✓ (`validate.sh` L3/L5) |
  - **T-16's 4 measurement-gate verdicts** (against `swarm-report/research/youtube-transcript-size-measurements.md`'s T-P3 data; full arithmetic and caveats also in `plugins/youtube-transcript/README.md`'s *Measurement gates* section):
    1. **Pagination ceiling** (3-hour srt fits `MAX_PAGES=20` at `MAX_PAGE_CHARS=50,000`) — **PASS**, large margin. Formula-based (45 chars/sec) → 10 pages; T-P3's synthetic-content-measured rate (~30 chars/sec) → 7 pages. Neither is an independently verified *real* caption chars/sec (T-P3 could not fetch live caption content this pass, §3/§4 of that report) — flagged honestly as the strongest available evidence, not a fully closed measurement, but not a failure either: 20-page margin covers both figures with room to spare.
    2. **`HTTP_TIMEOUT` tuning inequality** — **PASS**. `HTTP_MAX_ATTEMPTS(2) × 3 legs × HTTP_TIMEOUT(15) + 3 × max_backoff(1.25) = 93.75s ≤ TOOL_CALL_DEADLINE(180) − ENCODE_RESERVE(35) = 145s` (51.25s margin, matches tasks.md's own cited figures). Second half: `HTTP_TIMEOUT(15s) ≥` measured p95 of the two measured legs (leg1 1.081s, leg3 0.161s) — holds. Leg2's true p95 remains unmeasured (T-P3 §2), so this pass covers only the legs T-P3 could measure.
    3. **CPU-phase budget** (`p95(CPU phase) ≤ CPU_PHASE_BUDGET`) — **PASS**, cited from T-P3: measured p95=0.431s vs. `CPU_PHASE_BUDGET=20s` (~46x margin). Still recorded as measured on a dev laptop, not the CI matrix runner tasks.md specifies as the authoritative target.
    4. **MCP host tool-call timeout** (`≥ TOOL_CALL_DEADLINE(180) + HOST_TIMEOUT_MARGIN(30) = 210s`) — **UNMEASURED, explicitly deferred**, same status T-P3 left it in. No sandbox available this pass either (no live network egress, no ability to safely spin up a second real MCP host out-of-process from a subagent). Falls back to `maven-mcp`'s `TOOL_DEADLINE=30s` precedent per T-P3's own sanctioned fallback — **not** silently marked passing. Tracked as a blocking human-owned item above.
  - `git diff` for this task's own changes is documentation-only (3 new files: `plugins/youtube-transcript/{CLAUDE,AGENTS,README}.md`, plus this `progress.md` edit) — no `server/` code touched, so the "T-6b's/T-14's numeric-assertion re-verification" clause in tasks.md's T-16 acceptance text needed no action (the constants and their derived test assertions were unchanged by this task).
- T-15: live canary test — gated behind `YOUTUBE_TRANSCRIPT_LIVE_CANARY=1`, mirrors maven-mcp's pattern. **Live-network assertions unverified** — no egress in any sandbox this session had; skip-gate and CI discovery-pattern match with T-P2's workflow confirmed offline. Real verification is the same pending human-owned item T-P2 already tracks (manual `workflow_dispatch`).
- T-14: cross-cutting AC suite closed — `test_no_file_writes.py` (in-process, cwd
  pointed at an empty `tempfile.TemporaryDirectory()`, both tools dispatched
  against a `FakeProvider`, directory listing asserted empty before/after);
  `test_source_policy.py` gained 2 named ban-group tests (write primitives;
  exec/eval/serialization primitives), both zero-violation on the real tree, no
  prior offenders; `test_request_budget.py` (new) drives all 4 exact-request-count/
  timing scenarios through `composition.build_provider(sleep=, jitter=)` +
  `server.build_registry()` + real `handle_message` dispatch, never global `time`/
  `random` monkeypatching, mirroring `test_net_client_resources.py`'s
  `_ScriptedOpener`/`_FakeClock` pattern one layer up (patched at
  `net.client._OPENER`, the one real network-egress seam) instead of mocking
  `net.fetch` directly; `test_status_sweep.py` (new) proves reachability of all 13
  `Status` members by construction (through the real `get_transcript`/
  `list_transcript_tracks` handlers against `FakeProvider`/`FakeSession`), not by
  grepping other test files; `test_domain.py` gained the corrected 4-direct-
  children/13-leaf `DomainFailure` totality split; `test_import_boundaries.py`
  gained a genuinely new symbol-level check (`_module_local_bindings`/
  `_resolve_symbol_chain`) that follows `from X import NAME` through every
  re-export hop to the name's true defining module and re-validates each hop
  against `ALLOWED_EDGES` independently -- strictly stronger than
  `TestCurrentTreeCompliance`'s existing per-file, module-prefix-only check (which
  cannot see past one re-export hop); a self-test with a synthetic forged
  re-export chain (`formats` re-exporting a name whose true origin is
  `providers.innertube`) proves the mechanism actually fires. **AC-3's
  11-language-cap dispatch test needed a deliberate design choice, not just a
  literal reading of tasks.md's prose**: `tools/resolution.py::select_track`'s
  tier-5 fallback means an 11-entry (or any non-matching) `languages` list ALONE
  can never produce `language_unavailable` as long as the video has any caption
  track at all -- it always falls back to the first available track (AC-2's own
  documented behavior, and the same reason `test_tool_get_transcript.py`'s own
  `TestLanguageUnavailable` uses an unmatched `trackId`, never `languages` alone,
  to reach that status). `test_eleven_languages_rejected_as_domain_error_not_
  schema_error` combines the 11-entry array with an intentionally-unmatched
  `trackId` so the dispatched call legitimately resolves to `language_unavailable`
  while still proving the real point: an 11-entry array never trips a JSON-RPC
  `-32602` at the dispatch layer (`TOOL_SCHEMAS` declares no `maxItems`, by
  design, and `_handle_tools_call` only ever validates required fields). AC-26's
  new dispatch-level test reuses T-7's three adversarial fixture caption texts
  verbatim through a stub `TranscriptProvider`/`FakeSession` single-segment
  transcript, reading `response["result"]["content"][0]["text"]` verbatim with
  zero test-side `json.dumps()` calls -- the expected recovered region accounts
  for `formats/text.py`'s own documented single-segment render shape
  (`f"{segment.text}\n"`, a trailing newline `test_envelope.py`'s pure-envelope
  unit tests don't have to account for since they bypass `formats.encode`
  entirely). 240 tests total (226 pre-existing + 14 new: the 13 named `check`
  tests plus one self-test proving the import-graph mechanism actually fires),
  full suite green, 97% coverage, ruff/mypy clean via pinned `uvx` versions.
- T-1: package skeleton + pyproject.toml mirrored from maven-mcp; `[[tool.mypy.overrides]]`/`[tool.ruff.lint.per-file-ignores]` blocks intentionally omitted (empty placeholders would mirror maven-mcp findings that don't exist here) — add only when a real finding needs one.
- T-2: `domain/` complete, 8/8 tests green. Working on `feature/youtube-transcript-plugin` branch (created after T-1/T-2 — retroactively fixes that T-1 had landed directly on `main` uncommitted, per project CLAUDE.md's worktree/branch PR workflow).
- T-P2: 4 new named CI jobs added to `ci.yml` (`youtube-transcript-tests` matrix 3.9/3.13, `-ruff`, `-mypy`, `-coverage`), each with its own path-based change detector, mirroring maven-mcp's job shape exactly (job IDs prefixed to avoid collision, not generalized into a shared workflow — 2 plugins doesn't justify the abstraction cost). `release.yml` gained one new step (`working-directory: .`) running youtube-transcript's suite alongside maven-mcp's; the existing per-plugin-tag loop already reads `marketplace.json` generically so it needed no change. New `youtube-transcript-live-canary.yml` implements a real cache-based consecutive-failure counter (`actions/cache/restore` + `/save`, keyed by `github.run_id` with a `restore-keys` prefix, since cache entries are immutable per exact key) that fails loud only at 3 consecutive failures; `permissions: contents: read` only, so "fails loud" (not an opened issue) was the chosen escalation — an issue would need `issues: write`. It references T-15's not-yet-existing `test_live_canary.py`; verified empirically that `unittest discover -p <missing-pattern>` exits 5 ("NO TESTS RAN"), so the canary correctly fails (and the counter increments) until T-15 lands, rather than silently passing. `validate.sh` gained an L9 check (`check_workflow_permissions`) flagging any workflow file with no `permissions:` key anywhere (top-level or per-job) — a presence check only, not a least-privilege audit. `actionlint` run against all 5 workflow files: exit 0, no findings.
- T-13b: composition.py/server.py wired — server is now runnable end-to-end (mocked transport: 3 requests for get_transcript, 2 for list_transcript_tracks, verified). 226 tests, 97% coverage. Server-invocation smoke test (real `python3 server.py` subprocess on empty stdin) passes.
- T-12: get_transcript handler — cursor precedence over other args, empty-tracks short-circuits at exactly 2 requests, MAX_PAGES truncation via full fetch+decode replay (no cross-invocation caching, per AC-11). T-13b will need to wrap this module's and T-11's `(provider, deadline, args)`-shaped `handle` in a closure matching `Registry.Handler`'s `(args) -> ToolOutcome`, building a fresh `Deadline` per invocation.
- T-11: list_transcript_tracks handler — `estimate_characters` computed once per call not per track, response-only `TrackDescriptor` copies (originals never mutated), 50-track cap with `truncated`. Clean run, no deviations.
- T-10: InnerTube provider — positive `playabilityStatus=="OK"` gate read outside the JSON-structural-failure wrapper, three-way `captions` discrimination, per-track validation with fail-closed-if-all-dropped. **No live network egress in this sandbox pass** — 5 wire-protocol details (player-POST client version/UA, host choice, exact request-body field set, `is_default` derivation, plus one more — see `swarm-report/youtube-transcript-report-T-10.md`) synthesized from the research report + T-P3's fixture rather than captured live; flagged for confirmation once real traffic is available, ideally at T-15's live canary. 18/18 named tests + full 195-test regression green, ruff/mypy/compileall clean.
- T-13a: registry/dispatch — `Registry.call()` catches only `DomainFailure`, propagates everything else to `handle_message`'s sole `-32603` construction point; `tools/call` wraps the full result dict in exactly one `content[0].text` `json.dumps()` block, no `structuredContent`; did not copy maven-mcp's `str(e)`/`isError:true` fallback branch. Caught and fixed a pre-existing mypy error in T-8's `test_cursor.py` (loop-variable type redefinition across two `for` loops) — first time mypy had actually been run against that file since T-8's sandbox lacked it.
- T-8: cursor codec — strict `validate=True` base64url (never `urlsafe_b64decode`'s silent-strip form), exactly-five-key dict check, all 4 remaining fields independently re-validated at decode. 142 tests green at commit time.
- T-9: **tier-order bug caught before shipping** — tasks.md's T-9 acceptance text numbered `default_audio_language`/`is_default` as tiers 2-3 by counting after `track_id`, silently demoting `languages`-preference matching to *after* both default-signal tiers; this contradicted AC-2's literal order (`languages` before `default_audio_language`/`is_default`) and had no supporting rationale anywhere in the plan. The T-9 implementer flagged it explicitly instead of silently picking one; resolved in favor of AC-2's literal text (tasks.md fixed first, then `select_track()`/tests corrected to match — see the commit that reorders tier 4 before tiers 2-3 internally while keeping the existing test names).
- T-7: envelope/schemas — `build()` constructs `tracks`/`resolvedTrack` as fixed literal shapes from `TrackDescriptor` fields, two separate dict keys (`transcript`/`contentNotice`) never concatenated, `ValueError` (not `DomainFailure`) on its own invariant violation. Test coverage explicitly named unit-level-only for the reference parser (`test_reference_parser_unit_resists_*`) — AC-26 itself closes later at T-14 against the real dispatch stack, not here. 126 tests total, 100% coverage on both new files, ruff/mypy/coverage all clean via pinned `uvx` versions.
- T-6a: policy layer (opener singleton, exact-match host/scheme/port allowlist, redirect→PolicyRejected before 429/5xx). Implementing subagent's connection dropped mid-response right as it was writing its report — work itself was already complete and correct (80/80 tests green including all named checks); orchestrator verified directly and wrote the report on its behalf. No retry needed.
- T-4: `providers/video_ref.py` — exact-hostname allowlist via `urlsplit(...).hostname`, no scheme-less bare-domain support (read AC-6 as full-URL-or-bare-ID only, flagged as a judgment call if product intent differs).
- T-5: `formats/text.py`/`srt.py`/`vtt.py` + `formats/__init__.py` dispatch/`Page`/`FormatOptions`/`estimate_characters`. Added two same-package-only helpers beyond the brief's literal file list — `formats/_paging.py` (one `fit_page()`/`DeadlineStride` shared by every format's `encode()`/`count_pages_to()`, so the two literally cannot disagree on page boundaries by construction) and `formats/_cue.py` (blank-line-collapse then arrow-collapse, AC-21) — both fall under the existing `"formats": {"domain"}` `ALLOWED_EDGES` fallback row, no table edit needed. `Page`/`FormatOptions` live in `formats/__init__.py` (no owning file was named anywhere in tasks.md/plan.md/spec beyond the bare `-> Page` return-type mention); `text.py`/`srt.py`/`vtt.py` import them back from their own still-initializing parent package, which works because they're bound before the `from formats import text/srt/vtt` dispatch-table lines run — order-dependent, documented in the module docstring. Deadline-stride-bound test uses a poison-segment canary (a `.text` property that raises `AssertionError` if ever read) placed exactly at the analytically-derived stride checkpoint, rather than trying to measure "segments processed" from a function that only returns an int or raises. 68/68 tests green, 100% coverage on every new `formats/` file, ruff/mypy clean.
- T-P3: measurements recorded (`swarm-report/research/youtube-transcript-size-measurements.md`). CPU-phase p95=0.431s, ~45x margin under `CPU_PHASE_BUDGET=20s`. **Host allowlist corrected**: no `*.googlevideo.com` host observed for caption delivery — captions serve from `www.youtube.com/api/timedtext`; allowlist is exactly `{www.youtube.com, youtubei.googleapis.com}`, propagated to AC-19/T-6a/plan.md (the suffix-match branch is dropped, not just unused). Gate 4 (MCP host timeout) and 2 live network legs (InnerTube player POST, real caption body) unreproducible in this sandbox today — falls back to `maven-mcp`'s `TOOL_DEADLINE=30s` per the task's own sanctioned fallback; worth a fresh live attempt once T-6a/T-10 are actually being built, since the research report captured these legs working the day before.
- T-6b: `fetch()` completed (header merge — `BASE_HEADERS` wins on collision, both sides `.title()`-normalized; retry loop — floor+clamp both computed from backoff-inclusive `remaining_after_backoff`, pinned-jitter backoff via injected `Transport`; streaming byte cap; cumulative gzip-bomb cap ported from `plugins/maven-mcp/plugin/server/server.py`'s `_inflate_gzip_capped`; per-chunk network-budget deadline check) plus `parse_xml_guarded()` (raw `expat.ParserCreate()`, DOCTYPE/entity sentinel, `MalformedUpstream` mapping). Found and fixed one pre-existing defect from T-6a: the committed `Transport.jitter` field was typed `Callable[[], float]` (no args), but tasks.md's T-6a interface text (and this task's actual call site, `jitter(0, 0.25)`) always specified `Callable[[float, float], float]` — corrected the annotation, no behavior change since Python doesn't enforce annotations at runtime, but it was a real mypy-vs-actual-usage mismatch. Also found `fetch()`'s signature per tasks.md/plan.md has no default for `deadline`/`transport`, which would break every already-committed T-6a policy-layer test (`client.fetch(url)`, no kwargs) — resolved by giving both parameters `None` defaults that resolve internally to a freshly-started full-budget `Deadline` and a real-`time.sleep`/`random.uniform` `Transport`; production call sites (T-10) are expected to always pass both explicitly. Also found `plan.md`'s "Outbound headers" section (line ~169) still described the header-merge direction as "caller headers taking precedence", which is the cycle-9-draft-1 version tasks.md's own Y-5 narrow-check later corrected (base wins) — fixed the stale sentence in `plan.md` to match. 106/106 tests green (80 pre-existing + 26 new), ruff/mypy clean, 98% coverage overall (net/client.py 97%, remaining gaps are pre-existing T-6a lines plus one intentionally-unreachable defensive assertion). **Not yet closed**: the security-expert/human review pass this task's own acceptance text requires (see Blocking items above) — flagged, not silently skipped.
- T-3: contracts frozen — `providers/base.py` (port + 10-member `ProviderError`, `trackId` codec), `net/client.py` (constants + exception set + `Transport`/`Response`, no `fetch()` yet), `formats/__init__.py`/`tools/__init__.py` filled in, `_helpers.py` gained `FakeProvider`/`FakeSession`/`mock_urlopen`/`http_error`. `test_import_boundaries.py`'s `ALLOWED_EDGES` table is keyed by dotted module path with a package-level fallback (exact per-file key wins, else top-level package), so `providers/__init__.py`/`protocol/__init__.py` resolve without needing their own row. The 3.13 stdlib-name fixture was generated from a real `/usr/local/bin/python3.13` interpreter (exact, not approximated from this machine's 3.14 default); the 3.9 fixture has no real 3.9 interpreter available, so it was derived from the 3.13 list plus/minus the documented module additions/removals across 3.10–3.13 (cross-checked against official docs.python.org "What's New" removed/new-modules sections per version) — flagged as the one approximation in this task, worth a double-check at a later `/acceptance` pass if a 3.9 interpreter ever becomes available.

---
type: test-plan
slug: youtube-transcript
date: 2026-08-02
status: on-the-fly
source_spec: docs/specs/2026-08-01-youtube-transcript.md
platform: [cli]
phase_coverage: v1 (stdio-only)
---

# Test Plan: youtube-transcript MCP plugin (v1, stdio-only)

Generated on-the-fly for `/acceptance` (branch 3 — spec-only, no prior test-plan receipt or mounted
file existed). Every AC in `docs/specs/2026-08-01-youtube-transcript.md`'s `acceptance_criteria_ids`
already has a named, executable test in the repository — this document is a cross-reference of that
existing coverage (drawn from `docs/plans/youtube-transcript/tasks.md`'s per-task `check:` lines,
verified against the actual test files, not invented from scratch), plus the few cases that need real
execution (L5) rather than a mocked unit/integration test.

| TC | AC | Level | Verification | Status |
|---|---|---|---|---|
| TC-1 | AC-1 (list cap 50/`videoDurationSeconds`/sort order) | L2 | `test_tool_list_tracks.py::test_track_count_cap_and_sort`, `test_resolution.py` (sort tiers), `test_formats_*` (`estimate_characters`) | Automated |
| TC-2 | AC-2 (5-tier track resolution) | L2 | `test_resolution.py::{test_tier1..test_tier5,test_both_default_signals_absent_tier_skipped}` | Automated |
| TC-3 | AC-3 (languages cap/BCP-47 match/`availableLanguages`) | L2 | `test_resolution.py`, `test_tool_get_transcript.py::test_language_unavailable_includes_available_languages`, `test_dispatch.py::test_eleven_languages_rejected_as_domain_error_not_schema_error` | Automated |
| TC-4 | AC-4 (format enum/`includeTimestamps`) | L2 | `test_schemas.py`, `test_formats_*` | Automated |
| TC-5 | AC-5 (`trackId` precedence, `resolvedTrack`) | L2 | `test_resolution.py`, `test_tool_get_transcript.py::test_resolved_track_in_payload_on_success` | Automated |
| TC-6 | AC-6 (video-ref normalization, host allowlist, attack payloads) | L2 | `test_video_ref.py` (full URL-form table + `@evil.com`/`youtube.com.evil.com` payloads) | Automated |
| TC-7 | AC-7 (no captions → `no_transcript`) | L2 | `test_innertube.py::test_open_always_succeeds_empty_tracks_when_no_captions`, both tool handlers | Automated |
| TC-8 | AC-8 (video not found) | L2 | `test_tool_list_tracks.py`/`test_tool_get_transcript.py::test_invalid_video_ref_returns_not_found_without_opening`, `test_innertube.py` | Automated |
| TC-9 | AC-9 (playability discriminator table) | L2 | `test_innertube.py::test_non_ok_playability_raises_specific_subclass` (parametrized over all discriminators) | Automated |
| TC-10 | AC-10 (`isError` totality, `STATUS_POLICY`) | L2 | `test_domain.py::test_status_policy_totality`, `test_schemas.py` | Automated |
| TC-11 | AC-11 (pagination: cursor wire encoding, two-phase validation, page derivation, byte-exact reassembly) | L2 | `test_cursor.py`, `test_tool_get_transcript.py` (cursor/`MAX_PAGES` cases), `test_formats_*` (byte-exact concat) | Automated |
| TC-12 | AC-12 (plugin registration, version sync) | L1a | `bash scripts/validate.sh --check-tag 0.27.0` | Automated |
| TC-13 | AC-13 (live canary, 2+ pinned videos) | L5 | `test_live_canary.py` (gated, `YOUTUBE_TRANSCRIPT_LIVE_CANARY=1`) | **Deferred — no live network egress in this environment** |
| TC-14 | AC-14 (zero pip deps) | L1a | `test_import_boundaries.py::test_stdlib_check_against_committed_per_leg_lists` | Automated |
| TC-15 | AC-15 (no transport-vocabulary leakage, content-boundary + notice) | L2 | `test_envelope.py` (boundary/notice tests) | Automated |
| TC-16 | AC-16 (no filesystem writes, no exec/eval/serialization primitives) | L2 | `test_no_file_writes.py`, `test_source_policy.py::{test_no_file_write_calls,test_no_execution_or_serialization_primitives}` | Automated |
| TC-17 | AC-17 (full `Status`/`MESSAGES` reachability) | L2 | `test_status_sweep.py`, `test_domain.py`, `test_envelope.py::test_messages_and_fields_totality` | Automated |
| TC-18 | AC-18 (fetch precondition, `baseUrl` allowlist re-check) | L2 | `test_innertube.py`, `test_net_client_policy.py` | Automated |
| TC-19 | AC-19 (SSRF policy: scheme/host/port allowlist, TLS, redirect rejection) | L1b+L2 | `test_net_client_policy.py` (9 named tests), `security-expert` review pass (T-6a/T-6b, already done — 2 medium + 1 low found and fixed) | Automated + reviewed |
| TC-20 | AC-20 (outbound headers, retry/backoff/deadline arithmetic) | L2 | `test_net_client_resources.py` (16 named tests), `test_request_budget.py` (exact-count/timing) | Automated |
| TC-21 | AC-21 (control-char sanitization, cue-injection neutralization) | L2 | `test_domain.py::test_sanitize_text_strips_control_chars_widened_set`, `test_formats_srt.py`/`test_formats_vtt.py` (cue tests) | Automated |
| TC-22 | AC-22 (`Retry-After` clamp) | L2 | `test_envelope.py::test_retry_after_clamp_three_branches`, `test_innertube.py::test_retry_after_non_numeric_falls_back` | Automated |
| TC-23 | AC-23 (exactly-3/exactly-2 request budget, session-scoped provider) | L2 | `test_innertube.py`, `test_composition.py::{test_end_to_end_request_count_get_transcript,test_end_to_end_request_count_list_tracks}` | Automated |
| TC-24 | AC-24 (import-boundary enforcement) | L1a | `test_import_boundaries.py` (full suite incl. `test_real_import_graph_matches_allowed_edges`) | Automated |
| TC-25 | AC-25 (live-canary CI workflow, consecutive-failure counter) | L5 | `.github/workflows/youtube-transcript-live-canary.yml` (T-P2) | **Deferred — requires a real `workflow_dispatch` run, human-owned** |
| TC-26 | AC-26 (content-boundary reference parser against the real wire artifact) | L2 | `test_dispatch.py::test_ac26_reference_parser_against_real_dispatch_response` (dispatches through the real `handle_message` stack, no test-side re-serialization) | Automated |
| TC-27 | Server actually runs over stdio and answers a real JSON-RPC exchange | L5 | Real subprocess smoke test: `initialize` → `tools/list` → `tools/call` for both tools against a fake/no-network fixture path, or at minimum a well-formed JSON-RPC round trip | **To run as part of this acceptance pass** |

## Non-functional / Instrumentation

N/A: this plugin has no declared metrics/telemetry/instrumentation contract in the spec.

## Notes

- TC-13 and TC-25 require live network egress / a real GitHub Actions dispatch, neither available to
  this acceptance run. Both are already tracked as human-owned blocking items in
  `docs/plans/youtube-transcript/progress.md`. This acceptance pass treats them as tracked, accepted
  exceptions — not silently passed.
- TC-27 is the closest available proxy to "real execution" (L5) for a non-UI CLI/backend project, per
  the acceptance skill's own guidance ("для не-UI проекта L5 — тоже реальное исполнение: ... свежая
  сессия поднялась чисто"). It's run directly by this acceptance pass, not deferred.

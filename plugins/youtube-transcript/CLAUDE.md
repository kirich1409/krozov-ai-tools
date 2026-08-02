# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in `plugins/youtube-transcript/`.

## Non-negotiables

Rules that are not open for discussion. Violating these is an error, not a judgment call.

- **No pip dependencies — stdlib only.** Every module is written against the Python 3.9+ standard library. Matches the `maven-mcp` precedent in this repo, keeps the plugin runnable in Claude cloud and local environments with no install step, and avoids importing a third party's supply-chain risk into a tool that already touches an untrusted upstream (YouTube's InnerTube API).
- **No ASR / speech-to-text fallback.** This plugin surfaces only captions YouTube already publishes (manual or auto-generated); it never generates new transcript content. Decided by the user before research began — adding ASR changes the exposure from "republish existing public data" to "generate new derivative content," a materially different scope and risk.
- **No video/audio download.** Only caption text is fetched and returned; the `streamingData` section of the InnerTube response (audio/video segment URLs, `*.googlevideo.com`) is never read. A categorically larger surface (storage, formats, codecs) than this plugin's stated use case needs.
- **No file writes for tool output, ever.** Every tool returns transcript text directly in the MCP response; nothing is written to disk. Falsifiable via repo-grep (AC-16). Sidesteps the `yt-dlp` subtitle-write CVE class by not writing files at all.
- **Outbound egress is allowlisted by exact hostname, never by suffix or substring.** `net/client.py`'s `ALLOWED_HOSTS = frozenset({"www.youtube.com", "youtubei.googleapis.com"})` is the only route to the network in this codebase — enforced structurally (`net/client.py` is the sole module permitted to import `urllib.request`/`http.client`/`socket`/`ssl`, per `tests/test_import_boundaries.py`) and checked by exact `urlsplit(...).hostname` equality, never `in`/`startswith`/regex-on-the-raw-URL (which would let `https://www.youtube.com@evil.com/...` or `https://youtube.com.evil.com/...` pass). This is the SSRF boundary AC-19 exists to close.
- **Module layering (`domain/` ← `net/`, `providers/` ← `tools/`, `protocol/`) is one-directional and grep-enforced.** `tests/test_import_boundaries.py` asserts an explicit `ALLOWED_EDGES` table both per-file (module-prefix) and per-symbol (following re-export chains), plus that `providers/innertube.py` is reachable only via `composition.py`, never directly from `tools/`/`protocol/`. A change that needs a new cross-package import updates `ALLOWED_EDGES` deliberately, not by adding an unlisted import and hoping the test misses it.

## Project

MCP server that fetches existing YouTube captions (manual or auto-generated) via the InnerTube API and returns them as plain text, SRT, or VTT. It does not perform speech-to-text and does not download video/audio — only captions YouTube already publishes.

**Implementation:** `plugin/server/server.py` is the process entry point (`SERVER_VERSION`/`USER_AGENT`, `build_registry()`, `main()`) for a multi-module package under `plugin/server/` — `domain/`, `net/`, `providers/`, `formats/`, `protocol/`, `tools/`, plus `composition.py`. Unlike `maven-mcp`'s single-file design, this plugin has several layers with a declared, grep-enforced dependency direction (AC-23/AC-24); a single file would make that direction unenforceable. It speaks MCP over stdio (JSON-RPC 2.0 on stdin/stdout) only — no HTTP transport in v1 (see `maven-mcp` for that pattern if it's ever needed here). Registered via `plugin/.claude-plugin/plugin.json` as `command: python3`.

**Stack:** Python 3.9+ standard library only (`urllib`, `json`, `re`, `xml.parsers.expat`, `secrets`, `typing`). No build step, no install step.

## Commands

All commands run from the repository root.

```bash
python3 -m unittest discover -s plugins/youtube-transcript/tests       # Run all tests
python3 -m unittest discover -s plugins/youtube-transcript/tests -v    # Verbose
python3 -m compileall plugins/youtube-transcript/plugin/server         # Zero-dep syntax gate
```

Run a single test module:

```bash
python3 -m unittest discover -s plugins/youtube-transcript/tests -p test_tool_get_transcript.py
```

**Lint / type-check / coverage.** Dev-only tools, not runtime dependencies — install
ephemerally (`uvx --with ruff==0.15.22 ruff check ...`, or a venv). Config lives in
`plugins/youtube-transcript/pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`, `[tool.coverage.*]`).

```bash
ruff check plugins/youtube-transcript/plugin/server plugins/youtube-transcript/tests
mypy --config-file plugins/youtube-transcript/pyproject.toml
coverage run --rcfile=plugins/youtube-transcript/pyproject.toml -m unittest discover -s plugins/youtube-transcript/tests
coverage report --rcfile=plugins/youtube-transcript/pyproject.toml   # fail_under=75, ~97% measured
```

**Live canary** (real network, skipped by default):

```bash
YOUTUBE_TRANSCRIPT_LIVE_CANARY=1 python3 -m unittest discover -s plugins/youtube-transcript/tests -p test_live_canary.py
```

## Architecture

`plugin/server/` is a package of sub-packages with a one-directional dependency graph (`ALLOWED_EDGES` in `tests/test_import_boundaries.py` is the authoritative, enforced source):

- **`domain/`** — shared data types, exceptions, and policy tables. Zero imports from any other in-project package; every other package imports it, never the reverse. Owns `Transcript`, `TrackDescriptor`, `Segment`, the `Status` enum, `STATUS_POLICY` (retry/status/error policy table), `DomainFailure` and its 13 leaf subclasses, `CursorInvalid`, and the deadline/timeout constants (`HTTP_TIMEOUT=15`, `TOOL_CALL_DEADLINE=180`, `CPU_PHASE_BUDGET=20`, `ENCODE_RESERVE=HTTP_TIMEOUT+CPU_PHASE_BUDGET=35`, `HOST_TIMEOUT_MARGIN=30`, `DEADLINE_CHECK_STRIDE=1000`, `MAX_SEGMENTS`) — placed here rather than in their more "natural" owning module (`net/client.py`, `formats/__init__.py`) specifically so every cross-package consumer can reach them via an edge it already has to `domain/` ("symbol-placement rule", plan.md cycle 7).
- **`net/client.py`** — the one module permitted to import `urllib.request`/`http.client`/`socket`/`ssl`/`xml.*` (enforced). `fetch()`: opener construction, scheme/host/port allowlist + redirect-rejection policy (`ALLOWED_HOSTS`, T-6a), header merge, retry/backoff with a streaming network-budget deadline check, response byte cap, and a cumulative gzip-bomb cap ported from `maven-mcp`'s `_inflate_gzip_capped` (T-6b). `HTTP_MAX_ATTEMPTS=2` (at most one retry per leg). Also owns `parse_xml_guarded()` — raw `expat.ParserCreate()` with a DOCTYPE/entity sentinel, guarding against XML entity-expansion attacks in InnerTube's timedtext XML response.
- **`providers/`** — `base.py` declares the port (`TranscriptProvider`/`ProviderSession` ABCs, closed `ProviderError(DomainFailure)` hierarchy, opaque `trackId` codec) and `video_ref.py` (AC-6's URL/bare-ID normalizer, exact-hostname allowlist against the same SSRF-payload class as `net/client.py`'s host check). `innertube.py` is the concrete implementation: watch-page GET → InnerTube player POST → timedtext GET, translating `net/`'s exception set into `ProviderError` subclasses. `base.py` may **never** import `innertube.py` (would let the abstraction import its own concrete implementation).
- **`formats/`** — `text.py`/`srt.py`/`vtt.py` encoders plus `__init__.py`'s dispatch table, `Page`/`FormatOptions` types, `count_pages_to()` (the pagination-ceiling replay algorithm, AC-11), and `estimate_characters()`. `MAX_PAGE_CHARS=50_000`, `MAX_PAGES=20`, `CHARS_PER_SECOND=15`, `CUE_OVERHEAD_FACTOR=3`.
- **`protocol/`** — `schemas.py` (the two `TOOL_SCHEMAS` MCP tool declarations), `envelope.py` (turns a domain-level `ToolOutcome` into the wire-facing response dict — see *Untrusted-content boundary* below, this is the plan's most reviewed mechanism), `registry.py` (tool registration/invocation, `Registry`), `dispatch.py` (JSON-RPC 2.0 over stdio, `serve_stdio()`/`handle_message()`).
- **`tools/`** — `cursor.py` (AC-11's opaque pagination-cursor codec, five fields: `video_id`, `track_id`, `format`, `include_timestamps`, `segment_index`), `resolution.py` (AC-2's five-tier track resolution order, AC-3's language matching, manual-before-auto sort), `get_transcript.py` and `list_transcript_tracks.py` (the two tool handlers). May import `domain/`, `formats/`, `providers/base.py` — never `providers/innertube.py` directly.
- **`composition.py`** — startup wiring (`build_provider()`, `build_deadline()`), called exactly once at process start. May import `providers/innertube.py` but never `protocol/`/`tools/` — deliberately isolated from the layers that *consume* the provider it builds, so `server.py` (not this module) does the handler-registration wiring.
- **`server.py`** — process entry point. Widest import set on purpose (`composition.py`, `protocol/`, `tools/`, `domain/`). `SERVER_VERSION`/`USER_AGENT` live here literally, since `scripts/validate.sh --check-tag` greps this exact file by name.

**Tools (2):** `get_transcript` (track resolution + cursor-driven pagination + format encoding — the most complex handler, where AC-3/AC-4/AC-5/AC-7/AC-8/AC-11 all meet), `list_transcript_tracks` (lists a video's caption tracks with derived `estimatedCharacters`, never fetching track content).

## Untrusted-content boundary

Every `get_transcript` response wraps the caption text between two copies of a delimiter generated fresh, per call, from `secrets.token_hex(16)` (128 bits of entropy) — never a fixed constant. Since the caption text was authored on YouTube before this specific call's delimiter exists, an attacker cannot predict or pre-embed a matching forged copy. This closes prompt-injection-via-caption-text forgery **by construction**, not by scrubbing: `contentNotice` and the wrapped `transcript` text are two separate dict keys (never string-concatenated) so a reference parser can recover them independently — `json.loads()` the wire bytes first, then search only the parsed `transcript` value for exactly two occurrences of the value named in `contentNotice`. Six `multiexpert-review` cycles found genuine defects in an earlier fixed-sentinel design before this one replaced it; see `docs/plans/youtube-transcript/plan.md`'s "Untrusted-content boundary" section for the full history if touching `protocol/envelope.py`.

## Deadline budget

`TOOL_CALL_DEADLINE=180s` splits into a network budget and `ENCODE_RESERVE=35s` (`HTTP_TIMEOUT + CPU_PHASE_BUDGET`, reserved for the CPU-bound decode/sanitize/replay/encode phase after the last network call returns). Per-leg retry backoff is `0.5 × 2¹ + jitter(0, 0.25)` ≤ `1.25s` max. See `README.md`'s *Cost disclosures* section for the worked full-`MAX_PAGES`-read arithmetic and the four measurement-gate verdicts recorded in `docs/plans/youtube-transcript/progress.md`.

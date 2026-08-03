# AGENTS.md

This file provides guidance to AI coding agents (Cursor Agent and others) when working with code in `plugins/youtube-transcript/`.

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

**Implementation:** `plugin/server/server.py` is the process entry point (`SERVER_VERSION`/`USER_AGENT`, `build_registry()`, `main()`) for a multi-module package under `plugin/server/` — `domain/`, `net/`, `providers/`, `formats/`, `protocol/`, `tools/`, plus `composition.py`. Unlike `maven-mcp`'s single-file design, this plugin has several layers with a declared, grep-enforced dependency direction (AC-23/AC-24). It speaks MCP over stdio (JSON-RPC 2.0 on stdin/stdout) only — no HTTP transport in v1. Registered via `plugin/.claude-plugin/plugin.json` as `command: python3`.

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

See `CLAUDE.md`'s Commands section for the lint/type-check/coverage invocations and the live-canary command — kept in that file only, not duplicated here.

## Architecture

`plugin/server/` is a package of sub-packages with a one-directional dependency graph (`ALLOWED_EDGES` in `tests/test_import_boundaries.py` is the authoritative, enforced source):

- **`domain/`** — shared data types, exceptions, and policy tables. Zero imports from any other in-project package; every other package imports it, never the reverse. Owns `Transcript`, `TrackDescriptor`, `Segment`, the `Status` enum, `STATUS_POLICY`, `DomainFailure` and its 13 leaf subclasses, `CursorInvalid`, and the deadline/timeout constants (`HTTP_TIMEOUT=15`, `TOOL_CALL_DEADLINE=180`, `CPU_PHASE_BUDGET=20`, `ENCODE_RESERVE=35`, `HOST_TIMEOUT_MARGIN=30`, `DEADLINE_CHECK_STRIDE=1000`, `MAX_SEGMENTS`).
- **`net/client.py`** — the one module permitted to import `urllib.request`/`http.client`/`socket`/`ssl`/`xml.*` (enforced). `fetch()`: opener construction, scheme/host/port allowlist + redirect-rejection policy (`ALLOWED_HOSTS`, T-6a), header merge, retry/backoff with a streaming network-budget deadline check, response byte cap, cumulative gzip-bomb cap (T-6b). `HTTP_MAX_ATTEMPTS=2`. Also owns `parse_xml_guarded()` — raw `expat.ParserCreate()` with a DOCTYPE/entity sentinel.
- **`providers/`** — `base.py` (port ABCs, closed `ProviderError(DomainFailure)` hierarchy, opaque `trackId` codec) and `video_ref.py` (AC-6's URL/bare-ID normalizer, exact-hostname allowlist). `innertube.py` is the concrete implementation: watch-page GET → InnerTube player POST → timedtext GET. `base.py` may **never** import `innertube.py`.
- **`formats/`** — `text.py`/`srt.py`/`vtt.py` encoders plus `__init__.py`'s dispatch table, `Page`/`FormatOptions`, `count_pages_to()` (pagination-ceiling replay, AC-11), `estimate_characters()`. `MAX_PAGE_CHARS=50_000`, `MAX_PAGES=20`, `CHARS_PER_SECOND=15`, `CUE_OVERHEAD_FACTOR=3`.
- **`protocol/`** — `schemas.py` (`TOOL_SCHEMAS`), `envelope.py` (`ToolOutcome` → wire dict — see *Untrusted-content boundary* below), `registry.py` (`Registry`), `dispatch.py` (JSON-RPC 2.0 over stdio).
- **`tools/`** — `cursor.py` (AC-11's opaque pagination-cursor codec), `resolution.py` (AC-2's five-tier track resolution, AC-3's language matching), `get_transcript.py` and `list_transcript_tracks.py`. May import `domain/`, `formats/`, `providers/base.py` — never `providers/innertube.py` directly.
- **`composition.py`** — startup wiring (`build_provider()`, `build_deadline()`), called exactly once. May import `providers/innertube.py` but never `protocol/`/`tools/`.
- **`server.py`** — process entry point, widest import set on purpose. `SERVER_VERSION`/`USER_AGENT` live here literally, since `scripts/validate.sh --check-tag` greps this exact file by name.

**Tools (2):** `get_transcript` (track resolution + cursor-driven pagination + format encoding), `list_transcript_tracks` (lists caption tracks with derived `estimatedCharacters`, never fetching track content).

**MCPB bundle.** The bundle (`.mcpb`, see `docs/PLUGIN-STANDARDS.md` §12) ships exactly the tracked `.py` files under `plugin/server/` plus `LICENSE.md` and a generated `manifest.json` (from `plugins/youtube-transcript/mcpb/manifest.template.json`). Adding a **Python module** needs no bundle-side change. Adding a **tool** requires updating `tools` in the manifest template. Adding a **non-`.py` runtime asset** requires changing the staging allowlist in `scripts/pack-mcpb.sh` — the build fails loudly on the last case rather than shipping a bundle missing it.

## Untrusted-content boundary

Every `get_transcript` response wraps the caption text between two copies of a delimiter generated fresh, per call, from `secrets.token_hex(16)` (128 bits of entropy) — never a fixed constant, so an attacker who authored the caption text before this specific call cannot predict or pre-embed a matching forged copy. `contentNotice` and the wrapped `transcript` text are two separate dict keys (never string-concatenated), letting a reference parser recover them independently: `json.loads()` the wire bytes first, then search only the parsed `transcript` value for exactly two occurrences of the value named in `contentNotice`. See `CLAUDE.md`'s same section, or `docs/plans/youtube-transcript/plan.md`'s "Untrusted-content boundary" section for the full review history, before touching `protocol/envelope.py`.

## Deadline budget

`TOOL_CALL_DEADLINE=180s` splits into a network budget and `ENCODE_RESERVE=35s` (`HTTP_TIMEOUT + CPU_PHASE_BUDGET`). Per-leg retry backoff is `0.5 × 2¹ + jitter(0, 0.25)` ≤ `1.25s` max. See `README.md`'s *Cost disclosures* section for the worked full-`MAX_PAGES`-read arithmetic and measurement-gate verdicts.

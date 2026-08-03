# youtube-transcript

Claude Code plugin that fetches existing YouTube captions (manual or auto-generated) via the InnerTube API and returns them as plain text, SRT, or VTT. No speech-to-text, no video/audio download — only captions YouTube already publishes.

## How it works

The plugin bundles a Python 3 MCP server (`plugin/server/`) that speaks MCP over stdio (JSON-RPC 2.0 on stdin/stdout) only. It uses the Python standard library only — zero pip dependencies. The plugin manifest registers it with `command: python3`, so it runs the same way in Claude cloud and local environments with no extra runtime setup.

For a given video, the server does a watch-page GET, an InnerTube player POST (`ANDROID`/`IOS` client context), and a timedtext GET for the resolved caption track — each request restricted to an exact-hostname allowlist (`www.youtube.com`, `youtubei.googleapis.com`).

### Tools

| Tool | Description |
|------|-------------|
| `list_transcript_tracks` | List a video's caption tracks (language, manual/auto, estimated character count) without fetching any track's content |
| `get_transcript` | Fetch a video's transcript as `text` (default), `srt`, or `vtt`, with cursor-based pagination for long transcripts |

## Requirements

- **Python 3.9+** — the server uses the standard library only; no pip dependencies.

## Installation

```bash
claude plugin add /path/to/youtube-transcript/plugin
```

The plugin manifest registers the bundled server automatically; no separate install or build step is required.

## Use with any MCP client

The bundled server is a plain stdio MCP process, so any MCP-compatible agent can run it directly — no Claude Code required. The only requirement is Python 3.9+.

```bash
python3 /path/to/krozov-ai-tools/plugins/youtube-transcript/plugin/server/server.py
```

Point your agent's MCP config at that command (use the absolute path to `server.py`), same `mcpServers` shape as any stdio server:

```json
{
  "mcpServers": {
    "youtube-transcript": {
      "command": "python3",
      "args": ["/path/to/krozov-ai-tools/plugins/youtube-transcript/plugin/server/server.py"]
    }
  }
}
```

This works for Kimi Code (`~/.kimi-code/mcp.json`), Cursor (`~/.cursor/mcp.json`), Claude Desktop (`claude_desktop_config.json`) — same shape as above. For Gemini CLI (`~/.gemini/settings.json`) and Codex (`~/.codex/config.toml`), see `plugins/maven-mcp/README.md`'s *Use with any MCP client* section for the exact per-client key names; this server's `command`/`args` value is identical, only the tool name changes.

There is no HTTP transport in v1 — stdio only (see *Out of scope* in `docs/specs/2026-08-01-youtube-transcript.md` if that's needed later).

## Accepted ToS risk

YouTube's Terms of Service (youtube.com/static?template=terms, document dated 2022-01-05) explicitly prohibits "using the Service via automated means, such as bots, botnets, or scrapers" except for search-engine bots respecting `robots.txt`, YouTube's own written permission, or applicable law. This plugin's InnerTube-based caption retrieval falls under that prohibition. **The user reviewed this quote directly and decided to build and publish this plugin anyway** (public repository, `.claude-plugin/marketplace.json` entry) — this does not eliminate the legal risk, only accepts it knowingly for personal/local use at individual scale. **Trigger for reconsidering:** a takedown notice, a marketplace delisting notice, or a cease-and-desist addressed to this repository — any of these should prompt separating this plugin's distribution from `maven-mcp`'s, rather than accepting collateral loss of `maven-mcp`'s listing.

## Cost disclosures

### No-caching pagination cost (accepted, v1)

The server keeps **no cache** — every `get_transcript` call, including each page of a paginated read, does a full 3-leg fetch (watch page → InnerTube player → timedtext) plus a full decode/sanitize/replay/encode from scratch. A complete read of a transcript that needs the full `MAX_PAGES=20` pages therefore costs:

- **60 requests** (20 pages × 3 legs), up to **120 actual socket-level requests** under full retries (`HTTP_MAX_ATTEMPTS=2`).
- **20 full re-decodes** of the entire transcript (each page's handler re-parses and re-sanitizes the whole caption XML from byte one — there is no cross-call memoization).
- **O(pages²) replay cost** — each page `N` re-walks `formats.count_pages_to` from `segmentIndex=0` through page `N-1` to find its own start offset (AC-11's stateless-cursor design; no server-side session state), so total replay work across a full read grows quadratically in page count, not linearly.

This is a **disclosed, accepted cost for v1**, not an oversight: a server-side session/transcript cache would remove it but contradicts AC-11's stateless-cursor requirement (each `get_transcript` call, including continuations, must be independently resolvable from its cursor alone, with no server memory between calls). `MAX_PAGE_CHARS=50,000` (raising it reduces the page count needed for a given transcript length) is the lever if this cost proves unacceptable in practice; revisit only if real usage shows a problem — see `docs/plans/youtube-transcript/plan.md`'s Decisions Made table ("Pagination re-fetch cost").

### Computed full-`MAX_PAGES`-read cost (quantitative)

From `swarm-report/research/youtube-transcript-size-measurements.md` (T-P3)'s measured per-leg bytes/latency, projected across a full 20-page read:

| Component | Value | Source |
|---|---|---|
| Total logical requests | 60 (20 pages × 3 legs) | derived |
| Total socket-level requests (worst case, full retries) | up to 120 | `HTTP_MAX_ATTEMPTS=2` |
| Network wall-time | ≈42.5s | leg1 p50=0.989s × 20 (**measured**) + leg3 p50=0.146s × 20 (**measured**) + leg2 ≈0.99s × 20 (**assumed**, comparable order of magnitude to leg1 — leg2 could not be live-reproduced this pass, see T-P3 §2) |
| CPU-phase wall-time | ≈9.86s | **measured** directly (pages 1/5/10/15/20 sampled, 5 reps each, tracemalloc off; average 0.493s/page × 20) |
| **Grand total wall-time** | **≈52.4s** | 42.5s + 9.86s — comfortably under `TOOL_CALL_DEADLINE=180s`, though the network component carries real uncertainty from the unmeasured leg-2 assumption |
| Total bytes (leg 1 only) | ≈6.16 MB compressed (gzip) / ≈26.6 MB inflated | **live-derived**: 20 × 307,828 bytes compressed / 20 × 1,332,030 bytes inflated (single-request p50 × 20) |
| Total bytes (legs 2/3) | unmeasured | live caption content could not be captured this pass — see T-P3 §3 |

## Measurement gates (release-blocking, checked against T-P3's recorded data)

Full detail and re-derivable arithmetic live in `docs/plans/youtube-transcript/progress.md`'s Learnings section (T-16 entry) and `docs/plans/youtube-transcript/tasks.md`'s T-16 acceptance text. Summary:

1. **Pagination ceiling** (3-hour srt fits within `MAX_PAGES=20` at `MAX_PAGE_CHARS=50,000`) — **PASS**, large margin either way: formula-based (`CHARS_PER_SECOND × CUE_OVERHEAD_FACTOR = 45` chars/sec) gives 10 pages; T-P3's synthetic-content measurement (~30 chars/sec) gives 7 pages. Neither figure is an independently verified real-caption rate (T-P3 could not fetch live caption content this pass), so this is the strongest available evidence, not a fully closed measurement.
2. **`HTTP_TIMEOUT` tuning inequality** — **PASS**. `HTTP_MAX_ATTEMPTS(2) × 3 legs × HTTP_TIMEOUT(15) + 3 × max_backoff(1.25) = 93.75s ≤ TOOL_CALL_DEADLINE(180) - ENCODE_RESERVE(35) = 145s` (51.25s margin). `HTTP_TIMEOUT(15s) ≥` measured p95 of the two measured legs (leg1 1.081s, leg3 0.161s); leg2's true p95 remains unmeasured.
3. **CPU-phase budget** (`p95(CPU phase) ≤ CPU_PHASE_BUDGET`) — **PASS**. Measured p95 = 0.431s vs. `CPU_PHASE_BUDGET=20s` (~46x margin), on a dev laptop, not yet the CI matrix runner tasks.md specifies.
4. **MCP host tool-call timeout** (`≥ TOOL_CALL_DEADLINE(180) + HOST_TIMEOUT_MARGIN(30) = 210s`) — **UNMEASURED / explicitly deferred**. No sandbox this session had could invoke a real out-of-process MCP host to probe this. Falls back to the `maven-mcp` precedent (`TOOL_DEADLINE=30s`) as a documented, conservative starting value, per T-P3's own sanctioned fallback. Needs a real probe before this is a closed gate.

## Caching

The server keeps no cache of any kind, on disk or in memory across calls — see *No-caching pagination cost* above.

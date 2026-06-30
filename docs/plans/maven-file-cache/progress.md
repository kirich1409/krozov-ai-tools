# Progress: maven-mcp persistent file cache (#307)

> Plan: ./plan.md · Tasks: ./tasks.md · Branch feat/maven-file-cache (off main@1cefbab)

## Status
- [x] T-1 — FileCache primitive + unit tests
- [x] T-2 — http_get_cached seam + wire Maven read call sites + exclusion/integration tests
- [x] T-3 — docs (CLAUDE.md) + L5 smoke + open PR

## Learnings
- T-1: eviction test must check cache FILE existence (not call `get()`) to stay independent of wall-clock TTL vs synthetic `_now` timestamps.
- T-2: `_verify_one` existence probe already bypassed `http_get_cached` by calling raw `http_get`; the `use_cache=False` flag on `search_maven_central` handles the suggestion-search side.
- T-3: L5 smoke run 2026-06-30; all checks passed (see transcript below).

## L5 Smoke Transcript (2026-06-30)

```
Script: direct import of server module with real network; XDG_CACHE_HOME pinned to tmpdir;
        http_get patched with a call counter (does not alter behavior).

[PASS] fetch_metadata latest version: 4.13.2
[PASS] call 1 (network): 117ms, http_get calls=1
[PASS] call 2 (cache):   1ms,   http_get calls=1 (delta=0)
[PASS] second fetch_metadata was a cache hit (no additional http_get)
[PASS] results identical
[PASS] 1 cache file(s) on disk under XDG_CACHE_HOME
[PASS] 2x query_osv_batch: 0 http_get calls; cache count unchanged (1)

L5 smoke: ALL CHECKS PASSED
```

Test suite: `python3 -m unittest discover -s plugins/maven-mcp/tests` → **334 tests, 0 failures** (303 baseline + 31 new cache tests).
Validate: `bash scripts/validate.sh` → **All checks passed** (rc=0).

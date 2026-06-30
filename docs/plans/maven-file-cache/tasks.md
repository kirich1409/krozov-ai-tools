# Tasks: maven-mcp persistent file cache (#307)

> Plan: ./plan.md · One PR (branch `feat/maven-file-cache`, off main@1cefbab = post-#306). Baseline =
> 303 tests. stdlib-only; NO new dependencies. All shipped content English. Do not refactor
> unrelated handlers — add the cache layer + wire the 4 Maven read call sites only.

## T-1 — FileCache primitive + unit tests
- after: none
- files: `plugins/maven-mcp/plugin/server/server.py`, `plugins/maven-mcp/tests/_helpers.py`,
  `plugins/maven-mcp/tests/test_file_cache.py`
- acceptance: THE SYSTEM SHALL add a `FileCache` class (or equivalent module-level functions) to
  server.py, stdlib-only (new imports `hashlib`, `tempfile`, `time`, `base64`), with:
  - **dir resolution:** `${XDG_CACHE_HOME}/maven-central-mcp` else `~/.cache/maven-central-mcp`;
    created lazily with `os.makedirs(mode=0o700, exist_ok=True)` followed by an explicit
    `os.chmod(cache_dir, 0o700)` on the LEAF dir only (makedirs' mode is umask-masked and ignored
    when the dir pre-exists). Both inside the degrade-to-no-op try/except.
  - **key:** `hashlib.sha256(url.encode("utf-8")).hexdigest()` → path `{dir}/{hash}.json`. Add a
    code comment that the key intentionally excludes headers (safe: uniform UA on all callers).
  - **entry JSON:** `{"v":1,"url":url,"status":200,"body_b64":base64(body),"ts":_now()}`.
  - **`get(url, ttl) -> Optional[Tuple[int,bytes]]`:** returns `None` (miss) on
    missing/unreadable/corrupt JSON/`OSError` (never raises), on `_now()-ts > ttl` (strictly `>`, so
    exactly-at-ttl is a HIT), and on stored `url` ≠ requested `url`; otherwise `(status, body_bytes)`.
  - **`set(url, status, body)`:** writes ONLY when `status == 200`; atomic via `tempfile.mkstemp`
    in the SAME dir + `os.replace`; file `mode 0o600`; swallows `OSError` but LOGS one line on the
    swallow path via a module-level `logging.getLogger("maven_mcp")` whose `StreamHandler` targets
    `sys.stderr` (stdlib `logging`, NOT `print`; this is the file's first logger — handler MUST be
    stderr, never stdout = JSON-RPC channel). Set `logger.propagate = False` and guard against adding
    the handler twice on module re-import, so a future root `basicConfig` can't double-emit.
  - **eviction:** module constant `CACHE_MAX_ENTRIES = 2000`; policy = FIFO by write time
    (best-effort soft cap); on `set`, when entry count exceeds the cap, delete oldest-by-`mtime`
    down to ~90% of the cap, each per-file `os.unlink` swallowing `OSError`/`FileNotFoundError`.
  - **disable:** `MAVEN_MCP_CACHE_DISABLE` truthy → `get` always miss, `set` no-op — read
    **per operation** from `os.environ` (NOT memoized at import); also degrade to no-op if the dir
    can't be created/written.
  - **injectable clock:** module-level `_now = time.time`.
  - Add a `temp_cache_dir` contextmanager to `_helpers.py` using
    `unittest.mock.patch.dict("os.environ", {...})` to pin `XDG_CACHE_HOME` to a fresh
    `tempfile.TemporaryDirectory` AND clear `MAVEN_MCP_CACHE_DISABLE` (guaranteed restore); add it to
    `__all__`.
- check: `test_file_cache.py` (stdlib unittest; `import unittest.mock` + fully-qualified refs — NO
  mixed `import unittest`/`from unittest import …`; no unused imports). Cases: miss-then-set-then-hit
  returns identical bytes; **TTL boundary both sides** via monkeypatched `_now` — get at exactly
  `t0+ttl` → HIT, get at `t0+ttl+1` → miss (pins `>` not `>=`); corrupt entry (write `"{garbage"` to
  the computed cache file) → `get` None, no raise; `status != 200` (404) → `set` writes nothing;
  `(200, b"")` empty body → set+get returns identical `b""` (NOT a miss); `url`-mismatch (stored
  `url` ≠ requested at same path) → miss; `XDG_CACHE_HOME` honored (file under the temp dir); perms
  under a PINNED umask (`os.umask(0o077)` save/restore) → `stat` file `0o600`, dir `0o700`;
  **pre-existing loose-perm dir** — pre-create `maven-central-mcp` at `0o777` (makedirs+`chmod`)
  BEFORE cache init, then assert init tightens the LEAF to `0o700` (this is the case that actually
  exercises the explicit `chmod`; the fresh-dir umask test passes even if the `chmod` is deleted);
  **set-swallow channel safety** — force `os.replace`/temp-write to raise inside `set`, capture BOTH
  streams, assert `set` does NOT raise, `stdout == ""` (the load-bearing assertion), and the warning
  lands on stderr. NOTE: `StreamHandler(sys.stderr)` binds the stream at construction (import time),
  so `redirect_stderr`/`capsys` won't capture it — assert the stderr half against `handler.stream`
  directly (or `handler.setStream(buf)` for the duration), not via `redirect_stderr`;
  **disable truthiness** — `"1"/"true"/"yes"/"on"` (case-insensitive) disable; `"0"/"false"/""` do
  NOT disable; eviction (insert > cap) asserts INVARIANTS only — count ≈90% cap and the newest entry
  survives (do NOT assert a specific mtime-tie victim; if a specific victim is needed, set distinct
  mtimes via `os.utime`); `MAVEN_MCP_CACHE_DISABLE` toggled on the already-imported module → honored
  per-call (`get` miss after a `set`, no file written); atomic write leaves no `*.tmp` residue and
  the final file is complete JSON.

## T-2 — http_get_cached seam + wire Maven read call sites + exclusion/integration tests
- after: T-1
- files: `plugins/maven-mcp/plugin/server/server.py`,
  `plugins/maven-mcp/tests/test_file_cache.py` (or `test_handlers.py` for integration)
- acceptance: THE SYSTEM SHALL add `http_get_cached(url, ttl_seconds) -> Tuple[int,bytes]` (NO
  `headers` param) layered above `http_get`. Sensitive-host exclusion is by call-site discipline
  (only the 4 Maven fns call it; their URLs all come from `_repos_for`), NOT a host allowlist; as
  belt-and-suspenders the wrapper bypasses to raw `http_get` uncached when the URL host is in a
  static DENYLIST (`api.github.com`, `api.osv.dev`) — needs no `ctx`, so private/project-declared
  repos are still cached. On a cache hit return `(200, body)` WITHOUT calling `http_get`; on a miss call
  `http_get` (which retries per #306), and `set` the result ONLY when status is `200`; a non-200 or a
  propagating transport error is NOT cached (transport error propagates exactly as `http_get` does
  today). Add TTL constants `TTL_POM` (7d), `TTL_METADATA` (1h), `TTL_SEARCH` (1h). Add a
  `use_cache: bool = True` parameter to `search_maven_central`. Wire EXACTLY these call sites,
  preserving each function's current return contract:
  - `fetch_metadata` metadata GET → `http_get_cached(url, TTL_METADATA)`.
  - `check_version_in_repos` metadata GET → `http_get_cached(url, TTL_METADATA)`.
  - `fetch_pom` POM GET → `http_get_cached(url, TTL_POM)`.
  - `search_maven_central` GET → `http_get_cached(url, TTL_SEARCH)` when `use_cache` else raw `http_get`.
  - `handle_search_artifacts` calls `search_maven_central(...)` (cached); `_verify_one` calls
    `search_maven_central(..., use_cache=False)` (LIVE).
  Do NOT route through the cache: `query_osv_batch` (OSV/POST — stays `http_post_json`), `_gh_get` /
  `gh_repo_exists` (GitHub — stay `http_get`), `_verify_one`'s existence probe (stays raw `http_get`)
  AND its suggestion search (`use_cache=False`).
- check: integration tests (mock `urllib.request.urlopen`, `temp_cache_dir`). Positive cases use
  `200` bodies so #306 retry does not inflate counts: (1) two consecutive `fetch_metadata(g,a,ctx)`
  → `urlopen` ONCE (second from disk), bytes identical; (2) same for `fetch_pom` and the
  `handle_search_artifacts` search path; (3) one hit test additionally patches `server.http_get` and
  `assert_not_called` on the second call (pins the hit short-circuits above the retry). **Exclusion
  proofs, each with a POSITIVE CONTROL in the same fixture** (a `fetch_metadata` that IS cached =
  cache proven live): (4) two `query_osv_batch` → POST `urlopen` TWICE (never cached); (5) two
  GitHub `_gh_get`/`gh_repo_exists` → `urlopen` TWICE; (6) two `_verify_one` for the same coord →
  BOTH its existence probe AND its did-you-mean search hit the network each call (`urlopen` per
  call; `search_maven_central` invoked with `use_cache=False`). (7) not-cached-non-200: patch
  `server._sleep`; a `404` (single attempt) Maven metadata → not cached, no file, second call hits
  network again; a `503` → retried `HTTP_MAX_ATTEMPTS`× per call, not cached. (8) a propagating
  transport error from `http_get` → no cache file written + exception propagates unchanged.
  (9) `MAVEN_MCP_CACHE_DISABLE=1` (set on the live module) → `fetch_metadata` hits the network every
  call. (10) **private/project-declared repo IS cached** — a `fetch_metadata` whose `ctx` resolves a
  custom `maven { url }` host → second call served from cache (`urlopen` ONCE), proving the
  call-site-discipline path caches non-public Maven hosts. (11) **denylist bypass** — call
  `http_get_cached` directly with an `api.github.com`/`api.osv.dev` URL → not cached (no file written,
  second call hits network).

## T-3 — docs + L5 smoke + open PR
- after: T-2
- files: `plugins/maven-mcp/CLAUDE.md`, `docs/plans/maven-file-cache/progress.md`
- acceptance: THE SYSTEM SHALL update the plugin `CLAUDE.md` cache description (replace the
  "No persistent cache" line ~106) to document: the persistent file cache (dir + `XDG_CACHE_HOME` +
  `MAVEN_MCP_CACHE_DISABLE`), what is cached (metadata/POM/search-handler) with TTLs, and the
  explicit exclusions (OSV never cached — security; GitHub not cached; the whole `verify_coordinates`
  path — existence probe AND did-you-mean search — stays live; `check_version_exists` inherits a ≤1h
  staleness window). An L5 stdio
  smoke confirms a repeated Maven read is served from cache (cache file present; no second network
  call) and that an OSV query is not cached. Then open a ready PR (`Closes #307`, link the plan, note
  the security exclusion of OSV and that #308 GitHub/changelog caching is separate).
- check: `bash scripts/validate.sh` rc=0; full suite green (303 + new) on 3.9/3.13; `compileall`
  clean; L5 transcript in progress.md; PR open with `python-tests (3.9)/(3.13)` + `validate-marketplace`
  green and no CodeQL review threads.

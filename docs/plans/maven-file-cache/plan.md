---
type: plan
slug: maven-file-cache
date: 2026-06-30
status: approved
spec: none
risk_areas:
  - "serving stale security data (OSV vulnerability results) from cache"
  - "path traversal / unsafe cache file paths"
  - "torn/corrupt cache files breaking requests"
  - "stale 'latest version' answers from over-long metadata TTL"
  - "unbounded cache growth"
review_verdict: PASS
---

# Plan: maven-mcp persistent file cache (#307)

## Context & Decision

The #302 TS→Python port dropped the persistent on-disk cache. The shipped runtime
(`plugins/maven-mcp/plugin/server/server.py`, Python 3.9+, stdlib-only, stdio MCP) now has only
a single in-memory dict (`metadata_cache`, local to `handle_audit_project_dependencies`) that lives
for one handler call. Every other lookup re-hits the network on every call and across sessions.

**Decided change:** re-add a persistent file cache for the **Maven read paths** (version metadata,
POM, search), backed by a small stdlib `FileCache` primitive, with TTLs per resource class and an
explicit, reviewed exclusion of all security-sensitive data.

**Important scope clarification surfaced during investigation.** The retired TS `FileCache`
(`src/cache/file-cache.ts`) was wired **only** into the changelog providers (AGP/AndroidX/GitHub),
which were themselves dropped in #302 (tracked separately as #308). It never cached Maven
metadata/version/search/OSV. So this work **ports the TS storage primitive** (key handling, atomic
write, owner-only permissions, TTL) and applies it to the Maven read call sites that #307 names —
it is *not* a literal 1:1 re-wiring of the TS consumers.

## Technical Approach

Two pieces, both inside `server.py` (no package tree, stdlib-only):

1. **A `FileCache` primitive** — opaque key/value bytes cache on disk, ported from the TS design
   with its security properties preserved (atomic writes, owner-only perms, traversal-proof keys)
   plus a bounded-growth cap the TS version lacked.

2. **A `http_get_cached(url, ttl_seconds) -> (int, bytes)` seam** layered *above* `http_get`. A hit
   returns `(200, body)` and skips the network entirely (including the #306 retry); a miss calls
   `http_get` (which retries transient failures per #306) and caches **only** a `200` response. This
   wrapper is wired into the Maven read functions and **nowhere else**. It takes **no `headers`
   parameter** — every wired call site uses `http_get`'s default UA-only headers, and accepting
   headers that are not folded into the cache key would be a latent footgun (an auth-bearing GET
   would collide on key with an unauthenticated one and persist a credential-bearing body).

   **What keeps sensitive paths out of the cache is call-site discipline, not a host filter.** Only
   the four Maven read functions call `http_get_cached`, and every URL they build comes from a
   `_repos_for(...)` entry — so only Maven-repo hosts (Central / Google / Gradle Plugin Portal /
   project-declared repos) ever reach the seam. OSV is a POST (never wrapped); GitHub and the verify
   probe never call the wrapper. A host-*allowlist* was considered and rejected: the seam signature
   is `(url, ttl_seconds)` with no `ctx`, so it cannot know the dynamic project-declared hosts, and a
   static allowlist would silently stop caching private repos. As cheap belt-and-suspenders the
   wrapper instead applies a tiny static **denylist** — if the URL host is `api.github.com` or
   `api.osv.dev` it bypasses to `http_get` uncached (needs no `ctx`; catches a future accidental
   mis-wiring of a sensitive host without breaking private-repo caching).

### Why cache at the per-function layer, not at `http_get`

`http_get` is the single GET chokepoint for Maven metadata/POM/search **and** GitHub API calls and
the `verify_coordinates` existence probe. Caching at `http_get` would silently cache all of them.
Instead we add an explicit `http_get_cached` wrapper and call it only from the Maven read functions.
This makes every cached surface a deliberate, reviewable choice and excludes the sensitive paths by
construction:

| Path | Function(s) | Method | Cached? | Why |
|---|---|---|---|---|
| Version metadata | `fetch_metadata`, `check_version_in_repos` | GET | **Yes** (short TTL) | mutable (grows); keep "latest" fresh |
| POM | `fetch_pom` | GET | **Yes** (long TTL) | release POMs are immutable once published |
| Search (from `handle_search_artifacts`) | `search_maven_central(..., use_cache=True)` | GET | **Yes** (short TTL) | results drift slowly |
| **OSV vulnerabilities** | `query_osv_batch` | POST | **NEVER** | stale "no CVE" after a new advisory is a security failure; also POST, so never wrapped |
| GitHub API | `_gh_get`, `gh_repo_exists` | GET | **No** | token-bearing, rate-limited, time-sensitive (health/issue stats) |
| `verify_coordinates` existence probe | `_verify_one` raw `http_get` | GET | **No** | security tool must stay live — a cached "absent" must not mask a newly-published typosquat |
| `verify_coordinates` did-you-mean search | `_verify_one` → `search_maven_central(..., use_cache=False)` | GET | **No** | the suggestion set feeds `likelyHallucination`; must stay live so a just-published typosquat target surfaces as a candidate |

### FileCache design (ported from TS, adapted to stdlib)

- **Cache dir:** `${XDG_CACHE_HOME}/maven-central-mcp` if set, else `~/.cache/maven-central-mcp`
  (matches the retired TS path). Created lazily with `os.makedirs(mode=0o700, exist_ok=True)` —
  **and then an explicit `os.chmod(cache_dir, 0o700)` on the leaf dir only** (never the shared
  parent), because `makedirs`' `mode` is umask-masked and is ignored entirely when the dir already
  exists, so a pre-existing loose-perm dir (e.g. an `XDG_CACHE_HOME` pointed at a shared `/tmp`
  location) would otherwise stay world-readable. Both the makedirs and the chmod run inside the
  degrade-to-no-op `try/except`.
- **Key:** `hashlib.sha256(url.encode("utf-8")).hexdigest()` → file `{dir}/{hash}.json`. Hashing
  makes the on-disk path traversal-proof *by construction* (chosen over porting TS's path-segment
  validation, since we key on opaque URLs, not logical path keys). The resolved repo URL is part of
  the URL, so the same coordinate against different repos keys differently — no cross-project bleed.
  **The key intentionally excludes request headers** — safe because every wired caller uses uniform
  UA-only headers (documented in a code comment so a future varying-header caller is a conscious
  decision, not a silent collision).
- **Entry (JSON):** `{"v": 1, "url": <url>, "status": 200, "body_b64": <base64>, "ts": <epoch>}`.
  Only `status == 200` is ever written. Body bytes are base64-encoded for JSON. `url` is stored and
  re-checked on read; a mismatch (astronomically unlikely SHA-256 collision) is treated as a miss.
- **`get(url, ttl) -> Optional[(int, bytes)]`:** read+parse; missing/corrupt/`OSError` → `None`
  (miss, never raise); `_now() - ts > ttl` → `None`; `url` mismatch → `None`; else `(status, body)`.
- **`set(url, status, body):`** only for 200. Atomic: `tempfile.mkstemp` in the **same** dir →
  write → `os.replace` to final path; `os.chmod(..., 0o600)`. Any `OSError` is swallowed so a disk
  problem never breaks a request — but **not silently**: log a single one-line warning so a
  read-only/full/poisoned cache dir is operationally visible. `server.py` currently has **no logging
  infrastructure**; this introduces the file's first logger — a module-level
  `logging.getLogger("maven_mcp")` with a `logging.StreamHandler(sys.stderr)` (stdlib `logging`, not
  `print`, per the global logging policy; the handler MUST target **stderr** — stdout is the
  JSON-RPC channel and any byte there corrupts the protocol). Opportunistic eviction (below).
- **Bounded growth (beyond TS, which never evicted):** `CACHE_MAX_ENTRIES = 2000` cap; on `set`, if
  the entry count exceeds the cap, delete oldest entries down to ~90% of the cap. Policy is
  **FIFO by write time (best-effort, soft cap under concurrency)** — eviction sorts by file `mtime`
  and `get` never touches `mtime`, so this is FIFO-by-write, *not* LRU (acceptable for a best-effort
  cache). Each per-file `os.unlink` in the eviction loop swallows `OSError`/`FileNotFoundError`
  individually, so a second server instance deleting the same victim, or a file vanishing mid-scan,
  never raises.
- **Disable:** `MAVEN_MCP_CACHE_DISABLE` set to a truthy value → full no-op (`get` always misses,
  `set` does nothing). Truthiness is **explicitly defined**: case-insensitive `"1"`, `"true"`,
  `"yes"`, `"on"` disable; everything else — including `"0"`, `"false"`, empty, unset — leaves the
  cache enabled (avoids the `os.environ.get(...)`-non-empty footgun where `"0"` would disable).
  Also degrade to no-op if the cache dir cannot be created/written.
- **Injectable clock:** module-level `_now = time.time` so TTL tests don't sleep.
- **No in-flight coalescing** (the TS cache had it). Justified: the MCP dispatch loop (`main()`) is
  strictly sequential single-threaded (`for line in sys.stdin: dispatch(...)`), so there are no
  concurrent in-process identical requests to coalesce; coalescing is an in-memory concern
  orthogonal to a persistent file cache and would not help a cross-process cold burst anyway.

### TTLs (named constants — reviewer may tune)

- `TTL_POM = 7 * 86400` (7 days) — release POMs are immutable once published, so a long TTL is safe
  for *content*; capped at 7 days (not 30) to bound how long a **yanked** artifact would still read
  as available. Cached existence/POM availability is an efficiency signal, **not** a security
  signal — the authoritative security checks (OSV, and the live `verify_coordinates` probe) are
  never cached, so yank-detection latency on this path is accepted.
- `TTL_METADATA = 3600` (1 hour) — version lists grow; short TTL keeps "latest version" answers
  current while still cutting repeated lookups within a work session.
- `TTL_SEARCH = 3600` (1 hour) — applies only to `handle_search_artifacts`; the `verify_coordinates`
  did-you-mean search bypasses the cache (`use_cache=False`).
- `check_version_in_repos` reuses `TTL_METADATA`, so `check_version_exists` inherits a ≤1h staleness
  window (a just-published version may read as not-present for up to an hour). Accepted: it is a
  convenience "does this version exist" query, not on the anti-typosquat path.

## Affected Modules & Files

| Path | Change type | Note |
|---|---|---|
| `plugins/maven-mcp/plugin/server/server.py` | modify | add `FileCache` + `http_get_cached` + constants + new stdlib imports (`hashlib`, `tempfile`, `time`, `base64`, `logging`); the first module logger (→ stderr); `use_cache` param on `search_maven_central`; wire 4 Maven read call sites |
| `plugins/maven-mcp/tests/_helpers.py` | modify | add a `temp_cache_dir` fixture (tempdir + env override + restore) |
| `plugins/maven-mcp/tests/test_file_cache.py` | add | unit tests for the primitive + seam |
| `plugins/maven-mcp/tests/test_handlers.py` (or a new integration test) | modify | integration: second Maven read served from cache; OSV/GitHub/verify NOT cached |
| `plugins/maven-mcp/CLAUDE.md` | modify | replace the "No persistent cache" line (~106) with the new behavior; note the exclusions |

## Decisions Made

1. **Cache at the per-function layer via `http_get_cached`, not at `http_get`** — every cached
   surface is an explicit call-site choice; OSV/GitHub/verify excluded by construction. (Rationale
   above.)
2. **OSV vulnerability results are never cached** — the security non-negotiable. Enforced
   structurally: `query_osv_batch` uses `http_post_json`, which is never wrapped.
3. **GitHub API responses are not cached** — token-bearing, rate-limited, time-sensitive. A future
   short-TTL GitHub cache can be a separate decision; out of scope here.
4. **The entire `verify_coordinates` path stays live** — both the existence probe (raw `http_get`)
   **and** the did-you-mean suggestion search (`search_maven_central(..., use_cache=False)`). The
   anti-typosquat tool must read live state end-to-end: a cached "absent" must not mask a
   newly-published typosquat, and the suggestion set (which feeds `likelyHallucination`) must not be
   up to an hour stale. `search_maven_central` gains a `use_cache: bool = True` parameter; only
   `handle_search_artifacts` caches.
5. **`http_get_cached` takes no `headers` parameter; sensitive paths excluded by call-site
   discipline + a static denylist (no allowlist)** — keys are `sha256(url)` only and headers are not
   folded in; accepting a `headers` arg would be a dead, dangerous surface (auth-bearing GET → key
   collision + credential body on disk). Only the four Maven read functions call the wrapper and
   their URLs all come from `_repos_for(...)`, so only Maven-repo hosts reach it. A host *allowlist*
   was rejected (the `(url, ttl)` seam can't see dynamic project-declared hosts; a static allowlist
   would silently stop caching private repos); instead a tiny static **denylist**
   (`api.github.com`, `api.osv.dev`) bypasses caching with no `ctx` needed. (Convergent finding from
   all three reviewers; allowlist→denylist correction from cycle-2 arch + test.)
6. **Keys are `sha256(url)`** — traversal-proof by construction; `url` re-checked on read.
7. **Only `200` responses are cached** — `404`/`5xx`/transient/`unknown` are never written, so the
   tri-state contract and offline behavior are unchanged on a miss.
8. **Atomic writes + `0o700`/`0o600` perms, with an explicit leaf-dir `chmod`** — ported from TS
   (cache files may sit on shared systems); torn files are impossible, entries are owner-only, and
   the leaf dir is forced to `0o700` even if it pre-existed with looser perms.
9. **OSError on `set` is swallowed but logged to stderr** — fail-open (safe: a miss falls back to
   fresh network data) but never silent (logging policy).
10. **Bounded growth via `CACHE_MAX_ENTRIES = 2000`, FIFO-by-write** — improvement over the TS
    cache, which grew forever; per-file unlink is concurrency-tolerant.
11. **Disable env + fail-open to no-op** — `MAVEN_MCP_CACHE_DISABLE` is read **per operation** (not
    memoized at import) so it can be toggled at runtime; the cache also degrades to no-op when the
    disk is unavailable.
12. **Eviction reads the dir on each `set` to count entries** — a `scandir` per write; negligible at
    `CACHE_MAX_ENTRIES = 2000` small files; accepted (not optimized).

## Threat model (cache trust boundary)

The cache **trusts the local cache directory**. A process that can write to
`$XDG_CACHE_HOME/maven-central-mcp` could plant a JSON entry whose stored `url` matches a requested
URL and have a forged Maven body served as a hit — the `url` re-check is a collision guard, **not**
integrity protection against an attacker who controls the files. This is the standard "local
filesystem write access = already compromised" model and is **out of scope**; the mitigations are
the owner-only `0o700`/`0o600` perms and the explicit leaf-dir `chmod` (and, on a foreign-owned
pre-existing dir, the `chmod` fails → the cache fails open to no-op, the safe outcome). The denylist
and the `_repos_for`-only call discipline are defense-in-depth, not a trust boundary — project build
files can already declare arbitrary repo hosts that the *live* path fetches unauthenticated today,
so caching those (no auth header, full-URL key) adds no leak or SSRF surface beyond existing
behavior.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Stale security data (OSV) masking a fresh CVE | OSV never cached (structural — POST path never wrapped); asserted by test |
| Stale "latest version" | short `TTL_METADATA` (1h); POM long-TTL only because release POMs are immutable |
| Path traversal via crafted URL | key is `sha256(url)` hex — cannot contain path separators |
| Torn/corrupt cache file breaks a request | atomic `mkstemp`+`os.replace`; corrupt/`OSError` on read → miss, never raise |
| Caching an error body | only `status == 200` is written |
| Unbounded disk growth | `CACHE_MAX_ENTRIES` eviction on `set` |
| Caching token-bearing GitHub responses to disk | GitHub not cached at all |
| Future auth-bearing GET routed through the cache (key collision + credential on disk) | `http_get_cached` has no `headers` param; call-site discipline (only `_repos_for` URLs reach it) + static denylist (`api.github.com`/`api.osv.dev`) |
| Pre-existing cache dir with loose perms (shared `XDG_CACHE_HOME`) | explicit `os.chmod(leaf_dir, 0o700)` after `makedirs` |
| Stale did-you-mean candidates masking a fresh typosquat target | `verify_coordinates` suggestion search bypasses the cache (`use_cache=False`); existence probe also live |
| Yanked artifact still reported "available" | `TTL_POM` capped at 7d; existence/POM is a non-security signal (OSV/verify are authoritative + live) |
| Disk unavailable / read-only FS | `set` swallows `OSError` (logged to stderr); cache degrades to no-op |

## Verification & Sources

- **Source of truth for "done":** this plan + issue #307's requirements + the **security
  constraint** that vulnerability data is never cached. There is no separate spec; the cacheable
  set and the exclusions in the table above are the acceptance contract. The retired TS
  `file-cache.ts` (git history before `c438680`) is the reference for the storage primitive's
  design (key handling, atomic write, perms, TTL).
- **Testing strategy (pyramid):**
  - **L0 Build:** `python3 -m compileall plugins/maven-mcp/plugin/server/server.py` clean on 3.9 & 3.13.
  - **L1 Static:** `bash scripts/validate.sh` rc=0; CodeQL clean (no `py/illegal-raise`, no
    path-injection, no `import`+`from import` mix in tests).
  - **L2 Unit:** new `test_file_cache.py` + integration assertions (full list in `tasks.md`):
    hit/miss; **TTL boundary both sides** (`_now=t0+ttl` → HIT, `t0+ttl+1` → miss, pinning `>` not
    `>=`); atomic-write leaves no temp/torn file; corrupt-entry→miss (no raise); only-200-cached;
    `(200, b"")` empty-body round-trips identically (not a miss); `url`-mismatch→miss;
    `XDG_CACHE_HOME` honored; `0o600` file + `0o700` dir perms under a **pinned umask**
    (`os.umask(0o077)` save/restore); eviction asserts **invariants** (count ≈90% cap, newest
    survives — not a specific mtime-tie victim); `MAVEN_MCP_CACHE_DISABLE` read **per-operation**
    (toggled on the already-imported module). The **exclusion** assertions each carry a **positive
    control** under the *same* fixture: a repeated `fetch_metadata` hits the network **once** (proves
    the cache is live) paired with a repeated `query_osv_batch` hitting the network **every time**
    (never cached); likewise GitHub not cached, and **both** `_verify_one`'s existence probe and its
    did-you-mean search hit the network each call. Retry-aware counting: caching/exclusion positive
    cases use `200` bodies (no #306 retry → exact counts); the not-cached-non-200 case patches
    `server._sleep`, splits `404` (single attempt) from `503` (retried `HTTP_MAX_ATTEMPTS`×), and
    asserts no cache file was written. One hit test patches `server.http_get` and `assert_not_called`
    to pin that the hit short-circuits *above* the retry. `temp_cache_dir` pins both
    `XDG_CACHE_HOME` and `MAVEN_MCP_CACHE_DISABLE` via `mock.patch.dict` so no ambient value causes a
    vacuous pass.
  - **L5 smoke:** a stdio run showing a second identical Maven read served from cache (no second
    network call) and an OSV query always going to the network.
- This is an additive behavior change (new caching), not a "must not change behavior" migration, so
  no before-state baseline capture is required; the existing suite (303 tests after #306) plus the
  new tests are the regression guard.

## Out of Scope

- Re-adding the changelog providers (AGP/AndroidX/GitHub) and their caching — that is #308.
- A GitHub API cache (token-bearing, rate-limited) — possible future short-TTL decision.
- Caching the `verify_coordinates` probe.
- Caching OSV/vulnerability results under any TTL.
- The #306 retry behavior (separate PR #327, merged); this plan layers above it.

## Open Questions

_None blocking._ (non-blocking) TTL magnitudes are reviewer-tunable; the structure does not depend
on the exact numbers.

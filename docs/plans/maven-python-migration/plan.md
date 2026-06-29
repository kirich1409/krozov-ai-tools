---
type: plan
slug: maven-python-migration
date: 2026-06-29
status: approved
spec: none
risk_areas: [data-migration]
review_verdict: conditional
review_blockers: []
review_note: "2 cycles (architecture/devops/pr-test-analyzer). Cycle 1 FAIL → cycle 2 CONDITIONAL, all major/minor improvements folded in (6 divergences incl. 2 correctness regressions, release.yml/codeql/pr-template scope, ruleset two-step, coverage-map partial bucket). No remaining blockers."
---

# Plan: maven-mcp — Python as the single source of truth

> Built on current `main` (includes #303 npm-publish removal, #304 routing, #305 server.py version-sync in `validate.sh --check-tag`). Branch `chore/maven-python-tests` is rebased onto it.

## Context & Decision

The shipped maven-mcp runtime is `plugins/maven-mcp/plugin/server/server.py` (Python 3, stdio-only, stdlib-only, 1910 lines) — but it has **zero automated tests**. The TypeScript `plugins/maven-mcp/src/` is fully tested (407 vitest cases / 47 files) yet is **not shipped** (reference only). The two implementations have diverged (e.g. `compare_dependency_versions` no-match: server.py handles it cleanly, TS has the issue #263 non-null-assertion bug). The user has decided: **Python is the source of truth.** This plan makes server.py the only implementation with real coverage, then retires the TS reference. It is a two-PR migration (PR A: Python tests + CI; PR B: remove TS + fix all TS-coupled pipelines) — the HOW of an already-decided change.

## Technical Approach

**Test framework: Python stdlib `unittest`** (no pip dependency). Tests live dev-only at `plugins/maven-mcp/tests/`, import `server` via a `sys.path` shim that resolves `plugin/server/` from `__file__` (not cwd) in a shared `tests/_helpers.py`. Run with `python3 -m unittest discover -s plugins/maven-mcp/tests`. `import server` is safe (tail `if __name__ == "__main__": main()` guard, verified :1908). Preserves the zero-runtime-dependency ethos; no install step in CI.

**Network seam = `urllib.request.urlopen`** (server.py calls it as a module attribute at :92/:105 — verified, so `unittest.mock.patch("urllib.request.urlopen", ...)` is the correct target). server.py uses `with urllib.request.urlopen(...) as resp: resp.status / resp.read()` and maps `urllib.error.HTTPError → (code, b"")`. The `_helpers.mock_urlopen(responses)` helper therefore MUST return a **context-manager** object exposing `.status` + `.read()`, support a **sequence** of responses, and provide a helper to raise a correctly-constructed `HTTPError(url, code, msg, hdrs, fp)`. **Filesystem seam** (project scanning): tests write real build files into `tempfile.TemporaryDirectory()` and call `scan_project(path)` — exercises `_detect_build_system` + parsers end-to-end (better than patching `open`).

**Testable surface in server.py (verified by direct `def` inventory — corrected from the first draft):**
- Pure / parsing: `classify_version` (:204), `compare_versions` (:244), `_parse_segments`, `_extract_prerelease_numbers`, `_parse_metadata_xml` (:139), `_parse_toml_catalog` (:777), `_parse_gradle_deps` (:857), **`_parse_gradle_plugins_block` (:891 — TS plugins-block parser is 22 cases, the single largest parser test)**, `_parse_buildscript_classpath` (:910), `_parse_settings_modules` (:922), `_parse_settings_catalogs` (:930), `_parse_maven_deps` (:944), `_parse_maven_modules` (:965), `_detect_build_system` (:972), `_module_path_to_dir` (:1005), `scan_project` (:1011), `group_path`/`_metadata_url`/`_pom_url`/`_repos_for` (incl. the AndroidX/Google prefix routing constant at :30).
- Network (mock urlopen): `http_get`/`http_post_json` (:88/:98), `fetch_metadata` (:154), `check_version_in_repos` (:170), `fetch_pom` (:187), `search_maven_central` (:731), `gh_*` (:422+), `discover_github_repo` (:557), OSV batch query, `_get_dependency_changes_impl` (:585, **GitHub-releases-only**) + `_filter_version_range` (:574) + tag normalization.
- Handlers (mock urlopen + tempfile): all 10 `handle_*` (:1229–:1493), incl. the **#263 regression** for `handle_compare_dependency_versions` (:1293, guard at :1299).

**Parity is auditable, not by count.** PR A produces a required **coverage-map deliverable** (`docs/plans/maven-python-migration/coverage-map.md`): each of the 47 TS test files → one of FOUR buckets `{ported → <py file>, partial → <py file> + <diverged sub-cases → issue #>, diverged → <follow-up issue #>, N/A → <reason>}`. The `partial` bucket is mandatory for files where only some cases port — `http/client.test.ts` (GET/POST ported, retry diverged #1), `maven/resolver.test.ts` (symbol exercised but first-hit vs merge semantics diverged #6), `changelog/resolver.test.ts` (github branch ported, provider-selection diverged #3) — so coverage cannot leak silently at the divergence boundaries. The **behavioral coverage-map is the authoritative parity bar**; `python3 -m trace --count` over server.py is a *backstop* only (it proves a function was executed, not asserted) — derive zero-hit functions by mapping the `.cover` hit-lines onto the `def`-line inventory, and justify any unexercised function in the map. This makes parity falsifiable before PR B deletes the baseline.

**Confirmed divergences — TS had it, the shipped Python runtime does NOT. All are PRE-EXISTING gaps from the #302 Python port (grep/source-verified), NOT regressions this plan introduces. Per "test actual behavior + file follow-ups", each gets a tracked issue; none is fixed here. Two (#5, #6) are CORRECTNESS regressions (wrong answers), not mere feature gaps — flagged at higher priority and cross-linked to epic #293:**
1. **HTTP retry/backoff** — TS `fetchWithRetry` retries 5xx/429; Python does a single `urlopen`. (9 TS cases) — feature gap.
2. **Persistent file cache** — TS `file-cache` `~/.cache/...`; Python has only in-memory per-call memoization (`metadata_cache` :1526). The `plugin/CLAUDE.md` "Persistent cache" line is stale → corrected in PR B. (17 TS cases) — feature gap.
3. **AGP/AndroidX release-notes changelog providers + html-to-text + changelog/resolver provider-selection** — server.py has NO agp/androidx/html parser (`def` inventory = 0); `_get_dependency_changes_impl` (:585) is GitHub-releases-only and does NOT do the agp-vs-androidx-vs-github provider selection TS `changelog/resolver` tests. (TS `agp/` 15 + `androidx/` 17 + `html/` 7 + `changelog` resolver+providers ≈ 58 cases — largest divergence.) Note: AndroidX *version-metadata routing* IS present (:30 → `_repos_for`) and is tested under T-3/T-5. — feature gap.
4. **HTTP/SSE transport (#230/#231)** — exists only in the retired TS; server.py is stdio-only (no `--port`/HTTP server). Closing #230 assumed #231 delivered it, but #231's transport lives in the non-shipped TS. Follow-up (revisit Claude-Cloud compatibility). — feature gap, pre-existing from #302.
5. **Custom-repository discovery (CORRECTNESS)** — TS `discovery/{discover,gradle-parser,maven-parser}` parses build files for declared custom repos (`maven("url")`, `maven { url = uri(...) }`, JitPack/Nexus/Artifactory); server.py `_repos_for` (:128) is purely static group-prefix routing (Central/Google/Plugin-Portal) with NO `maven {`/`maven(` parsing. Consequence: for any project using a private/custom repo, version answers are **silently wrong**. Cross-links epic #293 (#295/#299). 3 TS discovery files → `diverged`.
6. **`resolveAll` merge vs first-hit metadata (CORRECTNESS)** — `fetch_metadata` (:154) returns the FIRST successful repo's metadata; TS `resolveAll` merges version sets across ALL repos (plugin CLAUDE.md line 86) for get_latest/check_multiple/compare. Consequence: an artifact mirrored across Google Maven + Central with divergent version sets gets a **different "latest"** answer. `maven/resolver.test.ts` → `partial`/`diverged` with a behavioral note, never silently `ported`.

**Intentional non-ports (accounted for in the 47→N delta, no follow-up needed):** `cli/parse-port` (no transport port in stdio-only server), `project/find-project-root` (Python `handle_scan` uses `projectPath or os.getcwd()`, no upward root-walk).

**Version-sync is ALREADY correct on current main** (do not re-solve): `validate.sh --check-tag` checks `server.py` `SERVER_VERSION`/`USER_AGENT` against the tag (#305, :184–204), and root `CLAUDE.md` already enumerates the 3 locations as `{plugin.json, marketplace.json, server.py}` with `package.json` excluded. PR B must PRESERVE this check and only drop the now-dead `package.json` dev-note from docs.

**CI strategy.** `.github/workflows/ci.yml` runs the `build` **job unconditionally** and gates only its heavy *steps* on a `Detect maven-mcp changes` output, so `build (20)/(22)` always REPORT (a required check that is job-level-skipped becomes "expected but missing" → BLOCKED-while-mergeable forever). PR A's new `python-tests` job MUST mirror this exactly: job always runs, replicate the detect step, condition only the `unittest` step. PR A keeps the node jobs so required checks stay green through the transition. PR B removes the node jobs and fixes every TS-coupled pipeline (`ci.yml`, `release.yml`, `codeql.yml`) plus the branch ruleset.

## Affected Modules & Files

| Path | Change | Note |
|---|---|---|
| `plugins/maven-mcp/tests/_helpers.py` | New (PR A) | `__file__`-based sys.path shim; `mock_urlopen` (ctx-mgr `.status`/`.read()`, sequence, HTTPError helper); `temp_project(files)` |
| `plugins/maven-mcp/tests/test_version.py` | New (PR A) | classify/compare/range |
| `plugins/maven-mcp/tests/test_parsers.py` | New (PR A) | gradle deps + **plugins-block + buildscript-classpath + settings-modules/catalogs**, maven deps + maven-modules, toml catalog (dedup+source), metadata-xml, detect-build-system, `scan_project` via tempfile |
| `plugins/maven-mcp/tests/test_github.py` | New (PR A) | gh_*, discover_github_repo, changelog (`_get_dependency_changes_impl`, `_filter_version_range`, tag normalization, repositoryNotFound/empty branches) |
| `plugins/maven-mcp/tests/test_maven_search_osv.py` | New (PR A) | fetch_metadata/check_version/fetch_pom across repo list, search, OSV batch |
| `plugins/maven-mcp/tests/test_handlers.py` | New (PR A) | all 10 handle_*; **#263 regression** |
| `plugins/maven-mcp/tests/test_http.py` | New (PR A) | http_get/http_post_json: (status,bytes), HTTPError→(code,b""), headers/User-Agent, POST JSON body; no-retry documented |
| `docs/plans/maven-python-migration/coverage-map.md` | New (PR A) | 47 TS files → ported/diverged/N/A audit artifact |
| `.github/workflows/ci.yml` | Modified (PR A add python job; PR B remove node job) | python-tests = always-run job (`fetch-depth: 0`) + step-gated, mirrors build; includes zero-dep `python -m compileall` static gate; matrix quoted `["3.9","3.13"]` |
| `.github/pull_request_template.md` | Modified (PR B) | replace npm `build/test/lint` checklist + `package.json` version item with `unittest` + 3 version locations |
| `plugins/maven-mcp/src/` (+ `package.json`, `package-lock.json`, `tsconfig.json`, `vitest.config.ts`, `eslint.config.js`, `node_modules/`) | Deleted (PR B) | retire TS reference |
| `.github/workflows/release.yml` | Modified (PR B) | remove setup-node + `npm ci/lint/test/build`; KEEP `validate.sh --check-tag`; add `python3 -m unittest discover` |
| `.github/workflows/codeql.yml` | Modified (PR B) | drop `javascript-typescript` matrix leg (keep `python` + `actions`); correct the stale "ruleset requires CodeQL" comment (it does not). CodeQL is not a required check — no ruleset reconcile |
| `plugins/maven-mcp/CLAUDE.md` | Modified (PR B) | Python is the documented impl + `unittest` commands; FIX stale "Persistent cache" claim; drop TS dev sections |
| `CLAUDE.md` (root) | Modified (PR B) | drop the `package.json` dev-note + any npm/TS references (version-locations non-negotiable already correct, leave it) |
| `plugins/maven-mcp/plugin/server/server.py` | Modified (PR B, doc only) | correct docstring "3.6+" → "3.9+" (matrix floor); NO runtime-logic change |
| branch ruleset (repo settings) | Modified (PR B, two steps) | required checks: +python-tests(3.9)/(3.13) [+validate-marketplace], −build(20)/(22); preserve all other rules |

## Decisions Made

| Decision | Rationale | Alternatives rejected |
|---|---|---|
| stdlib `unittest` | zero new deps, no CI install, matches stdlib-only ethos | pytest (adds dev dep + install for marginal gain) |
| Tests at `plugins/maven-mcp/tests/` (outside `plugin/`) | keep test code out of the shipped plugin tree | `plugin/server/tests/` (ships tests to users) |
| Mock `urllib.request.urlopen`; tempfile for FS | single network seam; real temp files exercise parsers+detection honestly | patching `open` (brittle); fake HTTP server (overkill) |
| Test Python's actual behavior; flag 4 divergences as follow-ups | user decided Python = truth; constraint forbids runtime changes except real bugs; divergences are pre-existing #302 gaps | porting retry/cache/agp/sse into Python now (scope creep — feature work, not a test migration) |
| Coverage-map.md + `trace --count` as PR-A deliverable | makes "parity by behavior" falsifiable before deleting 407 tested cases | manual human-judgment parity claim (unauditable) |
| Two PRs; PR B fixes ci+release+codeql+ruleset together | keep a green required gate at all times; never delete the tested reference before its replacement is proven and every TS-coupled pipeline is migrated | one big-bang PR (removes coverage+gate at once); PR B touching only ci.yml (breaks release.yml/codeql.yml) |
| python matrix [3.9, 3.13] + docstring→3.9+ | 3.6–3.8 awkward on current runners; don't claim a floor we don't test | matrix floor 3.6 (runner friction); keeping false "3.6+" docstring |

## Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| PR B breaks `release.yml` (npm ci with no lockfile) — every future release fails | critical | Dedicated PR-B task gutting npm from release.yml, keeping `validate.sh --check-tag`, adding python unittest; verify the release path logic before done |
| `codeql.yml` `javascript-typescript` leg finds no code after PR B (cosmetic red run) | minor | CodeQL is NOT a required check (verified: ruleset 13632214 has no code_scanning rule) — cannot block merge. T-13c drops the JS/TS leg + corrects the now-false codeql.yml "ruleset requires CodeQL" comment. No ruleset reconcile needed. |
| Required-check rename deadlocks (build(20)/(22) never report on PR B → BLOCKED-while-mergeable) | critical | T-16 split: (a) after PR A merge ADD python-tests required; (b) while PR B open with green python-tests, DROP build(20)/(22); validate via `gh api` ruleset diff, not a probe PR |
| `python-tests` job-level path-skip → required check never reports on non-maven PRs | critical | T-9 mandates always-run job + replicate detect step (incl. `fetch-depth: 0` for the three-dot diff) + step-gate only the unittest step (mirror build); never job-level `if:`/`paths` |
| `release.yml` new unittest step double-paths (`defaults.run.working-directory: plugins/maven-mcp`) → release fails | major | T-13b sets `working-directory: .` on the unittest step (consistent with the surviving `validate.sh`/tag steps) |
| Contributor-facing `.github/pull_request_template.md` still references npm + `package.json` after PR B | major | T-14 updates it to `python3 -m unittest discover` + the 3 version locations {plugin.json, marketplace.json, server.py} |
| Dropping required `npm run lint` (eslint) leaves no L1-static gate | minor | T-9 adds zero-dep `python -m compileall plugins/maven-mcp/plugin/server` to the python-tests job (syntax gate; accepted tradeoff vs adding ruff/mypy deps) |
| Divergences #5/#6 are silent CORRECTNESS regressions (wrong version answers for custom-repo / multi-repo artifacts) | major | Documented as divergences #5/#6 + dedicated follow-up issues (T-10) cross-linked to epic #293; coverage-map marks the affected TS files diverged/partial; not fixed here (feature/bugfix work for #293) |
| `gh api` ruleset PUT wipes other rules (squash-only, review-thread-resolution, linear-history, copilot, deletion/non-ff) | major | Read-modify-write the full ruleset doc; replace ONLY `required_status_checks.required_status_checks` contexts (each new context carries `integration_id: 15368`); verify all rules survive |
| Hidden coverage loss across the 4 divergences | major | coverage-map.md accounts for every one of the 47 TS files; 4 follow-up issues filed; stale cache doc fixed; nothing silent |
| Deleting 407 tested cases on a human-judgment parity bar | major | coverage-map + `trace --count` make it auditable while TS still exists; deletion reversible via git history |
| server.py runtime accidentally changed | minor | Migration touches tests/CI/docs only; the one server.py edit (PR B) is a docstring; L5 smoke confirms the server still responds |

## Verification & Sources

Migration / "shouldn't change behavior" task → the **before-state baseline** is the source of truth.

| Source of truth | Type | Status | Sufficient for verification? |
|---|---|---|---|
| `plugins/maven-mcp/src/**/__tests__` (vitest, 407 green) | before-state baseline | present (green now) | yes — coverage-map.md maps each of the 47 files to ported/diverged/N/A; a reviewer diffs coverage behavior-by-behavior |
| `docs/plans/maven-python-migration/coverage-map.md` | parity audit artifact (produced in PR A) | to-produce (PR A) | yes — the falsifiable parity record + `trace --count` of untested server.py functions |
| GitHub issue #263 | debug-repro | present | yes — defines the compare-no-match regression to lock |
| server.py actual behavior | before-state baseline (runtime) | present | yes — for the 4 divergences the runtime is the truth by the user's decision |

**Testing strategy (pyramid levels):** L0 build (python imports cleanly) + L1 static (`bash scripts/validate.sh`, the tests themselves) + L2 unit (the deliverable: `python3 -m unittest discover`) + **L5 manual mandatory** (infra/migration: smoke the actual MCP server over stdio — send a JSON-RPC `initialize`+`tools/list` and one real `get_latest_version` call — to confirm the runtime is intact after PR B touches CI/docs/docstring). L3/L4 N/A (no UI/E2E surface).

## Out of Scope

- Adding HTTP retry/backoff, persistent file cache, AGP/AndroidX release-notes providers + html-to-text, or HTTP/SSE transport to the Python runtime → **four follow-up issues** (T-10).
- Any new maven-mcp feature (epics #281/#293) — built on this foundation afterward.
- Changing server.py runtime behavior beyond the PR-B docstring fix (a test-revealed real bug would be a separate tracked change).

## Open Questions

- [non-blocking] File the 4 follow-up issues standalone (`enhancement`) and cross-link from epics #281/#293, or nest under an epic? Default: standalone, cross-linked. Resolvable while implementing.

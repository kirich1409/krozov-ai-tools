# Tasks: maven-mcp — Python as the single source of truth

> Plan: ./plan.md · No spec (works from task description)
> PR A = T-1…T-11 (branch `chore/maven-python-tests`, rebased on current main). PR B = T-12…T-17 (branch `chore/maven-remove-ts`, after PR A merged).

## T-1 — Test harness scaffold
- after: none
- files: `plugins/maven-mcp/tests/_helpers.py`, `plugins/maven-mcp/tests/test_smoke.py`
- acceptance: GIVEN a fresh checkout WHEN running `python3 -m unittest discover -s plugins/maven-mcp/tests` from ANY cwd THEN it imports `server` via a `__file__`-resolved sys.path shim and a smoke test passes. `_helpers` exposes: `mock_urlopen(responses)` returning a **context-manager** with `.status` + `.read()`, supporting a **sequence** of responses; `http_error(url, code, msg="", hdrs=None, body=b"")` building a valid 5-arg `urllib.error.HTTPError`; `temp_project(files: dict)` writing files into a `TemporaryDirectory` and returning the path
- check: `python3 -m unittest discover -s plugins/maven-mcp/tests` exits 0 from repo root AND from `/tmp`

## T-2 — version domain tests
- after: T-1
- files: `plugins/maven-mcp/tests/test_version.py`
- acceptance: THE SYSTEM SHALL cover `classify_version` (stable/rc/beta/alpha/milestone/snapshot + edge: empty/garbage), `compare_versions` (semantic order, prerelease ordering, equality), `_parse_segments`/`_extract_prerelease_numbers`, and the `find_latest_version*`/range selection used by compare+audit — mirroring `src/version/__tests__/{classify,compare,range}.test.ts` (33 cases)
- check: tests pass; each comments the TS test it mirrors

## T-3 — parser & scan tests
- after: T-1
- files: `plugins/maven-mcp/tests/test_parsers.py`
- acceptance: THE SYSTEM SHALL cover, each named explicitly: `_parse_gradle_deps`, **`_parse_gradle_plugins_block`** (incl. settings variant; mirrors TS plugins-block 22 cases), `_parse_buildscript_classpath`, `_parse_settings_modules`, `_parse_settings_catalogs`, `_parse_maven_deps`, `_parse_maven_modules`, `_parse_toml_catalog` (catalog dedup + source tracking), `_parse_metadata_xml`, `_detect_build_system`, and `scan_project` end-to-end via `temp_project` (gradle/kts single + multi-module, maven pom + modules, toml catalog) — mirroring `src/dependencies/**`, `src/maven/__tests__/repository.test.ts`. NOTE: do NOT claim to mirror `src/discovery/**` — custom-repo discovery (`maven{}`/`maven()` parsing) is divergence #5 (server.py `_repos_for` is static group-prefix only); those 3 discovery files go to the coverage-map `diverged` bucket
- check: tests pass; plugins-block and multi-module cases present and named; no test asserts custom-repo parsing

## T-4 — github + changelog tests
- after: T-1
- files: `plugins/maven-mcp/tests/test_github.py`
- acceptance: THE SYSTEM SHALL cover `gh_repo_exists`/`gh_fetch_repo`/`gh_fetch_releases`/`gh_fetch_user`/`gh_fetch_issue_stats` (mock urlopen; assert URL + headers incl. token header when `GITHUB_TOKEN` set), `discover_github_repo` (POM-SCM → guess fallback), AND the GitHub-only changelog path: `_get_dependency_changes_impl`, `_filter_version_range`, tag normalization (`re.sub(r"^[^0-9]*", "", tag)`), and the `repositoryNotFound` / no-releases / empty-range branches — mirroring `src/github/**` + `src/changelog/__tests__/github-provider`
- check: tests pass; named cases for version-range filter, tag normalization, and the no-repo/empty branches

## T-5 — maven/search/OSV network tests
- after: T-1
- files: `plugins/maven-mcp/tests/test_maven_search_osv.py`
- acceptance: THE SYSTEM SHALL cover `fetch_metadata`/`check_version_in_repos`/`fetch_pom` (mock urlopen across `_repos_for`, most-specific-first incl. AndroidX/Google prefix routing :30), `search_maven_central`, and the OSV batch query (POST body shape, CVSS/severity extraction) — mirroring `src/maven`, `src/search`, `src/vulnerabilities`. Test `fetch_metadata`'s ACTUAL first-hit semantics (returns the first successful repo's metadata, no cross-repo merge) and document it as divergence #6 (TS used `resolveAll` merge); `maven/resolver.test.ts` → coverage-map `partial`/`diverged` with a behavioral note, never plain `ported`
- check: tests pass; a test asserts first-hit (not merged) behavior of fetch_metadata

## T-6 — tool handler integration tests (+ #263 regression)
- after: T-2, T-3, T-4, T-5
- files: `plugins/maven-mcp/tests/test_handlers.py`
- acceptance: THE SYSTEM SHALL cover all 10 `handle_*` (mock urlopen + temp_project), AND the #263 regression: GIVEN `compare_dependency_versions` with one dependency whose `currentVersion` has no matching newer version AND a sibling dependency that resolves WHEN the handler runs THEN the no-match dependency's result has `error == "No matching version found"`, `upgradeAvailable is False`, `latestVersion == ""`, AND the sibling still resolves successfully (so removing the `if not latest` guard changes the output). ALSO add P3 edge cases for the dependency-health stat/date helpers (`median_days_to_close` :452 empty/single-element, `_months_since` :507, `_parse_iso` :496 naive-vs-aware ISO, `_summarize_releases` :523 release-cadence) — exercise the boundaries directly, not only transitively through the handler
- check: tests pass; #263 asserts the exact observable above (not merely "an error field exists"); health helper P3 boundaries asserted

## T-7 — http_get / http_post_json tests
- after: T-1
- files: `plugins/maven-mcp/tests/test_http.py`
- acceptance: THE SYSTEM SHALL cover `http_get`/`http_post_json` actual behavior: returns `(status, bytes)`; maps `HTTPError → (code, b"")` using the `http_error` helper; sets User-Agent + extra headers; POST encodes JSON body + Content-Type. A module-level comment documents that retry/backoff is intentionally absent (divergence #1, tracked in T-10) — no retry test
- check: tests pass; `HTTPError → (code, b"")` mapping asserted

## T-8 — coverage-map deliverable + trace
- after: T-2…T-7
- files: `docs/plans/maven-python-migration/coverage-map.md`
- acceptance: THE SYSTEM SHALL produce a table mapping EACH of the 47 TS test files to one of FOUR buckets: `ported → <py file>` / `partial → <py file> + <diverged sub-cases → issue #>` / `diverged → <follow-up issue #>` / `N/A → <reason>`. The `partial` bucket is REQUIRED for `http/client.test.ts` (GET/POST ported, retry diverged #1), `maven/resolver.test.ts` (symbol exercised, first-hit-vs-merge diverged #6), `changelog/resolver.test.ts` (github ported, provider-selection diverged #3). The 3 `discovery/*` files → `diverged` (#5). `cli/parse-port`, `find-project-root` → `N/A`. The behavioral map is the AUTHORITATIVE parity bar; `python3 -m trace --count -C /tmp/cov -m unittest discover -s plugins/maven-mcp/tests` is a BACKSTOP only — derive zero-hit functions by mapping `.cover` hit-lines onto the server.py `def`-line inventory; justify any unexercised function
- check: coverage-map.md exists, all 47 files classified into the 4 buckets (tally = 47); partial rows present for the 3 named files; no unexplained zero-hit server.py function

## T-9 — CI: add python-tests job (mirror build's gating)
- after: T-1
- files: `.github/workflows/ci.yml`
- acceptance: THE SYSTEM SHALL add a `python-tests` job (matrix `python-version: ["3.9", "3.13"]` — QUOTED, so the rendered required-check contexts `python-tests (3.9)`/`python-tests (3.13)` are stable) using `actions/setup-python`, that — like `build` — checks out with `fetch-depth: 0` (the three-dot detect diff needs the merge-base), runs the JOB unconditionally, replicates the `Detect maven-mcp changes` step, and gates ONLY the test steps on `steps.changes.outputs.maven_mcp == 'true'`: `python3 -m unittest discover -s plugins/maven-mcp/tests -v` AND a zero-dep static gate `python -m compileall plugins/maven-mcp/plugin/server` (replaces the eslint gate lost when the node job is removed in PR B). Existing `build (20)/(22)` + `validate-marketplace` unchanged. NO job-level `if:`/`paths` skip
- check: on the PR, `python-tests (3.9)` + `python-tests (3.13)` REPORT and pass; contexts match the strings T-16 will require; compileall step present

## T-10 — file divergence follow-up issues
- after: T-7
- files: (GitHub issues — no repo files)
- acceptance: THE SYSTEM SHALL open SIX issues for the Python runtime's pre-existing gaps vs the retired TS. Feature gaps (`enhancement`): (1) HTTP retry/backoff on 5xx/429; (2) persistent file cache; (3) AGP/AndroidX release-notes changelog providers + html-to-text + changelog provider-selection; (4) HTTP/SSE transport (revisit #230 Claude-Cloud compat). CORRECTNESS regressions (`bug`, cross-link epic #293 / #295 / #299): (5) custom-repository discovery missing → wrong version answers for private/custom-repo projects; (6) `fetch_metadata` first-hit vs `resolveAll` merge → wrong "latest" for multi-repo artifacts. Each describes the gap + retired TS reference + user impact; all six linked from the PR A description
- check: six issue URLs recorded in progress.md and the PR body; #5/#6 labeled `bug` and reference #293

## T-11 — open PR A
- after: T-8, T-9, T-10
- files: (PR)
- acceptance: THE SYSTEM SHALL open PR A from `chore/maven-python-tests` as ready-for-review, body linking the plan + coverage-map + the four follow-up issues; node build(20)/(22) + new python-tests(3.9)/(3.13) + validate-marketplace all green
- check: PR open, all checks green

---

## T-12 — remove TS reference (PR B)
- after: T-11 (PR A merged)
- files: delete `plugins/maven-mcp/src/`, `package.json`, `package-lock.json`, `tsconfig.json`, `vitest.config.ts`, `eslint.config.js`, `node_modules/`
- acceptance: GIVEN PR A merged (Python coverage live) WHEN the TS reference is deleted THEN no `*.ts` remains under `plugins/maven-mcp/`, and `python3 -m unittest discover` still passes
- check: `find plugins/maven-mcp -name '*.ts' -not -path '*/node_modules/*'` empty; python tests green

## T-13 — CI/release/codeql: remove node, python becomes gate (PR B)
- after: T-12
- files: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/workflows/codeql.yml`, `scripts/validate.sh`
- acceptance: THE SYSTEM SHALL (a) remove the node `build` matrix job + its package.json↔plugin.json step from ci.yml, keep `python-tests` + `validate-marketplace`; (b) in release.yml remove setup-node + `npm ci/lint/test/build`, KEEP the `validate.sh --check-tag` step (already guards server.py version, #305), add `python3 -m unittest discover -s plugins/maven-mcp/tests` WITH `working-directory: .` on that step (release.yml `defaults.run.working-directory` is `plugins/maven-mcp` → without the override the path double-resolves and the release fails); (c) in codeql.yml drop the `javascript-typescript` matrix leg (keep `python` + `actions`) AND correct the stale comment claiming the ruleset requires a CodeQL analysis (it does not); (d) ensure validate.sh has no npm/TS assumption and its server.py version-sync check stays intact
- check: no `setup-node`/`npm` in any workflow; `bash scripts/validate.sh` passes; release.yml still calls `validate.sh --check-tag` and its unittest step has `working-directory: .`; codeql matrix has no js/ts and the stale comment is gone

## T-14 — docs: Python-first (PR B)
- after: T-12
- files: `plugins/maven-mcp/CLAUDE.md`, `CLAUDE.md` (root), `.github/pull_request_template.md`
- acceptance: THE SYSTEM SHALL update plugin CLAUDE.md to document Python as the implementation with `python3 -m unittest discover` commands, remove TS dev sections, and FIX the stale "Persistent cache: ~/.cache/maven-central-mcp/" claim (server.py has only in-memory memoization); root CLAUDE.md SHALL drop the `package.json` dev-note and any npm/TS references (the 3-version-locations non-negotiable is already correct — leave it); `.github/pull_request_template.md` SHALL replace the `npm run build/test/lint` checklist items + the "Version bumped (package.json and plugin.json)" line with `python3 -m unittest discover` + the 3 version locations {plugin.json, marketplace.json, server.py}. All content English
- check: grep `npm`/`vitest`/`Persistent cache`/`package.json` in the three files returns none/intentional; `bash scripts/validate.sh` passes

## T-15 — server.py docstring fix (PR B)
- after: T-12
- files: `plugins/maven-mcp/plugin/server/server.py`
- acceptance: THE SYSTEM SHALL correct the module docstring "Python 3.6+" to "Python 3.9+" (matching the tested matrix floor). NO runtime-logic change
- check: `git diff` shows only the docstring line changed in server.py

## T-16 — branch ruleset: required-check transition (PR B)
- after: substep (a) after T-11 (PR A merged); substep (b) after T-13 (PR B open, green python-tests)
- files: (repo settings via `gh api`)
- acceptance: THE SYSTEM SHALL update the `main` branch ruleset (id 13632214) via read-modify-write: GET the full ruleset, replace ONLY `required_status_checks.required_status_checks` contexts, PUT the full doc back — preserving all six original rules (squash-only merge, required-review-thread-resolution, linear-history, copilot review, deletion, non-fast-forward). New required contexts: `python-tests (3.9)` + `python-tests (3.13)` (ADD) + `validate-marketplace` (ADD — this is an INTENTIONAL NEW requirement, not currently required; it always runs so it's zero-risk), REMOVE `build (20)`/`build (22)`. Each context carries `integration_id: 15368` (GitHub Actions). Two safe steps: (a) right after PR A merges, ADD python-tests + validate-marketplace (open PRs need a rebase to show them); (b) while PR B is open with green python-tests, DROP build(20)/(22) before merging PR B. CodeQL is NOT required → no codeql context to add. Validate via the `gh api` ruleset diff, NOT a probe PR
- check: `gh api repos/:owner/:repo/rulesets/13632214` shows required contexts = {python-tests (3.9), python-tests (3.13), validate-marketplace}, build(20)/(22) gone, and all six original rules still present

## T-17 — L5 runtime smoke + open PR B
- after: T-13, T-14, T-15
- files: (PR)
- acceptance: THE SYSTEM SHALL smoke the stdio server (`echo` JSON-RPC `initialize`+`tools/list`, then one `get_latest_version` call, piped into `python3 server.py`) and confirm valid responses; THEN open PR B ready-for-review linking the plan; checks python-tests + validate-marketplace green
- check: smoke transcript recorded in progress.md; PR B open, gating checks green

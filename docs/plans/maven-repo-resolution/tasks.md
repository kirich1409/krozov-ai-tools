# Tasks: maven-mcp repository resolution layer (#310 + #311; core of #299)

> Plan: ./plan.md · One PR (branch `fix/maven-repo-resolution`). Closes #310, #311; partial #299 (defers #317–#320). Baseline = 211 existing tests.

## T-1 — brace-depth block scanner (the risky core)
- after: none
- files: `plugins/maven-mcp/plugin/server/server.py`, `plugins/maven-mcp/tests/test_repo_discovery.py`
- acceptance: THE SYSTEM SHALL add `_extract_block(content, header)` that locates a block header and returns the balanced `{…}` body via a `{`/`}` depth counter that ignores braces inside string literals (`"`/`'`) and line comments. Returns the body (or None/empty if absent).
- check: tests — nested `pluginManagement { repositories { maven("X") } }`; sibling `pluginManagement{}` + `dependencyResolutionManagement{}` extracted independently (no over/under-capture); a `}` inside a quoted URL does not terminate the block; missing header → empty

## T-2 — Gradle/Maven repository parsers
- after: T-1
- files: `plugins/maven-mcp/plugin/server/server.py`, `plugins/maven-mcp/tests/test_repo_discovery.py`
- acceptance: THE SYSTEM SHALL add `_parse_gradle_repos(block)` (shorthands `mavenCentral/google/gradlePluginPortal/mavenLocal()`; explicit `maven("…")`/`maven(url=…)`) and for `maven { … }` BLOCKS use `_extract_block` to get each balanced maven body THEN regex `url`/`uri(...)` within it (NOT the brace-naive `maven\s*\{[^}]*url` — that skips `maven { credentials{…}; url=… }`). And `_parse_maven_repos(xml)` (`<repositories>` AND `<pluginRepositories>` → `<url>`s). Returns RepoEntry `{name,url,scope}`; dedup by URL.
- check: tests per Gradle form + a `maven { credentials { username=… }; url = uri("X") }` block (url AFTER a nested credentials block) is discovered; each Maven container; dedup; `mavenLocal()` parsed with a `file://` marker

## T-3 — scoped discovery orchestrator
- after: T-2
- files: `plugins/maven-mcp/plugin/server/server.py`, `plugins/maven-mcp/tests/test_repo_discovery.py`
- acceptance: THE SYSTEM SHALL add `discover_repositories(project_root)` → `{"dependency":[RepoEntry],"plugin":[RepoEntry]}`: Gradle `pluginManagement`+`buildscript` repos → plugin; `dependencyResolutionManagement`+project (bare top-level) `repositories{}` → dependency; Maven `<repositories>`→dependency, `<pluginRepositories>`→plugin; shorthands→URLs; gradle-first/pom-exclusive. MUST EXCISE already-consumed container spans (pluginManagement/dependencyResolutionManagement/buildscript) from the content BEFORE searching for the bare top-level `repositories{}`, else the buildscript-nested `repositories` is mis-read as dependency scope. Result IS `ctx.scoped_repos` (computed once at ctx construction — no separate cache map).
- check: tests — (1) the 2×2 NO-LEAK crux: ONE settings.gradle with `pluginManagement{repositories{maven("X")}}` AND `dependencyResolutionManagement{repositories{maven("Y")}}` → assert X∈plugin, X∉dependency, Y∈dependency, Y∉plugin; (2) build.gradle with `buildscript{repositories{maven("A")}}` + bare `repositories{maven("B")}}` → A∈plugin only, B∈dependency only; Maven dual-container separation; shorthand→URL; gradle-wins-over-pom; discover on an empty dir → both scopes empty

## T-4 — ResolutionContext + project-first `_repos_for` + fallback policy
- after: T-3
- files: `plugins/maven-mcp/plugin/server/server.py`, `plugins/maven-mcp/tests/test_resolution.py`
- acceptance: THE SYSTEM SHALL build a `ResolutionContext {project_path, scoped_repos, public_fallback}` once at the handler boundary (reading `MAVEN_MCP_PUBLIC_FALLBACK` there, not in leaves) and rework `_repos_for(group_id, artifact_id, ctx)` returning rich entries `{name,url,scope,is_public_fallback}`: coordinate kind by `.gradle.plugin` suffix; if relevant scope has ≥1 HTTP-queryable repo → exactly those (no public append); else → public fallback INCLUDING the Google-Maven group-prefix heuristic; `public_fallback=on` forces public append even when declared.
- check: test_resolution.py — (a) #310: custom `maven{url}` queried AND Central URL NOT in urlopen calls; (b) NO-REGRESSION: project declaring `mavenCentral()` → Central queried, resolves normally; (c) no build file → public fallback; (d) Google-group coord with no declaration → Google Maven queried; (e) toggle on → public appended despite declaration; (f) plugin coord → plugin scope only; (g) library coord ignores pluginManagement-only repo → falls back; (h) build file present but scope empty → public fallback; (i) mavenLocal-only → public fallback

## T-5 — merge metadata across repos, keep raise-contract (#311)
- after: T-4
- files: `plugins/maven-mcp/plugin/server/server.py`, `plugins/maven-mcp/tests/test_resolution.py`
- acceptance: THE SYSTEM SHALL change `fetch_metadata(g, a, ctx)` (ctx REQUIRED) to query all `ctx` repos, MERGE versions (union+dedup+sort) from those returning 200, and carry `lastUpdated` = MAX (most recent) across answering repos into the merged dict (health reads it); if NO repo answers → `raise ValueError("Could not fetch metadata…")` (same message as today; preserves unwrapped callers). Post-merge latest/release via existing stability-aware `find_latest_version*`. Intentional divergence from TS `resolveAll`: no proxy-dedup (documented).
- check: tests — A[1.0,2.0]+B[3.0]→merged latest 3.0 (#311); single-repo unchanged (versions AND lastUpdated identical); repo A 404 + repo B 200 → B's versions, no raise; overlapping version across repos → deduped; SNAPSHOT-repo + release-repo → `release` is the stable one; merged `lastUpdated` = most recent; all repos 404 → `get_latest_version` raises `ValueError("Could not fetch metadata…")` (assert the message, not NoneType — this is the all-404 path, distinct from #263 which is the all-200 no-newer-version guard)

## T-6 — thread ctx through ALL resolvers + tool schemas
- after: T-4
- files: `plugins/maven-mcp/plugin/server/server.py`, `plugins/maven-mcp/tests/test_handlers.py`
- acceptance: THE SYSTEM SHALL thread `ctx` as a REQUIRED arg into `check_version_in_repos`(:170), `fetch_pom`(:187), `discover_github_repo`(:563), `_get_dependency_changes_impl`(:591) and build `ctx` in the 7 resolution handlers (`project_path = args.get("projectPath") or os.getcwd()`); add optional `projectPath` to each tool's input schema. UPDATE the existing baseline tests for the contract change: `test_maven_search_osv.py` `TestReposFor` assertions → rich-dict shape, all old-arity `_repos_for/fetch_metadata/check_version_in_repos/fetch_pom` calls → pass a ctx, and **REWRITE `test_first_hit_not_resolveall_merge` to assert the cross-repo MERGE** (it encoded the now-fixed #311 bug); `test_github.py` `discover_github_repo`/`_get_dependency_changes_impl` calls → ctx arity. New resolution-handler tests pass an explicit repo-less tempdir.
- check: handler test — `check_version_exists` against a custom-repo-only artifact (projectPath) routes to the declared repo, Central not queried; `get_dependency_health` single-repo → `lastPublishedToMaven` unchanged; whole suite green AFTER the intentional baseline edits; `discover_repositories` on a build-file-free dir returns empty scopes (proves existing no-projectPath handler tests stay hermetic)

## T-7 — docs + coverage-map + L5 smoke
- after: T-5, T-6
- files: `plugins/maven-mcp/CLAUDE.md`, `docs/plans/maven-python-migration/coverage-map.md`
- acceptance: THE SYSTEM SHALL document project-first resolution, scoping, `MAVEN_MCP_PUBLIC_FALLBACK`, and the documented limitations (#317–#320, #290, mavenLocal, variable URLs); update coverage-map (discovery/* + maven/resolver → ported); L5 stdio smoke: public `get_latest_version` works AND a tempfile project with a custom `maven{url}` repo → that URL queried, Central not.
- check: `bash scripts/validate.sh` rc=0; full `python3 -m unittest discover` green (211 + new); L5 transcript in progress.md

## T-8 — open PR
- after: T-7
- files: (PR)
- acceptance: THE SYSTEM SHALL open a ready PR from `fix/maven-repo-resolution`, body: `Closes #310`, `Closes #311`, "partially addresses #299 (see #317–#320)", link the plan; python-tests(3.9/3.13)+validate-marketplace green.
- check: PR open, required checks green

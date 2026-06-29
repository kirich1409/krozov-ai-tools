---
type: plan
slug: maven-repo-resolution
date: 2026-06-29
status: approved
spec: none
risk_areas: [data-migration]
review_verdict: conditional
review_blockers: []
review_note: "2 cycles (build-engineer/architecture/pr-test-analyzer). Cycle 1 FAIL (~25 findings) → cycle 2 CONDITIONAL. All folded: descoped #299→core (deferred #317-#320), brace scanner incl. inner maven{} via _extract_block, ctx REQUIRED + threaded all resolvers, merge keeps raise + carries lastUpdated, Google-heuristic-in-fallback, baseline-test contract edits (TestReposFor dict-shape + rewrite first-hit→merge test), 2x2 no-leak + buildscript-excision tests. No criticals remain; descope coherent."
---

# Plan: maven-mcp repository resolution layer (#310 + #311; core of #299)

> Branch `fix/maven-repo-resolution` off main (034e522). Epic #293 foundation. server.py = Python 3.9+ stdlib-only stdio runtime. **Closes #310, #311. Partially addresses #299** (discovery + project-first scoping + cross-repo merge); the remaining #299 acceptance criteria are split into follow-ups #317 (provenance reporting), #318 (repositoriesMode), #319 (parent-POM/profile inheritance), #320 (content/group filtering).

## Context & Decision

Epic #293 (closed-perimeter) builds on project-first repository resolution. In the current Python runtime three issues are interdependent:
- **#310 (correctness bug, CLOSE):** the #302 port dropped build-file repository discovery; `_repos_for` (server.py:128) is static group-prefix routing only → custom/private repos (`maven { url … }`, Maven `<repositories>`, JitPack/Nexus/Artifactory) are invisible → wrong answers.
- **#311 (correctness bug, CLOSE):** `fetch_metadata` (server.py:154) returns the FIRST repo's metadata; it must MERGE across all resolved repos so a multi-repo artifact gets the union → correct "latest".
- **#299 (foundational, PARTIAL):** resolution must be project-first + coordinate-kind-scoped. This PR delivers the resolution mechanics (discover declared repos, scope plugin vs dependency, prefer them, demote public to fallback). #299's *reporting* AC and the deeper Gradle/Maven resolution semantics (repositoriesMode, parent-POM/profile inheritance, content filtering) are larger than this PR and are tracked as #317–#320 — so #299 is NOT auto-closed.

## Technical Approach

**Brace-depth scanner (THE risky core — regex cannot balance nested blocks).** Add a hand-written `_extract_block(content, header)` that, given a block header (`pluginManagement`, `dependencyResolutionManagement`, `buildscript`, `repositories`), finds the header then walks a `{`/`}` depth counter (string-literal aware: skip braces inside `"`/`'` and line comments) to return the balanced block body. This — not the ported regexes — is the load-bearing mechanism for scoping; it gets dedicated tests (nested `maven{}` in `repositories{}` in `pluginManagement{}`; sibling `pluginManagement{}`+`dependencyResolutionManagement{}`; a `}` inside a URL string).

**Repository parsers (regex, inside an already-extracted block — stdlib-only, "No XML parser" non-negotiable holds).** Port the retired TS regexes (git `c438680~1:.../discovery/gradle-parser.ts`): shorthands `mavenCentral/google/gradlePluginPortal/mavenLocal()` (`\b<fn>\s*\(\s*\)`), explicit `maven(...)`/`maven { url … }` (the 5 forms). Maven: `<repositories>` and `<pluginRepositories>` blocks → per-repo `<url>` (NOTE: the retired TS had NO `<pluginRepositories>` and NO scoping — the scoping layer is NET-NEW, its tests are authored fresh, not "mirrored").

**`discover_repositories(project_root)` → scoped result** `{"dependency":[RepoEntry], "plugin":[RepoEntry]}`, `RepoEntry = {"name":str, "url":str, "scope":str}`:
- Gradle scopes: `pluginManagement{repositories{}}` + `buildscript{repositories{}}` → **plugin** (buildscript backs legacy plugin/classpath resolution); `dependencyResolutionManagement{repositories{}}` + project `build.gradle* repositories{}` → **dependency**.
- Maven scopes: `<repositories>` → dependency; `<pluginRepositories>` → plugin.
- Shorthands mapped via `_SHORTHAND_URLS`. `mavenLocal()` recorded with a non-HTTP marker (`url=file://…`) — it does NOT count toward scope non-emptiness (see fallback policy) and is never HTTP-queried.
- Dedup by URL within scope, declaration order. Gradle-first / pom-exclusive (match TS).
- Memoized **per tool invocation** (a cache dict created at the handler boundary and passed down, like the existing `metadata_cache` in `audit_project_dependencies`:1532) — NOT process-global, so editing a build file between calls is never stale.

**Resolution policy resolved ONCE at the handler boundary (no env/cwd sniffing in leaf functions).** Each resolution handler computes a `ResolutionContext` = `{project_path, scoped_repos (from discover), public_fallback: bool}` and threads it down. `_repos_for(group_id, artifact_id, ctx)` then:
- coordinate kind: `.gradle.plugin` suffix → plugin scope, else dependency (NOTE: marker-suffix only; resolved plugin impl-GAVs classify as library — deferred to #290; documented, not a defect).
- if the relevant scope has ≥1 HTTP-queryable repo → return EXACTLY those (no implicit public append) — the #299/#310 core.
- else (scope has no queryable repo: no build file, empty block, or mavenLocal-only) → public fallback: the current static well-known routing **including the Google-Maven group-prefix heuristic** (`GOOGLE_MAVEN_GROUPS` → Google Maven) preserved here, so androidx/google coordinates still resolve in the no-declaration case.
- `MAVEN_MCP_PUBLIC_FALLBACK=on` (read once at the boundary into `ctx.public_fallback`) forces appending public even when the scope is declared (escape hatch for implicit/inherited-repo builds; #294/closed-mode wants it OFF).
- `_repos_for` returns rich entries `{name,url,scope,is_public_fallback}` (carries provenance for #317 later; this PR does not surface it in output).

**Threading (ALL resolvers, not just handlers).** `project_path`/`ctx` must reach every `_repos_for` call: `fetch_metadata`(:154), `check_version_in_repos`(:172), `fetch_pom`(:188), `discover_github_repo`(:565), `_get_dependency_changes_impl`(:585), and the 7 handlers (get_latest_version, check_version_exists, check_multiple_dependencies, compare_dependency_versions, get_dependency_changes, get_dependency_health, audit_project_dependencies). Handlers default `project_path = args.get("projectPath") or os.getcwd()`; add optional `projectPath` to each tool schema. (Without threading the intermediates, `check_version_exists`/`health`/`changes` silently ignore the project — the #310 core would stay unfixed for those paths.)

**`fetch_metadata` → merge, PRESERVING the no-match contract.** Current `fetch_metadata` ends in `raise ValueError("Could not fetch metadata…")` on no-match; callers (e.g. `handle_get_latest_version`:1239) call it UNWRAPPED. Keep that contract: query all `ctx` repos, parse each returning 200, MERGE versions (union, dedup, sort by `compare_versions`); if ≥1 repo answered → return merged metadata; if NONE answered (all 404/error) → `raise ValueError` with the same message as today (so every unwrapped caller keeps working). Post-merge "latest"/"release" selection uses the existing stability-aware `find_latest_version*` (PREFER_STABLE / STABLE_ONLY) over the merged set — so a SNAPSHOT-only repo merged with a release repo does not surface `-SNAPSHOT` as `release`. The merged dict MUST also carry **`lastUpdated`** = the MAX (most recent) across answering repos — `handle_get_dependency_health`:1387 reads `metadata.get("lastUpdated")` into `lastPublishedToMaven`, so dropping it would silently regress health even single-repo. This **intentionally diverges from the retired TS `resolveAll`**: no proxy-target dedup (naive union is closer to Gradle's dynamic-version union across repos) — a conscious choice, not "matching TS". **Single-repo result is identical to today** because the merge of one repo's metadata = that metadata (versions union of one set = itself; lastUpdated max of one = itself); the *runtime answer* (versions[] + lastUpdated) is the invariant, not any test count.

**ctx is REQUIRED, not optional-defaulted, on the leaf resolvers** (`_repos_for`, `fetch_metadata`, `check_version_in_repos`, `fetch_pom`, `discover_github_repo`, `_get_dependency_changes_impl`). An optional ctx defaulting to public routing would reintroduce the silent-global anti-pattern this design rejects — a future caller that forgets ctx would get public-only routing and silently resurrect #310. Required ctx makes project-awareness enforced at every call site. The signature-update cost on existing baseline tests is paid explicitly (see Affected Files).

**Inner `maven{}` body parsing also uses `_extract_block`, not brace-naive regex.** Per-`maven{}` block: extract the balanced body via the scanner, THEN regex `url`/`uri(...)` within it. The retired TS `maven\s*\{[^}]*url…` regex silently skips `maven { credentials { … }; url = uri("…") }` (url after a nested `credentials{}`) — and `credentials{}` is characteristic of exactly the private Nexus/Artifactory repos #310 targets, so brace-naive inner parsing would miss the highest-value case.

## Affected Modules & Files

| Path | Change | Note |
|---|---|---|
| `plugins/maven-mcp/plugin/server/server.py` | Modified | `_extract_block` (brace scanner), `_parse_gradle_repos`, `_parse_maven_repos`, `discover_repositories`, `_SHORTHAND_URLS`, `ResolutionContext` builder; rework `_repos_for(..., ctx)` (rich entries, project-first, fallback incl. Google heuristic); `fetch_metadata` first-hit→merge (keep `raise`); thread ctx through `check_version_in_repos`, `fetch_pom`, `discover_github_repo`, `_get_dependency_changes_impl` + 7 handlers; add `projectPath` to those tool schemas |
| `plugins/maven-mcp/tests/test_repo_discovery.py` | New | brace scanner (nested/sibling/string-brace), gradle/maven parsers, scoping, shorthand mapping, dedup, buildscript→plugin, mavenLocal-not-queryable |
| `plugins/maven-mcp/tests/test_resolution.py` | New | project-first + Central-NOT-queried (#310 negative), public-project-no-regression (mavenCentral() still → Central), Google-group heuristic in fallback, plugin vs dependency scope (both directions), scope-empty-with-build-file → fallback, toggle on, mavenLocal-only → fallback, merge: A[1,2]+B[3]→3, 404+200 tolerant, overlapping-version dedup, SNAPSHOT+release → release stable, all-404 → raise |
| `plugins/maven-mcp/tests/test_handlers.py` | Modified | resolution handlers honor `projectPath` (explicit tempdir for isolation); `check_version_exists` against custom-repo-only artifact; `get_dependency_health.lastPublishedToMaven` preserved |
| `plugins/maven-mcp/tests/test_maven_search_osv.py` | Modified | `TestReposFor` assertions updated for rich-dict return shape; old-arity calls updated for required ctx; **`test_first_hit_not_resolveall_merge` REWRITTEN** to assert the cross-repo MERGE (it deliberately encoded the now-fixed #311 first-hit bug — it must invert, not "stay green") |
| `plugins/maven-mcp/tests/test_github.py` | Modified | `discover_github_repo`/`_get_dependency_changes_impl` calls updated for required ctx arity |
| `docs/plans/maven-python-migration/coverage-map.md` | Modified | discovery/* + maven/resolver: diverged/partial → ported |
| `plugins/maven-mcp/CLAUDE.md` | Modified | project-first resolution, scoping, `MAVEN_MCP_PUBLIC_FALLBACK`, documented limitations (#317–#320, #290, mavenLocal, variable URLs) |

## Decisions Made

| Decision | Rationale | Alternatives rejected |
|---|---|---|
| Hand-written brace-depth scanner for block extraction | regex cannot balance nested `{}`; scoping correctness depends on it | non-greedy/greedy regex (truncates/over-captures — the #299-defeating bug) |
| Close #310/#311 fully; #299 PARTIAL (defer #317–#320) | #299's 5 ACs + Gradle/Maven edge semantics exceed one PR; auto-closing it with ACs unmet is the anti-pattern reviewers flagged | "Closes #299" (dishonest); doing all of #299 now (huge, blocks the correctness fixes) |
| `fetch_metadata` keeps `raise`-on-no-match | unwrapped callers + #263 depend on it; switching to None breaks them | return None (NoneType subscript / degraded error) |
| Google-group heuristic preserved in the FALLBACK path only | no-declaration androidx lookups must still reach Google Maven; declared-repo projects use exactly their repos | drop heuristic (regresses androidx); keep it always (re-introduces the #299 false-positive) |
| buildscript{} repos → plugin scope | buildscript backs legacy plugin/classpath resolution | ignore (custom buildscript repo invisible — #310 persists there) |
| mavenLocal() recorded, non-queryable, doesn't count for non-emptiness | it's `file://`; HTTP can't read it; mavenLocal-only must still fall back to public | count it (mavenLocal-only project → everything reported missing) |
| Merge = naive union, no proxy-dedup; stability-aware selection | closer to Gradle dynamic-version union; proxy-dedup was a TS hack | claim "matches resolveAll" (false); first-hit (the bug) |
| Policy/repos resolved once at handler boundary (ctx), threaded down | env/cwd in leaf = hidden global that #294/#295 would compound | env-sniff inside `_repos_for` (untestable, surprises #294) |
| Per-invocation memoization (ctx-carried) | long-lived stdio server; per-process serves stale repo sets during editing | per-process global keyed by project_root (stale) |
| Rich `_repos_for` entries {name,url,scope,is_public_fallback} | carries provenance for #317 without surfacing it now; clean seam | flat tuples (can't carry scope/fallback for #294/#317) |

## Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Brace scanner mis-extracts nested/sibling blocks → plugin repos leak into dependency scope | critical | First-class scanner with depth counter + string-awareness; dedicated tests for nested, sibling, and brace-in-string before any scoping test |
| Normal public project (declares mavenCentral()) regresses | critical | shorthand→URL means Central IS queried; explicit no-regression test (gson-style coord resolves via Central); Google-group heuristic kept in fallback |
| Threading gap leaves check_version_exists/health/changes project-blind | critical | thread ctx through ALL intermediates (check_version_in_repos, fetch_pom, discover_github_repo, _get_dependency_changes_impl); test check_version_exists routes to a custom repo |
| Merge changes existing answers | major | invariant is the single-repo RUNTIME answer (versions[] + lastUpdated), NOT a test count: the contract change (tuple→dict, first-hit→merge, +ctx arity) intentionally edits `TestReposFor` + rewrites `test_first_hit_not_resolveall_merge` + updates arity in test_maven_search_osv/test_github — so the suite total moves by design. Gate = "all tests green after those intentional edits" + new partial-failure (404+200) + dedup + lastUpdated-preserved tests |
| `fetch_metadata` contract change breaks unwrapped callers | major | keep `raise`-on-no-match; explicit get_latest_version all-404 → clean #263 error test (not NoneType) |
| Silent #299 over-claim (repositoriesMode, parent-POM, content-filter) | major | descoped to #317–#320 + documented limitations; not claimed closed |
| Handler tests implicitly discover against runner cwd | minor | resolution-handler tests pass an explicit repo-less tempdir projectPath |

## Verification & Sources

Correctness-fix (#310/#311) + foundational feature (#299 core). Before-state baseline = current behavior (211 tests) + the retired TS parsing reference + the issue specs.

| Source of truth | Type | Status | Sufficient? |
|---|---|---|---|
| Issues #310, #311, #299 | requirements | present | yes — define correct behavior + bugs (with #317–#320 carving the deferred #299 ACs) |
| Retired TS `discovery/*` + tests (git `c438680~1`) | parsing reference | present in history | yes — for the regex parsers ONLY; scoping is net-new (fresh tests) |
| Current server.py (211 tests on main) | before-state baseline | present | yes — single-repo resolution must stay identical; new tests assert deltas |

**Testing strategy:** L0 build + L1 (validate.sh, tests) + L2 unit (brace scanner, parsers, scoped resolution, merge, fallback matrix — mock urlopen + tempfile) + **L5 manual** (stdio smoke: public `get_latest_version` still works; tempfile project with custom `maven{url}` repo → assert that URL queried and Central NOT queried). No UI → no L3/L4.

## Out of Scope (documented limitations, with trackers)

- #299 provenance reporting (`resolvedFrom`/`viaPublicFallback`) → **#317**.
- Gradle `repositoriesMode` (PREFER_PROJECT vs union) → **#318**.
- Maven parent-POM `<parent>` + `<profiles>` repo inheritance → **#319**.
- Repository content/group filtering (`includeGroup`/`exclusiveContent`) → **#320**.
- settings.xml `mirrorOf` / offline (#294), repo-manager search backends (#295), degradation (#296), TLS/proxy (#298), auth (#291) — consume this layer.
- `mavenLocal()` file:// reads; variable-interpolated repo URLs; resolved plugin impl-GAV scoping (#290) — documented, deferred.
- Per-submodule `build.gradle*` repos (discovery reads root build/settings only); `maven { credentials{} }` body is parsed via `_extract_block` but auth itself is #291. Multi-module per-module repo discovery → documented limitation (fallback-to-public mitigates). The #318 settings∪project union OVER-reports vs strict `repositoriesMode` (safe direction for an advisory tool — may query a repo Gradle wouldn't; never under-queries).

## Open Questions

- [non-blocking] Default of `MAVEN_MCP_PUBLIC_FALLBACK` when scope is declared: plan sets OFF (correctness-first); flip if real public-project usage regresses (covered by the no-regression test + L5).

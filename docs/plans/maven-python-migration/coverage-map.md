# Coverage Map — TS test suite → Python parity (T-8)

Maps each of the **47** TypeScript test files under `plugins/maven-mcp/src/**/__tests__/`
to the shipped Python runtime (`plugin/server/server.py`) and its 8 test modules
(`tests/test_{version,parsers,github,maven_search_osv,handlers,http,repo_discovery,resolution}.py`).

> Update (`fix/maven-repo-resolution`): the repository-resolution layer (#310/#311,
> core of #299) added project-repo discovery + cross-repo metadata merge, so the
> 3 `discovery/*` files and `maven/resolver.test.ts` move from diverged/partial to
> **ported** (covered by `test_repo_discovery.py` + `test_resolution.py`).

**This behavioral map is the AUTHORITATIVE parity bar.** It records what the Python
suite actually asserts. `python3 -m trace --count` (see *Untested server.py functions*)
is a **backstop only** — it proves a function executed, never that behavior was asserted.

## The four buckets

- **ported → `<py file>`** — the file's behavior is reproduced and asserted by the named Python module(s).
- **partial → `<py file>` + `<diverged sub-cases → #n>`** — the core behavior is ported, but a specific sub-feature diverged (tracked as follow-up #n).
- **diverged → `#n`** — the behavior does not exist in the shipped Python runtime; tracked as follow-up #n. Pre-existing gap from the #302 Python port — **not** a regression introduced here.
- **N/A → `<reason>`** — intentionally not ported; no follow-up needed.

**Follow-up divergences** (TS had it, shipped Python does not — all pre-existing #302 gaps):
- **#1** HTTP retry/backoff (feature gap)
- **#2** persistent file cache (feature gap)
- **#3** AGP/AndroidX release-notes changelog providers + html-to-text + github CHANGELOG.md markdown fallback + `changelog/resolver` provider-selection — server.py has no agp/androidx/html parser and `_get_dependency_changes_impl` is GitHub-releases-only (feature gap)
- **#4** HTTP/SSE transport — server.py is stdio-only (feature gap)

**Resolved by this PR** (`fix/maven-repo-resolution`) — both former CORRECTNESS regressions are now **ported**:
- **#5** custom-repository discovery — `discover_repositories` + project-first `_repos_for` parse declared Gradle/Maven repos (covered by `test_repo_discovery.py` + `test_resolution.py`).
- **#6** `resolveAll` parallel-merge vs first-hit — `fetch_metadata` now merges versions across all answering repos (covered by `test_resolution.py` `TestMetadataMerge`).

## Map

### version/ (3) — all ported
| TS test file | Bucket | Python |
|---|---|---|
| `version/classify.test.ts` | ported | `test_version.py` (ClassifyVersion, FindLatestVersionForCurrent) |
| `version/compare.test.ts` | ported | `test_version.py` (CompareVersions, GetUpgradeType) |
| `version/range.test.ts` | ported | `test_version.py` (FilterVersionRange); also `test_github.py` (FilterVersionRange) |

### dependencies/ (8) — all ported
| TS test file | Bucket | Python |
|---|---|---|
| `dependencies/gradle-deps-parser.test.ts` | ported | `test_parsers.py` (TestParseGradleDeps) |
| `dependencies/maven-deps-parser.test.ts` | ported | `test_parsers.py` (TestParseMavenDeps) |
| `dependencies/maven-modules-parser.test.ts` | ported | `test_parsers.py` (TestParseMavenModules) |
| `dependencies/plugins-block-parser.test.ts` | ported | `test_parsers.py` (TestParseGradlePluginsBlock) |
| `dependencies/settings-catalogs-parser.test.ts` | ported | `test_parsers.py` (TestParseSettingsCatalogs) |
| `dependencies/settings-gradle-parser.test.ts` | ported | `test_parsers.py` (TestParseSettingsModules) |
| `dependencies/toml-parser.test.ts` | ported | `test_parsers.py` (TestParseTomlCatalog) |
| `dependencies/scan.test.ts` | ported | `test_parsers.py` (TestDetectBuildSystem) + `test_handlers.py` (TestScanProjectDependencies) |

### github/ (6) — 5 ported, 1 diverged
| TS test file | Bucket | Python |
|---|---|---|
| `github/github-client.test.ts` | ported | `test_github.py` (GhRepoExists, GhFetchRepo, GhFetchReleases, GhFetchUser, GhFetchIssueStats, GitHubAuthHeader) |
| `github/discover-repo.test.ts` | ported | `test_github.py` (DiscoverGithubRepo) |
| `github/guess-repo.test.ts` | ported | `test_github.py` (DiscoverGithubRepo — falls-back-to-guess cases) |
| `github/pom-scm.test.ts` | ported | `test_github.py` (DiscoverGithubRepo — returns-repo-from-pom-scm) |
| `github/tag-matcher.test.ts` | ported | `test_github.py` (TagNormalization + DependencyChangesImpl tag-normalization) |
| `github/changelog-parser.test.ts` | diverged → #3 | CHANGELOG.md markdown parser (`parseChangelogSections`) has no server.py equivalent; the Python github path uses release bodies only |

### changelog/ (4) — 1 ported, 1 partial, 2 diverged
| TS test file | Bucket | Python |
|---|---|---|
| `changelog/github-provider.test.ts` | ported | `test_github.py` (DependencyChangesImpl) + `test_handlers.py` (TestGetDependencyChanges) — github releases path |
| `changelog/resolver.test.ts` | partial → `test_github.py` + provider-selection diverged → #3 | github branch ported; agp-vs-androidx-vs-github provider selection not in server.py |
| `changelog/agp-provider.test.ts` | diverged → #3 | no AGP changelog provider in server.py |
| `changelog/androidx-provider.test.ts` | diverged → #3 | no AndroidX changelog provider in server.py |

### agp/ + androidx/ + html/ (5) — all diverged → #3
| TS test file | Bucket | Python |
|---|---|---|
| `agp/release-notes-parser.test.ts` | diverged → #3 | no AGP release-notes parser in server.py |
| `agp/url.test.ts` | diverged → #3 | no AGP URL mapping in server.py |
| `androidx/release-notes-parser.test.ts` | diverged → #3 | no AndroidX release-notes parser in server.py |
| `androidx/url.test.ts` | diverged → #3 | no AndroidX URL mapping in server.py |
| `html/to-text.test.ts` | diverged → #3 | no htmlToText util in server.py (only used by agp/androidx providers) |

### maven/ + search/ + vulnerabilities/ (4) — all ported
| TS test file | Bucket | Python |
|---|---|---|
| `maven/repository.test.ts` | ported | `test_maven_search_osv.py` (TestReposFor + metadata/pom URL construction) |
| `maven/resolver.test.ts` | ported | `test_resolution.py` (TestMetadataMerge — cross-repo union/dedup/sort, `lastUpdated` max, all-404 raise; TestProjectFirstRouting) + `test_maven_search_osv.py`. Cross-repo merge now ported (#6); the former `test_first_hit_not_resolveall_merge` was rewritten to assert the merge |
| `search/maven-search.test.ts` | ported | `test_maven_search_osv.py` (TestSearchMavenCentral) |
| `vulnerabilities/osv-client.test.ts` | ported | `test_maven_search_osv.py` (TestQueryOsvBatch) |

### http/ (1) — partial
| TS test file | Bucket | Python |
|---|---|---|
| `http/client.test.ts` | partial → `test_http.py` + retry diverged → #1 | GET/POST + header builders ported (HttpGet, HttpPostJson, MakeHeaders, GithubHeaders); retry/backoff not in server.py |

### cache/ (1) — diverged → #2
| TS test file | Bucket | Python |
|---|---|---|
| `cache/file-cache.test.ts` | diverged → #2 | no persistent file cache in server.py (in-memory memoization only) |

### discovery/ (3) — all ported
| TS test file | Bucket | Python |
|---|---|---|
| `discovery/discover.test.ts` | ported | `test_repo_discovery.py` (TestDiscoverRepositories — plugin/dependency scoping, gradle-wins-over-pom, 2x2 no-leak, buildscript-vs-bare) + `test_resolution.py` (TestProjectFirstRouting) |
| `discovery/gradle-parser.test.ts` | ported | `test_repo_discovery.py` (TestParseGradleRepos — shorthands, `maven("url")`, `maven { url }` incl. url-after-credentials; TestExtractBlock — brace scanner) |
| `discovery/maven-parser.test.ts` | ported | `test_repo_discovery.py` (TestParseMavenRepos — `<repositories>` / `<pluginRepositories>` dual-container separation) |

### tools/ (10) — all ported (`test_handlers.py`)
| TS test file | Bucket | Python |
|---|---|---|
| `tools/get-latest-version.test.ts` | ported | `test_handlers.py` (TestGetLatestVersion) |
| `tools/check-version-exists.test.ts` | ported | `test_handlers.py` (TestCheckVersionExists) |
| `tools/check-multiple-dependencies.test.ts` | ported | `test_handlers.py` (TestCheckMultipleDependencies) |
| `tools/compare-dependency-versions.test.ts` | ported | `test_handlers.py` (TestCompareDependencyVersions — incl. #263 regression) |
| `tools/get-dependency-changes.test.ts` | ported | `test_handlers.py` (TestGetDependencyChanges) |
| `tools/scan-project-dependencies.test.ts` | ported | `test_handlers.py` (TestScanProjectDependencies) |
| `tools/get-dependency-vulnerabilities.test.ts` | ported | `test_handlers.py` (TestGetDependencyVulnerabilities) |
| `tools/get-dependency-health.test.ts` | ported | `test_handlers.py` (TestGetDependencyHealth + TestDependencyHealthHelpers) |
| `tools/search-artifacts.test.ts` | ported | `test_handlers.py` (TestSearchArtifacts) |
| `tools/audit-project-dependencies.test.ts` | ported | `test_handlers.py` (TestAuditProjectDependencies) |

### cli/ + project/ (2) — N/A
| TS test file | Bucket | Reason |
|---|---|---|
| `cli/parse-port.test.ts` | N/A | stdio-only server — no `--port` / HTTP transport to parse |
| `project/find-project-root.test.ts` | N/A | cwd-based — Python `scan_project` takes an explicit path (`projectPath or os.getcwd()`); no upward root-walk |

## Tally

| Bucket | Count |
|---|---|
| ported | 34 |
| partial | 2 |
| diverged | 9 |
| N/A | 2 |
| **Total** | **47** |

partial files = `http/client.test.ts` (#1), `changelog/resolver.test.ts` (#3). (`maven/resolver.test.ts` graduated partial → ported with the cross-repo merge; the 3 `discovery/*` files graduated diverged → ported with project-repo discovery — both via `fix/maven-repo-resolution`.)

## Untested server.py functions (trace backstop)

Backstop: `python3 -m trace --count -C /tmp/cov --module unittest discover -s plugins/maven-mcp/tests`
(the plan's literal `-m unittest` misparses — trace's `-m` is `--missing`, not module; `--module` is the correct flag). Zero-hit functions were derived by mapping the executed lines in `/tmp/cov/server.cover` onto each `def`'s body (excluding the signature line, which always shows count 1 from import-time definition).

86 functions total; **8** have no executed body line:

| Function (line) | Justification |
|---|---|
| `_handle_initialize` (:1805) | stdio JSON-RPC transport — exercised by the L5 stdio smoke (T-17, subprocess, not in-process trace), not unit tests. Belongs to divergence #4 scope (transport). |
| `_handle_tools_list` (:1817) | transport — same as above. |
| `_handle_tools_call` (:1825) | transport — same as above. |
| `_handle_ping` (:1853) | transport — same as above. |
| `dispatch` (:1857) | transport router — same as above. |
| `main` (:1882) | stdin read loop — same as above. |
| `_write_response` (:1800) | transport output helper, only called by the `_handle_*`/`dispatch` path above. |
| `_is_excluded_path` (:756) | **dead code** — no caller anywhere in server.py (path exclusion in `scan_project` is implemented inline). Unused artifact of the #302 port; safe to drop in a later cleanup, out of scope here. |

All 10 `handle_*` tool entrypoints and every pure/IO helper on the live request paths are exercised; the only gaps are the stdio transport layer (covered by the L5 smoke, divergence #4) and one dead helper.

> Runtime note (not addressed here): `server.py:513` (`_months_since`) uses `datetime.utcnow()`, which emits a `DeprecationWarning` on Python 3.12+. This is runtime code and is out of scope for the test-migration work.

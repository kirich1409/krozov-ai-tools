# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in `plugins/maven-mcp/`.

## Project

MCP server for Maven dependency intelligence. Provides tools to query artifact versions from Maven repositories (Maven Central, Google Maven, custom repos). Distributed as npm package, runs via `npx @krozov/maven-central-mcp`.

**Stack:** TypeScript, Node.js, `@modelcontextprotocol/sdk`, `zod/v4`, `vitest`

## Commands

All commands run from `plugins/maven-mcp/` directory.

```bash
npm run build          # TypeScript compilation (tsc)
npm run test           # Run all tests (vitest run)
npx vitest run src/tools/__tests__/get-latest-version.test.ts  # Single test file
npm run lint           # ESLint
npm run dev            # Watch mode (tsc --watch)
```

## Architecture

```
src/
  index.ts              # Entry point: MCP server setup, tool registration, repository wiring
  maven/
    repository.ts       # MavenRepository interface + HttpMavenRepository (works with any Maven repo)
    resolver.ts         # resolveFirst (sequential) / resolveAll (parallel + merge) strategies
    types.ts            # MavenMetadata
  discovery/
    discover.ts         # Orchestrator: scans project build files, returns RepositoryConfig[]
    gradle-parser.ts    # Regex-based parser for build.gradle[.kts] / settings.gradle[.kts]
    maven-parser.ts     # Regex-based parser for pom.xml <repositories>
    types.ts            # RepositoryConfig, DiscoveryResult
  project/
    find-project-root.ts  # Walks up from cwd to find build file markers
  dependencies/
    scan.ts             # Orchestrator: detects build system, delegates to parsers, returns ScanResult { buildSystem, dependencies }
    gradle-deps-parser.ts # Parses build.gradle[.kts] for dependency declarations
    maven-deps-parser.ts  # Parses pom.xml for dependency declarations
    toml-parser.ts      # Parses gradle/libs.versions.toml version catalogs
  search/
    maven-search.ts     # Maven Central Solr Search API client (keyword search)
  vulnerabilities/
    osv-client.ts       # OSV.dev batch API client for CVE/vulnerability checking
  tools/                # MCP tool handlers (one file per tool)
  github/
    pom-scm.ts          # POM SCM parser → GitHub owner/repo extraction
    guess-repo.ts        # Fallback: guess GitHub repo from groupId
    github-client.ts     # GitHub REST API client (releases, changelog, repo check)
    changelog-parser.ts  # Parse CHANGELOG.md sections by version
    tag-matcher.ts       # Match GitHub release tags to Maven versions
    discover-repo.ts     # Orchestrator: POM → guess → validate
  agp/
    url.ts               # AGP version → developer.android.com URL mapping
    release-notes-parser.ts  # Parse AGP release notes HTML (data-text headings)
  html/
    to-text.ts           # Shared htmlToText utility (strip tags, unescape entities)
  cache/
    file-cache.ts        # Persistent JSON file cache (~/.cache/maven-central-mcp/)
  version/
    classify.ts         # classifyVersion() + findLatestVersion() + findLatestVersionForCurrent() — stability detection
    compare.ts          # getUpgradeType() — major/minor/patch comparison
    range.ts            # filterVersionRange() — extract versions between two bounds
    types.ts            # StabilityType, StabilityFilter, UpgradeType
```

**Key data flow:** Tool call -> `getRepositories()` (lazy, cached) -> `findProjectRoot()` -> `discoverRepositories()` -> parser extracts repos from build files -> `HttpMavenRepository[]` built with Maven Central as fallback -> resolver strategy (`resolveAll`/`resolveFirst`) fetches `maven-metadata.xml` from repos -> tool handler processes versions.

**Repository resolution strategies per tool:**
- `get_latest_version`, `check_multiple_dependencies`, `compare_dependency_versions` -> `resolveAll` (parallel, merged versions)
- `check_version_exists` -> sequential iteration, checks each repo for the specific version
- `get_dependency_changes` -> `resolveAll` (versions) + POM fetch → GitHub API → releases/changelog
- `scan_project_dependencies` -> local only (no network), delegates to `dependencies/scan.ts`
- `search_artifacts` -> Maven Central Solr Search API (no repo resolution)
- `get_dependency_vulnerabilities` -> OSV batch API (`api.osv.dev/v1/querybatch`)
- `audit_project_dependencies` -> `scanDependencies` + `resolveAll` (memoized per GA) + `queryOsvBatch` (deduplicated per GAV)

**Deduplication responsibility:** Parsers return raw results; `discoverRepositories()` in `discover.ts` handles URL deduplication.

**Well-known repo constants** are defined once in `repository.ts` (`MAVEN_CENTRAL`, `GOOGLE_MAVEN`, `GRADLE_PLUGIN_PORTAL`) and referenced from `gradle-parser.ts`.

## Environment

- `GITHUB_TOKEN` — optional, enables higher GitHub API rate limits (5000 req/h vs 60) for `get_dependency_changes` tool
- Persistent cache: `~/.cache/maven-central-mcp/` — SCM mappings (permanent), releases/changelog (24h TTL)

## Conventions

- ESM (`"type": "module"` in package.json), all imports use `.js` extension
- Tests colocated in `__tests__/` directories next to source
- No XML parser dependency — all XML parsing is regex-based
- Tool handlers that resolve versions accept `MavenRepository[]` as first argument; tools that don't need repo resolution (`scan_project_dependencies`, `search_artifacts`, `get_dependency_vulnerabilities`) accept only input
- `findLatestVersion()` and `findLatestVersionForCurrent()` in `version/classify.ts` are the version selection functions; `findLatestVersion` is used by `get_latest_version` and `check_multiple_dependencies`, while `findLatestVersionForCurrent` is used by `compare_dependency_versions` and `audit_project_dependencies`
- `get_dependency_changes` fetches POM from Maven repos to discover GitHub SCM URL; falls back to guessing from `groupId` pattern (`io.github.*`/`com.github.*`)
- `audit_project_dependencies` is an orchestrator: scan → version compare → vulnerability check; memoizes `resolveAll` per GA and deduplicates OSV queries per GAV
- GitHub API: unauthenticated = 60 req/h; set `GITHUB_TOKEN` env for 5000 req/h

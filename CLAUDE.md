# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MCP server for Maven dependency intelligence. Provides tools to query artifact versions from Maven repositories (Maven Central, Google Maven, custom repos). Distributed as npm package, runs via `npx maven-central-mcp`.

**Stack:** TypeScript, Node.js, `@modelcontextprotocol/sdk`, `zod/v4`, `vitest`

## Commands

```bash
npm run build          # TypeScript compilation (tsc)
npm run test           # Run all tests (vitest run)
npx vitest run src/tools/__tests__/get-latest-version.test.ts  # Single test file
npm run dev            # Watch mode (tsc --watch)
```

## Architecture

```
src/
  index.ts              # Entry point: MCP server setup, tool registration, repository wiring
  maven/
    repository.ts       # MavenRepository interface + HttpMavenRepository (works with any Maven repo)
    resolver.ts         # resolveFirst (sequential) / resolveAll (parallel + merge) strategies
    types.ts            # MavenMetadata, MavenSearchResponse
  discovery/
    discover.ts         # Orchestrator: scans project build files, returns RepositoryConfig[]
    gradle-parser.ts    # Regex-based parser for build.gradle[.kts] / settings.gradle[.kts]
    maven-parser.ts     # Regex-based parser for pom.xml <repositories>
    types.ts            # RepositoryConfig, DiscoveryResult
  project/
    find-project-root.ts  # Walks up from cwd to find build file markers
  tools/                # MCP tool handlers (one file per tool)
  github/
    pom-scm.ts          # POM SCM parser → GitHub owner/repo extraction
    guess-repo.ts        # Fallback: guess GitHub repo from groupId
    github-client.ts     # GitHub REST API client (releases, changelog, repo check)
    changelog-parser.ts  # Parse CHANGELOG.md sections by version
    tag-matcher.ts       # Match GitHub release tags to Maven versions
    discover-repo.ts     # Orchestrator: POM → guess → validate
  cache/
    file-cache.ts        # Persistent JSON file cache (~/.cache/maven-central-mcp/)
  version/
    classify.ts         # classifyVersion() + findLatestVersion() — stability detection
    compare.ts          # getUpgradeType() — major/minor/patch comparison
    range.ts            # filterVersionRange() — extract versions between two bounds
    types.ts            # StabilityType, StabilityFilter, UpgradeType
```

**Key data flow:** Tool call -> `getRepositories()` (lazy, cached) -> `findProjectRoot()` -> `discoverRepositories()` -> parser extracts repos from build files -> `HttpMavenRepository[]` built with Maven Central as fallback -> resolver strategy (`resolveAll`/`resolveFirst`) fetches `maven-metadata.xml` from repos -> tool handler processes versions.

**Repository resolution strategies per tool:**
- `get_latest_version`, `check_multiple_dependencies`, `compare_dependency_versions` -> `resolveAll` (parallel, merged versions)
- `check_version_exists` -> sequential iteration, checks each repo for the specific version
- `get_dependency_changes` -> `resolveAll` (versions) + POM fetch → GitHub API → releases/changelog

**Deduplication responsibility:** Parsers return raw results; `discoverRepositories()` in `discover.ts` handles URL deduplication.

**Well-known repo constants** are defined once in `repository.ts` (`MAVEN_CENTRAL`, `GOOGLE_MAVEN`, `GRADLE_PLUGIN_PORTAL`) and referenced from `gradle-parser.ts`.

## Conventions

- ESM (`"type": "module"` in package.json), all imports use `.js` extension
- Tests colocated in `__tests__/` directories next to source
- No XML parser dependency — all XML parsing is regex-based
- Tool handlers accept `MavenRepository[]` as first argument (not a single client)
- `findLatestVersion()` in `version/classify.ts` is the single source of truth for stable version selection logic

## Worktrees

Worktree directory: `.worktrees/` (gitignored). Clean up stale worktrees after merging feature branches.

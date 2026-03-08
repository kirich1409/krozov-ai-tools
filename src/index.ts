#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { HttpMavenRepository, MAVEN_CENTRAL, GOOGLE_MAVEN, GRADLE_PLUGIN_PORTAL } from "./maven/repository.js";
import type { MavenRepository } from "./maven/repository.js";
import { findProjectRoot } from "./project/find-project-root.js";
import { discoverRepositories } from "./discovery/discover.js";
import { getLatestVersionHandler } from "./tools/get-latest-version.js";
import { checkVersionExistsHandler } from "./tools/check-version-exists.js";
import { checkMultipleDependenciesHandler } from "./tools/check-multiple-dependencies.js";
import { compareDependencyVersionsHandler } from "./tools/compare-dependency-versions.js";
import { getDependencyChangesHandler } from "./tools/get-dependency-changes.js";
import { scanProjectDependenciesHandler } from "./tools/scan-project-dependencies.js";
import { getDependencyVulnerabilitiesHandler } from "./tools/get-dependency-vulnerabilities.js";
import { searchArtifactsHandler } from "./tools/search-artifacts.js";
import { auditProjectDependenciesHandler } from "./tools/audit-project-dependencies.js";

const server = new McpServer({
  name: "maven-central-mcp",
  version: "0.2.6",
});

let cachedRepos: MavenRepository[] | null = null;

function getRepositories(): MavenRepository[] {
  if (cachedRepos) return cachedRepos;

  const repos: MavenRepository[] = [];
  const projectRoot = findProjectRoot(process.cwd());

  if (projectRoot) {
    const discovery = discoverRepositories(projectRoot);
    console.error(`Discovered ${discovery.repositories.length} repositories from ${discovery.buildSystem} project at ${projectRoot}`);
    for (const config of discovery.repositories) {
      repos.push(new HttpMavenRepository(config.name, config.url));
    }
  }

  // Add well-known repos as fallback (skip if already discovered)
  for (const fallback of [GOOGLE_MAVEN, GRADLE_PLUGIN_PORTAL, MAVEN_CENTRAL]) {
    if (!repos.some((r) => r.url === fallback.url)) {
      repos.push(fallback);
    }
  }

  cachedRepos = repos;
  return repos;
}

server.tool(
  "get_latest_version",
  "Find the latest version of a Maven artifact with stability-aware selection",
  {
    groupId: z.string().describe("Maven group ID (e.g. io.ktor)"),
    artifactId: z.string().describe("Maven artifact ID (e.g. ktor-server-core)"),
    stabilityFilter: z
      .enum(["STABLE_ONLY", "PREFER_STABLE", "ALL"])
      .optional()
      .describe("Version stability filter (default: STABLE_ONLY)"),
  },
  async (params) => {
    const result = await getLatestVersionHandler(getRepositories(), params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);

server.tool(
  "check_version_exists",
  "Verify a specific version exists and classify its stability",
  {
    groupId: z.string().describe("Maven group ID"),
    artifactId: z.string().describe("Maven artifact ID"),
    version: z.string().describe("Version to check"),
  },
  async (params) => {
    const result = await checkVersionExistsHandler(getRepositories(), params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);

server.tool(
  "check_multiple_dependencies",
  "Bulk lookup of latest versions for a list of Maven dependencies",
  {
    dependencies: z.array(z.object({
      groupId: z.string().describe("Maven group ID"),
      artifactId: z.string().describe("Maven artifact ID"),
    })).describe("List of dependencies to check"),
  },
  async (params) => {
    const result = await checkMultipleDependenciesHandler(getRepositories(), params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);

server.tool(
  "compare_dependency_versions",
  "Compare current dependency versions against latest available, showing upgrade type (major/minor/patch)",
  {
    dependencies: z.array(z.object({
      groupId: z.string().describe("Maven group ID"),
      artifactId: z.string().describe("Maven artifact ID"),
      currentVersion: z.string().describe("Currently used version"),
    })).describe("Dependencies with current versions to compare"),
  },
  async (params) => {
    const result = await compareDependencyVersionsHandler(getRepositories(), params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);

server.tool(
  "get_dependency_changes",
  "Show what changed between two versions of a dependency. Fetches release notes from GitHub and changelog files. Returns raw change descriptions for each intermediate version — summarize the most important changes for the user.",
  {
    groupId: z.string().describe("Maven group ID (e.g. io.ktor)"),
    artifactId: z.string().describe("Maven artifact ID (e.g. ktor-server-core)"),
    fromVersion: z.string().describe("Current version"),
    toVersion: z.string().describe("Target version to upgrade to"),
  },
  async (params) => {
    const result = await getDependencyChangesHandler(getRepositories(), params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);

server.tool(
  "scan_project_dependencies",
  "Scan project build files (Gradle, Maven, version catalogs) and extract all declared dependencies with versions.",
  {
    projectPath: z.string().optional().describe("Path to project root (default: auto-detect from cwd)"),
  },
  async (params) => {
    const result = await scanProjectDependenciesHandler(params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);

server.tool(
  "get_dependency_vulnerabilities",
  "Check Maven dependencies for known vulnerabilities (CVEs) via OSV database. Supports batch checking.",
  {
    dependencies: z.array(z.object({
      groupId: z.string().describe("Maven group ID"),
      artifactId: z.string().describe("Maven artifact ID"),
      version: z.string().describe("Version to check"),
    })).describe("Dependencies to check for vulnerabilities"),
  },
  async (params) => {
    const result = await getDependencyVulnerabilitiesHandler(params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);

server.tool(
  "search_artifacts",
  "Search Maven Central for artifacts by keyword. Use when looking for libraries by name or functionality.",
  {
    query: z.string().describe("Search query (library name, keyword)"),
    limit: z.number().int().min(1).max(100).optional().describe("Max results (default: 10, max: 100)"),
  },
  async (params) => {
    const result = await searchArtifactsHandler(params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);

server.tool(
  "audit_project_dependencies",
  "Full project dependency audit: scans build files, compares versions against latest, checks for vulnerabilities. One-stop tool for dependency health check.",
  {
    projectPath: z.string().optional().describe("Path to project root (default: auto-detect)"),
    includeVulnerabilities: z.boolean().optional().describe("Check for CVEs via OSV (default: true)"),
  },
  async (params) => {
    const result = await auditProjectDependenciesHandler(getRepositories(), params);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("maven-central-mcp running on stdio");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});

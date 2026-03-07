#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { HttpMavenRepository, MAVEN_CENTRAL, WELL_KNOWN_URLS } from "./maven/repository.js";
import type { MavenRepository } from "./maven/repository.js";
import { findProjectRoot } from "./project/find-project-root.js";
import { discoverRepositories } from "./discovery/discover.js";
import { getLatestVersionHandler } from "./tools/get-latest-version.js";
import { checkVersionExistsHandler } from "./tools/check-version-exists.js";
import { checkMultipleDependenciesHandler } from "./tools/check-multiple-dependencies.js";
import { compareDependencyVersionsHandler } from "./tools/compare-dependency-versions.js";

const server = new McpServer({
  name: "maven-central-mcp",
  version: "0.2.0",
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

  // Add Maven Central as fallback only if no custom (non-well-known) repos found.
  // Custom repos (e.g. Nexus, Artifactory) typically proxy Maven Central,
  // so adding it would cause redundant queries and potential version mismatches.
  const hasCustomRepo = repos.some((r) => !WELL_KNOWN_URLS.has(r.url));
  if (!hasCustomRepo && !repos.some((r) => r.url === MAVEN_CENTRAL.url)) {
    repos.push(MAVEN_CENTRAL);
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
      .describe("Version stability filter (default: PREFER_STABLE)"),
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

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("maven-central-mcp running on stdio");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});

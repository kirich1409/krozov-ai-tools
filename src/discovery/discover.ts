import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { DiscoveryResult, RepositoryConfig } from "./types.js";
import { parseGradleRepositories } from "./gradle-parser.js";
import { parseMavenRepositories } from "./maven-parser.js";

const GRADLE_FILES = [
  "settings.gradle.kts",
  "settings.gradle",
  "build.gradle.kts",
  "build.gradle",
] as const;

export function discoverRepositories(projectRoot: string): DiscoveryResult {
  const allRepos: RepositoryConfig[] = [];
  const seen = new Set<string>();
  let buildSystem: DiscoveryResult["buildSystem"] = "unknown";

  function addRepos(repos: RepositoryConfig[]) {
    for (const repo of repos) {
      if (!seen.has(repo.url)) {
        seen.add(repo.url);
        allRepos.push(repo);
      }
    }
  }

  // Try Gradle files
  for (const file of GRADLE_FILES) {
    const path = join(projectRoot, file);
    if (existsSync(path)) {
      buildSystem = "gradle";
      try {
        const content = readFileSync(path, "utf-8");
        addRepos(parseGradleRepositories(content));
      } catch {
        console.error(`Failed to parse ${path}`);
      }
    }
  }

  // Try Maven pom.xml (only if no Gradle files found)
  if (buildSystem === "unknown") {
    const pomPath = join(projectRoot, "pom.xml");
    if (existsSync(pomPath)) {
      buildSystem = "maven";
      try {
        const content = readFileSync(pomPath, "utf-8");
        addRepos(parseMavenRepositories(content));
      } catch {
        console.error(`Failed to parse ${pomPath}`);
      }
    }
  }

  return {
    repositories: allRepos,
    buildSystem,
    projectRoot,
  };
}

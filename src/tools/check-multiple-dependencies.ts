import { classifyVersion } from "../version/classify.js";
import type { MavenCentralClient } from "../maven/client.js";

interface Dependency {
  groupId: string;
  artifactId: string;
}

export interface CheckMultipleDependenciesInput {
  dependencies: Dependency[];
}

export interface DependencyResult {
  groupId: string;
  artifactId: string;
  latestVersion: string;
  stability: string;
  error?: string;
}

export interface CheckMultipleDependenciesResult {
  results: DependencyResult[];
}

export async function checkMultipleDependenciesHandler(
  client: MavenCentralClient,
  input: CheckMultipleDependenciesInput,
): Promise<CheckMultipleDependenciesResult> {
  const results = await Promise.all(
    input.dependencies.map(async (dep) => {
      try {
        const metadata = await client.fetchMetadata(dep.groupId, dep.artifactId);
        const versions = [...metadata.versions].reverse();
        const latest = versions.find((v) => classifyVersion(v) === "stable") ?? versions[0];
        return {
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          latestVersion: latest,
          stability: classifyVersion(latest),
        };
      } catch (e) {
        return {
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          latestVersion: "",
          stability: "",
          error: e instanceof Error ? e.message : String(e),
        };
      }
    }),
  );

  return { results };
}

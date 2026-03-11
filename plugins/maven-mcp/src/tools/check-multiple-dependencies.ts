import { classifyVersion, findLatestVersion } from "../version/classify.js";
import type { MavenRepository } from "../maven/repository.js";
import { resolveAll } from "../maven/resolver.js";

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
  repos: MavenRepository[],
  input: CheckMultipleDependenciesInput,
): Promise<CheckMultipleDependenciesResult> {
  const results = await Promise.all(
    input.dependencies.map(async (dep) => {
      try {
        const metadata = await resolveAll(repos, dep.groupId, dep.artifactId);
        const latest = findLatestVersion(metadata.versions, "PREFER_STABLE")!;
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

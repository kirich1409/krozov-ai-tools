import { classifyVersion, findLatestVersionForCurrent } from "../version/classify.js";
import { getUpgradeType } from "../version/compare.js";
import type { MavenRepository } from "../maven/repository.js";
import { resolveAll } from "../maven/resolver.js";

interface DependencyWithVersion {
  groupId: string;
  artifactId: string;
  currentVersion: string;
}

export interface CompareDependencyVersionsInput {
  dependencies: DependencyWithVersion[];
}

export interface CompareResult {
  groupId: string;
  artifactId: string;
  currentVersion: string;
  latestVersion: string;
  latestStability: string;
  upgradeType: string;
  upgradeAvailable: boolean;
  error?: string;
}

export interface CompareDependencyVersionsResult {
  results: CompareResult[];
  summary: { total: number; upgradeable: number; major: number; minor: number; patch: number };
}

export async function compareDependencyVersionsHandler(
  repos: MavenRepository[],
  input: CompareDependencyVersionsInput,
): Promise<CompareDependencyVersionsResult> {
  const results = await Promise.all(
    input.dependencies.map(async (dep) => {
      try {
        const metadata = await resolveAll(repos, dep.groupId, dep.artifactId);
        const latest = findLatestVersionForCurrent(metadata.versions, dep.currentVersion)!;
        const upgradeType = getUpgradeType(dep.currentVersion, latest);

        return {
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          currentVersion: dep.currentVersion,
          latestVersion: latest,
          latestStability: classifyVersion(latest),
          upgradeType,
          upgradeAvailable: upgradeType !== "none",
        };
      } catch (e) {
        return {
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          currentVersion: dep.currentVersion,
          latestVersion: "",
          latestStability: "",
          upgradeType: "none",
          upgradeAvailable: false,
          error: e instanceof Error ? e.message : String(e),
        };
      }
    }),
  );

  const summary = {
    total: results.length,
    upgradeable: results.filter((r) => r.upgradeAvailable).length,
    major: results.filter((r) => r.upgradeType === "major").length,
    minor: results.filter((r) => r.upgradeType === "minor").length,
    patch: results.filter((r) => r.upgradeType === "patch").length,
  };

  return { results, summary };
}

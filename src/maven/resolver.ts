import type { MavenRepository } from "./repository.js";
import type { MavenMetadata } from "./types.js";

export interface ResolveFirstResult {
  metadata: MavenMetadata;
  repository: MavenRepository;
}

export async function resolveFirst(
  repos: MavenRepository[],
  groupId: string,
  artifactId: string,
): Promise<ResolveFirstResult | null> {
  for (const repo of repos) {
    try {
      const metadata = await repo.fetchMetadata(groupId, artifactId);
      return { metadata, repository: repo };
    } catch {
      continue;
    }
  }
  return null;
}

export async function resolveAll(
  repos: MavenRepository[],
  groupId: string,
  artifactId: string,
): Promise<MavenMetadata> {
  if (repos.length === 0) {
    throw new Error(`No repositories configured to search for ${groupId}:${artifactId}`);
  }

  const results = await Promise.all(
    repos.map(async (repo) => {
      try {
        return await repo.fetchMetadata(groupId, artifactId);
      } catch {
        return null;
      }
    }),
  );

  const successful = results.filter((r): r is MavenMetadata => r !== null);
  if (successful.length === 0) {
    throw new Error(`Artifact ${groupId}:${artifactId} not found in any repository`);
  }

  const orderedVersions: string[] = [];
  const seen = new Set<string>();
  for (const meta of successful) {
    for (const v of meta.versions) {
      if (!seen.has(v)) {
        seen.add(v);
        orderedVersions.push(v);
      }
    }
  }

  // Pick the most recent latest/release across all repos
  const allLatest = successful.map((m) => m.latest).filter(Boolean) as string[];
  const allRelease = successful.map((m) => m.release).filter(Boolean) as string[];
  const lastVersion = orderedVersions[orderedVersions.length - 1];

  return {
    groupId,
    artifactId,
    versions: orderedVersions,
    latest: allLatest.includes(lastVersion) ? lastVersion : allLatest[allLatest.length - 1] ?? lastVersion,
    release: allRelease.includes(lastVersion) ? lastVersion : allRelease[allRelease.length - 1] ?? lastVersion,
    lastUpdated: successful[0].lastUpdated,
  };
}

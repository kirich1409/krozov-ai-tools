import type { MavenRepository } from "./repository.js";
import { PROXY_TARGET_URLS } from "./repository.js";
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

  // Custom repos (Nexus, Artifactory) typically proxy Maven Central.
  // When a custom repo returns results for an artifact, skip Maven Central
  // results to avoid duplicates and stale metadata from proxy caching.
  // Google Maven and Gradle Plugin Portal are NOT proxy targets —
  // they host unique artifacts and always contribute results.
  const all = results.map((r, i) => ({ result: r, repo: repos[i] }));
  const hasCustomResult = all.some(
    ({ result, repo }) => result !== null && !PROXY_TARGET_URLS.has(repo.url),
  );
  const successful = all
    .filter(({ result, repo }) =>
      result !== null && !(hasCustomResult && PROXY_TARGET_URLS.has(repo.url)),
    )
    .map(({ result }) => result!);

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

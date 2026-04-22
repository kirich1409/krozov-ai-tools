import type { MavenRepository } from "./repository.js";
import { PROXY_TARGET_URLS } from "./repository.js";
import type { MavenMetadata } from "./types.js";
import { compareVersions } from "../version/compare.js";
import { findLatestVersion } from "../version/classify.js";

function maxByCompare(versions: string[]): string | undefined {
  if (versions.length === 0) return undefined;
  return versions.reduce((max, v) => (compareVersions(v, max) > 0 ? v : max));
}

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

  // Merge unique versions and sort via semver-aware comparator. maven-metadata.xml
  // inside a single repo is typically chronological, but after cross-repo merge
  // the positional order no longer reflects semver — so we resort.
  const mergedSet = new Set<string>();
  for (const meta of successful) {
    for (const v of meta.versions) mergedSet.add(v);
  }
  const orderedVersions = Array.from(mergedSet).sort(compareVersions);

  // Choose latest/release by semver, not by repo order. Prefer <latest>/<release>
  // values reported by repos (they are authoritative for the publisher) but only
  // if they still appear in the merged version list. Otherwise fall back to
  // stability-aware selection from the merged list.
  const advertisedLatest = successful
    .map((m) => m.latest)
    .filter((v): v is string => Boolean(v) && mergedSet.has(v!));
  const advertisedRelease = successful
    .map((m) => m.release)
    .filter((v): v is string => Boolean(v) && mergedSet.has(v!));

  const latest =
    maxByCompare(advertisedLatest) ??
    findLatestVersion(orderedVersions, "PREFER_STABLE") ??
    orderedVersions[orderedVersions.length - 1];

  const release =
    maxByCompare(advertisedRelease) ??
    findLatestVersion(orderedVersions, "STABLE_ONLY") ??
    latest;

  // lastUpdated is formatted YYYYMMDDHHMMSS — lexicographic sort == chronological.
  const lastUpdated = successful
    .map((m) => m.lastUpdated)
    .filter((s): s is string => Boolean(s))
    .sort()
    .pop();

  return {
    groupId,
    artifactId,
    versions: orderedVersions,
    latest,
    release,
    lastUpdated,
  };
}

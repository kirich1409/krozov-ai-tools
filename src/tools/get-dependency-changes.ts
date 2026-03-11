import type { MavenRepository } from "../maven/repository.js";
import { resolveAll } from "../maven/resolver.js";
import { filterVersionRange } from "../version/range.js";
import { resolveChangelog } from "../changelog/resolver.js";
import type { ChangelogProvider } from "../changelog/types.js";
import { AndroidXChangelogProvider } from "../changelog/androidx-provider.js";
import { AgpChangelogProvider } from "../changelog/agp-provider.js";
import { FirebaseChangelogProvider } from "../changelog/firebase-provider.js";
import { GitHubChangelogProvider } from "../changelog/github-provider.js";

export interface DependencyChangesInput {
  groupId: string;
  artifactId: string;
  fromVersion: string;
  toVersion: string;
}

export interface VersionChange {
  version: string;
  releaseUrl?: string;
  body?: string;
}

export interface DependencyChangesResult {
  groupId: string;
  artifactId: string;
  fromVersion: string;
  toVersion: string;
  repositoryUrl?: string;
  changes: VersionChange[];
  changelogUrl?: string;
  repositoryNotFound?: boolean;
  error?: string;
}

const defaultProviders: ChangelogProvider[] = [
  new AndroidXChangelogProvider(),
  new AgpChangelogProvider(),
  new FirebaseChangelogProvider(),
  new GitHubChangelogProvider(),
];

export async function getDependencyChangesHandler(
  repos: MavenRepository[],
  input: DependencyChangesInput,
  providers: ChangelogProvider[] = defaultProviders,
): Promise<DependencyChangesResult> {
  const { groupId, artifactId, fromVersion, toVersion } = input;

  const baseResult: DependencyChangesResult = {
    groupId,
    artifactId,
    fromVersion,
    toVersion,
    changes: [],
  };

  // Step 1: Resolve all versions
  let allVersions: string[];
  try {
    const metadata = await resolveAll(repos, groupId, artifactId);
    allVersions = metadata.versions;
  } catch (e) {
    return { ...baseResult, error: String(e) };
  }

  // Step 2: Filter version range
  const intermediateVersions = filterVersionRange(allVersions, fromVersion, toVersion);
  if (intermediateVersions.length === 0) {
    return {
      ...baseResult,
      error: `No versions found between ${fromVersion} and ${toVersion}`,
    };
  }

  // Step 3: Resolve changelog from providers
  const changelog = await resolveChangelog(providers, repos, groupId, artifactId, toVersion);

  if (!changelog) {
    return { ...baseResult, repositoryNotFound: true };
  }

  // Step 4: Build changes from changelog entries
  const changes: VersionChange[] = intermediateVersions.map((version) => {
    const entry = changelog.entries.get(version);
    if (!entry) return { version };
    return {
      version,
      ...(entry.releaseUrl && { releaseUrl: entry.releaseUrl }),
      ...(entry.body && { body: entry.body }),
    };
  });

  return {
    ...baseResult,
    repositoryUrl: changelog.repositoryUrl,
    changes,
    changelogUrl: changelog.changelogUrl,
  };
}

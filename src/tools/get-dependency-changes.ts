import type { MavenRepository } from "../maven/repository.js";
import { resolveAll } from "../maven/resolver.js";
import { filterVersionRange } from "../version/range.js";
import { discoverGitHubRepo } from "../github/discover-repo.js";
import { GitHubClient } from "../github/github-client.js";
import type { GitHubRelease } from "../github/github-client.js";
import { matchReleaseToVersion } from "../github/tag-matcher.js";
import { parseChangelogSections } from "../github/changelog-parser.js";
import { FileCache } from "../cache/file-cache.js";
import type { GitHubRepo } from "../github/pom-scm.js";

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

const TTL_24H = 24 * 60 * 60 * 1000;

const cache = new FileCache(".cache/mcp-maven-central");
const githubClient = new GitHubClient(process.env.GITHUB_TOKEN);

export async function getDependencyChangesHandler(
  repos: MavenRepository[],
  input: DependencyChangesInput,
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

  // Step 3: Discover GitHub repo
  const scmCacheKey = `scm/${groupId}/${artifactId}`;
  let ghRepo: GitHubRepo | null | undefined = await cache.get<GitHubRepo>(scmCacheKey);

  if (ghRepo === undefined) {
    ghRepo = await discoverGitHubRepo(repos, groupId, artifactId, toVersion, githubClient);
    if (ghRepo) {
      await cache.set(scmCacheKey, ghRepo);
    }
  }

  if (!ghRepo) {
    return { ...baseResult, repositoryNotFound: true };
  }

  const { owner, repo } = ghRepo;
  const repositoryUrl = `https://github.com/${owner}/${repo}`;

  // Step 4: Fetch GitHub releases (with cache)
  const releasesCacheKey = `releases/${owner}/${repo}`;
  let releases: GitHubRelease[] | undefined = await cache.get<GitHubRelease[]>(releasesCacheKey, TTL_24H);
  if (releases === undefined) {
    releases = await githubClient.fetchReleases(owner, repo);
    await cache.set(releasesCacheKey, releases);
  }

  // Step 5: Match releases to versions
  const changes: VersionChange[] = [];
  const unmatchedVersions: string[] = [];

  for (const version of intermediateVersions) {
    const release = matchReleaseToVersion(releases, version);
    if (release) {
      changes.push({
        version,
        releaseUrl: release.html_url,
        body: release.body,
      });
    } else {
      unmatchedVersions.push(version);
    }
  }

  // Step 6: For unmatched versions, try CHANGELOG.md
  let changelogUrl: string | undefined;
  if (unmatchedVersions.length > 0) {
    const changelogCacheKey = `changelog/${owner}/${repo}`;
    let changelogContent: string | null | undefined = await cache.get<string | null>(changelogCacheKey, TTL_24H);
    if (changelogContent === undefined) {
      changelogContent = await githubClient.fetchChangelog(owner, repo);
      if (changelogContent !== null) {
        await cache.set(changelogCacheKey, changelogContent);
      }
    }

    if (changelogContent) {
      changelogUrl = `https://github.com/${owner}/${repo}/blob/main/CHANGELOG.md`;
      const sections = parseChangelogSections(changelogContent);

      for (const version of unmatchedVersions) {
        const body = sections.get(version);
        if (body) {
          changes.push({ version, body });
        } else {
          changes.push({ version });
        }
      }
    } else {
      for (const version of unmatchedVersions) {
        changes.push({ version });
      }
    }
  }

  // Step 7: Sort changes by version order (same order as intermediateVersions)
  const versionOrder = new Map(intermediateVersions.map((v, i) => [v, i]));
  changes.sort((a, b) => (versionOrder.get(a.version) ?? 0) - (versionOrder.get(b.version) ?? 0));

  return {
    ...baseResult,
    repositoryUrl,
    changes,
    changelogUrl,
  };
}

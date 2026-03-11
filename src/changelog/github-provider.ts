import type { ChangelogProvider, ChangelogResult, ChangelogEntry } from "./types.js";
import type { MavenRepository } from "../maven/repository.js";
import type { GitHubRepo } from "../github/pom-scm.js";
import type { GitHubRelease } from "../github/github-client.js";
import { discoverGitHubRepo } from "../github/discover-repo.js";
import { GitHubClient } from "../github/github-client.js";
import { parseChangelogSections } from "../github/changelog-parser.js";
import { FileCache } from "../cache/file-cache.js";

const TTL_24H = 24 * 60 * 60 * 1000;

export class GitHubChangelogProvider implements ChangelogProvider {
  private readonly cache = new FileCache();
  private readonly githubClient = new GitHubClient(process.env.GITHUB_TOKEN);

  canHandle(_groupId: string, _artifactId: string): boolean {
    return true;
  }

  async fetchChangelog(
    groupId: string,
    artifactId: string,
    version: string,
    repos: MavenRepository[],
  ): Promise<ChangelogResult | null> {
    const scmCacheKey = `scm/${groupId}/${artifactId}`;
    const ghRepo = await this.cache.getOrFetch<GitHubRepo | null>(
      scmCacheKey,
      undefined,
      () => discoverGitHubRepo(repos, groupId, artifactId, version, this.githubClient),
    );

    if (!ghRepo) return null;

    const { owner, repo } = ghRepo;
    const repositoryUrl = `https://github.com/${owner}/${repo}`;
    const entries = new Map<string, ChangelogEntry>();
    let changelogUrl: string | undefined;

    const releases = await this.cache.getOrFetch<GitHubRelease[]>(
      `releases/${owner}/${repo}`,
      TTL_24H,
      () => this.githubClient.fetchReleases(owner, repo),
    );

    for (const release of releases) {
      if (!release.body) continue;
      const tag = release.tag_name;
      const ver = tag.startsWith("v") ? tag.slice(1) : tag;
      entries.set(ver, {
        body: release.body,
        releaseUrl: release.html_url,
      });
    }

    const changelogContent = await this.cache.getOrFetch<string | null>(
      `changelog/${owner}/${repo}`,
      TTL_24H,
      () => this.githubClient.fetchChangelog(owner, repo),
    );

    if (changelogContent) {
      changelogUrl = `https://github.com/${owner}/${repo}/blob/main/CHANGELOG.md`;
      const sections = parseChangelogSections(changelogContent);
      for (const [ver, body] of sections) {
        if (!entries.has(ver)) {
          entries.set(ver, { body });
        }
      }
    }

    if (entries.size === 0) return null;

    return { repositoryUrl, changelogUrl, entries };
  }
}

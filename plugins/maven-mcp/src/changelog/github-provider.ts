import type { ChangelogProvider, ChangelogResult, ChangelogEntry } from "./types.js";
import type { MavenRepository } from "../maven/repository.js";
import type { GitHubRepo } from "../github/pom-scm.js";
import type { GitHubRelease } from "../github/github-client.js";
import { discoverGitHubRepo } from "../github/discover-repo.js";
import { GitHubClient } from "../github/github-client.js";
import { parseChangelogSections } from "../github/changelog-parser.js";
import { FileCache } from "../cache/file-cache.js";

const TTL_24H = 24 * 60 * 60 * 1000;

const VERSION_RE = /^\d+(?:\.\d+)*(?:[.-].*)?$/;

/**
 * Extract version from a Git tag using the same strategies as matchReleaseToVersion:
 * 1. v-prefix — strip leading "v" only when followed by a digit (e.g. "v1.2.3")
 * 2. Suffix after `-` or `/` — extract trailing part only if it looks like a version
 * 3. Exact — return tag as-is
 */
function normalizeTag(tag: string): string {
  if (tag.length > 1 && tag[0] === "v" && tag[1] >= "0" && tag[1] <= "9") {
    return tag.slice(1);
  }
  const dashIdx = tag.lastIndexOf("-");
  if (dashIdx !== -1) {
    const suffix = tag.slice(dashIdx + 1);
    if (VERSION_RE.test(suffix)) return suffix;
  }
  const slashIdx = tag.lastIndexOf("/");
  if (slashIdx !== -1) {
    const suffix = tag.slice(slashIdx + 1);
    if (VERSION_RE.test(suffix)) return suffix;
  }
  return tag;
}

export class GitHubChangelogProvider implements ChangelogProvider {
  private readonly cache = new FileCache();
  private readonly githubClient = new GitHubClient(process.env.GITHUB_TOKEN);

  canHandle(): boolean {
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
      const ver = normalizeTag(release.tag_name);
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

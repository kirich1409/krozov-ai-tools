import type { ChangelogProvider, ChangelogResult, ChangelogEntry } from "./types.js";
import { isAgpArtifact, getAgpReleasesUrl, getAgpVersionUrl } from "../agp/url.js";
import { parseAgpReleaseNotes } from "../agp/release-notes-parser.js";
import { FileCache } from "../cache/file-cache.js";

const TTL_7_DAYS = 7 * 24 * 60 * 60 * 1000;

export class AgpChangelogProvider implements ChangelogProvider {
  private readonly cache = new FileCache();

  canHandle(groupId: string): boolean {
    return isAgpArtifact(groupId);
  }

  async fetchChangelog(
    groupId: string,
    artifactId: string,
    version: string,
  ): Promise<ChangelogResult | null> {
    const { major, minor } = extractMajorMinor(version);
    const cacheKey = `agp/${major}.${minor}`;

    const rawEntries = await this.cache.getOrFetch<[string, string][] | null>(
      cacheKey,
      TTL_7_DAYS,
      () => this.fetchAndParse(version),
    );

    if (!rawEntries || rawEntries.length === 0) return null;

    const entries = new Map<string, ChangelogEntry>();
    for (const [ver, body] of rawEntries) {
      entries.set(ver, {
        body,
        releaseUrl: getAgpVersionUrl(ver),
      });
    }

    return {
      repositoryUrl: getAgpReleasesUrl(version),
      entries,
    };
  }

  private async fetchAndParse(version: string): Promise<[string, string][] | null> {
    try {
      const url = getAgpReleasesUrl(version);
      const response = await fetch(url, {
        signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) {
        return response.status === 404 ? [] : null;
      }

      const html = await response.text();
      const entries = parseAgpReleaseNotes(html);
      if (entries.size === 0) return [];

      return [...entries.entries()];
    } catch {
      return null;
    }
  }
}

function extractMajorMinor(version: string): { major: string; minor: string } {
  const parts = version.split(".");
  return { major: parts[0], minor: parts[1] };
}

import type { ChangelogProvider, ChangelogResult, ChangelogEntry } from "./types.js";
import { isAndroidXArtifact, getAndroidXReleasesUrl, getAndroidXSlug, getAndroidXVersionUrl } from "../androidx/url.js";
import { parseAndroidXReleaseNotes } from "../androidx/release-notes-parser.js";
import { FileCache } from "../cache/file-cache.js";

const TTL_7_DAYS = 7 * 24 * 60 * 60 * 1000;

export class AndroidXChangelogProvider implements ChangelogProvider {
  private readonly cache = new FileCache();

  canHandle(groupId: string): boolean {
    return isAndroidXArtifact(groupId);
  }

  async fetchChangelog(
    groupId: string,
  ): Promise<ChangelogResult | null> {
    const slug = getAndroidXSlug(groupId);
    const cacheKey = `androidx/${slug}`;

    const rawEntries = await this.cache.getOrFetch<[string, string][] | null>(
      cacheKey,
      TTL_7_DAYS,
      () => this.fetchAndParse(groupId),
    );

    if (!rawEntries || rawEntries.length === 0) return null;

    const entries = new Map<string, ChangelogEntry>();
    for (const [version, body] of rawEntries) {
      entries.set(version, {
        body,
        releaseUrl: getAndroidXVersionUrl(groupId, version),
      });
    }

    return {
      repositoryUrl: getAndroidXReleasesUrl(groupId),
      entries,
    };
  }

  private async fetchAndParse(groupId: string): Promise<[string, string][] | null> {
    try {
      const url = getAndroidXReleasesUrl(groupId);
      const response = await fetch(url, {
        signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) {
        return response.status === 404 ? [] : null;
      }

      const html = await response.text();
      const entries = parseAndroidXReleaseNotes(html);
      if (entries.size === 0) return [];

      return [...entries.entries()];
    } catch {
      return null;
    }
  }
}

import type { ChangelogProvider, ChangelogResult, ChangelogEntry } from "./types.js";
import { isFirebaseArtifact, getFirebaseSlug, getFirebaseReleasesUrl, getFirebaseVersionUrl } from "../firebase/url.js";
import { parseFirebaseReleaseNotes } from "../firebase/release-notes-parser.js";
import { FileCache } from "../cache/file-cache.js";

const TTL_7_DAYS = 7 * 24 * 60 * 60 * 1000;

export class FirebaseChangelogProvider implements ChangelogProvider {
  private readonly cache = new FileCache();

  canHandle(groupId: string): boolean {
    return isFirebaseArtifact(groupId);
  }

  async fetchChangelog(
    groupId: string,
    artifactId: string,
  ): Promise<ChangelogResult | null> {
    const slug = getFirebaseSlug(artifactId);
    const cacheKey = `firebase/${slug}`;

    const rawEntries = await this.cache.getOrFetch<[string, string][] | null>(
      cacheKey,
      TTL_7_DAYS,
      () => this.fetchAndParse(slug),
    );

    if (!rawEntries || rawEntries.length === 0) return null;

    const entries = new Map<string, ChangelogEntry>();
    for (const [version, body] of rawEntries) {
      entries.set(version, {
        body,
        releaseUrl: getFirebaseVersionUrl(artifactId, version),
      });
    }

    return {
      repositoryUrl: getFirebaseReleasesUrl(),
      entries,
    };
  }

  private async fetchAndParse(slug: string): Promise<[string, string][] | null> {
    try {
      const url = getFirebaseReleasesUrl();
      const response = await fetch(url, {
        signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) {
        return response.status === 404 ? [] : null;
      }

      const html = await response.text();
      const entries = parseFirebaseReleaseNotes(html, slug);
      if (entries.size === 0) return [];

      return [...entries.entries()];
    } catch {
      return null;
    }
  }
}

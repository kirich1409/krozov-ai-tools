import type { GitHubRelease } from "./github-client.js";

/**
 * Find the release whose tag matches the given Maven version.
 *
 * Match strategies (in priority order):
 * 1. Exact: tag === version
 * 2. v-prefix: tag === "v" + version
 * 3. Suffix after separator: tag ends with version and the preceding char is `-` or `/`
 */
export function matchReleaseToVersion(
  releases: GitHubRelease[],
  version: string,
): GitHubRelease | undefined {
  let vPrefixMatch: GitHubRelease | undefined;
  let suffixMatch: GitHubRelease | undefined;

  for (const release of releases) {
    const tag = release.tag_name;

    // Strategy 1: Exact match
    if (tag === version) {
      return release;
    }

    // Strategy 2: v-prefix
    if (!vPrefixMatch && tag === `v${version}`) {
      vPrefixMatch = release;
    }

    // Strategy 3: Suffix after `-` or `/`
    if (!suffixMatch && tag.endsWith(version)) {
      const prefixLength = tag.length - version.length;
      if (prefixLength > 0) {
        const separator = tag[prefixLength - 1];
        if (separator === "-" || separator === "/") {
          suffixMatch = release;
        }
      }
    }
  }

  return vPrefixMatch ?? suffixMatch;
}

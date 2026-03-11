import type { ChangelogProvider, ChangelogResult } from "./types.js";
import type { MavenRepository } from "../maven/repository.js";

export async function resolveChangelog(
  providers: ChangelogProvider[],
  repos: MavenRepository[],
  groupId: string,
  artifactId: string,
  version: string,
): Promise<ChangelogResult | null> {
  for (const provider of providers) {
    if (!provider.canHandle(groupId, artifactId)) continue;

    try {
      const result = await provider.fetchChangelog(groupId, artifactId, version, repos);
      if (result) return result;
    } catch {
      continue;
    }
  }
  return null;
}

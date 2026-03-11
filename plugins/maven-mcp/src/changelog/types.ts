import type { MavenRepository } from "../maven/repository.js";

export interface ChangelogEntry {
  body: string;
  releaseUrl?: string;
}

export interface ChangelogResult {
  repositoryUrl?: string;
  changelogUrl?: string;
  entries: Map<string, ChangelogEntry>;
}

export interface ChangelogProvider {
  canHandle(groupId: string, artifactId: string): boolean;
  fetchChangelog(
    groupId: string,
    artifactId: string,
    version: string,
    repos: MavenRepository[],
  ): Promise<ChangelogResult | null>;
}

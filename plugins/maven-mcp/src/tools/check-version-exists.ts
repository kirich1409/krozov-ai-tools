import { classifyVersion } from "../version/classify.js";
import type { MavenRepository } from "../maven/repository.js";

export interface CheckVersionExistsInput {
  groupId: string;
  artifactId: string;
  version: string;
}

export interface CheckVersionExistsResult {
  groupId: string;
  artifactId: string;
  version: string;
  exists: boolean;
  stability?: string;
  repository?: string;
}

export async function checkVersionExistsHandler(
  repos: MavenRepository[],
  input: CheckVersionExistsInput,
): Promise<CheckVersionExistsResult> {
  for (const repo of repos) {
    try {
      const metadata = await repo.fetchMetadata(input.groupId, input.artifactId);
      if (metadata.versions.includes(input.version)) {
        return {
          groupId: input.groupId,
          artifactId: input.artifactId,
          version: input.version,
          exists: true,
          stability: classifyVersion(input.version),
          repository: repo.name,
        };
      }
    } catch {
      continue;
    }
  }

  return {
    groupId: input.groupId,
    artifactId: input.artifactId,
    version: input.version,
    exists: false,
  };
}

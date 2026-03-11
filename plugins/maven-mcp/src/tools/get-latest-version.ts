import { classifyVersion, findLatestVersion } from "../version/classify.js";
import type { StabilityFilter } from "../version/types.js";
import type { MavenRepository } from "../maven/repository.js";
import { resolveAll } from "../maven/resolver.js";

export interface GetLatestVersionInput {
  groupId: string;
  artifactId: string;
  stabilityFilter?: StabilityFilter;
}

export interface GetLatestVersionResult {
  groupId: string;
  artifactId: string;
  latestVersion: string;
  stability: string;
  allVersionsCount: number;
}

export async function getLatestVersionHandler(
  repos: MavenRepository[],
  input: GetLatestVersionInput,
): Promise<GetLatestVersionResult> {
  const metadata = await resolveAll(repos, input.groupId, input.artifactId);
  const filter = input.stabilityFilter ?? "PREFER_STABLE";
  const selected = findLatestVersion(metadata.versions, filter);

  if (!selected) {
    throw new Error(
      `No stable version found for ${input.groupId}:${input.artifactId}`,
    );
  }

  return {
    groupId: input.groupId,
    artifactId: input.artifactId,
    latestVersion: selected,
    stability: classifyVersion(selected),
    allVersionsCount: metadata.versions.length,
  };
}

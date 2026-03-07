import { classifyVersion } from "../version/classify.js";
import type { StabilityFilter } from "../version/types.js";
import type { MavenCentralClient } from "../maven/client.js";

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
  client: MavenCentralClient,
  input: GetLatestVersionInput,
): Promise<GetLatestVersionResult> {
  const metadata = await client.fetchMetadata(input.groupId, input.artifactId);
  const filter = input.stabilityFilter ?? "PREFER_STABLE";
  const versions = [...metadata.versions].reverse();

  let selected: string | undefined;

  if (filter === "ALL") {
    selected = versions[0];
  } else if (filter === "STABLE_ONLY") {
    selected = versions.find((v) => classifyVersion(v) === "stable");
    if (!selected) {
      throw new Error(
        `No stable version found for ${input.groupId}:${input.artifactId}`,
      );
    }
  } else {
    // PREFER_STABLE
    selected = versions.find((v) => classifyVersion(v) === "stable") ?? versions[0];
  }

  return {
    groupId: input.groupId,
    artifactId: input.artifactId,
    latestVersion: selected!,
    stability: classifyVersion(selected!),
    allVersionsCount: metadata.versions.length,
  };
}

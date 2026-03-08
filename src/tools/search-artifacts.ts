import { searchMavenCentral } from "../search/maven-search.js";

export interface SearchArtifactsInput {
  query: string;
  limit?: number;
}

export interface SearchArtifactsResult {
  results: {
    groupId: string;
    artifactId: string;
    latestVersion: string;
    versionCount: number;
  }[];
}

export async function searchArtifactsHandler(
  input: SearchArtifactsInput,
): Promise<SearchArtifactsResult> {
  const results = await searchMavenCentral(input.query, input.limit);
  return { results };
}

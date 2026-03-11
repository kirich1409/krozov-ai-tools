import { queryOsvBatch } from "../vulnerabilities/osv-client.js";

export interface VulnerabilitiesInput {
  dependencies: { groupId: string; artifactId: string; version: string }[];
}

export interface VulnerabilitiesResult {
  results: {
    groupId: string;
    artifactId: string;
    version: string;
    vulnerabilities: { id: string; summary: string; severity?: string; fixedVersion?: string; url: string }[];
    vulnerabilityCount: number;
  }[];
}

export async function getDependencyVulnerabilitiesHandler(
  input: VulnerabilitiesInput,
): Promise<VulnerabilitiesResult> {
  const raw = await queryOsvBatch(input.dependencies);
  return {
    results: raw.map((r) => ({
      ...r,
      vulnerabilityCount: r.vulnerabilities.length,
    })),
  };
}

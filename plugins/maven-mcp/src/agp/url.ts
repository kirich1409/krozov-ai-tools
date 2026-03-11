const AGP_GROUP_ID = "com.android.tools.build";
const BASE_URL = "https://developer.android.com/build/releases";

export function isAgpArtifact(groupId: string): boolean {
  return groupId === AGP_GROUP_ID;
}

function extractMajorMinor(version: string): { major: string; minor: string } {
  const parts = version.split(".");
  return { major: parts[0], minor: parts[1] };
}

export function getAgpReleasesUrl(version: string): string {
  const { major, minor } = extractMajorMinor(version);
  return `${BASE_URL}/agp-${major}-${minor}-0-release-notes`;
}

export function getAgpVersionUrl(version: string): string {
  return `${getAgpReleasesUrl(version)}#fixed-issues-agp-${version}`;
}

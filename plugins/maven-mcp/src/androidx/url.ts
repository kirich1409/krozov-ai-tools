const ANDROIDX_PREFIX = "androidx.";
const BASE_URL = "https://developer.android.com/jetpack/androidx/releases";

export function isAndroidXArtifact(groupId: string): boolean {
  return groupId.startsWith(ANDROIDX_PREFIX);
}

export function getAndroidXSlug(groupId: string): string {
  return groupId.slice(ANDROIDX_PREFIX.length).replaceAll(".", "-");
}

export function getAndroidXReleasesUrl(groupId: string): string {
  return `${BASE_URL}/${getAndroidXSlug(groupId)}`;
}

export function getAndroidXVersionUrl(groupId: string, version: string): string {
  return `${getAndroidXReleasesUrl(groupId)}#${version}`;
}

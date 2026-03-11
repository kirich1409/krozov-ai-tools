const FIREBASE_GROUP_ID = "com.google.firebase";
const RELEASES_URL = "https://firebase.google.com/support/release-notes/android";
const FIREBASE_PREFIX = "firebase-";

export function isFirebaseArtifact(groupId: string): boolean {
  return groupId === FIREBASE_GROUP_ID;
}

export function getFirebaseSlug(artifactId: string): string {
  return artifactId.startsWith(FIREBASE_PREFIX)
    ? artifactId.slice(FIREBASE_PREFIX.length)
    : artifactId;
}

export function getFirebaseReleasesUrl(): string {
  return RELEASES_URL;
}

function versionToDashed(version: string): string {
  return version.replaceAll(".", "-");
}

export function getFirebaseVersionUrl(artifactId: string, version: string): string {
  const slug = getFirebaseSlug(artifactId);
  return `${RELEASES_URL}#${slug}_v${versionToDashed(version)}`;
}

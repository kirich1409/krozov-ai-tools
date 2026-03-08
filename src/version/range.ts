/**
 * Filters a versions array to return only versions between fromVersion (exclusive)
 * and toVersion (inclusive).
 *
 * Returns an empty array if either version is not found or fromIndex >= toIndex.
 */
export function filterVersionRange(
  versions: string[],
  fromVersion: string,
  toVersion: string,
): string[] {
  const fromIndex = versions.indexOf(fromVersion);
  const toIndex = versions.indexOf(toVersion);

  if (fromIndex === -1 || toIndex === -1 || fromIndex >= toIndex) {
    return [];
  }

  return versions.slice(fromIndex + 1, toIndex + 1);
}

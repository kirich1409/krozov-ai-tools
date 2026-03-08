export interface CatalogEntry {
  groupId: string;
  artifactId: string;
  version: string | null;
}

export function parseVersionCatalog(content: string): Map<string, CatalogEntry> {
  const entries = new Map<string, CatalogEntry>();
  const versions = new Map<string, string>();

  const versionsMatch = content.match(/\[versions\]([\s\S]*?)(?=\n\[|$)/);
  if (versionsMatch) {
    const versionLines = versionsMatch[1].matchAll(/^(\S+)\s*=\s*"([^"]+)"/gm);
    for (const m of versionLines) {
      versions.set(m[1], m[2]);
    }
  }

  const librariesMatch = content.match(/\[libraries\]([\s\S]*?)(?=\n\[|$)/);
  if (!librariesMatch) return entries;

  const libLines = librariesMatch[1].matchAll(/^(\S+)\s*=\s*\{([^}]+)\}/gm);
  for (const m of libLines) {
    const alias = m[1];
    const props = m[2];

    let groupId: string | undefined;
    let artifactId: string | undefined;
    let version: string | null = null;

    const moduleMatch = props.match(/module\s*=\s*"([^"]+):([^"]+)"/);
    if (moduleMatch) {
      groupId = moduleMatch[1];
      artifactId = moduleMatch[2];
    }

    const groupMatch = props.match(/group\s*=\s*"([^"]+)"/);
    const nameMatch = props.match(/name\s*=\s*"([^"]+)"/);
    if (groupMatch && nameMatch) {
      groupId = groupMatch[1];
      artifactId = nameMatch[1];
    }

    const versionRef = props.match(/version\.ref\s*=\s*"([^"]+)"/);
    if (versionRef) {
      version = versions.get(versionRef[1]) ?? null;
    }

    const versionInline = props.match(/(?<!\.ref\s*=\s*)version\s*=\s*"([^"]+)"/);
    if (versionInline && !versionRef) {
      version = versionInline[1];
    }

    if (groupId && artifactId) {
      entries.set(alias, { groupId, artifactId, version });
    }
  }

  return entries;
}

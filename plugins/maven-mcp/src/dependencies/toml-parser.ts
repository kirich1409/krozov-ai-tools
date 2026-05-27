export interface CatalogEntry {
  groupId: string;
  artifactId: string;
  version: string | null;
}

export interface PluginEntry {
  id: string;
  version: string | null;
}

export interface ParsedCatalog {
  libraries: Map<string, CatalogEntry>;
  plugins: Map<string, PluginEntry>;
}

export function parseVersionCatalog(content: string): ParsedCatalog {
  const libraries = new Map<string, CatalogEntry>();
  const plugins = new Map<string, PluginEntry>();
  const versions = new Map<string, string>();

  const versionsMatch = content.match(/\[versions\]([\s\S]*?)(?=\n\[|$)/);
  if (versionsMatch) {
    const versionLines = versionsMatch[1].matchAll(/^(\S+)\s*=\s*"([^"]+)"/gm);
    for (const m of versionLines) {
      versions.set(m[1], m[2]);
    }
  }

  const librariesMatch = content.match(/\[libraries\]([\s\S]*?)(?=\n\[|$)/);
  if (librariesMatch) {
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

      const versionInline = props.match(/\bversion\s*=\s*"([^"]+)"/);
      if (versionInline && !versionRef) {
        version = versionInline[1];
      }

      if (groupId && artifactId) {
        libraries.set(alias, { groupId, artifactId, version });
      }
    }
  }

  const pluginsMatch = content.match(/\[plugins\]([\s\S]*?)(?=\n\[|$)/);
  if (pluginsMatch) {
    const pluginsSection = pluginsMatch[1];

    // Shorthand: alias = "id:version"
    const shorthandLines = pluginsSection.matchAll(/^(\S+)\s*=\s*"([^":]+):([^"]+)"/gm);
    for (const m of shorthandLines) {
      plugins.set(m[1], { id: m[2], version: m[3] });
    }

    // Inline table: alias = { id = "...", version = "..." | version.ref = "..." }
    const inlineLines = pluginsSection.matchAll(/^(\S+)\s*=\s*\{([^}]+)\}/gm);
    for (const m of inlineLines) {
      const alias = m[1];
      // Skip aliases already captured by shorthand
      if (plugins.has(alias)) continue;

      const props = m[2];
      const idMatch = props.match(/\bid\s*=\s*"([^"]+)"/);
      if (!idMatch) continue;

      const id = idMatch[1];
      let version: string | null = null;

      const versionRef = props.match(/version\.ref\s*=\s*"([^"]+)"/);
      if (versionRef) {
        version = versions.get(versionRef[1]) ?? null;
      } else {
        const versionInline = props.match(/\bversion\s*=\s*"([^"]+)"/);
        if (versionInline) {
          version = versionInline[1];
        }
      }

      plugins.set(alias, { id, version });
    }
  }

  return { libraries, plugins };
}

const VERSION_HEADING_RE = /^##\s+\[?v?(\d+[^\]\s]*)\]?/;

/**
 * Parse markdown changelog content into a map of version -> body text.
 * Recognizes headings like `## [2.0.0] - 2024-01-15`, `## 1.0.0`, `## v3.0.0`.
 * Returns empty Map for non-changelog content.
 */
export function parseChangelogSections(content: string): Map<string, string> {
  const sections = new Map<string, string>();
  const lines = content.split("\n");

  let currentVersion: string | null = null;
  let currentBody: string[] = [];

  for (const line of lines) {
    const match = line.match(VERSION_HEADING_RE);
    if (match) {
      if (currentVersion !== null) {
        sections.set(currentVersion, currentBody.join("\n").trim());
      }
      currentVersion = match[1];
      currentBody = [];
    } else if (currentVersion !== null) {
      currentBody.push(line);
    }
  }

  if (currentVersion !== null) {
    sections.set(currentVersion, currentBody.join("\n").trim());
  }

  return sections;
}

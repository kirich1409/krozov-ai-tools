import { htmlToText } from "../html/to-text.js";

/**
 * Match h3/h4 headings with id="{slug}_v{version-dashed}".
 * Captures: [1] = slug, [2] = dashed version.
 */
const HEADING_RE = /<h[34][^>]*\s+id="([a-z][a-z0-9_-]*)_v([\da-z][\da-z.-]*)"[^>]*>/gi;

/**
 * Convert dashed version back to dotted.
 * Only replace `-` between consecutive digit groups:
 * "26-1-1" → "26.1.1", "16-0-0-beta01" → "16.0.0-beta01"
 */
function dashedToVersion(dashed: string): string {
  return dashed.replace(/(\d)-(?=\d)/g, "$1.");
}

export function parseFirebaseReleaseNotes(
  html: string,
  slug: string,
): Map<string, string> {
  const sections = new Map<string, string>();

  // Collect ALL headings (for boundary detection) and mark which ones match our slug
  const allHeadings: { startIndex: number; endIndex: number; version?: string }[] = [];
  let match: RegExpExecArray | null;

  HEADING_RE.lastIndex = 0;

  while ((match = HEADING_RE.exec(html)) !== null) {
    const headingSlug = match[1];
    const entry: { startIndex: number; endIndex: number; version?: string } = {
      startIndex: match.index,
      endIndex: match.index + match[0].length,
    };
    if (headingSlug === slug) {
      entry.version = dashedToVersion(match[2]);
    }
    allHeadings.push(entry);
  }

  for (let i = 0; i < allHeadings.length; i++) {
    const heading = allHeadings[i];
    if (!heading.version) continue;

    const start = heading.endIndex;
    const end = i + 1 < allHeadings.length
      ? allHeadings[i + 1].startIndex
      : html.length;

    const rawContent = html.slice(start, end);
    const body = htmlToText(rawContent);

    if (body) {
      sections.set(heading.version, body);
    }
  }

  return sections;
}

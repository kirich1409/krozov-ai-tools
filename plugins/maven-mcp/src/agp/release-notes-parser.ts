import { htmlToText } from "../html/to-text.js";

const AGP_HEADING_RE = /<h3[^>]*\s+data-text="Android Gradle plugin ([\d][^\s"]*)"[^>]*>/gi;

export function parseAgpReleaseNotes(html: string): Map<string, string> {
  const sections = new Map<string, string>();
  const headings: { version: string; startIndex: number; endIndex: number }[] = [];
  let match: RegExpExecArray | null;

  AGP_HEADING_RE.lastIndex = 0;

  while ((match = AGP_HEADING_RE.exec(html)) !== null) {
    headings.push({
      version: match[1],
      startIndex: match.index,
      endIndex: match.index + match[0].length,
    });
  }

  for (let i = 0; i < headings.length; i++) {
    const start = headings[i].endIndex;
    const end = i + 1 < headings.length
      ? headings[i + 1].startIndex
      : html.length;

    const rawContent = html.slice(start, end);
    const body = htmlToText(rawContent);

    if (body) {
      sections.set(headings[i].version, body);
    }
  }

  return sections;
}

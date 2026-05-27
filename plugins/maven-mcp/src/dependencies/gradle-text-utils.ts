/**
 * Shared text-processing utilities for Gradle DSL parsers.
 * Used by settings-catalogs-parser.ts and plugins-block-parser.ts.
 */

/**
 * Strips single-line (`//`) and block (`/* ... *\/`) comments from Gradle DSL content.
 */
export function stripComments(content: string): string {
  return content
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/[^\n]*/g, "");
}

/**
 * Finds the brace-balanced block following `keyword` in `content`, searching from `fromIdx`.
 * Returns `{ inner, end }` where `inner` is the content between `{` and its matching `}`,
 * and `end` is the index just past the closing `}`. Returns null if not found or unbalanced.
 */
export function findFirstBlock(
  content: string,
  keyword: string,
  fromIdx = 0,
): { inner: string; end: number } | null {
  const kwIdx = content.indexOf(keyword, fromIdx);
  if (kwIdx === -1) return null;

  const openIdx = content.indexOf("{", kwIdx + keyword.length);
  if (openIdx === -1) return null;

  let depth = 1;
  let pos = openIdx + 1;
  while (pos < content.length && depth > 0) {
    if (content[pos] === "{") depth++;
    else if (content[pos] === "}") depth--;
    pos++;
  }

  if (depth !== 0) return null;
  return { inner: content.slice(openIdx + 1, pos - 1), end: pos };
}

/**
 * Extracts the inner content of the first brace-balanced block following `keyword`.
 * Returns null if not found or unbalanced.
 */
export function extractBlock(content: string, keyword: string): string | null {
  return findFirstBlock(content, keyword)?.inner ?? null;
}

/**
 * Extracts the first brace-balanced block starting at position `fromIdx` in `content`
 * (i.e. searches for the opening `{` from that position without requiring a keyword match).
 * Returns null if not found or unbalanced.
 */
export function extractBlockAt(content: string, fromIdx: number): string | null {
  const openIdx = content.indexOf("{", fromIdx);
  if (openIdx === -1) return null;

  let depth = 1;
  let pos = openIdx + 1;
  while (pos < content.length && depth > 0) {
    if (content[pos] === "{") depth++;
    else if (content[pos] === "}") depth--;
    pos++;
  }

  if (depth !== 0) return null;
  return content.slice(openIdx + 1, pos - 1);
}

/**
 * Finds all occurrences of `keyword` in `content` and returns the inner content
 * of the brace-balanced block following each occurrence.
 */
export function findAllBlocks(content: string, keyword: string): string[] {
  const results: string[] = [];
  let searchFrom = 0;

  while (true) {
    const result = findFirstBlock(content, keyword, searchFrom);
    if (result === null) break;
    results.push(result.inner);
    searchFrom = result.end;
  }

  return results;
}

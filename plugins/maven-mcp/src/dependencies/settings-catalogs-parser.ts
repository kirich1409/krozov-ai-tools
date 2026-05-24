export interface CatalogDescriptor {
  name: string;
  tomlPath: string;
}

const DEFAULT_CATALOG: CatalogDescriptor = {
  name: "libs",
  tomlPath: "gradle/libs.versions.toml",
};

function stripComments(content: string): string {
  return content
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/[^\n]*/g, "");
}

/**
 * Extracts the inner content of a brace-balanced block starting after `keyword`.
 * Returns the content between the opening `{` and its matching `}`, or null if not found.
 */
function extractBlock(content: string, keyword: string): string | null {
  const kwIdx = keyword === "" ? 0 : content.indexOf(keyword);
  if (kwIdx === -1) return null;

  const startSearchAt = keyword === "" ? 0 : kwIdx + keyword.length;
  const openIdx = content.indexOf("{", startSearchAt);
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
 * Parses `dependencyResolutionManagement { versionCatalogs { ... } }` blocks from
 * settings.gradle or settings.gradle.kts content to extract catalog descriptors.
 *
 * Supports:
 * - Kotlin DSL: `create("name") { from(files("path")) }`
 * - Groovy DSL: `create("name") { from files("path") }` or `create('name') { ... }`
 * - Chained form: `create("name").from(files("path"))`
 * - Multi-line blocks
 *
 * Only `from(files("..."))` / `from files("...")` forms are handled.
 * `from("g:a:v")` (catalog-as-Maven-dep) is silently ignored.
 *
 * Returns the default `[{ name: "libs", tomlPath: "gradle/libs.versions.toml" }]`
 * when the `versionCatalogs` block is absent entirely.
 * Returns `[]` when the block is present but contains no `create()` calls.
 */
export function parseSettingsCatalogs(content: string): CatalogDescriptor[] {
  const stripped = stripComments(content);

  const drmBlock = extractBlock(stripped, "dependencyResolutionManagement");
  if (drmBlock === null) return [DEFAULT_CATALOG];

  const vcBlock = extractBlock(drmBlock, "versionCatalogs");
  if (vcBlock === null) return [DEFAULT_CATALOG];

  const descriptors: CatalogDescriptor[] = [];

  // Match create("name") or create('name') — then look for from(files("path"))
  // inside the following block or in a chained .from(files("path")) on the same line.
  const createPattern = /create\s*\(\s*["']([^"']+)["']\s*\)/g;
  let m: RegExpExecArray | null;

  while ((m = createPattern.exec(vcBlock)) !== null) {
    const name = m[1];
    const afterCreate = vcBlock.slice(m.index + m[0].length);

    let tomlPath: string | null = null;

    // Chained form: .from(files("path")) immediately after create("name")
    const chainedMatch = afterCreate.match(/^\s*\.from\s*\(\s*files\s*\(\s*["']([^"']+)["']\s*\)\s*\)/);
    if (chainedMatch) {
      tomlPath = chainedMatch[1];
    } else {
      // Block form: extract { ... } block after create("name"), search inside
      const blockContent = extractBlock(afterCreate, "");
      if (blockContent !== null) {
        // Kotlin DSL: from(files("path"))
        const kotlinMatch = blockContent.match(/\bfrom\s*\(\s*files\s*\(\s*["']([^"']+)["']\s*\)\s*\)/);
        if (kotlinMatch) {
          tomlPath = kotlinMatch[1];
        } else {
          // Groovy DSL: from files("path") or from files('path')
          const groovyMatch = blockContent.match(/\bfrom\s+files\s*\(\s*["']([^"']+)["']\s*\)/);
          if (groovyMatch) {
            tomlPath = groovyMatch[1];
          }
        }
      }
    }

    if (tomlPath !== null) {
      descriptors.push({ name, tomlPath });
    }
    // from("g:a:v") and other non-files forms: silently skip (tomlPath stays null)
  }

  return descriptors;
}

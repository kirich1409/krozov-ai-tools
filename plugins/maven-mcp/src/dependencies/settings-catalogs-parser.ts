import { stripComments, extractBlock, extractBlockAt } from "./gradle-text-utils.js";

export interface CatalogDescriptor {
  name: string;
  tomlPath: string;
}

const DEFAULT_CATALOG: CatalogDescriptor = {
  name: "libs",
  tomlPath: "gradle/libs.versions.toml",
};

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
 * Gradle always auto-configures the `libs` catalog from `gradle/libs.versions.toml`
 * regardless of what's in `versionCatalogs`. The block declares ADDITIONAL catalogs,
 * not replacements. The implicit default is only suppressed when `create("libs")` is
 * present in the block with an explicit `from(files("..."))` path.
 *
 * Returns the default `[{ name: "libs", tomlPath: "gradle/libs.versions.toml" }]`
 * when the `versionCatalogs` block is absent entirely or contains no `create()` calls.
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
      const blockContent = extractBlockAt(afterCreate, 0);
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

  // Gradle always auto-configures the implicit "libs" catalog from gradle/libs.versions.toml.
  // The versionCatalogs block declares ADDITIONAL catalogs. Prepend the default only when
  // no explicit create("libs") with a from(files("...")) path was declared in the block.
  const hasExplicitLibs = descriptors.some((d) => d.name === "libs");
  if (!hasExplicitLibs) {
    return [DEFAULT_CATALOG, ...descriptors];
  }

  return descriptors;
}

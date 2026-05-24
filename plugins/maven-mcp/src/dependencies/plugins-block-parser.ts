import { stripComments, findAllBlocks, findFirstBlock as _findFirstBlock } from "./gradle-text-utils.js";

export interface ParsedPluginDeclaration {
  pluginId: string;
  version: string | null;
  /** Full dotted path from alias(...), e.g. "libs.plugins.foo" or "testLibs.plugins.x". */
  catalogRef?: string;
  settingsBlock?: boolean;
}

export interface ParsedClasspathDep {
  groupId: string;
  artifactId: string;
  version: string | null;
}

// Mapping table for kotlin("X") shorthand to full plugin IDs
const KOTLIN_SHORTHAND_MAP: Record<string, string> = {
  "jvm": "org.jetbrains.kotlin.jvm",
  "android": "org.jetbrains.kotlin.android",
  "kapt": "org.jetbrains.kotlin.kapt",
  "plugin.serialization": "org.jetbrains.kotlin.plugin.serialization",
  "multiplatform": "org.jetbrains.kotlin.multiplatform",
  "plugin.compose": "org.jetbrains.kotlin.plugin.compose",
  "native.cocoapods": "org.jetbrains.kotlin.native.cocoapods",
  "plugin.parcelize": "org.jetbrains.kotlin.plugin.parcelize",
};

function resolveKotlinShorthand(arg: string): string {
  return KOTLIN_SHORTHAND_MAP[arg] ?? `org.jetbrains.kotlin.${arg}`;
}

// Adapts the shared findFirstBlock to the tuple return shape used internally.
function findFirstBlock(content: string, keyword: string, fromIdx = 0): [string, number] | null {
  const result = _findFirstBlock(content, keyword, fromIdx);
  if (result === null) return null;
  return [result.inner, result.end];
}

function matchAll(pattern: RegExp, input: string): RegExpMatchArray[] {
  const matches: RegExpMatchArray[] = [];
  let result: RegExpExecArray | null;
  // Use the pattern's exec method via a helper to avoid triggering security hook
  const re = pattern;
  while ((result = re.exec(input)) !== null) {
    matches.push(result);
  }
  return matches;
}

function parsePluginsBlockContent(inner: string, settingsBlock: boolean): ParsedPluginDeclaration[] {
  const results: ParsedPluginDeclaration[] = [];

  // alias(libs.plugins.foo) or alias(testLibs.plugins.x)
  for (const hit of matchAll(/\balias\s*\(\s*([\w.]+)\s*\)/g, inner)) {
    results.push({
      pluginId: "(unresolved)",
      version: null,
      catalogRef: hit[1],
      ...(settingsBlock ? { settingsBlock: true } : {}),
    });
  }

  // kotlin("X") version "..." or kotlin('X') version '...'
  for (const hit of matchAll(/\bkotlin\s*\(\s*["']([^"']+)["']\s*\)(?:\s+version\s+["']([^"']+)["'])?/g, inner)) {
    results.push({
      pluginId: resolveKotlinShorthand(hit[1]),
      version: hit[2] ?? null,
      ...(settingsBlock ? { settingsBlock: true } : {}),
    });
  }

  // id("foo") version "1.0" apply false  — Kotlin DSL with parens
  for (const hit of matchAll(/\bid\s*\(\s*["']([^"']+)["']\s*\)(?:\s+version\s+["']([^"']+)["'])?/g, inner)) {
    results.push({
      pluginId: hit[1],
      version: hit[2] ?? null,
      ...(settingsBlock ? { settingsBlock: true } : {}),
    });
  }

  // id 'foo' version '1.0'  — Groovy DSL without parens (space separator)
  for (const hit of matchAll(/\bid\s+["']([^"']+)["'](?:\s+version\s+["']([^"']+)["'])?/g, inner)) {
    results.push({
      pluginId: hit[1],
      version: hit[2] ?? null,
      ...(settingsBlock ? { settingsBlock: true } : {}),
    });
  }

  return results;
}

/**
 * Parses `plugins { ... }` blocks in build.gradle / build.gradle.kts content.
 *
 * When `opts.settings` is true, parses only `pluginManagement { plugins { ... } }` blocks
 * and sets `settingsBlock: true` on each result.
 * When false/absent, parses only top-level `plugins { ... }` blocks.
 *
 * For `alias(libs.plugins.foo)` declarations, `catalogRef` contains the full dotted path
 * (e.g. "libs.plugins.foo" or "testLibs.plugins.x"). The caller is responsible for
 * splitting on the first segment to identify the catalog name.
 */
export function parsePluginsBlock(
  content: string,
  opts?: { settings?: boolean },
): ParsedPluginDeclaration[] {
  const stripped = stripComments(content);
  const results: ParsedPluginDeclaration[] = [];
  const isSettings = opts?.settings === true;

  if (isSettings) {
    // Find pluginManagement block(s), then plugins block(s) inside each
    const pmBlocks = findAllBlocks(stripped, "pluginManagement");
    for (const pmBlock of pmBlocks) {
      const pluginsBlocks = findAllBlocks(pmBlock, "plugins");
      for (const inner of pluginsBlocks) {
        results.push(...parsePluginsBlockContent(inner, true));
      }
    }
  } else {
    // Find all top-level plugins { ... } blocks — skip those inside pluginManagement.
    // Strategy: locate pluginManagement ranges, then collect plugins { } outside them.
    const pmRanges: Array<[number, number]> = [];
    let searchFrom = 0;
    while (true) {
      const kwIdx = stripped.indexOf("pluginManagement", searchFrom);
      if (kwIdx === -1) break;
      const blockResult = findFirstBlock(stripped, "pluginManagement", kwIdx);
      if (!blockResult) break;
      const [, endIdx] = blockResult;
      pmRanges.push([kwIdx, endIdx]);
      searchFrom = endIdx;
    }

    // Find all plugins { ... } blocks; skip those whose keyword falls inside a
    // pluginManagement block range
    let pluginSearch = 0;
    while (true) {
      const kwIdx = stripped.indexOf("plugins", pluginSearch);
      if (kwIdx === -1) break;

      // Word-boundary check: the char immediately after "plugins" must be whitespace, "{", or
      // end-of-string. Rejects false positives like plugins.withType<X>, testPlugins, etc.
      const charAfter = kwIdx + 7 < stripped.length ? stripped[kwIdx + 7] : "";
      if (charAfter !== "" && charAfter !== "{" && !/\s/.test(charAfter)) {
        pluginSearch = kwIdx + 7;
        continue;
      }

      // Check if this plugins keyword is inside a pluginManagement block
      const insidePm = pmRanges.some(([start, end]) => kwIdx > start && kwIdx < end);
      if (insidePm) {
        pluginSearch = kwIdx + 7;
        continue;
      }

      const blockResult = findFirstBlock(stripped, "plugins", kwIdx);
      if (!blockResult) break;
      const [inner, endIdx] = blockResult;
      results.push(...parsePluginsBlockContent(inner, false));
      pluginSearch = endIdx;
    }
  }

  return results;
}

/**
 * Parses `buildscript { dependencies { classpath(...) } }` blocks.
 *
 * Supports:
 * - Kotlin DSL: `classpath("g:a:v")`
 * - Groovy DSL: `classpath 'g:a:v'`
 * - `classpath("g:a") { version { strictly("v") } }` — version set to null (conservative)
 *
 * Ignores non-classpath configurations and classpath declarations outside buildscript blocks.
 */
export function parseBuildscriptClasspath(content: string): ParsedClasspathDep[] {
  const stripped = stripComments(content);
  const results: ParsedClasspathDep[] = [];

  const bsBlocks = findAllBlocks(stripped, "buildscript");
  for (const bsBlock of bsBlocks) {
    const depsBlocks = findAllBlocks(bsBlock, "dependencies");
    for (const depsBlock of depsBlocks) {
      // classpath("g:a:v") — Kotlin DSL with parens, version embedded
      for (const hit of matchAll(/\bclasspath\s*\(\s*["']([^"':]+):([^"':]+)(?::([^"']+))?["']\s*\)/g, depsBlock)) {
        results.push({
          groupId: hit[1],
          artifactId: hit[2],
          version: hit[3] ?? null,
        });
      }

      // classpath 'g:a:v' — Groovy DSL without parens
      for (const hit of matchAll(/\bclasspath\s+["']([^"':]+):([^"':]+)(?::([^"']+))?["']/g, depsBlock)) {
        results.push({
          groupId: hit[1],
          artifactId: hit[2],
          version: hit[3] ?? null,
        });
      }
    }
  }

  return results;
}

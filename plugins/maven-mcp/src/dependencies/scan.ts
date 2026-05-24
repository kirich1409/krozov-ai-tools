import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parseGradleDependencies } from "./gradle-deps-parser.js";
import { parseMavenDependencies } from "./maven-deps-parser.js";
import { parseVersionCatalog } from "./toml-parser.js";
import type { ParsedCatalog } from "./toml-parser.js";
import { parseSettingsGradleModules } from "./settings-gradle-parser.js";
import { parseSettingsCatalogs } from "./settings-catalogs-parser.js";
import type { CatalogDescriptor } from "./settings-catalogs-parser.js";
import { parsePluginsBlock, parseBuildscriptClasspath } from "./plugins-block-parser.js";
import { parseMavenModules } from "./maven-modules-parser.js";

export type DepSource =
  | { kind: "catalog-library"; catalogName: string; tomlPath: string; alias: string }
  | { kind: "catalog-plugin"; catalogName: string; tomlPath: string; alias: string }
  | { kind: "module-direct"; file: string; module?: string }
  | { kind: "plugins-dsl"; file: string; module?: string; settingsBlock?: boolean }
  | { kind: "buildscript-classpath"; file: string };

/**
 * Compile-time exhaustiveness guard. Call from a `default` branch of a switch on a
 * discriminated union — if any variant is unhandled, TypeScript infers `value: never`
 * and the call fails to compile. At runtime throws to surface the gap.
 */
export function assertNever(value: never): never {
  throw new Error(`Unhandled DepSource kind: ${JSON.stringify(value)}`);
}

export interface DepUsage {
  module?: string;       // ":foo" / undefined for root
  configuration: string; // "implementation" / "testImplementation" / "classpath" / "plugin-dsl" / etc.
}

export interface ScannedDependency {
  groupId: string;
  artifactId: string;
  version: string | null;
  source: DepSource;
  usages: DepUsage[];   // empty for unused catalog entries; populated for everything else
}

export interface ScanResult {
  buildSystem: "gradle" | "maven" | "unknown";
  dependencies: ScannedDependency[];
}

const GRADLE_BUILD_FILES = ["build.gradle.kts", "build.gradle"] as const;
const GRADLE_SETTINGS_FILES = ["settings.gradle.kts", "settings.gradle"] as const;

// Guards against circular / malformed <modules> trees in Maven reactor projects.
const MAX_MODULE_DEPTH = 5;

interface CatalogData {
  tomlPath: string;
  parsed: ParsedCatalog;
}

function detectBuildSystem(projectRoot: string): ScanResult["buildSystem"] {
  for (const file of [...GRADLE_BUILD_FILES, ...GRADLE_SETTINGS_FILES]) {
    if (existsSync(join(projectRoot, file))) return "gradle";
  }
  // A version catalog TOML without any build file is still a Gradle project
  if (existsSync(join(projectRoot, "gradle", "libs.versions.toml"))) return "gradle";
  if (existsSync(join(projectRoot, "pom.xml"))) return "maven";
  return "unknown";
}

function readGradleSettingsFile(projectRoot: string): { content: string; file: string } | null {
  for (const file of GRADLE_SETTINGS_FILES) {
    const path = join(projectRoot, file);
    if (existsSync(path)) return { content: readFileSync(path, "utf-8"), file };
  }
  return null;
}

// Default Gradle layout only — `project(":foo").projectDir = ...` overrides are not supported.
function gradleModulePathToDir(projectRoot: string, modulePath: string): string {
  const parts = modulePath.replace(/^:/, "").split(":").filter(Boolean);
  return join(projectRoot, ...parts);
}

/**
 * Parses a full catalog ref (e.g. "libs.foo.bar" or "testLibs.x") into
 * { catalogName, alias } by splitting on the first ".".
 */
function parseCatalogRef(ref: string): { catalogName: string; alias: string } | null {
  const dotIdx = ref.indexOf(".");
  if (dotIdx === -1) return null;
  return { catalogName: ref.slice(0, dotIdx), alias: ref.slice(dotIdx + 1) };
}

/**
 * Loads catalog data for each descriptor. Returns a Map from catalog name to CatalogData.
 */
function loadCatalogs(projectRoot: string, descriptors: CatalogDescriptor[]): Map<string, CatalogData> {
  const map = new Map<string, CatalogData>();
  for (const desc of descriptors) {
    const tomlPath = join(projectRoot, desc.tomlPath);
    if (!existsSync(tomlPath)) continue;
    const content = readFileSync(tomlPath, "utf-8");
    map.set(desc.name, { tomlPath: desc.tomlPath, parsed: parseVersionCatalog(content) });
  }
  return map;
}

/**
 * Emits ScannedDependency entries for each catalog library and plugin declaration.
 * usages start as []. Populated later when build files reference them.
 */
function emitCatalogEntries(
  catalogs: Map<string, CatalogData>,
  result: ScannedDependency[],
  catalogEntryMap: Map<string, ScannedDependency>,
): void {
  for (const [catalogName, { tomlPath, parsed }] of catalogs) {
    for (const [alias, entry] of parsed.libraries) {
      const dep: ScannedDependency = {
        groupId: entry.groupId,
        artifactId: entry.artifactId,
        version: entry.version,
        source: { kind: "catalog-library", catalogName, tomlPath, alias },
        usages: [],
      };
      result.push(dep);
      // Key: catalogName + "." + alias (dotted) — also register dashed form
      catalogEntryMap.set(`${catalogName}.lib.${alias}`, dep);
      const dashed = alias.replace(/\./g, "-");
      if (dashed !== alias) {
        catalogEntryMap.set(`${catalogName}.lib.${dashed}`, dep);
      }
    }

    for (const [alias, entry] of parsed.plugins) {
      // Synthesize plugin marker artifact: groupId = pluginId, artifactId = pluginId + ".gradle.plugin"
      const dep: ScannedDependency = {
        groupId: entry.id,
        artifactId: `${entry.id}.gradle.plugin`,
        version: entry.version,
        source: { kind: "catalog-plugin", catalogName, tomlPath, alias },
        usages: [],
      };
      result.push(dep);
      // Key for plugin lookup from build files: catalogName.plugin.alias (both dotted and dashed)
      catalogEntryMap.set(`${catalogName}.plugin.${alias}`, dep);
      const dashed = alias.replace(/\./g, "-");
      if (dashed !== alias) {
        catalogEntryMap.set(`${catalogName}.plugin.${dashed}`, dep);
      }
    }
  }
}

/**
 * Processes dependencies from a single module's build.gradle[.kts] file,
 * adding usages to catalog entries or emitting new module-direct deps.
 */
function processBuildFileDeps(
  content: string,
  file: string,
  module: string | undefined,
  catalogs: Map<string, CatalogData>,
  catalogEntryMap: Map<string, ScannedDependency>,
  result: ScannedDependency[],
): void {
  const gradleDeps = parseGradleDependencies(content, file);
  for (const dep of gradleDeps) {
    if (dep.catalogRef) {
      const parsed = parseCatalogRef(dep.catalogRef);
      if (!parsed) continue;
      const { catalogName, alias } = parsed;
      if (!catalogs.has(catalogName)) continue;

      // Try both dotted alias (as-is from parser) and dashed form (TOML key convention)
      const dashedAlias = alias.replace(/\./g, "-");
      const entry = catalogEntryMap.get(`${catalogName}.lib.${alias}`)
        ?? catalogEntryMap.get(`${catalogName}.lib.${dashedAlias}`);
      if (entry) {
        entry.usages.push({ module, configuration: dep.configuration });
      }
      // If not found (catalog exists but alias missing) — silently drop
    } else if (dep.groupId && dep.artifactId) {
      result.push({
        groupId: dep.groupId,
        artifactId: dep.artifactId,
        version: dep.version,
        source: { kind: "module-direct", file, module },
        usages: [{ module, configuration: dep.configuration }],
      });
    }
  }
}

/**
 * Processes plugins {} block declarations for a module's build file.
 * catalogRef plugins add usages to existing catalog plugin entries.
 * Non-catalog plugins emit new ScannedDependency with kind: plugins-dsl.
 */
function processPluginsBlock(
  content: string,
  file: string,
  module: string | undefined,
  isSettings: boolean,
  catalogs: Map<string, CatalogData>,
  catalogEntryMap: Map<string, ScannedDependency>,
  result: ScannedDependency[],
): void {
  const declarations = parsePluginsBlock(content, { settings: isSettings });
  for (const decl of declarations) {
    if (decl.catalogRef) {
      // catalogRef format: "libs.plugins.foo" — catalog name is first segment,
      // then strip "plugins." prefix to get alias key in parsed.plugins map.
      const parsed = parseCatalogRef(decl.catalogRef);
      if (!parsed) continue;
      const { catalogName, alias: aliasPath } = parsed;
      if (!catalogs.has(catalogName)) continue;

      // aliasPath is "plugins.foo" — strip "plugins." prefix
      const pluginsPrefix = "plugins.";
      if (!aliasPath.startsWith(pluginsPrefix)) continue;
      const pluginAlias = aliasPath.slice(pluginsPrefix.length);

      // Try both dotted and dashed form (TOML key convention for plugins)
      const dashedPluginAlias = pluginAlias.replace(/\./g, "-");
      const entry = catalogEntryMap.get(`${catalogName}.plugin.${pluginAlias}`)
        ?? catalogEntryMap.get(`${catalogName}.plugin.${dashedPluginAlias}`);
      if (entry) {
        entry.usages.push({ module, configuration: "plugin-dsl" });
      }
      // If not found — silently drop
    } else if (decl.pluginId !== "(unresolved)") {
      const settingsBlock = decl.settingsBlock === true ? true : undefined;
      result.push({
        groupId: decl.pluginId,
        artifactId: `${decl.pluginId}.gradle.plugin`,
        version: decl.version,
        source: { kind: "plugins-dsl", file, module, settingsBlock },
        usages: [{ module, configuration: "plugin-dsl" }],
      });
    }
  }
}

/**
 * Processes buildscript classpath declarations from a build file.
 */
function processBuildscriptClasspath(
  content: string,
  file: string,
  result: ScannedDependency[],
): void {
  const classpathDeps = parseBuildscriptClasspath(content);
  for (const dep of classpathDeps) {
    result.push({
      groupId: dep.groupId,
      artifactId: dep.artifactId,
      version: dep.version,
      source: { kind: "buildscript-classpath", file },
      usages: [{ module: undefined, configuration: "classpath" }],
    });
  }
}

function scanMavenRecursive(
  modulePath: string,
  label: string | undefined,
  acc: ScannedDependency[],
  depth: number,
): void {
  const pomPath = join(modulePath, "pom.xml");
  if (!existsSync(pomPath)) return;

  const content = readFileSync(pomPath, "utf-8");
  // Use relative path within the module for the file field (always "pom.xml" relative to module root)
  const pomFile = label == null ? "pom.xml" : `${label}/pom.xml`;
  for (const dep of parseMavenDependencies(content)) {
    acc.push({
      groupId: dep.groupId,
      artifactId: dep.artifactId,
      version: dep.version,
      source: { kind: "module-direct", file: pomFile, module: label },
      usages: [{ module: label, configuration: dep.configuration }],
    });
  }

  if (depth >= MAX_MODULE_DEPTH) return;

  for (const sub of parseMavenModules(content)) {
    const childPath = join(modulePath, sub);
    const childLabel = label == null ? sub : `${label}/${sub}`;
    scanMavenRecursive(childPath, childLabel, acc, depth + 1);
  }
}

export function scanProjectWithSubmodules(projectRoot: string): ScanResult {
  const buildSystem = detectBuildSystem(projectRoot);
  const dependencies: ScannedDependency[] = [];

  if (buildSystem === "gradle") {
    // Step 1: Determine catalog descriptors from settings.gradle[.kts]
    const settingsResult = readGradleSettingsFile(projectRoot);
    let descriptors: CatalogDescriptor[];
    if (settingsResult) {
      descriptors = parseSettingsCatalogs(settingsResult.content);
    } else {
      // No settings file: use default descriptor if toml exists
      const defaultToml = join(projectRoot, "gradle", "libs.versions.toml");
      descriptors = existsSync(defaultToml)
        ? [{ name: "libs", tomlPath: "gradle/libs.versions.toml" }]
        : [];
    }

    // Step 2: Load all catalogs
    const catalogs = loadCatalogs(projectRoot, descriptors);

    // Step 3: Emit catalog entries (libraries + plugins) with empty usages
    const catalogEntryMap = new Map<string, ScannedDependency>();
    emitCatalogEntries(catalogs, dependencies, catalogEntryMap);

    // Step 4: Scan module build files for dependency usages
    const settingsContent = settingsResult?.content ?? null;
    const modules = settingsContent ? parseSettingsGradleModules(settingsContent) : [];

    for (const modulePath of modules) {
      const dir = gradleModulePathToDir(projectRoot, modulePath);
      for (const file of GRADLE_BUILD_FILES) {
        const path = join(dir, file);
        if (!existsSync(path)) continue;
        const content = readFileSync(path, "utf-8");
        processBuildFileDeps(content, file, modulePath, catalogs, catalogEntryMap, dependencies);
        processPluginsBlock(content, file, modulePath, false, catalogs, catalogEntryMap, dependencies);
        processBuildscriptClasspath(content, file, dependencies);
        break; // prefer .kts, skip .gradle if .kts found
      }
    }

    // Step 5: Scan root build file
    for (const file of GRADLE_BUILD_FILES) {
      const path = join(projectRoot, file);
      if (!existsSync(path)) continue;
      const content = readFileSync(path, "utf-8");
      processBuildFileDeps(content, file, undefined, catalogs, catalogEntryMap, dependencies);
      processPluginsBlock(content, file, undefined, false, catalogs, catalogEntryMap, dependencies);
      processBuildscriptClasspath(content, file, dependencies);
      break; // prefer .kts
    }

    // Step 6: Scan settings file for pluginManagement { plugins {} }
    if (settingsResult) {
      processPluginsBlock(
        settingsResult.content,
        settingsResult.file,
        undefined,
        true,
        catalogs,
        catalogEntryMap,
        dependencies,
      );
    }
  } else if (buildSystem === "maven") {
    scanMavenRecursive(projectRoot, undefined, dependencies, 0);
  }

  return { buildSystem, dependencies };
}

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parseGradleDependencies } from "./gradle-deps-parser.js";
import { parseMavenDependencies } from "./maven-deps-parser.js";
import { parseVersionCatalog } from "./toml-parser.js";
import type { CatalogEntry } from "./toml-parser.js";
import { parseSettingsGradleModules } from "./settings-gradle-parser.js";
import { parseMavenModules } from "./maven-modules-parser.js";

export interface ScannedDependency {
  groupId: string;
  artifactId: string;
  version: string | null;
  configuration: string;
  source: string;
  // Submodule label: ":foo" / ":foo:bar" for Gradle subprojects, "foo" / "foo/sub" for Maven
  // submodules, undefined for the root project. Formats differ because Gradle paths are
  // colon-separated by spec; consumers must handle both shapes.
  module?: string;
}

export interface ScanResult {
  buildSystem: "gradle" | "maven" | "unknown";
  dependencies: ScannedDependency[];
}

const GRADLE_BUILD_FILES = ["build.gradle.kts", "build.gradle"] as const;
const GRADLE_SETTINGS_FILES = ["settings.gradle.kts", "settings.gradle"] as const;

// Guards against circular / malformed <modules> trees in Maven reactor projects.
const MAX_MODULE_DEPTH = 5;

function resolveCatalogRef(ref: string, catalog: Map<string, CatalogEntry>): CatalogEntry | undefined {
  const dashed = ref.replace(/\./g, "-");
  return catalog.get(dashed) ?? catalog.get(ref);
}

function readCatalog(projectRoot: string): Map<string, CatalogEntry> {
  const catalogPath = join(projectRoot, "gradle", "libs.versions.toml");
  if (!existsSync(catalogPath)) return new Map();
  return parseVersionCatalog(readFileSync(catalogPath, "utf-8"));
}

// `label` becomes ScannedDependency.module: undefined for the root, ":foo" / "core/sub" for
// Gradle / Maven submodules. `catalog` is the root's libs.versions.toml shared across modules.
function scanSingleModule(
  modulePath: string,
  label: string | undefined,
  catalog: Map<string, CatalogEntry>,
): ScannedDependency[] {
  const deps: ScannedDependency[] = [];

  for (const file of GRADLE_BUILD_FILES) {
    const path = join(modulePath, file);
    if (!existsSync(path)) continue;

    const content = readFileSync(path, "utf-8");
    const gradleDeps = parseGradleDependencies(content, file);

    for (const dep of gradleDeps) {
      if (dep.catalogRef) {
        const entry = resolveCatalogRef(dep.catalogRef, catalog);
        if (entry) {
          deps.push({
            groupId: entry.groupId,
            artifactId: entry.artifactId,
            version: entry.version,
            configuration: dep.configuration,
            source: "libs.versions.toml",
            module: label,
          });
        }
      } else if (dep.groupId && dep.artifactId) {
        deps.push({
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          version: dep.version,
          configuration: dep.configuration,
          source: file,
          module: label,
        });
      }
    }
    return deps;
  }

  const pomPath = join(modulePath, "pom.xml");
  if (existsSync(pomPath)) {
    const content = readFileSync(pomPath, "utf-8");
    for (const dep of parseMavenDependencies(content)) {
      deps.push({ ...dep, module: label });
    }
  }

  return deps;
}

function detectBuildSystem(projectRoot: string): ScanResult["buildSystem"] {
  for (const file of [...GRADLE_BUILD_FILES, ...GRADLE_SETTINGS_FILES]) {
    if (existsSync(join(projectRoot, file))) return "gradle";
  }
  if (existsSync(join(projectRoot, "pom.xml"))) return "maven";
  return "unknown";
}

export function scanDependencies(projectRoot: string): ScanResult {
  const catalog = readCatalog(projectRoot);
  const buildSystem = detectBuildSystem(projectRoot);
  const dependencies = scanSingleModule(projectRoot, undefined, catalog);
  return { buildSystem, dependencies };
}

export function scanProjectWithSubmodules(projectRoot: string): ScanResult {
  const buildSystem = detectBuildSystem(projectRoot);
  const catalog = readCatalog(projectRoot);
  const dependencies: ScannedDependency[] = [];

  if (buildSystem === "gradle") {
    const settingsContent = readGradleSettings(projectRoot);
    if (settingsContent) {
      const modules = parseSettingsGradleModules(settingsContent);
      for (const modulePath of modules) {
        const dir = gradleModulePathToDir(projectRoot, modulePath);
        dependencies.push(...scanSingleModule(dir, modulePath, catalog));
      }
    }
    // Root build.gradle[.kts] often carries platform / convention deps in multi-module setups.
    dependencies.push(...scanSingleModule(projectRoot, undefined, catalog));
  } else if (buildSystem === "maven") {
    scanMavenRecursive(projectRoot, undefined, dependencies, 0);
  }

  return { buildSystem, dependencies };
}

function readGradleSettings(projectRoot: string): string | null {
  for (const file of GRADLE_SETTINGS_FILES) {
    const path = join(projectRoot, file);
    if (existsSync(path)) return readFileSync(path, "utf-8");
  }
  return null;
}

// Default Gradle layout only — `project(":foo").projectDir = ...` overrides are not supported.
function gradleModulePathToDir(projectRoot: string, modulePath: string): string {
  const parts = modulePath.replace(/^:/, "").split(":").filter(Boolean);
  return join(projectRoot, ...parts);
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
  for (const dep of parseMavenDependencies(content)) {
    acc.push({ ...dep, module: label });
  }

  if (depth >= MAX_MODULE_DEPTH) return;

  for (const sub of parseMavenModules(content)) {
    const childPath = join(modulePath, sub);
    const childLabel = label == null ? sub : `${label}/${sub}`;
    scanMavenRecursive(childPath, childLabel, acc, depth + 1);
  }
}

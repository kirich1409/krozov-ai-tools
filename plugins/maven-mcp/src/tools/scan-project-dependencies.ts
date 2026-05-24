import { scanProjectWithSubmodules, assertNever } from "../dependencies/scan.js";
import type { ScanResult, DepSource } from "../dependencies/scan.js";
import { findProjectRoot } from "../project/find-project-root.js";

export interface ScanProjectInput {
  projectPath?: string;
}

interface FlattenedDependency {
  groupId: string;
  artifactId: string;
  version: string | null;
  configuration: string;
  module?: string;
  /**
   * File path of the artifact that declared this dependency.
   * Catalog entries: TOML file path (e.g. "gradle/libs.versions.toml").
   * Direct/plugin/buildscript entries: build file name (e.g. "build.gradle.kts", "pom.xml").
   * Preserved for backward compatibility — use sourceKind for the new discriminator.
   */
  source: string;
  /** Discriminator for the dependency source kind (e.g. "catalog-library", "module-direct", "plugins-dsl"). */
  sourceKind: DepSource["kind"];
}

export interface FlatScanResult {
  buildSystem: ScanResult["buildSystem"];
  dependencies: FlattenedDependency[];
}

/**
 * Returns the file path component of a DepSource for the backward-compatible `source` field.
 * Catalog entries emit the TOML path; all others emit the build file name.
 */
function sourceFilePath(src: DepSource): string {
  switch (src.kind) {
    case "catalog-library":
    case "catalog-plugin":
      return src.tomlPath;
    case "module-direct":
    case "plugins-dsl":
      return src.file;
    case "buildscript-classpath":
      return src.file;
    default:
      return assertNever(src);
  }
}

/**
 * Flattens the new ScannedDependency shape (with usages[]) back into the old flat shape
 * for backward compatibility with existing callers of scan_project_dependencies.
 *
 * - usages.length === 0 (unused catalog entry) → one item with configuration: "(unused)"
 * - usages.length === 1 → one item
 * - usages.length > 1 (same catalog entry used in multiple modules) → one item per usage
 */
function flattenScanResult(scan: ReturnType<typeof scanProjectWithSubmodules>): FlatScanResult {
  const dependencies: FlattenedDependency[] = [];

  for (const dep of scan.dependencies) {
    const sourceFile = sourceFilePath(dep.source);
    const sourceKind = dep.source.kind;
    if (dep.usages.length === 0) {
      dependencies.push({
        groupId: dep.groupId,
        artifactId: dep.artifactId,
        version: dep.version,
        configuration: "(unused)",
        module: undefined,
        source: sourceFile,
        sourceKind,
      });
    } else {
      for (const usage of dep.usages) {
        dependencies.push({
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          version: dep.version,
          configuration: usage.configuration,
          module: usage.module,
          source: sourceFile,
          sourceKind,
        });
      }
    }
  }

  return { buildSystem: scan.buildSystem, dependencies };
}

export function scanProjectDependenciesHandler(input: ScanProjectInput): FlatScanResult {
  const projectRoot = input.projectPath ?? findProjectRoot(process.cwd()) ?? process.cwd();
  const scan = scanProjectWithSubmodules(projectRoot);
  return flattenScanResult(scan);
}

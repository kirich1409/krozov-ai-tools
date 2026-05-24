import { scanProjectWithSubmodules } from "../dependencies/scan.js";
import type { ScanResult } from "../dependencies/scan.js";
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
  source: string;
}

export interface FlatScanResult {
  buildSystem: ScanResult["buildSystem"];
  dependencies: FlattenedDependency[];
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
    const sourceLabel = dep.source.kind;
    if (dep.usages.length === 0) {
      dependencies.push({
        groupId: dep.groupId,
        artifactId: dep.artifactId,
        version: dep.version,
        configuration: "(unused)",
        module: undefined,
        source: sourceLabel,
      });
    } else {
      for (const usage of dep.usages) {
        dependencies.push({
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          version: dep.version,
          configuration: usage.configuration,
          module: usage.module,
          source: sourceLabel,
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

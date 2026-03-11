import { scanDependencies } from "../dependencies/scan.js";
import { findProjectRoot } from "../project/find-project-root.js";

export interface ScanProjectInput {
  projectPath?: string;
}

export function scanProjectDependenciesHandler(input: ScanProjectInput) {
  const projectRoot = input.projectPath ?? findProjectRoot(process.cwd()) ?? process.cwd();
  return scanDependencies(projectRoot);
}

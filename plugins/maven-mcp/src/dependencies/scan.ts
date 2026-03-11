import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parseGradleDependencies } from "./gradle-deps-parser.js";
import { parseMavenDependencies } from "./maven-deps-parser.js";
import { parseVersionCatalog } from "./toml-parser.js";
import type { CatalogEntry } from "./toml-parser.js";

export interface ScannedDependency {
  groupId: string;
  artifactId: string;
  version: string | null;
  configuration: string;
  source: string;
}

export interface ScanResult {
  buildSystem: "gradle" | "maven" | "unknown";
  dependencies: ScannedDependency[];
}

function resolveCatalogRef(ref: string, catalog: Map<string, CatalogEntry>): CatalogEntry | undefined {
  const dashed = ref.replace(/\./g, "-");
  return catalog.get(dashed) ?? catalog.get(ref);
}

export function scanDependencies(projectRoot: string): ScanResult {
  const deps: ScannedDependency[] = [];
  const gradleFiles = ["build.gradle.kts", "build.gradle"];
  let buildSystem: ScanResult["buildSystem"] = "unknown";

  for (const file of gradleFiles) {
    const path = join(projectRoot, file);
    if (!existsSync(path)) continue;
    buildSystem = "gradle";

    const content = readFileSync(path, "utf-8");
    const gradleDeps = parseGradleDependencies(content, file);

    const catalogPath = join(projectRoot, "gradle", "libs.versions.toml");
    let catalog = new Map<string, CatalogEntry>();
    if (existsSync(catalogPath)) {
      catalog = parseVersionCatalog(readFileSync(catalogPath, "utf-8"));
    }

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
          });
        }
      } else if (dep.groupId && dep.artifactId) {
        deps.push({
          groupId: dep.groupId,
          artifactId: dep.artifactId,
          version: dep.version,
          configuration: dep.configuration,
          source: file,
        });
      }
    }
    break;
  }

  if (buildSystem === "unknown") {
    const pomPath = join(projectRoot, "pom.xml");
    if (existsSync(pomPath)) {
      buildSystem = "maven";
      const content = readFileSync(pomPath, "utf-8");
      deps.push(...parseMavenDependencies(content));
    }
  }

  return { buildSystem, dependencies: deps };
}

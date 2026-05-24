import type { MavenRepository } from "../maven/repository.js";
import type { MavenMetadata } from "../maven/types.js";
import type { UpgradeType } from "../version/types.js";
import { scanProjectWithSubmodules } from "../dependencies/scan.js";
import type { ScanResult, ScannedDependency, DepSource, DepUsage } from "../dependencies/scan.js";
import { isTestConfiguration } from "../dependencies/gradle-deps-parser.js";
import { findProjectRoot } from "../project/find-project-root.js";
import { resolveAll } from "../maven/resolver.js";
import { findLatestVersionForCurrent } from "../version/classify.js";
import { getUpgradeType } from "../version/compare.js";
import { queryOsvBatch } from "../vulnerabilities/osv-client.js";

export interface AuditInput {
  projectPath?: string;
  includeVulnerabilities?: boolean;
  productionOnly?: boolean;
}

export interface AuditDependency {
  groupId: string;
  artifactId: string;
  currentVersion?: string;
  latestVersion?: string;
  upgradeType?: UpgradeType;
  vulnerabilities?: { id: string; severity?: string; fixedVersion?: string }[];
  /**
   * Discriminated union identifying where this dependency originates.
   * Consumers should use this instead of inferring source from module/configuration.
   */
  source: DepSource;
  /**
   * All module:configuration pairs that use this dependency.
   * For catalog entries, may be empty (unused catalog entry — still audited for version/CVE).
   * For non-catalog entries, always has exactly one element.
   * When productionOnly is true and the entry has mixed prod+test usages, all usages are
   * retained in this array — filtering only controls inclusion, not which usages are shown.
   */
  usages: DepUsage[];
  /**
   * @deprecated Legacy field. Use usages[0]?.module instead.
   * Submodule label from the first usage: ":foo" / ":foo:bar" for Gradle,
   * "foo" / "foo/sub" for Maven, undefined for root. Two formats differ by design
   * (Gradle paths are colon-separated); consumers must handle both shapes.
   */
  module?: string;
  /**
   * @deprecated Legacy field. Use usages[0]?.configuration instead.
   * Configuration name from the first usage.
   */
  configuration?: string;
}

/**
 * productionOnly filter policy:
 *
 * - catalog-library / catalog-plugin with non-empty usages:
 *     include if at least one usage is NOT test-scope (per isTestConfiguration).
 *     Exclude if ALL usages are test-scope.
 *
 * - catalog-library / catalog-plugin with empty usages (unused catalog entry):
 *     ALWAYS include when productionOnly is true.
 *     Rationale: the catalog is the single source of truth for declared dependencies;
 *     unused entries still need version updates and CVE scanning.
 *
 * - module-direct / plugins-dsl / buildscript-classpath:
 *     include if the single usage's configuration is NOT test-scope.
 *     "plugin-dsl" and "classpath" are always production (isTestConfiguration returns false).
 */
function isIncludedInProductionAudit(dep: ScannedDependency): boolean {
  const { source, usages } = dep;
  if (source.kind === "catalog-library" || source.kind === "catalog-plugin") {
    if (usages.length === 0) return true; // unused catalog entry — always include
    return usages.some((u) => !isTestConfiguration(u.configuration));
  }
  // module-direct, plugins-dsl, buildscript-classpath — single usage
  if (usages.length === 0) return false;
  return !isTestConfiguration(usages[0].configuration);
}

export interface AuditResult {
  buildSystem: ScanResult["buildSystem"];
  dependencies: AuditDependency[];
  summary: {
    total: number;
    upgradeable: number;
    vulnerable: number;
    major: number;
    minor: number;
    patch: number;
  };
}

export async function auditProjectDependenciesHandler(
  repos: MavenRepository[],
  input: AuditInput,
): Promise<AuditResult> {
  const projectRoot = input.projectPath ?? findProjectRoot(process.cwd()) ?? process.cwd();
  const scan = scanProjectWithSubmodules(projectRoot);
  const includeVulns = input.includeVulnerabilities !== false;
  const productionOnly = input.productionOnly !== false;

  // productionOnly: use isIncludedInProductionAudit which handles catalog unused entries,
  // mixed prod+test usages, and non-catalog entries (see JSDoc above).
  // When productionOnly is false, include all deps — including unused catalog entries.
  const filteredScanDeps = productionOnly
    ? scan.dependencies.filter(isIncludedInProductionAudit)
    : scan.dependencies;

  const auditDeps: AuditDependency[] = [];

  const depsWithVersion = filteredScanDeps.filter((d) => d.version !== null);
  const depsWithoutVersion = filteredScanDeps.filter((d) => d.version === null);

  // Memoize resolveAll per GA to avoid redundant metadata fetches for duplicate deps
  const metadataCache = new Map<string, Promise<MavenMetadata>>();

  const versionResults = await Promise.all(
    depsWithVersion.map(async (dep) => {
      try {
        const gaKey = `${dep.groupId}:${dep.artifactId}`;
        if (!metadataCache.has(gaKey)) {
          metadataCache.set(gaKey, resolveAll(repos, dep.groupId, dep.artifactId));
        }
        const metadata = await metadataCache.get(gaKey)!;
        const latest = findLatestVersionForCurrent(metadata.versions, dep.version!);
        const upgradeType = latest ? getUpgradeType(dep.version!, latest) : "none" as const;
        return { dep, latest, upgradeType };
      } catch {
        return { dep, latest: undefined, upgradeType: undefined };
      }
    }),
  );

  for (const { dep, latest, upgradeType } of versionResults) {
    auditDeps.push({
      groupId: dep.groupId,
      artifactId: dep.artifactId,
      currentVersion: dep.version!,
      latestVersion: latest,
      upgradeType,
      source: dep.source,
      usages: dep.usages,
      module: dep.usages[0]?.module,
      configuration: dep.usages[0]?.configuration,
    });
  }

  for (const dep of depsWithoutVersion) {
    auditDeps.push({
      groupId: dep.groupId,
      artifactId: dep.artifactId,
      source: dep.source,
      usages: dep.usages,
      module: dep.usages[0]?.module,
      configuration: dep.usages[0]?.configuration,
    });
  }

  // Vulnerability check — deduplicate OSV queries by GAV, then map results back.
  // Plugin marker artifacts (pluginId + ".gradle.plugin") are queried via the same Maven
  // ecosystem path as regular deps. OSV indexes implementation artifacts, not plugin markers —
  // CVEs are filed against e.g. "org.jetbrains.kotlin:kotlin-gradle-plugin", not the marker
  // "org.jetbrains.kotlin.android:org.jetbrains.kotlin.android.gradle.plugin". Plugin entries
  // therefore always return no advisories here — a known v1 limitation; resolving marker →
  // implementation GAV via POM lookup is tracked for v2.
  if (includeVulns && depsWithVersion.length > 0) {
    const auditDepMap = new Map<string, AuditDependency[]>();
    for (const a of auditDeps) {
      if (!a.currentVersion) continue;
      const key = `${a.groupId}:${a.artifactId}:${a.currentVersion}`;
      const existing = auditDepMap.get(key);
      if (existing) {
        existing.push(a);
      } else {
        auditDepMap.set(key, [a]);
      }
    }

    const uniqueGavs = [...auditDepMap.entries()].map(([key, deps]) => {
      const d = deps[0];
      return { key, groupId: d.groupId, artifactId: d.artifactId, version: d.currentVersion! };
    });

    const vulnResults = await queryOsvBatch(
      uniqueGavs.map((d) => ({
        groupId: d.groupId, artifactId: d.artifactId, version: d.version,
      })),
    );

    for (let i = 0; i < uniqueGavs.length; i++) {
      const targets = auditDepMap.get(uniqueGavs[i].key);
      if (targets) {
        const mappedVulns = vulnResults[i].vulnerabilities.map((v) => ({
          id: v.id, severity: v.severity, fixedVersion: v.fixedVersion,
        }));
        for (const target of targets) {
          target.vulnerabilities = mappedVulns;
        }
      }
    }
  }

  const summary = {
    total: auditDeps.length,
    upgradeable: auditDeps.filter((d) => d.upgradeType && d.upgradeType !== "none").length,
    vulnerable: auditDeps.filter((d) => d.vulnerabilities && d.vulnerabilities.length > 0).length,
    major: auditDeps.filter((d) => d.upgradeType === "major").length,
    minor: auditDeps.filter((d) => d.upgradeType === "minor").length,
    patch: auditDeps.filter((d) => d.upgradeType === "patch").length,
  };

  return { buildSystem: scan.buildSystem, dependencies: auditDeps, summary };
}

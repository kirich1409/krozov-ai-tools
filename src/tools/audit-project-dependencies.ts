import type { MavenRepository } from "../maven/repository.js";
import type { UpgradeType } from "../version/types.js";
import { scanDependencies } from "../dependencies/scan.js";
import { findProjectRoot } from "../project/find-project-root.js";
import { resolveAll } from "../maven/resolver.js";
import { findLatestVersionForCurrent } from "../version/classify.js";
import { getUpgradeType } from "../version/compare.js";
import { queryOsvBatch } from "../vulnerabilities/osv-client.js";

export interface AuditInput {
  projectPath?: string;
  includeVulnerabilities?: boolean;
}

export interface AuditDependency {
  groupId: string;
  artifactId: string;
  currentVersion?: string;
  latestVersion?: string;
  upgradeType?: UpgradeType;
  vulnerabilities?: { id: string; severity?: string; fixedVersion?: string }[];
}

export interface AuditResult {
  buildSystem: ReturnType<typeof scanDependencies>["buildSystem"];
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
  const scan = scanDependencies(projectRoot);
  const includeVulns = input.includeVulnerabilities !== false;

  const auditDeps: AuditDependency[] = [];

  const depsWithVersion = scan.dependencies.filter((d) => d.version !== null);
  const depsWithoutVersion = scan.dependencies.filter((d) => d.version === null);

  // Memoize resolveAll per GA to avoid redundant metadata fetches for duplicate deps
  const metadataCache = new Map<string, ReturnType<typeof resolveAll>>();

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
    });
  }

  for (const dep of depsWithoutVersion) {
    auditDeps.push({ groupId: dep.groupId, artifactId: dep.artifactId });
  }

  // Vulnerability check — deduplicate OSV queries by GAV, then map results back
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

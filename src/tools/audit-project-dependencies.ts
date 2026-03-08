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
  buildSystem: string;
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

  // Fetch latest versions in parallel
  const versionResults = await Promise.all(
    depsWithVersion.map(async (dep) => {
      try {
        const metadata = await resolveAll(repos, dep.groupId, dep.artifactId);
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

  // Vulnerability check — correlate by groupId:artifactId key, not positional index
  if (includeVulns && depsWithVersion.length > 0) {
    const vulnResults = await queryOsvBatch(
      depsWithVersion.map((d) => ({
        groupId: d.groupId, artifactId: d.artifactId, version: d.version!,
      })),
    );
    for (let i = 0; i < depsWithVersion.length; i++) {
      const dep = depsWithVersion[i];
      const target = auditDeps.find(
        (a) => a.groupId === dep.groupId && a.artifactId === dep.artifactId,
      );
      if (target) {
        target.vulnerabilities = vulnResults[i].vulnerabilities.map((v) => ({
          id: v.id, severity: v.severity, fixedVersion: v.fixedVersion,
        }));
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

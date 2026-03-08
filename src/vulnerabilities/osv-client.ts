const OSV_API = "https://api.osv.dev/v1/querybatch";

interface DependencyRef {
  groupId: string;
  artifactId: string;
  version: string;
}

export interface VulnerabilityInfo {
  id: string;
  summary: string;
  severity?: string;
  fixedVersion?: string;
  url: string;
}

export interface DependencyVulnerabilities {
  groupId: string;
  artifactId: string;
  version: string;
  vulnerabilities: VulnerabilityInfo[];
}

interface OsvSeverity {
  type: string;
  score: string;
}

interface OsvEvent {
  introduced?: string;
  fixed?: string;
}

interface OsvRange {
  type: string;
  events: OsvEvent[];
}

interface OsvAffected {
  ranges?: OsvRange[];
}

interface OsvReference {
  type: string;
  url: string;
}

interface OsvVulnerability {
  id: string;
  summary?: string;
  severity?: OsvSeverity[];
  affected?: OsvAffected[];
  references?: OsvReference[];
}

interface OsvBatchResponse {
  results: { vulns?: OsvVulnerability[] }[];
}

function cvssToSeverity(score: number): string {
  if (score >= 9.0) return "CRITICAL";
  if (score >= 7.0) return "HIGH";
  if (score >= 4.0) return "MEDIUM";
  return "LOW";
}

function extractSeverity(vuln: OsvVulnerability): string | undefined {
  const cvss = vuln.severity?.find((s) => s.type === "CVSS_V3" || s.type === "CVSS_V4");
  if (cvss?.score) return cvssToSeverity(parseFloat(cvss.score));
  return undefined;
}

function extractFixedVersion(vuln: OsvVulnerability): string | undefined {
  for (const affected of vuln.affected ?? []) {
    for (const range of affected.ranges ?? []) {
      if (range.type !== "ECOSYSTEM") continue;
      for (const event of range.events ?? []) {
        if (event.fixed) return event.fixed;
      }
    }
  }
  return undefined;
}

function extractUrl(vuln: OsvVulnerability): string {
  const advisory = vuln.references?.find((r) => r.type === "ADVISORY");
  return advisory?.url ?? `https://osv.dev/vulnerability/${vuln.id}`;
}

export async function queryOsvBatch(deps: DependencyRef[]): Promise<DependencyVulnerabilities[]> {
  const queries = deps.map((dep) => ({
    package: { name: `${dep.groupId}:${dep.artifactId}`, ecosystem: "Maven" },
    version: dep.version,
  }));

  try {
    const response = await fetch(OSV_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ queries }),
      signal: AbortSignal.timeout(15_000),
    });

    if (!response.ok) {
      return deps.map((dep) => ({ ...dep, vulnerabilities: [] }));
    }

    const data = (await response.json()) as OsvBatchResponse;

    return deps.map((dep, i) => {
      const vulns = data.results[i]?.vulns ?? [];
      return {
        ...dep,
        vulnerabilities: vulns.map((v) => ({
          id: v.id,
          summary: v.summary ?? "",
          severity: extractSeverity(v),
          fixedVersion: extractFixedVersion(v),
          url: extractUrl(v),
        })),
      };
    });
  } catch {
    return deps.map((dep) => ({ ...dep, vulnerabilities: [] }));
  }
}

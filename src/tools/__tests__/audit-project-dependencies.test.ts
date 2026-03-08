import { describe, it, expect, vi, beforeEach } from "vitest";
import { auditProjectDependenciesHandler } from "../audit-project-dependencies.js";
import * as fs from "node:fs";
import type { MavenRepository } from "../../maven/repository.js";

vi.mock("node:fs");
const mockedFs = vi.mocked(fs);

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function mockRepo(versions: string[]): MavenRepository {
  return {
    name: "central",
    url: "https://repo1.maven.org/maven2",
    fetchMetadata: vi.fn().mockResolvedValue({
      groupId: "io.ktor", artifactId: "ktor-client-core", versions,
      latest: versions[versions.length - 1],
      release: versions[versions.length - 1],
    }),
  };
}

function mockGradleProject(content: string) {
  mockedFs.existsSync.mockImplementation((p: fs.PathLike) => {
    if (p.toString().endsWith("build.gradle.kts")) return true;
    return false;
  });
  mockedFs.readFileSync.mockReturnValue(content);
}

describe("auditProjectDependenciesHandler", () => {
  beforeEach(() => vi.clearAllMocks());

  it("scans, compares, and checks vulnerabilities", async () => {
    mockGradleProject(`
dependencies {
    implementation("io.ktor:ktor-client-core:3.0.0")
}`);

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ results: [{ vulns: [] }] }),
    });

    const repos = [mockRepo(["3.0.0", "3.1.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: true,
    });

    expect(result.summary.total).toBe(1);
    expect(result.summary.upgradeable).toBe(1);
    expect(result.dependencies[0].currentVersion).toBe("3.0.0");
    expect(result.dependencies[0].latestVersion).toBe("3.1.1");
    expect(result.dependencies[0].upgradeType).toBe("minor");
  });

  it("skips deps without version", async () => {
    mockGradleProject(`implementation("io.ktor:ktor-bom")`);

    const repos = [mockRepo([])];
    const result = await auditProjectDependenciesHandler(repos, { projectPath: "/project" });

    expect(result.summary.total).toBe(1);
    expect(result.dependencies[0].upgradeType).toBeUndefined();
  });

  it("skips vulnerability check when includeVulnerabilities is false", async () => {
    mockGradleProject(`implementation("io.ktor:ktor-client-core:3.0.0")`);

    const repos = [mockRepo(["3.0.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    expect(mockFetch).not.toHaveBeenCalled();
    expect(result.dependencies[0].vulnerabilities).toBeUndefined();
  });

  it("handles resolution failure gracefully", async () => {
    mockGradleProject(`implementation("io.ktor:ktor-client-core:3.0.0")`);

    const failingRepo: MavenRepository = {
      name: "central",
      url: "https://repo1.maven.org/maven2",
      fetchMetadata: vi.fn().mockResolvedValue(null),
    };

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ results: [{ vulns: [] }] }),
    });

    const result = await auditProjectDependenciesHandler([failingRepo], {
      projectPath: "/project",
    });

    expect(result.summary.total).toBe(1);
    expect(result.dependencies[0].upgradeType).toBeUndefined();
    expect(result.dependencies[0].latestVersion).toBeUndefined();
  });

  it("reports vulnerabilities in summary count", async () => {
    mockGradleProject(`implementation("io.ktor:ktor-client-core:3.0.0")`);

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        results: [{
          vulns: [{
            id: "GHSA-1234",
            summary: "test vuln",
            database_specific: { severity: "HIGH" },
            affected: [{ ranges: [{ type: "ECOSYSTEM", events: [{ fixed: "3.1.0" }] }] }],
            references: [],
          }],
        }],
      }),
    });

    const repos = [mockRepo(["3.0.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, { projectPath: "/project" });

    expect(result.summary.vulnerable).toBe(1);
    expect(result.dependencies[0].vulnerabilities).toHaveLength(1);
    expect(result.dependencies[0].vulnerabilities![0].id).toBe("GHSA-1234");
  });
});

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

// Mock fs for multi-module fixtures: files keyed by absolute path → content.
// existsSync returns true iff the path exists in the map; readFileSync returns
// the matching content or throws (mirrors real node:fs behavior).
function mockFileSystem(files: Record<string, string>) {
  mockedFs.existsSync.mockImplementation((p: fs.PathLike) =>
    Object.prototype.hasOwnProperty.call(files, p.toString()),
  );
  mockedFs.readFileSync.mockImplementation((p: fs.PathOrFileDescriptor) => {
    const key = p.toString();
    if (!Object.prototype.hasOwnProperty.call(files, key)) {
      throw new Error(`ENOENT: no such file '${key}'`);
    }
    return files[key];
  });
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

  it("handles duplicate dependencies with same GA but different versions", async () => {
    mockGradleProject(`
dependencies {
    implementation("io.ktor:ktor-client-core:3.0.0")
    testImplementation("io.ktor:ktor-client-core:3.1.0")
}`);

    const repos = [mockRepo(["3.0.0", "3.1.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
      productionOnly: false,
    });

    expect(result.dependencies).toHaveLength(2);
    expect(result.dependencies[0].currentVersion).toBe("3.0.0");
    expect(result.dependencies[1].currentVersion).toBe("3.1.0");
  });

  it("deduplicates OSV queries for same GAV and maps vulns to all entries", async () => {
    mockGradleProject(`
dependencies {
    implementation("io.ktor:ktor-client-core:3.0.0")
    testImplementation("io.ktor:ktor-client-core:3.0.0")
}`);

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        results: [{
          vulns: [{
            id: "GHSA-5678",
            summary: "test vuln",
            database_specific: { severity: "MEDIUM" },
            affected: [],
            references: [],
          }],
        }],
      }),
    });

    const repos = [mockRepo(["3.0.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: true,
      productionOnly: false,
    });

    // Only one OSV query should be made (deduplicated)
    expect(mockFetch).toHaveBeenCalledTimes(1);
    // Both entries should have the same vulnerability
    expect(result.dependencies).toHaveLength(2);
    expect(result.dependencies[0].vulnerabilities).toHaveLength(1);
    expect(result.dependencies[0].vulnerabilities![0].id).toBe("GHSA-5678");
    expect(result.dependencies[1].vulnerabilities).toHaveLength(1);
    expect(result.dependencies[1].vulnerabilities![0].id).toBe("GHSA-5678");
    expect(result.summary.vulnerable).toBe(2);
  });

  it("excludes testImplementation when productionOnly is true, keeps kapt/ksp as production", async () => {
    mockGradleProject(`
dependencies {
    implementation("io.ktor:ktor-client-core:3.0.0")
    testImplementation("junit:junit:4.13")
    kapt("com.google.dagger:dagger-compiler:2.50")
    ksp("androidx.room:room-compiler:2.6.0")
}`);

    const repos = [mockRepo(["3.0.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    // testImplementation is test-scope → excluded
    // kapt and ksp are NOT test-scope → included (annotation processors are production tools)
    expect(result.dependencies).toHaveLength(3);
    const artifacts = result.dependencies.map((d) => d.artifactId).sort();
    expect(artifacts).toEqual(["dagger-compiler", "ktor-client-core", "room-compiler"]);
  });

  it("includes test configurations when productionOnly is false", async () => {
    mockGradleProject(`
dependencies {
    implementation("io.ktor:ktor-client-core:3.0.0")
    testImplementation("junit:junit:4.13")
    kapt("com.google.dagger:dagger-compiler:2.50")
}`);

    const repos = [mockRepo(["3.0.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
      productionOnly: false,
    });

    expect(result.dependencies).toHaveLength(3);
    const artifacts = result.dependencies.map((d) => d.artifactId).sort();
    expect(artifacts).toEqual(["dagger-compiler", "junit", "ktor-client-core"]);
  });

  it("scans Gradle multi-module project with :app and :lib", async () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":app", ":lib")`,
      "/project/app/build.gradle.kts": `implementation("io.ktor:ktor-client-core:3.0.0")`,
      "/project/lib/build.gradle.kts": `api("io.ktor:ktor-client-core:3.1.0")`,
    });

    const repos = [mockRepo(["3.0.0", "3.1.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    expect(result.buildSystem).toBe("gradle");
    expect(result.dependencies).toHaveLength(2);
    const byModule = Object.fromEntries(
      result.dependencies.map((d) => [d.module, d.currentVersion]),
    );
    expect(byModule).toEqual({ ":app": "3.0.0", ":lib": "3.1.0" });
  });

  it("scans Maven multi-module project with two <module> entries", async () => {
    mockFileSystem({
      "/project/pom.xml": `
<project>
  <modules>
    <module>core</module>
    <module>app</module>
  </modules>
</project>`,
      "/project/core/pom.xml": `
<project>
  <dependencies>
    <dependency>
      <groupId>io.ktor</groupId>
      <artifactId>ktor-client-core</artifactId>
      <version>3.0.0</version>
    </dependency>
  </dependencies>
</project>`,
      "/project/app/pom.xml": `
<project>
  <dependencies>
    <dependency>
      <groupId>io.ktor</groupId>
      <artifactId>ktor-client-core</artifactId>
      <version>3.1.0</version>
    </dependency>
  </dependencies>
</project>`,
    });

    const repos = [mockRepo(["3.0.0", "3.1.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    expect(result.buildSystem).toBe("maven");
    expect(result.dependencies).toHaveLength(2);
    const byModule = Object.fromEntries(
      result.dependencies.map((d) => [d.module, d.currentVersion]),
    );
    expect(byModule).toEqual({ core: "3.0.0", app: "3.1.0" });
  });

  it("propagates module field through audit output", async () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":app")`,
      "/project/app/build.gradle.kts": `implementation("io.ktor:ktor-client-core:3.0.0")`,
    });

    const repos = [mockRepo(["3.0.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    expect(result.dependencies).toHaveLength(1);
    expect(result.dependencies[0].module).toBe(":app");
  });

  it("assigns different vulns to correct versioned entries for same GA", async () => {
    mockGradleProject(`
dependencies {
    implementation("io.ktor:ktor-client-core:3.0.0")
    testImplementation("io.ktor:ktor-client-core:3.1.0")
}`);

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        results: [
          {
            vulns: [{
              id: "GHSA-OLD",
              summary: "old vuln",
              database_specific: { severity: "HIGH" },
              affected: [{ ranges: [{ type: "ECOSYSTEM", events: [{ fixed: "3.0.1" }] }] }],
              references: [],
            }],
          },
          {
            vulns: [],
          },
        ],
      }),
    });

    const repos = [mockRepo(["3.0.0", "3.1.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: true,
      productionOnly: false,
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(result.dependencies).toHaveLength(2);
    // 3.0.0 should have the vulnerability
    expect(result.dependencies[0].currentVersion).toBe("3.0.0");
    expect(result.dependencies[0].vulnerabilities).toHaveLength(1);
    expect(result.dependencies[0].vulnerabilities![0].id).toBe("GHSA-OLD");
    // 3.1.0 should have no vulnerabilities
    expect(result.dependencies[1].currentVersion).toBe("3.1.0");
    expect(result.dependencies[1].vulnerabilities).toHaveLength(0);
    expect(result.summary.vulnerable).toBe(1);
  });

  // ---- Phase 3: source + usages field tests ----

  it("source.kind catalog-library survives through AuditDependency", async () => {
    mockFileSystem({
      "/project/settings.gradle.kts": ``,
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-client = { module = "io.ktor:ktor-client-core", version = "3.0.0" }
`,
      "/project/build.gradle.kts": `
dependencies {
    implementation(libs.ktor.client)
}
`,
    });

    const repos = [mockRepo(["3.0.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    const dep = result.dependencies.find((d) => d.artifactId === "ktor-client-core");
    expect(dep).toBeDefined();
    expect(dep!.source.kind).toBe("catalog-library");
  });

  it("source.kind module-direct survives through AuditDependency", async () => {
    mockGradleProject(`implementation("io.ktor:ktor-client-core:3.0.0")`);

    const repos = [mockRepo(["3.0.0"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    expect(result.dependencies[0].source.kind).toBe("module-direct");
  });

  it("source.kind plugins-dsl survives through AuditDependency", async () => {
    mockFileSystem({
      "/project/build.gradle.kts": `
plugins {
    id("org.jetbrains.kotlin.jvm") version "2.0.0"
}
`,
    });

    const repos = [mockRepo(["2.0.0"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    const dep = result.dependencies.find((d) => d.source.kind === "plugins-dsl");
    expect(dep).toBeDefined();
    expect(dep!.source.kind).toBe("plugins-dsl");
  });

  it("source.kind buildscript-classpath survives through AuditDependency", async () => {
    mockFileSystem({
      "/project/build.gradle.kts": `
buildscript {
    dependencies {
        classpath("com.android.tools.build:gradle:8.1.0")
    }
}
`,
    });

    const repos = [mockRepo(["8.1.0"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    const dep = result.dependencies.find((d) => d.source.kind === "buildscript-classpath");
    expect(dep).toBeDefined();
  });

  it("source.kind catalog-plugin survives through AuditDependency", async () => {
    mockFileSystem({
      "/project/settings.gradle.kts": ``,
      "/project/gradle/libs.versions.toml": `
[plugins]
kotlin-jvm = { id = "org.jetbrains.kotlin.jvm", version = "2.0.0" }
`,
      "/project/build.gradle.kts": ``,
    });

    const repos = [mockRepo(["2.0.0"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    const dep = result.dependencies.find((d) => d.source.kind === "catalog-plugin");
    expect(dep).toBeDefined();
    expect(dep!.source.kind).toBe("catalog-plugin");
  });

  it("productionOnly excludes catalog library whose only usages are testImplementation", async () => {
    mockFileSystem({
      "/project/settings.gradle.kts": ``,
      "/project/gradle/libs.versions.toml": `
[libraries]
junit = { module = "junit:junit", version = "4.13" }
`,
      "/project/build.gradle.kts": `
dependencies {
    testImplementation(libs.junit)
}
`,
    });

    const repos = [mockRepo(["4.13"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    expect(result.dependencies.find((d) => d.artifactId === "junit")).toBeUndefined();
  });

  it("productionOnly includes catalog library used in both testImplementation and implementation", async () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":app")`,
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-client = { module = "io.ktor:ktor-client-core", version = "3.0.0" }
`,
      "/project/app/build.gradle.kts": `
dependencies {
    implementation(libs.ktor.client)
    testImplementation(libs.ktor.client)
}
`,
    });

    const repos = [mockRepo(["3.0.0"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
    });

    const dep = result.dependencies.find((d) => d.artifactId === "ktor-client-core");
    expect(dep).toBeDefined();
    // Both usages retained in output
    expect(dep!.usages).toHaveLength(2);
  });

  it("productionOnly includes unused catalog library (documented default policy)", async () => {
    mockFileSystem({
      "/project/settings.gradle.kts": ``,
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-client = { module = "io.ktor:ktor-client-core", version = "3.0.0" }
`,
      "/project/build.gradle.kts": `
dependencies {
}
`,
    });

    const repos = [mockRepo(["3.0.0", "3.1.1"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
      productionOnly: true,
    });

    // Unused catalog entry should still appear — it needs version audit
    const dep = result.dependencies.find((d) => d.artifactId === "ktor-client-core");
    expect(dep).toBeDefined();
    expect(dep!.usages).toHaveLength(0);
  });

  it("productionOnly includes unused catalog plugin", async () => {
    mockFileSystem({
      "/project/settings.gradle.kts": ``,
      "/project/gradle/libs.versions.toml": `
[plugins]
kotlin-jvm = { id = "org.jetbrains.kotlin.jvm", version = "2.0.0" }
`,
      "/project/build.gradle.kts": ``,
    });

    const repos = [mockRepo(["2.0.0"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
      productionOnly: true,
    });

    const dep = result.dependencies.find((d) => d.source.kind === "catalog-plugin");
    expect(dep).toBeDefined();
    expect(dep!.usages).toHaveLength(0);
  });

  it("productionOnly includes plugins-dsl entry (treated as production)", async () => {
    mockFileSystem({
      "/project/build.gradle.kts": `
plugins {
    id("org.jetbrains.kotlin.jvm") version "2.0.0"
}
`,
    });

    const repos = [mockRepo(["2.0.0"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
      productionOnly: true,
    });

    const dep = result.dependencies.find((d) => d.source.kind === "plugins-dsl");
    expect(dep).toBeDefined();
  });

  it("productionOnly includes buildscript-classpath entry", async () => {
    mockFileSystem({
      "/project/build.gradle.kts": `
buildscript {
    dependencies {
        classpath("com.android.tools.build:gradle:8.1.0")
    }
}
`,
    });

    const repos = [mockRepo(["8.1.0"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
      productionOnly: true,
    });

    expect(result.dependencies.find((d) => d.source.kind === "buildscript-classpath")).toBeDefined();
  });

  it("usages array surfaces every using module:configuration pair for a multi-used catalog entry", async () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":app", ":lib")`,
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-client = { module = "io.ktor:ktor-client-core", version = "3.0.0" }
`,
      "/project/app/build.gradle.kts": `
dependencies {
    implementation(libs.ktor.client)
}
`,
      "/project/lib/build.gradle.kts": `
dependencies {
    api(libs.ktor.client)
}
`,
    });

    const repos = [mockRepo(["3.0.0"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: false,
      productionOnly: false,
    });

    const dep = result.dependencies.find((d) => d.artifactId === "ktor-client-core");
    expect(dep).toBeDefined();
    expect(dep!.usages).toHaveLength(2);
    const usageMap = Object.fromEntries(dep!.usages.map((u) => [u.module, u.configuration]));
    expect(usageMap[":app"]).toBe("implementation");
    expect(usageMap[":lib"]).toBe("api");
  });

  it("vulnerability lookup for plugin marker artifactId works the same as regular deps", async () => {
    mockFileSystem({
      "/project/build.gradle.kts": `
plugins {
    id("org.jetbrains.kotlin.jvm") version "2.0.0"
}
`,
    });

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        results: [{
          vulns: [{
            id: "GHSA-PLUGIN-TEST",
            summary: "plugin vuln",
            database_specific: { severity: "HIGH" },
            affected: [],
            references: [],
          }],
        }],
      }),
    });

    const repos = [mockRepo(["2.0.0"])];
    const result = await auditProjectDependenciesHandler(repos, {
      projectPath: "/project",
      includeVulnerabilities: true,
    });

    // Plugin marker: groupId = pluginId, artifactId = pluginId + ".gradle.plugin"
    const dep = result.dependencies.find((d) => d.artifactId === "org.jetbrains.kotlin.jvm.gradle.plugin");
    expect(dep).toBeDefined();
    expect(dep!.vulnerabilities).toHaveLength(1);
    expect(dep!.vulnerabilities![0].id).toBe("GHSA-PLUGIN-TEST");
  });
});

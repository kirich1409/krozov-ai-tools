import { describe, it, expect, vi, beforeEach } from "vitest";
import { scanProjectDependenciesHandler } from "../scan-project-dependencies.js";
import * as fs from "node:fs";

vi.mock("node:fs");
const mockedFs = vi.mocked(fs);

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

beforeEach(() => vi.clearAllMocks());

describe("scanProjectDependenciesHandler", () => {
  it("scans project and returns flattened dependencies", () => {
    mockFileSystem({
      "/project/build.gradle.kts": `
dependencies {
    implementation("io.ktor:ktor-client-core:3.1.1")
}`,
    });

    const result = scanProjectDependenciesHandler({ projectPath: "/project" });
    expect(result.buildSystem).toBe("gradle");
    expect(result.dependencies).toHaveLength(1);
    expect(result.dependencies[0]).toMatchObject({
      groupId: "io.ktor",
      artifactId: "ktor-client-core",
      version: "3.1.1",
      configuration: "implementation",
      source: "build.gradle.kts",
      sourceKind: "module-direct",
    });
  });

  it("emits one item per usage for catalog entries used in multiple modules", () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":app", ":lib")`,
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }
`,
      "/project/app/build.gradle.kts": `implementation(libs.ktor.core)`,
      "/project/lib/build.gradle.kts": `api(libs.ktor.core)`,
    });

    const result = scanProjectDependenciesHandler({ projectPath: "/project" });
    const ktorDeps = result.dependencies.filter((d) => d.artifactId === "ktor-client-core");
    expect(ktorDeps).toHaveLength(2);
    expect(ktorDeps.map((d) => d.module).sort()).toEqual([":app", ":lib"].sort());
    expect(ktorDeps.map((d) => d.configuration).sort()).toEqual(["api", "implementation"].sort());
  });

  it("emits unused catalog entry with configuration (unused)", () => {
    mockFileSystem({
      "/project/gradle/libs.versions.toml": `
[libraries]
unused-lib = { module = "com.example:unused", version = "1.0.0" }
`,
    });

    const result = scanProjectDependenciesHandler({ projectPath: "/project" });
    const unusedDep = result.dependencies.find((d) => d.artifactId === "unused");
    expect(unusedDep).toBeDefined();
    expect(unusedDep!.configuration).toBe("(unused)");
    // source emits the TOML file path (backward-compat), not the kind string
    expect(unusedDep!.source).toBe("gradle/libs.versions.toml");
    expect(unusedDep!.sourceKind).toBe("catalog-library");
  });

  it("source field emits file path (backward-compat); sourceKind exposes the new discriminator", () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":app")`,
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }
[plugins]
kotlin-android = { id = "org.jetbrains.kotlin.android", version = "2.0.0" }
`,
      "/project/app/build.gradle.kts": `
dependencies {
    implementation(libs.ktor.core)
}`,
    });

    const result = scanProjectDependenciesHandler({ projectPath: "/project" });

    // Catalog library → TOML path in source, "catalog-library" in sourceKind
    const libDep = result.dependencies.find((d) => d.artifactId === "ktor-client-core");
    expect(libDep).toBeDefined();
    expect(libDep!.source).toBe("gradle/libs.versions.toml");
    expect(libDep!.sourceKind).toBe("catalog-library");

    // Unused catalog plugin → TOML path in source, "catalog-plugin" in sourceKind
    const pluginDep = result.dependencies.find((d) => d.artifactId === "org.jetbrains.kotlin.android.gradle.plugin");
    expect(pluginDep).toBeDefined();
    expect(pluginDep!.source).toBe("gradle/libs.versions.toml");
    expect(pluginDep!.sourceKind).toBe("catalog-plugin");
  });
});

import { describe, it, expect, vi } from "vitest";
import { scanProjectDependenciesHandler } from "../scan-project-dependencies.js";
import * as fs from "node:fs";

vi.mock("node:fs");
const mockedFs = vi.mocked(fs);

describe("scanProjectDependenciesHandler", () => {
  it("scans project and returns dependencies", () => {
    mockedFs.existsSync.mockImplementation((p: fs.PathLike) => {
      if (p.toString().endsWith("build.gradle.kts")) return true;
      return false;
    });
    mockedFs.readFileSync.mockReturnValue(`
dependencies {
    implementation("io.ktor:ktor-client-core:3.1.1")
}`);

    const result = scanProjectDependenciesHandler({ projectPath: "/project" });
    expect(result.buildSystem).toBe("gradle");
    expect(result.dependencies).toHaveLength(1);
  });
});

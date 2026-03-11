import { describe, it, expect, vi } from "vitest";
import { scanDependencies } from "../scan.js";
import * as fs from "node:fs";

vi.mock("node:fs");
const mockedFs = vi.mocked(fs);

describe("scanDependencies", () => {
  it("scans Gradle project with version catalog", () => {
    mockedFs.existsSync.mockImplementation((p: fs.PathLike) => {
      if (p.toString().endsWith("build.gradle.kts")) return true;
      if (p.toString().endsWith("libs.versions.toml")) return true;
      return false;
    });
    mockedFs.readFileSync.mockImplementation((p: fs.PathLike) => {
      if (p.toString().endsWith("build.gradle.kts")) {
        return `
dependencies {
    implementation(libs.ktor.core)
    implementation("com.google.code.gson:gson:2.11.0")
}`;
      }
      if (p.toString().endsWith("libs.versions.toml")) {
        return `
[versions]
ktor = "3.1.1"

[libraries]
ktor-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }
`;
      }
      return "";
    });

    const result = scanDependencies("/project");
    expect(result.buildSystem).toBe("gradle");
    expect(result.dependencies).toContainEqual(expect.objectContaining({
      groupId: "io.ktor", artifactId: "ktor-client-core", version: "3.1.1",
    }));
    expect(result.dependencies).toContainEqual(expect.objectContaining({
      groupId: "com.google.code.gson", artifactId: "gson", version: "2.11.0",
    }));
  });

  it("scans Maven project", () => {
    mockedFs.existsSync.mockImplementation((p: fs.PathLike) => {
      if (p.toString().endsWith("pom.xml")) return true;
      return false;
    });
    mockedFs.readFileSync.mockImplementation(() => `
<dependencies>
  <dependency>
    <groupId>io.ktor</groupId>
    <artifactId>ktor-core</artifactId>
    <version>3.1.1</version>
  </dependency>
</dependencies>`);

    const result = scanDependencies("/project");
    expect(result.buildSystem).toBe("maven");
    expect(result.dependencies).toHaveLength(1);
  });

  it("returns empty for unknown project", () => {
    mockedFs.existsSync.mockReturnValue(false);
    const result = scanDependencies("/empty");
    expect(result.buildSystem).toBe("unknown");
    expect(result.dependencies).toEqual([]);
  });
});

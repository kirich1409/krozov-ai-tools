import { describe, it, expect } from "vitest";
import { parseGradleDependencies } from "../gradle-deps-parser.js";

describe("parseGradleDependencies", () => {
  it("parses string notation with version", () => {
    const content = `
dependencies {
    implementation("io.ktor:ktor-client-core:3.1.1")
    testImplementation("org.junit:junit:5.10.0")
}`;
    const deps = parseGradleDependencies(content);
    expect(deps).toContainEqual({
      groupId: "io.ktor", artifactId: "ktor-client-core", version: "3.1.1",
      configuration: "implementation", source: "build.gradle.kts",
    });
    expect(deps).toContainEqual({
      groupId: "org.junit", artifactId: "junit", version: "5.10.0",
      configuration: "testImplementation", source: "build.gradle.kts",
    });
  });

  it("parses string notation without version (BOM)", () => {
    const content = `implementation("io.ktor:ktor-client-core")`;
    const deps = parseGradleDependencies(content);
    expect(deps[0].version).toBeNull();
  });

  it("parses Groovy single-quote notation", () => {
    const content = `implementation 'io.ktor:ktor-client-core:3.1.1'`;
    const deps = parseGradleDependencies(content, "build.gradle");
    expect(deps[0].groupId).toBe("io.ktor");
    expect(deps[0].version).toBe("3.1.1");
    expect(deps[0].source).toBe("build.gradle");
  });

  it("parses version catalog references", () => {
    const content = `implementation(libs.ktor.client.core)`;
    const deps = parseGradleDependencies(content);
    expect(deps[0]).toEqual({
      groupId: null, artifactId: null, version: null,
      configuration: "implementation", source: "build.gradle.kts",
      catalogRef: "ktor.client.core",
    });
  });

  it("extracts various configurations", () => {
    const content = `
api("com.example:api-lib:1.0")
compileOnly("com.example:compile-lib:1.0")
runtimeOnly("com.example:runtime-lib:1.0")
`;
    const deps = parseGradleDependencies(content);
    expect(deps.map(d => d.configuration)).toEqual(["api", "compileOnly", "runtimeOnly"]);
  });

  it("returns empty for no dependencies", () => {
    expect(parseGradleDependencies("plugins { }")).toEqual([]);
  });
});

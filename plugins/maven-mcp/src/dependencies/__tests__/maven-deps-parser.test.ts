import { describe, it, expect } from "vitest";
import { parseMavenDependencies } from "../maven-deps-parser.js";

describe("parseMavenDependencies", () => {
  it("parses dependencies with version and scope", () => {
    const pom = `
<dependencies>
  <dependency>
    <groupId>io.ktor</groupId>
    <artifactId>ktor-client-core</artifactId>
    <version>3.1.1</version>
  </dependency>
  <dependency>
    <groupId>junit</groupId>
    <artifactId>junit</artifactId>
    <version>4.13.2</version>
    <scope>test</scope>
  </dependency>
</dependencies>`;
    const deps = parseMavenDependencies(pom);
    expect(deps).toHaveLength(2);
    expect(deps[0]).toEqual({
      groupId: "io.ktor", artifactId: "ktor-client-core", version: "3.1.1",
      configuration: "implementation", source: "pom.xml",
    });
    expect(deps[1].configuration).toBe("testImplementation");
  });

  it("parses dependencies without version (BOM)", () => {
    const pom = `
<dependency>
  <groupId>io.ktor</groupId>
  <artifactId>ktor-client-core</artifactId>
</dependency>`;
    const deps = parseMavenDependencies(pom);
    expect(deps[0].version).toBeNull();
  });

  it("handles property references as null version", () => {
    const pom = `
<dependency>
  <groupId>io.ktor</groupId>
  <artifactId>ktor-core</artifactId>
  <version>\${ktor.version}</version>
</dependency>`;
    const deps = parseMavenDependencies(pom);
    expect(deps[0].version).toBeNull();
  });

  it("returns empty for no dependencies", () => {
    expect(parseMavenDependencies("<project></project>")).toEqual([]);
  });
});

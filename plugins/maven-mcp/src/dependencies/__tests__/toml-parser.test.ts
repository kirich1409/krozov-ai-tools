import { describe, it, expect } from "vitest";
import { parseVersionCatalog } from "../toml-parser.js";

describe("parseVersionCatalog", () => {
  it("parses libraries with version.ref", () => {
    const toml = `
[versions]
ktor = "3.1.1"
kotlin = "2.1.0"

[libraries]
ktor-client-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }
kotlin-stdlib = { module = "org.jetbrains.kotlin:kotlin-stdlib", version.ref = "kotlin" }
`;
    const result = parseVersionCatalog(toml);
    expect(result.get("ktor-client-core")).toEqual({
      groupId: "io.ktor", artifactId: "ktor-client-core", version: "3.1.1",
    });
    expect(result.get("kotlin-stdlib")).toEqual({
      groupId: "org.jetbrains.kotlin", artifactId: "kotlin-stdlib", version: "2.1.0",
    });
  });

  it("parses libraries with inline version", () => {
    const toml = `
[libraries]
gson = { module = "com.google.code.gson:gson", version = "2.11.0" }
`;
    const result = parseVersionCatalog(toml);
    expect(result.get("gson")).toEqual({
      groupId: "com.google.code.gson", artifactId: "gson", version: "2.11.0",
    });
  });

  it("parses libraries with group/name syntax", () => {
    const toml = `
[versions]
ktor = "3.1.1"

[libraries]
ktor-core = { group = "io.ktor", name = "ktor-client-core", version.ref = "ktor" }
`;
    const result = parseVersionCatalog(toml);
    expect(result.get("ktor-core")).toEqual({
      groupId: "io.ktor", artifactId: "ktor-client-core", version: "3.1.1",
    });
  });

  it("returns null version for libraries without version", () => {
    const toml = `
[libraries]
bom-lib = { module = "io.ktor:ktor-bom" }
`;
    const result = parseVersionCatalog(toml);
    expect(result.get("bom-lib")).toEqual({
      groupId: "io.ktor", artifactId: "ktor-bom", version: null,
    });
  });

  it("returns empty map for empty content", () => {
    expect(parseVersionCatalog("").size).toBe(0);
  });
});

import { describe, it, expect } from "vitest";
import { HttpMavenRepository, MAVEN_CENTRAL, GOOGLE_MAVEN } from "../repository.js";

describe("HttpMavenRepository", () => {
  it("builds correct metadata URL", () => {
    const repo = new HttpMavenRepository("test", "https://repo.example.com/maven2");
    const url = repo.buildMetadataUrl("io.ktor", "ktor-server-core");
    expect(url).toBe(
      "https://repo.example.com/maven2/io/ktor/ktor-server-core/maven-metadata.xml"
    );
  });

  it("builds metadata URL with trailing slash in base URL", () => {
    const repo = new HttpMavenRepository("test", "https://repo.example.com/maven2/");
    const url = repo.buildMetadataUrl("io.ktor", "ktor-server-core");
    expect(url).toBe(
      "https://repo.example.com/maven2/io/ktor/ktor-server-core/maven-metadata.xml"
    );
  });

  it("parses metadata XML correctly", () => {
    const repo = new HttpMavenRepository("test", "https://repo.example.com");
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<metadata>
  <groupId>io.ktor</groupId>
  <artifactId>ktor-server-core</artifactId>
  <versioning>
    <latest>3.1.1</latest>
    <release>3.1.1</release>
    <versions>
      <version>2.0.0</version>
      <version>3.0.0</version>
      <version>3.1.1</version>
    </versions>
    <lastUpdated>20250301</lastUpdated>
  </versioning>
</metadata>`;

    const result = repo.parseMetadataXml(xml, "io.ktor", "ktor-server-core");
    expect(result.groupId).toBe("io.ktor");
    expect(result.artifactId).toBe("ktor-server-core");
    expect(result.versions).toEqual(["2.0.0", "3.0.0", "3.1.1"]);
    expect(result.latest).toBe("3.1.1");
    expect(result.release).toBe("3.1.1");
  });

  it("exposes name and url properties", () => {
    const repo = new HttpMavenRepository("My Repo", "https://repo.example.com");
    expect(repo.name).toBe("My Repo");
    expect(repo.url).toBe("https://repo.example.com");
  });

  it("MAVEN_CENTRAL has correct values", () => {
    expect(MAVEN_CENTRAL.name).toBe("Maven Central");
    expect(MAVEN_CENTRAL.url).toBe("https://repo1.maven.org/maven2");
  });

  it("GOOGLE_MAVEN has correct values", () => {
    expect(GOOGLE_MAVEN.name).toBe("Google");
    expect(GOOGLE_MAVEN.url).toBe("https://maven.google.com");
  });
});

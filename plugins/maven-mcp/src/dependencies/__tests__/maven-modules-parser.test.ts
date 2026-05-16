import { describe, it, expect } from "vitest";
import { parseMavenModules } from "../maven-modules-parser.js";

describe("parseMavenModules", () => {
  it("extracts <module> entries from <modules>", () => {
    const content = `
<project>
  <modules>
    <module>core</module>
    <module>app</module>
  </modules>
</project>
`;
    expect(parseMavenModules(content)).toEqual(["core", "app"]);
  });

  it("returns empty array when no <modules> section", () => {
    const content = `<project><artifactId>solo</artifactId></project>`;
    expect(parseMavenModules(content)).toEqual([]);
  });

  it("handles multiple <modules> blocks (e.g. profiles)", () => {
    const content = `
<project>
  <modules>
    <module>core</module>
  </modules>
  <profiles>
    <profile>
      <modules>
        <module>integration-tests</module>
      </modules>
    </profile>
  </profiles>
</project>
`;
    expect(parseMavenModules(content)).toEqual(["core", "integration-tests"]);
  });
});

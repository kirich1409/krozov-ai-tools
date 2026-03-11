import { describe, it, expect } from "vitest";
import { parseMavenRepositories } from "../maven-parser.js";

describe("parseMavenRepositories", () => {
  it("parses repositories from pom.xml", () => {
    const content = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <repositories>
    <repository>
      <id>spring-milestones</id>
      <url>https://repo.spring.io/milestone</url>
    </repository>
    <repository>
      <id>jitpack</id>
      <url>https://jitpack.io</url>
    </repository>
  </repositories>
</project>`;

    const repos = parseMavenRepositories(content);
    expect(repos).toEqual([
      { name: "spring-milestones", url: "https://repo.spring.io/milestone" },
      { name: "jitpack", url: "https://jitpack.io" },
    ]);
  });

  it("returns empty array when no repositories block", () => {
    const content = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <groupId>com.example</groupId>
</project>`;

    const repos = parseMavenRepositories(content);
    expect(repos).toEqual([]);
  });

  it("handles repository without id", () => {
    const content = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <repositories>
    <repository>
      <url>https://repo.spring.io/milestone</url>
    </repository>
  </repositories>
</project>`;

    const repos = parseMavenRepositories(content);
    expect(repos).toEqual([
      { name: "https://repo.spring.io/milestone", url: "https://repo.spring.io/milestone" },
    ]);
  });

  it("returns all entries including duplicates (dedup is caller's responsibility)", () => {
    const content = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <repositories>
    <repository>
      <id>a</id>
      <url>https://jitpack.io</url>
    </repository>
    <repository>
      <id>b</id>
      <url>https://jitpack.io</url>
    </repository>
  </repositories>
</project>`;

    const repos = parseMavenRepositories(content);
    expect(repos).toHaveLength(2);
  });
});

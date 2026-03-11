import { describe, it, expect, vi } from "vitest";
import { compareDependencyVersionsHandler } from "../compare-dependency-versions.js";
import type { MavenRepository } from "../../maven/repository.js";

describe("compareDependencyVersionsHandler", () => {
  it("compares current versions against latest", async () => {
    const repo: MavenRepository = {
      name: "central",
      url: "https://repo1.maven.org/maven2",
      fetchMetadata: vi.fn()
        .mockResolvedValueOnce({
          groupId: "io.ktor",
          artifactId: "ktor-server-core",
          versions: ["2.0.0", "3.0.0", "3.1.0"],
        })
        .mockResolvedValueOnce({
          groupId: "org.slf4j",
          artifactId: "slf4j-api",
          versions: ["2.0.0", "2.0.1"],
        }),
    };

    const result = await compareDependencyVersionsHandler([repo], {
      dependencies: [
        { groupId: "io.ktor", artifactId: "ktor-server-core", currentVersion: "2.0.0" },
        { groupId: "org.slf4j", artifactId: "slf4j-api", currentVersion: "2.0.0" },
      ],
    });

    expect(result.results).toHaveLength(2);
    expect(result.results[0].upgradeType).toBe("major");
    expect(result.results[0].latestVersion).toBe("3.1.0");
    expect(result.results[1].upgradeType).toBe("patch");
  });
});

import { describe, it, expect, vi } from "vitest";
import { checkMultipleDependenciesHandler } from "../check-multiple-dependencies.js";
import type { MavenRepository } from "../../maven/repository.js";

describe("checkMultipleDependenciesHandler", () => {
  it("returns latest versions for multiple dependencies", async () => {
    const repo: MavenRepository = {
      name: "central",
      url: "https://repo1.maven.org/maven2",
      fetchMetadata: vi.fn()
        .mockResolvedValueOnce({
          groupId: "io.ktor",
          artifactId: "ktor-server-core",
          versions: ["2.0.0", "3.0.0"],
        })
        .mockResolvedValueOnce({
          groupId: "org.jetbrains.kotlin",
          artifactId: "kotlin-stdlib",
          versions: ["1.9.0", "2.0.0"],
        }),
    };

    const result = await checkMultipleDependenciesHandler([repo], {
      dependencies: [
        { groupId: "io.ktor", artifactId: "ktor-server-core" },
        { groupId: "org.jetbrains.kotlin", artifactId: "kotlin-stdlib" },
      ],
    });

    expect(result.results).toHaveLength(2);
    expect(result.results[0].latestVersion).toBe("3.0.0");
    expect(result.results[1].latestVersion).toBe("2.0.0");
  });
});

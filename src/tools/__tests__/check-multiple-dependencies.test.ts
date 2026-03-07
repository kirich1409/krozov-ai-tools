import { describe, it, expect, vi } from "vitest";
import { checkMultipleDependenciesHandler } from "../check-multiple-dependencies.js";
import type { MavenCentralClient } from "../../maven/client.js";

describe("checkMultipleDependenciesHandler", () => {
  it("returns latest versions for multiple dependencies", async () => {
    const client = {
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
    } as unknown as MavenCentralClient;

    const result = await checkMultipleDependenciesHandler(client, {
      dependencies: [
        { groupId: "io.ktor", artifactId: "ktor-server-core" },
        { groupId: "org.jetbrains.kotlin", artifactId: "kotlin-stdlib" },
      ],
    });

    expect(result.results).toHaveLength(2);
    expect(result.results[0].latestVersion).toBe("3.0.0");
    expect(result.results[1].latestVersion).toBe("2.0.0");
  });

  it("handles errors gracefully for individual dependencies", async () => {
    const client = {
      fetchMetadata: vi.fn()
        .mockResolvedValueOnce({
          groupId: "io.ktor",
          artifactId: "ktor-server-core",
          versions: ["3.0.0"],
        })
        .mockRejectedValueOnce(new Error("Not found")),
    } as unknown as MavenCentralClient;

    const result = await checkMultipleDependenciesHandler(client, {
      dependencies: [
        { groupId: "io.ktor", artifactId: "ktor-server-core" },
        { groupId: "com.example", artifactId: "nonexistent" },
      ],
    });

    expect(result.results).toHaveLength(2);
    expect(result.results[0].latestVersion).toBe("3.0.0");
    expect(result.results[1].error).toBe("Not found");
  });
});

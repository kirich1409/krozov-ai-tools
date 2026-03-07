import { describe, it, expect, vi } from "vitest";
import { checkVersionExistsHandler } from "../check-version-exists.js";
import type { MavenRepository } from "../../maven/repository.js";

function mockRepo(name: string, versions: string[] | null): MavenRepository {
  return {
    name,
    url: `https://${name}.example.com`,
    fetchMetadata: versions === null
      ? vi.fn().mockRejectedValue(new Error("Not found"))
      : vi.fn().mockResolvedValue({
          groupId: "io.ktor",
          artifactId: "ktor-server-core",
          versions,
        }),
  };
}

describe("checkVersionExistsHandler", () => {
  it("returns true and stability for existing version", async () => {
    const repos = [mockRepo("central", ["1.0.0", "2.0.0-beta1"])];
    const result = await checkVersionExistsHandler(repos, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      version: "1.0.0",
    });
    expect(result.exists).toBe(true);
    expect(result.stability).toBe("stable");
    expect(result.repository).toBe("central");
  });

  it("returns false for non-existing version", async () => {
    const repos = [mockRepo("central", ["1.0.0"])];
    const result = await checkVersionExistsHandler(repos, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      version: "9.9.9",
    });
    expect(result.exists).toBe(false);
  });

  it("finds version in second repo when first repo fails", async () => {
    const repos = [
      mockRepo("google", null),
      mockRepo("central", ["1.0.0"]),
    ];
    const result = await checkVersionExistsHandler(repos, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      version: "1.0.0",
    });
    expect(result.exists).toBe(true);
    expect(result.repository).toBe("central");
  });

  it("finds version in second repo when first repo has artifact but not the version", async () => {
    const repos = [
      mockRepo("google", ["1.0.0", "2.0.0"]),
      mockRepo("central", ["1.0.0", "3.0.0"]),
    ];
    const result = await checkVersionExistsHandler(repos, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      version: "3.0.0",
    });
    expect(result.exists).toBe(true);
    expect(result.repository).toBe("central");
  });

  it("returns false when version not in any repo", async () => {
    const repos = [
      mockRepo("google", ["1.0.0"]),
      mockRepo("central", ["2.0.0"]),
    ];
    const result = await checkVersionExistsHandler(repos, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      version: "9.9.9",
    });
    expect(result.exists).toBe(false);
  });
});

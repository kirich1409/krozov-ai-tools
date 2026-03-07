import { describe, it, expect, vi } from "vitest";
import { resolveFirst, resolveAll } from "../resolver.js";
import type { MavenRepository } from "../repository.js";
import { MAVEN_CENTRAL, GOOGLE_MAVEN } from "../repository.js";
import type { MavenMetadata } from "../types.js";

function mockRepo(name: string, versions: string[] | null, url?: string): MavenRepository {
  return {
    name,
    url: url ?? `https://${name}.example.com`,
    fetchMetadata: versions === null
      ? vi.fn().mockRejectedValue(new Error("Not found"))
      : vi.fn().mockResolvedValue({
          groupId: "io.ktor",
          artifactId: "ktor-core",
          versions,
        } as MavenMetadata),
  };
}

describe("resolveFirst", () => {
  it("returns metadata from first repo that has the artifact", async () => {
    const repos = [mockRepo("empty", null), mockRepo("has-it", ["1.0.0", "2.0.0"])];
    const result = await resolveFirst(repos, "io.ktor", "ktor-core");
    expect(result).not.toBeNull();
    expect(result!.metadata.versions).toEqual(["1.0.0", "2.0.0"]);
    expect(result!.repository.name).toBe("has-it");
  });

  it("returns null when no repo has the artifact", async () => {
    const repos = [mockRepo("a", null), mockRepo("b", null)];
    const result = await resolveFirst(repos, "io.ktor", "ktor-core");
    expect(result).toBeNull();
  });

  it("stops at first successful repo", async () => {
    const repo1 = mockRepo("first", ["1.0.0"]);
    const repo2 = mockRepo("second", ["2.0.0"]);
    await resolveFirst([repo1, repo2], "io.ktor", "ktor-core");
    expect(repo1.fetchMetadata).toHaveBeenCalled();
    expect(repo2.fetchMetadata).not.toHaveBeenCalled();
  });
});

describe("resolveAll", () => {
  it("merges versions from all repos and deduplicates", async () => {
    const repos = [
      mockRepo("repo1", ["1.0.0", "2.0.0"]),
      mockRepo("repo2", ["2.0.0", "3.0.0"]),
    ];
    const result = await resolveAll(repos, "io.ktor", "ktor-core");
    expect(result.versions).toEqual(["1.0.0", "2.0.0", "3.0.0"]);
  });

  it("skips failed repos and returns versions from successful ones", async () => {
    const repos = [
      mockRepo("fails", null),
      mockRepo("works", ["1.0.0"]),
    ];
    const result = await resolveAll(repos, "io.ktor", "ktor-core");
    expect(result.versions).toEqual(["1.0.0"]);
  });

  it("throws when all repos fail", async () => {
    const repos = [mockRepo("a", null), mockRepo("b", null)];
    await expect(resolveAll(repos, "io.ktor", "ktor-core")).rejects.toThrow();
  });

  it("returns empty result for empty repos list", async () => {
    await expect(resolveAll([], "io.ktor", "ktor-core")).rejects.toThrow();
  });

  it("picks latest/release from the last version in merged list", async () => {
    const repo1: MavenRepository = {
      name: "repo1",
      url: "https://repo1.example.com",
      fetchMetadata: vi.fn().mockResolvedValue({
        groupId: "io.ktor",
        artifactId: "ktor-core",
        versions: ["1.0.0", "2.0.0"],
        latest: "2.0.0",
        release: "2.0.0",
      } as MavenMetadata),
    };
    const repo2: MavenRepository = {
      name: "repo2",
      url: "https://repo2.example.com",
      fetchMetadata: vi.fn().mockResolvedValue({
        groupId: "io.ktor",
        artifactId: "ktor-core",
        versions: ["2.0.0", "3.0.0"],
        latest: "3.0.0",
        release: "3.0.0",
      } as MavenMetadata),
    };

    const result = await resolveAll([repo1, repo2], "io.ktor", "ktor-core");
    expect(result.versions).toEqual(["1.0.0", "2.0.0", "3.0.0"]);
    expect(result.latest).toBe("3.0.0");
    expect(result.release).toBe("3.0.0");
  });

  it("prefers custom repo results over well-known when both have the artifact", async () => {
    const nexus = mockRepo("nexus", ["1.0.0", "2.0.0"]);
    const central = mockRepo("central", ["1.0.0", "2.0.0", "3.0.0"], MAVEN_CENTRAL.url);
    const result = await resolveAll([nexus, central], "io.ktor", "ktor-core");
    // Nexus result preferred — 3.0.0 from Central is excluded
    expect(result.versions).toEqual(["1.0.0", "2.0.0"]);
  });

  it("falls back to well-known repos when custom repos dont have the artifact", async () => {
    const nexus = mockRepo("nexus", null);
    const central = mockRepo("central", ["1.0.0", "2.0.0"], MAVEN_CENTRAL.url);
    const result = await resolveAll([nexus, central], "io.ktor", "ktor-core");
    expect(result.versions).toEqual(["1.0.0", "2.0.0"]);
  });

  it("merges all well-known repos when no custom repos are present", async () => {
    const central = mockRepo("central", ["1.0.0"], MAVEN_CENTRAL.url);
    const google = mockRepo("google", ["1.0.0", "2.0.0"], GOOGLE_MAVEN.url);
    const result = await resolveAll([central, google], "io.ktor", "ktor-core");
    expect(result.versions).toEqual(["1.0.0", "2.0.0"]);
  });
});

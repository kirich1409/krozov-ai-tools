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

  it("uses only custom repo results even when some custom repos fail", async () => {
    const internal = mockRepo("internal", ["1.0.0"]);
    const nexusFail = mockRepo("nexus", null);
    const central = mockRepo("central", ["1.0.0", "2.0.0", "3.0.0"], MAVEN_CENTRAL.url);
    const result = await resolveAll([internal, nexusFail, central], "io.ktor", "ktor-core");
    // internal succeeded (custom) — Central results excluded despite nexus failing
    expect(result.versions).toEqual(["1.0.0"]);
  });

  it("merges all well-known repos when no custom repos are present", async () => {
    const central = mockRepo("central", ["1.0.0"], MAVEN_CENTRAL.url);
    const google = mockRepo("google", ["1.0.0", "2.0.0"], GOOGLE_MAVEN.url);
    const result = await resolveAll([central, google], "io.ktor", "ktor-core");
    expect(result.versions).toEqual(["1.0.0", "2.0.0"]);
  });

  it("keeps Google Maven results when custom repo is present", async () => {
    const nexus = mockRepo("nexus", ["1.0.0"]);
    const google = mockRepo("google", ["1.0.0", "2.0.0"], GOOGLE_MAVEN.url);
    const central = mockRepo("central", ["1.0.0", "3.0.0"], MAVEN_CENTRAL.url);
    const result = await resolveAll([nexus, google, central], "io.ktor", "ktor-core");
    // Nexus + Google kept, Maven Central excluded (proxy target)
    expect(result.versions).toEqual(["1.0.0", "2.0.0"]);
  });

  it("sorts merged versions by semver, not by repo order", async () => {
    // Repo A returns [3.0.0, 1.0.0] (non-chronological), Repo B returns [2.0.0].
    // Central is excluded because A is custom, so merged is just [3.0.0, 1.0.0, 2.0.0].
    // After semver sort: [1.0.0, 2.0.0, 3.0.0].
    const repoA = mockRepo("custom-a", ["3.0.0", "1.0.0"]);
    const repoB = mockRepo("custom-b", ["2.0.0"]);
    const result = await resolveAll([repoA, repoB], "io.ktor", "ktor-core");
    expect(result.versions).toEqual(["1.0.0", "2.0.0", "3.0.0"]);
  });

  it("picks semver-max latest from advertised values across repos", async () => {
    // Repo A advertises latest=1.5.0, Repo B advertises latest=2.0.0.
    // Even if A is listed first, the max by semver wins.
    const repoA: MavenRepository = {
      name: "repo-a",
      url: "https://a.example.com",
      fetchMetadata: vi.fn().mockResolvedValue({
        groupId: "io.ktor", artifactId: "ktor-core",
        versions: ["1.0.0", "1.5.0"], latest: "1.5.0", release: "1.5.0",
      } as MavenMetadata),
    };
    const repoB: MavenRepository = {
      name: "repo-b",
      url: "https://b.example.com",
      fetchMetadata: vi.fn().mockResolvedValue({
        groupId: "io.ktor", artifactId: "ktor-core",
        versions: ["1.5.0", "2.0.0"], latest: "2.0.0", release: "2.0.0",
      } as MavenMetadata),
    };
    const result = await resolveAll([repoA, repoB], "io.ktor", "ktor-core");
    expect(result.latest).toBe("2.0.0");
    expect(result.release).toBe("2.0.0");
  });

  it("does not return a stale advertised latest from a lagging proxy", async () => {
    // Custom repo advertises latest=1.5.0 with only older versions.
    // Maven Central is excluded (custom repo present), so latest must be 1.5.0 —
    // this exact regression would have been masked by the old positional picker.
    const proxy: MavenRepository = {
      name: "proxy",
      url: "https://proxy.example.com",
      fetchMetadata: vi.fn().mockResolvedValue({
        groupId: "io.ktor", artifactId: "ktor-core",
        versions: ["1.0.0", "1.5.0"], latest: "1.5.0", release: "1.5.0",
      } as MavenMetadata),
    };
    const result = await resolveAll([proxy], "io.ktor", "ktor-core");
    expect(result.latest).toBe("1.5.0");
    expect(result.release).toBe("1.5.0");
  });

  it("orders pre-releases before corresponding stable", async () => {
    const repo = mockRepo("r", ["2.0.0", "2.0.0-beta-1", "2.0.0-rc-1", "1.9.0"]);
    const result = await resolveAll([repo], "io.ktor", "ktor-core");
    expect(result.versions).toEqual([
      "1.9.0", "2.0.0-beta-1", "2.0.0-rc-1", "2.0.0",
    ]);
    // release should be stable (2.0.0), not the last array entry by position.
    expect(result.release).toBe("2.0.0");
  });

  it("picks semver-max lastUpdated across repos", async () => {
    const repoA: MavenRepository = {
      name: "repo-a",
      url: "https://a.example.com",
      fetchMetadata: vi.fn().mockResolvedValue({
        groupId: "io.ktor", artifactId: "ktor-core",
        versions: ["1.0.0"], lastUpdated: "20240101000000",
      } as MavenMetadata),
    };
    const repoB: MavenRepository = {
      name: "repo-b",
      url: "https://b.example.com",
      fetchMetadata: vi.fn().mockResolvedValue({
        groupId: "io.ktor", artifactId: "ktor-core",
        versions: ["2.0.0"], lastUpdated: "20260301000000",
      } as MavenMetadata),
    };
    const result = await resolveAll([repoA, repoB], "io.ktor", "ktor-core");
    expect(result.lastUpdated).toBe("20260301000000");
  });
});

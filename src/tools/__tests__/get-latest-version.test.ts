import { describe, it, expect, vi } from "vitest";
import { getLatestVersionHandler } from "../get-latest-version.js";
import type { MavenCentralClient } from "../../maven/client.js";

function mockClient(versions: string[]): MavenCentralClient {
  return {
    fetchMetadata: vi.fn().mockResolvedValue({
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      versions,
      latest: versions[versions.length - 1],
      release: versions[versions.length - 1],
    }),
  } as unknown as MavenCentralClient;
}

describe("getLatestVersionHandler", () => {
  it("returns latest stable version with STABLE_ONLY filter", async () => {
    const client = mockClient(["1.0.0", "2.0.0-beta1", "2.0.0-RC1", "1.5.0"]);
    const result = await getLatestVersionHandler(client, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      stabilityFilter: "STABLE_ONLY",
    });
    expect(result.latestVersion).toBe("1.5.0");
    expect(result.stability).toBe("stable");
  });

  it("returns latest version with ALL filter", async () => {
    const client = mockClient(["1.0.0", "2.0.0-beta1", "2.0.0-RC1"]);
    const result = await getLatestVersionHandler(client, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      stabilityFilter: "ALL",
    });
    expect(result.latestVersion).toBe("2.0.0-RC1");
  });

  it("prefers stable with PREFER_STABLE filter", async () => {
    const client = mockClient(["1.0.0", "2.0.0-beta1"]);
    const result = await getLatestVersionHandler(client, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      stabilityFilter: "PREFER_STABLE",
    });
    expect(result.latestVersion).toBe("1.0.0");
    expect(result.stability).toBe("stable");
  });

  it("falls back to unstable with PREFER_STABLE when no stable exists", async () => {
    const client = mockClient(["1.0.0-alpha1", "2.0.0-beta1"]);
    const result = await getLatestVersionHandler(client, {
      groupId: "io.ktor",
      artifactId: "ktor-server-core",
      stabilityFilter: "PREFER_STABLE",
    });
    expect(result.latestVersion).toBe("2.0.0-beta1");
  });
});

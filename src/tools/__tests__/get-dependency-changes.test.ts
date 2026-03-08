import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getDependencyChangesHandler } from "../get-dependency-changes.js";
import type { MavenRepository } from "../../maven/repository.js";

// Mock node:fs/promises to prevent FileCache from writing to disk
vi.mock("node:fs/promises", () => ({
  readFile: vi.fn().mockRejectedValue(new Error("ENOENT")),
  writeFile: vi.fn().mockResolvedValue(undefined),
  mkdir: vi.fn().mockResolvedValue(undefined),
}));

function mockRepo(versions: string[]): MavenRepository {
  return {
    name: "central",
    url: "https://repo1.maven.org/maven2",
    fetchMetadata: vi.fn().mockResolvedValue({
      groupId: "io.ktor",
      artifactId: "ktor-core",
      versions,
      latest: versions[versions.length - 1],
      release: versions[versions.length - 1],
    }),
  };
}

const POM_WITH_SCM = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <groupId>io.ktor</groupId>
  <artifactId>ktor-core</artifactId>
  <version>2.3.0</version>
  <scm>
    <url>https://github.com/ktorio/ktor</url>
  </scm>
</project>`;

const POM_WITHOUT_SCM = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <groupId>com.example</groupId>
  <artifactId>no-scm</artifactId>
  <version>1.0.0</version>
</project>`;

describe("getDependencyChangesHandler", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns changes from GitHub releases", async () => {
    const repo = mockRepo(["2.1.0", "2.2.0", "2.3.0"]);

    const releases = [
      { tag_name: "2.2.0", body: "Bug fixes for 2.2.0", html_url: "https://github.com/ktorio/ktor/releases/tag/2.2.0" },
      { tag_name: "2.3.0", body: "New features in 2.3.0", html_url: "https://github.com/ktorio/ktor/releases/tag/2.3.0" },
    ];

    globalThis.fetch = vi.fn()
      // First call: POM fetch (from discoverGitHubRepo)
      .mockResolvedValueOnce(new Response(POM_WITH_SCM, { status: 200 }))
      // Second call: GitHub releases
      .mockResolvedValueOnce(new Response(JSON.stringify(releases), { status: 200 })) as typeof fetch;

    const result = await getDependencyChangesHandler([repo], {
      groupId: "io.ktor",
      artifactId: "ktor-core",
      fromVersion: "2.1.0",
      toVersion: "2.3.0",
    });

    expect(result.groupId).toBe("io.ktor");
    expect(result.artifactId).toBe("ktor-core");
    expect(result.fromVersion).toBe("2.1.0");
    expect(result.toVersion).toBe("2.3.0");
    expect(result.repositoryUrl).toBe("https://github.com/ktorio/ktor");
    expect(result.repositoryNotFound).toBeUndefined();
    expect(result.changes).toHaveLength(2);
    expect(result.changes[0]).toEqual({
      version: "2.2.0",
      releaseUrl: "https://github.com/ktorio/ktor/releases/tag/2.2.0",
      body: "Bug fixes for 2.2.0",
    });
    expect(result.changes[1]).toEqual({
      version: "2.3.0",
      releaseUrl: "https://github.com/ktorio/ktor/releases/tag/2.3.0",
      body: "New features in 2.3.0",
    });
  });

  it("returns repositoryNotFound when no GitHub repo found", async () => {
    const repo = mockRepo(["1.0.0", "1.1.0", "1.2.0"]);

    globalThis.fetch = vi.fn()
      // POM fetch returns no SCM info
      .mockResolvedValueOnce(new Response(POM_WITHOUT_SCM, { status: 200 }))
      // repoExists check for guessed repo fails
      .mockResolvedValueOnce(new Response("", { status: 404 })) as typeof fetch;

    const result = await getDependencyChangesHandler([repo], {
      groupId: "com.example",
      artifactId: "no-scm",
      fromVersion: "1.0.0",
      toVersion: "1.2.0",
    });

    expect(result.repositoryNotFound).toBe(true);
    expect(result.changes).toEqual([]);
  });

  it("falls back to changelog when releases don't match versions", async () => {
    const repo = mockRepo(["2.1.0", "2.2.0", "2.3.0"]);

    const changelogContent = Buffer.from(
      "# Changelog\n\n## [2.3.0] - 2024-03-01\n\nNew stuff\n\n## [2.2.0] - 2024-02-01\n\nOlder stuff\n",
    ).toString("base64");

    globalThis.fetch = vi.fn()
      // POM fetch
      .mockResolvedValueOnce(new Response(POM_WITH_SCM, { status: 200 }))
      // Releases fetch — empty array, no matches
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      // Changelog fetch (CHANGELOG.md)
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ content: changelogContent }), { status: 200 }),
      ) as typeof fetch;

    const result = await getDependencyChangesHandler([repo], {
      groupId: "io.ktor",
      artifactId: "ktor-core",
      fromVersion: "2.1.0",
      toVersion: "2.3.0",
    });

    expect(result.repositoryNotFound).toBeUndefined();
    expect(result.changes).toHaveLength(2);
    expect(result.changes[0].version).toBe("2.2.0");
    expect(result.changes[0].body).toBe("Older stuff");
    expect(result.changes[1].version).toBe("2.3.0");
    expect(result.changes[1].body).toBe("New stuff");
    expect(result.changelogUrl).toContain("CHANGELOG.md");
  });

  it("returns error when no versions found between from and to", async () => {
    const repo = mockRepo(["1.0.0", "3.0.0"]);

    const result = await getDependencyChangesHandler([repo], {
      groupId: "io.ktor",
      artifactId: "ktor-core",
      fromVersion: "2.0.0",
      toVersion: "2.5.0",
    });

    expect(result.error).toContain("No versions found between");
    expect(result.changes).toEqual([]);
  });
});

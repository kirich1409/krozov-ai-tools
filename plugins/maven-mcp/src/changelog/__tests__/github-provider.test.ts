import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { GitHubChangelogProvider } from "../github-provider.js";
import type { MavenRepository } from "../../maven/repository.js";

vi.mock("node:fs/promises", () => ({
  readFile: vi.fn().mockRejectedValue(new Error("ENOENT")),
  writeFile: vi.fn().mockResolvedValue(undefined),
  mkdir: vi.fn().mockResolvedValue(undefined),
  rename: vi.fn().mockResolvedValue(undefined),
}));

const POM_WITH_SCM = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <scm><url>https://github.com/ktorio/ktor</url></scm>
</project>`;

const POM_WITHOUT_SCM = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <groupId>com.example</groupId>
</project>`;

function mockRepo(): MavenRepository {
  return {
    name: "central",
    url: "https://repo1.maven.org/maven2",
    fetchMetadata: vi.fn(),
  };
}

describe("GitHubChangelogProvider", () => {
  let provider: GitHubChangelogProvider;
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    provider = new GitHubChangelogProvider();
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  describe("canHandle", () => {
    it("returns true for any artifact (universal fallback)", () => {
      expect(provider.canHandle("io.ktor", "ktor-core")).toBe(true);
      expect(provider.canHandle("com.example", "lib")).toBe(true);
    });
  });

  describe("fetchChangelog", () => {
    it("returns entries from GitHub releases", async () => {
      const releases = [
        { tag_name: "2.0.0", body: "New features", html_url: "https://github.com/ktorio/ktor/releases/tag/2.0.0" },
      ];

      globalThis.fetch = vi.fn()
        .mockResolvedValueOnce(new Response(POM_WITH_SCM, { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(releases), { status: 200 }))
        .mockResolvedValueOnce(new Response("", { status: 404 })) as typeof fetch;

      const result = await provider.fetchChangelog("io.ktor", "ktor-core", "2.0.0", [mockRepo()]);

      expect(result).not.toBeNull();
      expect(result!.repositoryUrl).toBe("https://github.com/ktorio/ktor");
      expect(result!.entries.has("2.0.0")).toBe(true);
      expect(result!.entries.get("2.0.0")!.body).toContain("New features");
      expect(result!.entries.get("2.0.0")!.releaseUrl).toBe("https://github.com/ktorio/ktor/releases/tag/2.0.0");
    });

    it("returns null when no GitHub repo discovered", async () => {
      globalThis.fetch = vi.fn()
        .mockResolvedValueOnce(new Response(POM_WITHOUT_SCM, { status: 200 }))
        .mockResolvedValueOnce(new Response("", { status: 404 })) as typeof fetch;

      const result = await provider.fetchChangelog("com.example", "lib", "1.0.0", [mockRepo()]);
      expect(result).toBeNull();
    });

    it("falls back to CHANGELOG.md when no releases match", async () => {
      const changelogContent = Buffer.from(
        "## [1.0.0] - 2024-01-01\n\nInitial release\n",
      ).toString("base64");

      globalThis.fetch = vi.fn()
        .mockResolvedValueOnce(new Response(POM_WITH_SCM, { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify({ content: changelogContent }), { status: 200 })) as typeof fetch;

      const result = await provider.fetchChangelog("io.ktor", "ktor-core", "1.0.0", [mockRepo()]);

      expect(result).not.toBeNull();
      expect(result!.entries.has("1.0.0")).toBe(true);
      expect(result!.entries.get("1.0.0")!.body).toContain("Initial release");
      expect(result!.changelogUrl).toContain("CHANGELOG.md");
    });
  });
});

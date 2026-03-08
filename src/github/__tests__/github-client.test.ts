import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { GitHubClient } from "../github-client.js";

describe("GitHubClient", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.fetch = originalFetch;
  });

  function mockFetch(handler: (url: string, init?: RequestInit) => Promise<Response>) {
    vi.stubGlobal("fetch", vi.fn(handler));
  }

  describe("fetchReleases", () => {
    it("returns releases on success", async () => {
      const releases = [
        { tag_name: "v1.0.0", body: "First release", html_url: "https://github.com/owner/repo/releases/tag/v1.0.0" },
        { tag_name: "v2.0.0", body: "Second release", html_url: "https://github.com/owner/repo/releases/tag/v2.0.0" },
      ];
      mockFetch(async () => new Response(JSON.stringify(releases), { status: 200 }));

      const client = new GitHubClient();
      const result = await client.fetchReleases("owner", "repo");

      expect(result).toEqual(releases);
      expect(fetch).toHaveBeenCalledOnce();
      const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(url).toBe("https://api.github.com/repos/owner/repo/releases?per_page=100");
      expect(init.headers["Accept"]).toBe("application/vnd.github.v3+json");
      expect(init.headers["User-Agent"]).toBe("maven-central-mcp");
    });

    it("returns empty array on non-ok response", async () => {
      mockFetch(async () => new Response("Not Found", { status: 404 }));

      const client = new GitHubClient();
      const result = await client.fetchReleases("owner", "repo");

      expect(result).toEqual([]);
    });

    it("returns empty array on fetch error", async () => {
      mockFetch(async () => { throw new Error("Network error"); });

      const client = new GitHubClient();
      const result = await client.fetchReleases("owner", "repo");

      expect(result).toEqual([]);
    });

    it("sends Authorization header when token is provided", async () => {
      mockFetch(async () => new Response(JSON.stringify([]), { status: 200 }));

      const client = new GitHubClient("my-token");
      await client.fetchReleases("owner", "repo");

      const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(init.headers["Authorization"]).toBe("Bearer my-token");
    });

    it("does not send Authorization header when no token", async () => {
      mockFetch(async () => new Response(JSON.stringify([]), { status: 200 }));

      const client = new GitHubClient();
      await client.fetchReleases("owner", "repo");

      const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(init.headers["Authorization"]).toBeUndefined();
    });

    it("uses 15s timeout via AbortSignal", async () => {
      mockFetch(async (_url: string, init?: RequestInit) => {
        expect(init?.signal).toBeDefined();
        return new Response(JSON.stringify([]), { status: 200 });
      });

      const client = new GitHubClient();
      await client.fetchReleases("owner", "repo");
    });
  });

  describe("fetchChangelog", () => {
    it("returns decoded content for CHANGELOG.md", async () => {
      const content = "# Changelog\n\n## v1.0.0\n- Initial release";
      const base64Content = Buffer.from(content).toString("base64");
      mockFetch(async () => new Response(JSON.stringify({ content: base64Content }), { status: 200 }));

      const client = new GitHubClient();
      const result = await client.fetchChangelog("owner", "repo");

      expect(result).toBe(content);
      const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(url).toBe("https://api.github.com/repos/owner/repo/contents/CHANGELOG.md");
    });

    it("tries changelog.md if CHANGELOG.md returns 404", async () => {
      const content = "# Changes";
      const base64Content = Buffer.from(content).toString("base64");
      let callCount = 0;
      mockFetch(async () => {
        callCount++;
        if (callCount === 1) return new Response("Not Found", { status: 404 });
        return new Response(JSON.stringify({ content: base64Content }), { status: 200 });
      });

      const client = new GitHubClient();
      const result = await client.fetchChangelog("owner", "repo");

      expect(result).toBe(content);
      expect(fetch).toHaveBeenCalledTimes(2);
      const [url2] = (fetch as ReturnType<typeof vi.fn>).mock.calls[1];
      expect(url2).toBe("https://api.github.com/repos/owner/repo/contents/changelog.md");
    });

    it("tries CHANGES.md if first two return 404", async () => {
      const content = "# Changes";
      const base64Content = Buffer.from(content).toString("base64");
      let callCount = 0;
      mockFetch(async () => {
        callCount++;
        if (callCount <= 2) return new Response("Not Found", { status: 404 });
        return new Response(JSON.stringify({ content: base64Content }), { status: 200 });
      });

      const client = new GitHubClient();
      const result = await client.fetchChangelog("owner", "repo");

      expect(result).toBe(content);
      expect(fetch).toHaveBeenCalledTimes(3);
      const [url3] = (fetch as ReturnType<typeof vi.fn>).mock.calls[2];
      expect(url3).toBe("https://api.github.com/repos/owner/repo/contents/CHANGES.md");
    });

    it("returns null if all changelog files return 404", async () => {
      mockFetch(async () => new Response("Not Found", { status: 404 }));

      const client = new GitHubClient();
      const result = await client.fetchChangelog("owner", "repo");

      expect(result).toBeNull();
      expect(fetch).toHaveBeenCalledTimes(3);
    });

    it("returns null on fetch error", async () => {
      mockFetch(async () => { throw new Error("Network error"); });

      const client = new GitHubClient();
      const result = await client.fetchChangelog("owner", "repo");

      expect(result).toBeNull();
    });
  });

  describe("repoExists", () => {
    it("returns true when repo exists", async () => {
      mockFetch(async () => new Response("{}", { status: 200 }));

      const client = new GitHubClient();
      const result = await client.repoExists("owner", "repo");

      expect(result).toBe(true);
      const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(url).toBe("https://api.github.com/repos/owner/repo");
    });

    it("returns false when repo does not exist", async () => {
      mockFetch(async () => new Response("Not Found", { status: 404 }));

      const client = new GitHubClient();
      const result = await client.repoExists("owner", "repo");

      expect(result).toBe(false);
    });

    it("returns false on fetch error", async () => {
      mockFetch(async () => { throw new Error("Network error"); });

      const client = new GitHubClient();
      const result = await client.repoExists("owner", "repo");

      expect(result).toBe(false);
    });
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AndroidXChangelogProvider } from "../androidx-provider.js";

vi.mock("node:fs/promises", () => ({
  readFile: vi.fn().mockRejectedValue(new Error("ENOENT")),
  writeFile: vi.fn().mockResolvedValue(undefined),
  mkdir: vi.fn().mockResolvedValue(undefined),
}));

describe("AndroidXChangelogProvider", () => {
  let provider: AndroidXChangelogProvider;
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    provider = new AndroidXChangelogProvider();
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  describe("canHandle", () => {
    it("returns true for androidx.core", () => {
      expect(provider.canHandle("androidx.core", "core")).toBe(true);
    });

    it("returns true for androidx.compose.material3", () => {
      expect(provider.canHandle("androidx.compose.material3", "material3")).toBe(true);
    });

    it("returns false for io.ktor", () => {
      expect(provider.canHandle("io.ktor", "ktor-core")).toBe(false);
    });
  });

  describe("fetchChangelog", () => {
    it("fetches and parses AndroidX release notes", async () => {
      const html = `
        <h3 id="1.2.0">Version 1.2.0</h3>
        <p>New features.</p>
        <h3 id="1.1.0">Version 1.1.0</h3>
        <p>Bug fixes.</p>
      `;
      globalThis.fetch = vi.fn().mockResolvedValueOnce(
        new Response(html, { status: 200 }),
      ) as typeof fetch;

      const result = await provider.fetchChangelog("androidx.core", "core", "1.2.0", []);

      expect(result).not.toBeNull();
      expect(result!.repositoryUrl).toBe(
        "https://developer.android.com/jetpack/androidx/releases/core",
      );
      expect(result!.entries.size).toBe(2);
      expect(result!.entries.has("1.2.0")).toBe(true);
      expect(result!.entries.get("1.2.0")!.body).toContain("New features");
      expect(result!.entries.has("1.1.0")).toBe(true);
    });

    it("returns null when fetch fails", async () => {
      globalThis.fetch = vi.fn().mockRejectedValueOnce(
        new Error("Network error"),
      ) as typeof fetch;

      const result = await provider.fetchChangelog("androidx.core", "core", "1.0.0", []);
      expect(result).toBeNull();
    });

    it("returns null when page returns 404", async () => {
      globalThis.fetch = vi.fn().mockResolvedValueOnce(
        new Response("Not Found", { status: 404 }),
      ) as typeof fetch;

      const result = await provider.fetchChangelog("androidx.core", "core", "1.0.0", []);
      expect(result).toBeNull();
    });

    it("returns null when page has no version headings", async () => {
      globalThis.fetch = vi.fn().mockResolvedValueOnce(
        new Response("<h1>Empty Page</h1>", { status: 200 }),
      ) as typeof fetch;

      const result = await provider.fetchChangelog("androidx.core", "core", "1.0.0", []);
      expect(result).toBeNull();
    });
  });
});

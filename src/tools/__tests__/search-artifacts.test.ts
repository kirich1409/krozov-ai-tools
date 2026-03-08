import { describe, it, expect, vi, beforeEach } from "vitest";
import { searchArtifactsHandler } from "../search-artifacts.js";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("searchArtifactsHandler", () => {
  beforeEach(() => vi.clearAllMocks());

  it("returns search results", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        response: {
          numFound: 1,
          docs: [{ g: "com.google.code.gson", a: "gson", latestVersion: "2.11.0", versionCount: 30 }],
        },
      }),
    });
    const result = await searchArtifactsHandler({ query: "gson" });
    expect(result.results).toHaveLength(1);
    expect(result.results[0].groupId).toBe("com.google.code.gson");
  });
});

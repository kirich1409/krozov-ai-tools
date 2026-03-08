import { describe, it, expect, vi, beforeEach } from "vitest";
import { searchMavenCentral } from "../maven-search.js";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("searchMavenCentral", () => {
  beforeEach(() => vi.clearAllMocks());

  it("returns parsed search results", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        response: {
          numFound: 2,
          docs: [
            { g: "io.ktor", a: "ktor-client-core", latestVersion: "3.1.1", p: "jar", versionCount: 50 },
            { g: "io.ktor", a: "ktor-server-core", latestVersion: "3.1.1", p: "jar", versionCount: 48 },
          ],
        },
      }),
    });
    const result = await searchMavenCentral("ktor");
    expect(result).toHaveLength(2);
    expect(result[0].groupId).toBe("io.ktor");
    expect(result[0].artifactId).toBe("ktor-client-core");
    expect(result[0].latestVersion).toBe("3.1.1");
  });

  it("respects limit parameter", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ response: { numFound: 0, docs: [] } }),
    });
    await searchMavenCentral("test", 5);
    const [url] = mockFetch.mock.calls[0];
    expect(url).toContain("rows=5");
  });

  it("returns empty array on error", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });
    const result = await searchMavenCentral("fail");
    expect(result).toEqual([]);
  });

  it("returns empty array when fetch rejects", async () => {
    mockFetch.mockRejectedValueOnce(new Error("network error"));
    const result = await searchMavenCentral("network-fail");
    expect(result).toEqual([]);
  });
});

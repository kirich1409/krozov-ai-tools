import { describe, it, expect, vi, beforeEach } from "vitest";
import { queryOsvBatch } from "../osv-client.js";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("queryOsvBatch", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("returns vulnerabilities for affected packages", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        results: [
          {
            vulns: [
              {
                id: "GHSA-1234-abcd",
                summary: "Remote code execution",
                severity: [{ type: "CVSS_V3", score: "9.8" }],
                affected: [{
                  ranges: [{ type: "ECOSYSTEM", events: [{ introduced: "0" }, { fixed: "2.0.1" }] }],
                }],
                references: [{ type: "ADVISORY", url: "https://github.com/advisories/GHSA-1234-abcd" }],
              },
            ],
          },
          { vulns: [] },
        ],
      }),
    });

    const results = await queryOsvBatch([
      { groupId: "com.example", artifactId: "lib", version: "2.0.0" },
      { groupId: "io.safe", artifactId: "safe-lib", version: "1.0.0" },
    ]);

    expect(results).toHaveLength(2);
    expect(results[0].vulnerabilities).toHaveLength(1);
    expect(results[0].vulnerabilities[0].id).toBe("GHSA-1234-abcd");
    expect(results[0].vulnerabilities[0].severity).toBe("CRITICAL");
    expect(results[0].vulnerabilities[0].fixedVersion).toBe("2.0.1");
    expect(results[1].vulnerabilities).toHaveLength(0);
  });

  it("sends correct request format", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ results: [{ vulns: [] }] }),
    });

    await queryOsvBatch([{ groupId: "io.ktor", artifactId: "ktor-core", version: "2.3.0" }]);

    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe("https://api.osv.dev/v1/querybatch");
    const body = JSON.parse(init.body);
    expect(body.queries[0].package.name).toBe("io.ktor:ktor-core");
    expect(body.queries[0].package.ecosystem).toBe("Maven");
    expect(body.queries[0].version).toBe("2.3.0");
  });

  it("returns empty vulnerabilities on API error", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

    const results = await queryOsvBatch([
      { groupId: "com.example", artifactId: "lib", version: "1.0.0" },
    ]);

    expect(results).toHaveLength(1);
    expect(results[0].vulnerabilities).toHaveLength(0);
  });
});

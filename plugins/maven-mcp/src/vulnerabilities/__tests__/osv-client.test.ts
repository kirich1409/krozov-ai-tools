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
                severity: [{ type: "CVSS_V3", score: "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H" }],
                database_specific: { severity: "CRITICAL" },
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

  it("normalizes MODERATE severity to MEDIUM", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        results: [{
          vulns: [{
            id: "GHSA-mod-erat-eeee",
            summary: "moderate severity",
            database_specific: { severity: "MODERATE" },
            affected: [],
            references: [],
          }],
        }],
      }),
    });

    const results = await queryOsvBatch([
      { groupId: "com.example", artifactId: "lib", version: "1.0.0" },
    ]);

    expect(results[0].vulnerabilities).toHaveLength(1);
    expect(results[0].vulnerabilities[0].severity).toBe("MEDIUM");
  });

  it("rejects unknown severity strings", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        results: [{
          vulns: [{
            id: "GHSA-unkn-own1",
            summary: "unknown severity",
            database_specific: { severity: "BOGUS" },
            affected: [],
            references: [],
          }],
        }],
      }),
    });

    const results = await queryOsvBatch([
      { groupId: "com.example", artifactId: "lib", version: "1.0.0" },
    ]);

    expect(results[0].vulnerabilities[0].severity).toBeUndefined();
  });

  it("filters out withdrawn vulnerabilities before mapping", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        results: [{
          vulns: [
            {
              id: "GHSA-active-active",
              summary: "active",
              database_specific: { severity: "HIGH" },
              affected: [],
              references: [],
            },
            {
              id: "GHSA-with-drawn",
              summary: "withdrawn",
              database_specific: { severity: "CRITICAL" },
              withdrawn: "2024-01-01T00:00:00Z",
              affected: [],
              references: [],
            },
          ],
        }],
      }),
    });

    const results = await queryOsvBatch([
      { groupId: "com.example", artifactId: "lib", version: "1.0.0" },
    ]);

    expect(results[0].vulnerabilities).toHaveLength(1);
    expect(results[0].vulnerabilities[0].id).toBe("GHSA-active-active");
  });
});

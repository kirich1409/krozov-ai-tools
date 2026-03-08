import { describe, it, expect, vi, beforeEach } from "vitest";
import { getDependencyVulnerabilitiesHandler } from "../get-dependency-vulnerabilities.js";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("getDependencyVulnerabilitiesHandler", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("returns vulnerability results for dependencies", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        results: [
          { vulns: [{ id: "CVE-2024-001", summary: "XSS bug", severity: [{ type: "CVSS_V3", score: "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:N" }], database_specific: { severity: "HIGH" }, affected: [{ ranges: [{ type: "ECOSYSTEM", events: [{ introduced: "0" }, { fixed: "1.5.0" }] }] }], references: [{ type: "ADVISORY", url: "https://example.com" }] }] },
          { vulns: [] },
        ],
      }),
    });

    const result = await getDependencyVulnerabilitiesHandler({
      dependencies: [
        { groupId: "com.example", artifactId: "vuln-lib", version: "1.0.0" },
        { groupId: "io.safe", artifactId: "safe-lib", version: "2.0.0" },
      ],
    });

    expect(result.results).toHaveLength(2);
    expect(result.results[0].vulnerabilityCount).toBe(1);
    expect(result.results[0].vulnerabilities[0].id).toBe("CVE-2024-001");
    expect(result.results[1].vulnerabilityCount).toBe(0);
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getDependencyHealthHandler, scmHost } from "../get-dependency-health.js";
import type { MavenRepository } from "../../maven/repository.js";

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
      lastUpdated: "20240101000000",
    }),
  };
}

const POM_WITH_SCM = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <groupId>io.ktor</groupId>
  <artifactId>ktor-core</artifactId>
  <version>1.2.0</version>
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

const RECENT = new Date(Date.now() - 5 * 86_400_000).toISOString();
const OLD = new Date(Date.now() - 760 * 86_400_000).toISOString(); // ~25 months ago

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("getDependencyHealthHandler", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("reports healthy signals for an active, well-maintained library", async () => {
    const repo = mockRepo(["1.0.0", "1.1.0", "1.2.0"]);

    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(POM_WITH_SCM, { status: 200 }))
      .mockResolvedValueOnce(json({
        stargazers_count: 5000,
        forks_count: 500,
        archived: false,
        pushed_at: RECENT,
        open_issues_count: 80,
        created_at: "2018-01-01T00:00:00Z",
        license: { spdx_id: "Apache-2.0", name: "Apache License 2.0" },
        owner: { login: "ktorio", type: "Organization" },
      }))
      .mockResolvedValueOnce(json([
        { tag_name: "1.2.0", body: "", html_url: "", published_at: RECENT },
        { tag_name: "1.1.0", body: "", html_url: "", published_at: new Date(Date.now() - 40 * 86_400_000).toISOString() },
      ]))
      .mockResolvedValueOnce(json({ total_count: 80 }))   // open issues
      .mockResolvedValueOnce(json({ total_count: 920 }))  // closed issues
      .mockResolvedValueOnce(json({ items: [             // recent closed issues
        { created_at: "2024-01-01T00:00:00Z", closed_at: "2024-01-03T00:00:00Z" },
        { created_at: "2024-02-01T00:00:00Z", closed_at: "2024-02-04T00:00:00Z" },
      ] }))
      .mockResolvedValueOnce(json({ public_repos: 120, created_at: "2011-05-01T00:00:00Z" })) as typeof fetch;

    const { results } = await getDependencyHealthHandler([repo], {
      dependencies: [{ groupId: "io.ktor", artifactId: "ktor-core" }],
    });

    expect(results).toHaveLength(1);
    const r = results[0];
    expect(r.latestVersion).toBe("1.2.0");
    expect(r.stability).toBe("stable");
    expect(r.repository).toEqual({
      owner: "ktorio",
      repo: "ktor",
      url: "https://github.com/ktorio/ktor",
    });
    expect(r.scm).toEqual({ url: "https://github.com/ktorio/ktor", host: "github" });
    expect(r.github?.stars).toBe(5000);
    expect(r.github?.ownerType).toBe("Organization");
    expect(r.github?.ownerPublicRepos).toBe(120);
    expect(r.github?.ownerAccountCreatedAt).toBe("2011-05-01T00:00:00Z");
    expect(r.github?.license).toBe("Apache-2.0");
    expect(r.github?.archived).toBe(false);
    expect(r.github?.issues?.closeRatio).toBeCloseTo(0.92, 2);
    expect(r.signals).toHaveLength(0);
    expect(r.healthError).toBeUndefined();
  });

  it("flags archived, stale, and unresponsive repositories", async () => {
    const repo = mockRepo(["1.0.0", "1.1.0"]);

    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(POM_WITH_SCM, { status: 200 }))
      .mockResolvedValueOnce(json({
        stargazers_count: 12,
        forks_count: 2,
        archived: true,
        pushed_at: OLD,
        open_issues_count: 200,
        created_at: "2015-01-01T00:00:00Z",
        license: null,
        owner: { login: "old", type: "User" },
      }))
      .mockResolvedValueOnce(json([
        { tag_name: "1.1.0", body: "", html_url: "", published_at: OLD },
      ]))
      .mockResolvedValueOnce(json({ total_count: 200 }))  // open
      .mockResolvedValueOnce(json({ total_count: 100 }))  // closed
      .mockResolvedValueOnce(json({ items: [
        { created_at: "2022-01-01T00:00:00Z", closed_at: "2023-02-05T00:00:00Z" }, // ~400 days
      ] }))
      .mockResolvedValueOnce(new Response("not found", { status: 404 })) as typeof fetch; // user lookup fails → null

    const { results } = await getDependencyHealthHandler([repo], {
      dependencies: [{ groupId: "io.ktor", artifactId: "ktor-core" }],
    });

    const r = results[0];
    expect(r.github?.archived).toBe(true);
    expect(r.github?.ownerType).toBe("User");
    expect(r.github?.ownerPublicRepos).toBeNull();
    expect(r.github?.ownerAccountCreatedAt).toBeNull();
    expect(r.signals).toContain("repository archived");
    expect(r.signals).toContain("no license declared");
    expect(r.signals).toContain("high open-issue backlog, low close ratio");
    expect(r.signals.some((s) => s.startsWith("no commits in"))).toBe(true);
    expect(r.signals.some((s) => s.startsWith("no release in"))).toBe(true);
    expect(r.signals.some((s) => s.startsWith("slow issue response"))).toBe(true);
  });

  it("degrades gracefully when there is no public GitHub repository", async () => {
    const repo = mockRepo(["1.0.0", "1.1.0"]);

    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(POM_WITHOUT_SCM, { status: 200 })) as typeof fetch;

    const { results } = await getDependencyHealthHandler([repo], {
      dependencies: [{ groupId: "com.example", artifactId: "no-scm" }],
    });

    const r = results[0];
    expect(r.github).toBeNull();
    expect(r.repository).toBeNull();
    expect(r.signals).toContain("no public GitHub repository found");
    expect(r.signals).toContain("no license declared");
    expect(r.healthError).toContain("not found");
  });

  it("sets healthError when GitHub metadata is unavailable (rate limit)", async () => {
    const repo = mockRepo(["1.0.0", "1.1.0", "1.2.0"]);

    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(POM_WITH_SCM, { status: 200 }))
      .mockResolvedValueOnce(new Response("rate limited", { status: 403 })) as typeof fetch;

    const { results } = await getDependencyHealthHandler([repo], {
      dependencies: [{ groupId: "io.ktor", artifactId: "ktor-core" }],
    });

    const r = results[0];
    expect(r.repository).toEqual({
      owner: "ktorio",
      repo: "ktor",
      url: "https://github.com/ktorio/ktor",
    });
    expect(r.github).toBeNull();
    expect(r.healthError).toContain("metadata unavailable");
  });
});

describe("scmHost", () => {
  it("detects github from https URL", () => {
    expect(scmHost("https://github.com/owner/repo")).toBe("github");
  });

  it("detects github from git:// URL", () => {
    expect(scmHost("git://github.com/owner/repo")).toBe("github");
  });

  it("detects github from scp-like SSH URL", () => {
    expect(scmHost("git@github.com:owner/repo.git")).toBe("github");
  });

  it("detects gitlab from https URL", () => {
    expect(scmHost("https://gitlab.com/owner/repo")).toBe("gitlab");
  });

  it("detects bitbucket from https URL", () => {
    expect(scmHost("https://bitbucket.org/owner/repo")).toBe("bitbucket");
  });

  it("returns other for a self-hosted gitlab subdomain", () => {
    expect(scmHost("https://gitlab.example.com/owner/repo")).toBe("other");
  });

  it("returns other for an attacker URL containing github.com as a substring", () => {
    expect(scmHost("https://evil-github.com.attacker.io/x")).toBe("other");
  });

  it("returns other for an empty string", () => {
    expect(scmHost("")).toBe("other");
  });

  it("returns other for a malformed URL", () => {
    expect(scmHost("not a url at all")).toBe("other");
  });
});

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

const POM_WITH_GITLAB_SCM = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <groupId>com.example</groupId>
  <artifactId>gitlab-lib</artifactId>
  <version>1.0.0</version>
  <scm>
    <url>https://gitlab.com/somegroup/gitlab-lib</url>
  </scm>
</project>`;

const POM_WITH_BITBUCKET_SCM = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <groupId>com.example</groupId>
  <artifactId>bitbucket-lib</artifactId>
  <version>1.0.0</version>
  <scm>
    <url>https://bitbucket.org/somegroup/bitbucket-lib</url>
  </scm>
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

  it("emits non-alarming SCM signal (not healthError) when SCM is on GitLab", async () => {
    const repo = mockRepo(["1.0.0", "1.1.0"]);
    (repo.fetchMetadata as ReturnType<typeof vi.fn>).mockResolvedValue({
      groupId: "com.example",
      artifactId: "gitlab-lib",
      versions: ["1.0.0", "1.1.0"],
      latest: "1.1.0",
      release: "1.1.0",
      lastUpdated: "20240101000000",
    });

    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(POM_WITH_GITLAB_SCM, { status: 200 })) as typeof fetch;

    const { results } = await getDependencyHealthHandler([repo], {
      dependencies: [{ groupId: "com.example", artifactId: "gitlab-lib" }],
    });

    const r = results[0];
    expect(r.github).toBeNull();
    expect(r.repository).toBeNull();
    expect(r.scm).toEqual({ url: "https://gitlab.com/somegroup/gitlab-lib", host: "gitlab" });
    // Non-alarming informational signal — not a transparency red flag
    expect(r.signals).toContain("SCM hosted on gitlab; GitHub metrics unavailable");
    // Must NOT be treated as a missing-repo error
    expect(r.signals).not.toContain("no public GitHub repository found");
    expect(r.healthError).toBeUndefined();
  });

  it("emits non-alarming SCM signal (not healthError) when SCM is on Bitbucket", async () => {
    const repo = mockRepo(["2.0.0"]);
    (repo.fetchMetadata as ReturnType<typeof vi.fn>).mockResolvedValue({
      groupId: "com.example",
      artifactId: "bitbucket-lib",
      versions: ["2.0.0"],
      latest: "2.0.0",
      release: "2.0.0",
      lastUpdated: "20240101000000",
    });

    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(POM_WITH_BITBUCKET_SCM, { status: 200 })) as typeof fetch;

    const { results } = await getDependencyHealthHandler([repo], {
      dependencies: [{ groupId: "com.example", artifactId: "bitbucket-lib" }],
    });

    const r = results[0];
    expect(r.scm).toEqual({ url: "https://bitbucket.org/somegroup/bitbucket-lib", host: "bitbucket" });
    expect(r.signals).toContain("SCM hosted on bitbucket; GitHub metrics unavailable");
    expect(r.signals).not.toContain("no public GitHub repository found");
    expect(r.healthError).toBeUndefined();
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

  // Comment #1 fix: latestVersion always reflects real latest even when a specific version is requested
  it("reports real latestVersion when a specific (older) version is requested", async () => {
    const repo = mockRepo(["1.0.0", "1.1.0", "1.2.0"]);

    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(POM_WITH_SCM, { status: 200 }))
      .mockResolvedValueOnce(json({
        stargazers_count: 100,
        forks_count: 10,
        archived: false,
        pushed_at: RECENT,
        open_issues_count: 5,
        created_at: "2020-01-01T00:00:00Z",
        license: { spdx_id: "MIT", name: "MIT License" },
        owner: { login: "ktorio", type: "Organization" },
      }))
      .mockResolvedValueOnce(json([
        { tag_name: "1.2.0", body: "", html_url: "", published_at: RECENT },
      ]))
      .mockResolvedValueOnce(json({ total_count: 5 }))
      .mockResolvedValueOnce(json({ total_count: 50 }))
      .mockResolvedValueOnce(json({ items: [] }))
      .mockResolvedValueOnce(json({ public_repos: 10, created_at: "2015-01-01T00:00:00Z" })) as typeof fetch;

    const { results } = await getDependencyHealthHandler([repo], {
      dependencies: [{ groupId: "io.ktor", artifactId: "ktor-core", version: "1.0.0" }],
    });

    const r = results[0];
    // latestVersion must be 1.2.0 (real latest), not 1.0.0 (requested version)
    expect(r.latestVersion).toBe("1.2.0");
    expect(r.stability).toBe("stable");
  });

  // Comment #2 fix: issue stats should preserve null when one Search API call fails
  it("returns null for issue counts when Search API calls fail", async () => {
    const repo = mockRepo(["1.0.0", "1.1.0", "1.2.0"]);

    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(POM_WITH_SCM, { status: 200 }))
      .mockResolvedValueOnce(json({
        stargazers_count: 100,
        forks_count: 10,
        archived: false,
        pushed_at: RECENT,
        open_issues_count: 5,
        created_at: "2020-01-01T00:00:00Z",
        license: { spdx_id: "MIT", name: "MIT License" },
        owner: { login: "ktorio", type: "Organization" },
      }))
      .mockResolvedValueOnce(json([]))  // releases
      .mockResolvedValueOnce(json({ total_count: 200 }))              // open issues — success
      .mockResolvedValueOnce(new Response("forbidden", { status: 403 }))  // closed issues — fail
      .mockResolvedValueOnce(new Response("forbidden", { status: 403 }))  // median — fail
      .mockResolvedValueOnce(json({ public_repos: 10, created_at: "2015-01-01T00:00:00Z" })) as typeof fetch;

    const { results } = await getDependencyHealthHandler([repo], {
      dependencies: [{ groupId: "io.ktor", artifactId: "ktor-core" }],
    });

    const r = results[0];
    expect(r.github?.issues).not.toBeNull();
    expect(r.github?.issues?.open).toBe(200);
    // closed should be null (failed), not 0 (which would be misleading)
    expect(r.github?.issues?.closed).toBeNull();
    // closeRatio requires both counts — must be null when one is missing
    expect(r.github?.issues?.closeRatio).toBeNull();
  });

  // Comment #3 fix: guess path should call fetchRepo only once (not repoExists + fetchRepo)
  it("calls fetchRepo only once when guessing the GitHub repo", async () => {
    const POM_NO_SCM_GITHUB_GROUP = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <groupId>io.github.someowner</groupId>
  <artifactId>some-lib</artifactId>
  <version>1.0.0</version>
</project>`;

    const repoWithGithubGroup = mockRepo(["1.0.0"]);
    (repoWithGithubGroup.fetchMetadata as ReturnType<typeof vi.fn>).mockResolvedValue({
      groupId: "io.github.someowner",
      artifactId: "some-lib",
      versions: ["1.0.0"],
      latest: "1.0.0",
      release: "1.0.0",
      lastUpdated: "20240101000000",
    });

    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(POM_NO_SCM_GITHUB_GROUP, { status: 200 }))
      // Single fetchRepo call for the guessed repo (owner=someowner, repo=some-lib)
      .mockResolvedValueOnce(json({
        stargazers_count: 50,
        forks_count: 5,
        archived: false,
        pushed_at: RECENT,
        open_issues_count: 2,
        created_at: "2021-01-01T00:00:00Z",
        license: { spdx_id: "MIT", name: "MIT License" },
        owner: { login: "someowner", type: "User" },
      }))
      .mockResolvedValueOnce(json([]))  // releases
      .mockResolvedValueOnce(json({ total_count: 2 }))    // open issues
      .mockResolvedValueOnce(json({ total_count: 10 }))   // closed issues
      .mockResolvedValueOnce(json({ items: [] }))         // median
      .mockResolvedValueOnce(json({ public_repos: 5, created_at: "2018-01-01T00:00:00Z" })) as typeof fetch;

    globalThis.fetch = fetchMock;

    const { results } = await getDependencyHealthHandler([repoWithGithubGroup], {
      dependencies: [{ groupId: "io.github.someowner", artifactId: "some-lib" }],
    });

    const r = results[0];
    expect(r.repository?.owner).toBe("someowner");
    expect(r.github).not.toBeNull();
    // Verify fetchRepo was called exactly once for the guessed repo — no prior repoExists call.
    // Use a regex that matches /repos/owner/repo exactly (no trailing path) to avoid
    // matching /repos/owner/repo/releases or similar sub-paths.
    const repoMetaCalls = fetchMock.mock.calls.filter(
      (call) => typeof call[0] === "string" && /\/repos\/someowner\/some-lib$/.test(call[0]),
    );
    expect(repoMetaCalls).toHaveLength(1);
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

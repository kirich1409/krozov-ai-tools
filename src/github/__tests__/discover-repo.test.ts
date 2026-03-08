import { describe, it, expect, vi, beforeEach } from "vitest";
import { discoverGitHubRepo } from "../discover-repo.js";
import type { MavenRepository } from "../../maven/repository.js";
import { GitHubClient } from "../github-client.js";

function makeMockRepo(name: string, url: string): MavenRepository {
  return {
    name,
    url,
    fetchMetadata: vi.fn(),
  };
}

const POM_WITH_SCM = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <groupId>com.squareup.okhttp3</groupId>
  <artifactId>okhttp</artifactId>
  <version>4.12.0</version>
  <scm>
    <url>https://github.com/square/okhttp</url>
  </scm>
</project>`;

const POM_WITHOUT_SCM = `<?xml version="1.0" encoding="UTF-8"?>
<project>
  <groupId>com.example</groupId>
  <artifactId>lib</artifactId>
  <version>1.0.0</version>
</project>`;

describe("discoverGitHubRepo", () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);
  });

  it("returns GitHub repo from POM SCM", async () => {
    const repo = makeMockRepo("Maven Central", "https://repo1.maven.org/maven2");

    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: async () => POM_WITH_SCM,
    });

    const result = await discoverGitHubRepo(
      [repo],
      "com.squareup.okhttp3",
      "okhttp",
      "4.12.0",
    );

    expect(result).toEqual({ owner: "square", repo: "okhttp" });
    expect(mockFetch).toHaveBeenCalledWith(
      "https://repo1.maven.org/maven2/com/squareup/okhttp3/okhttp/4.12.0/okhttp-4.12.0.pom",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("tries multiple repos and returns first POM with GitHub SCM", async () => {
    const repo1 = makeMockRepo("Custom", "https://custom.repo.com/maven2");
    const repo2 = makeMockRepo("Maven Central", "https://repo1.maven.org/maven2");

    // First repo POM fetch fails
    mockFetch.mockResolvedValueOnce({ ok: false });
    // Second repo returns POM with SCM
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: async () => POM_WITH_SCM,
    });

    const result = await discoverGitHubRepo(
      [repo1, repo2],
      "com.squareup.okhttp3",
      "okhttp",
      "4.12.0",
    );

    expect(result).toEqual({ owner: "square", repo: "okhttp" });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("falls back to guess when POM has no GitHub SCM", async () => {
    const repo = makeMockRepo("Maven Central", "https://repo1.maven.org/maven2");

    // POM without SCM
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: async () => POM_WITHOUT_SCM,
    });

    // repoExists check for guessed repo
    mockFetch.mockResolvedValueOnce({ ok: true });

    const result = await discoverGitHubRepo(
      [repo],
      "io.github.javalin",
      "javalin",
      "5.0.0",
    );

    expect(result).toEqual({ owner: "javalin", repo: "javalin" });
  });

  it("returns null when guess repo does not exist on GitHub", async () => {
    const repo = makeMockRepo("Maven Central", "https://repo1.maven.org/maven2");

    // POM without SCM
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: async () => POM_WITHOUT_SCM,
    });

    // repoExists returns false
    mockFetch.mockResolvedValueOnce({ ok: false });

    const result = await discoverGitHubRepo(
      [repo],
      "io.github.someuser",
      "nonexistent-lib",
      "1.0.0",
    );

    expect(result).toBeNull();
  });

  it("returns null when no POM found and groupId is not guessable", async () => {
    const repo = makeMockRepo("Maven Central", "https://repo1.maven.org/maven2");

    // POM fetch fails
    mockFetch.mockResolvedValueOnce({ ok: false });

    const result = await discoverGitHubRepo(
      [repo],
      "org.apache.commons",
      "commons-lang3",
      "3.14.0",
    );

    expect(result).toBeNull();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("handles fetch errors gracefully during POM retrieval", async () => {
    const repo = makeMockRepo("Maven Central", "https://repo1.maven.org/maven2");

    // POM fetch throws
    mockFetch.mockRejectedValueOnce(new Error("Network error"));

    const result = await discoverGitHubRepo(
      [repo],
      "org.example",
      "lib",
      "1.0.0",
    );

    expect(result).toBeNull();
  });

  it("uses provided githubClient for repoExists check", async () => {
    const repo = makeMockRepo("Maven Central", "https://repo1.maven.org/maven2");

    // POM without SCM
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: async () => POM_WITHOUT_SCM,
    });

    const client = new GitHubClient("test-token");
    const repoExistsSpy = vi.spyOn(client, "repoExists").mockResolvedValue(true);

    const result = await discoverGitHubRepo(
      [repo],
      "com.github.myuser",
      "mylib",
      "1.0.0",
      client,
    );

    expect(result).toEqual({ owner: "myuser", repo: "mylib" });
    expect(repoExistsSpy).toHaveBeenCalledWith("myuser", "mylib");
  });

  it("skips POM without GitHub info and tries next repo", async () => {
    const repo1 = makeMockRepo("Repo1", "https://repo1.example.com");
    const repo2 = makeMockRepo("Repo2", "https://repo2.example.com");

    // First repo returns POM without GitHub SCM
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: async () => POM_WITHOUT_SCM,
    });

    // Second repo returns POM with GitHub SCM
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: async () => POM_WITH_SCM,
    });

    const result = await discoverGitHubRepo(
      [repo1, repo2],
      "com.squareup.okhttp3",
      "okhttp",
      "4.12.0",
    );

    expect(result).toEqual({ owner: "square", repo: "okhttp" });
  });
});

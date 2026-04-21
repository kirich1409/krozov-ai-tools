import { describe, it, expect } from "vitest";
import { buildPomUrl, extractGitHubRepo } from "../pom-scm.js";

describe("buildPomUrl", () => {
  it("builds URL with dots replaced by slashes in groupId", () => {
    expect(
      buildPomUrl(
        "https://repo1.maven.org/maven2",
        "com.google.guava",
        "guava",
        "31.1-jre",
      ),
    ).toBe(
      "https://repo1.maven.org/maven2/com/google/guava/guava/31.1-jre/guava-31.1-jre.pom",
    );
  });

  it("handles single-segment groupId", () => {
    expect(
      buildPomUrl("https://repo.example.com", "commons", "commons-lang", "3.0"),
    ).toBe(
      "https://repo.example.com/commons/commons-lang/3.0/commons-lang-3.0.pom",
    );
  });

  it("strips trailing slash from repo URL", () => {
    expect(
      buildPomUrl(
        "https://repo1.maven.org/maven2/",
        "org.apache",
        "commons",
        "1.0",
      ),
    ).toBe(
      "https://repo1.maven.org/maven2/org/apache/commons/1.0/commons-1.0.pom",
    );
  });
});

describe("extractGitHubRepo", () => {
  it("extracts from scm url", () => {
    const pom = `
      <project>
        <scm>
          <url>https://github.com/google/guava</url>
        </scm>
      </project>`;
    expect(extractGitHubRepo(pom)).toEqual({ owner: "google", repo: "guava" });
  });

  it("extracts from scm connection with git protocol", () => {
    const pom = `
      <project>
        <scm>
          <connection>scm:git:git://github.com/apache/commons-lang.git</connection>
        </scm>
      </project>`;
    expect(extractGitHubRepo(pom)).toEqual({
      owner: "apache",
      repo: "commons-lang",
    });
  });

  it("extracts from scm developerConnection with ssh", () => {
    const pom = `
      <project>
        <scm>
          <developerConnection>scm:git:ssh://git@github.com/square/okhttp.git</developerConnection>
        </scm>
      </project>`;
    expect(extractGitHubRepo(pom)).toEqual({
      owner: "square",
      repo: "okhttp",
    });
  });

  it("falls back to root url outside scm", () => {
    const pom = `
      <project>
        <url>https://github.com/reactor/reactor-core</url>
      </project>`;
    expect(extractGitHubRepo(pom)).toEqual({
      owner: "reactor",
      repo: "reactor-core",
    });
  });

  it("handles .git suffix", () => {
    const pom = `
      <project>
        <scm>
          <url>https://github.com/jetbrains/kotlin.git</url>
        </scm>
      </project>`;
    expect(extractGitHubRepo(pom)).toEqual({
      owner: "jetbrains",
      repo: "kotlin",
    });
  });

  it("handles /tree/main suffix", () => {
    const pom = `
      <project>
        <scm>
          <url>https://github.com/owner/repo/tree/main</url>
        </scm>
      </project>`;
    expect(extractGitHubRepo(pom)).toEqual({ owner: "owner", repo: "repo" });
  });

  it("returns null when no GitHub URL found", () => {
    const pom = `
      <project>
        <scm>
          <url>https://gitlab.com/owner/repo</url>
        </scm>
      </project>`;
    expect(extractGitHubRepo(pom)).toBeNull();
  });

  it("returns null for empty POM", () => {
    expect(extractGitHubRepo("")).toBeNull();
  });

  it("prefers scm url over root url", () => {
    const pom = `
      <project>
        <url>https://github.com/wrong/fallback</url>
        <scm>
          <url>https://github.com/correct/repo</url>
        </scm>
      </project>`;
    expect(extractGitHubRepo(pom)).toEqual({
      owner: "correct",
      repo: "repo",
    });
  });

  it("extracts from https connection string", () => {
    const pom = `
      <project>
        <scm>
          <connection>scm:git:https://github.com/owner/repo.git</connection>
        </scm>
      </project>`;
    expect(extractGitHubRepo(pom)).toEqual({ owner: "owner", repo: "repo" });
  });

  it("ignores URLs inside XML comments", () => {
    const pom = `
      <project>
        <scm>
          <!-- <url>https://github.com/wrong/repo</url> -->
          <url>https://github.com/correct/repo</url>
        </scm>
      </project>`;
    expect(extractGitHubRepo(pom)).toEqual({ owner: "correct", repo: "repo" });
  });

  it("returns null when the only GitHub url is inside an XML comment", () => {
    const pom = `
      <project>
        <!-- <url>https://github.com/wrong/repo</url> -->
      </project>`;
    expect(extractGitHubRepo(pom)).toBeNull();
  });

  it("strips smuggled nested comments (looped sanitization)", () => {
    // After the outer <!-- … --> is removed in pass 1, a fresh <!-- --> appears
    // that also has to be stripped before any <scm> probe can be fooled.
    const pom = `
      <project>
        <!<!----->-- <scm><url>https://github.com/evil/repo</url></scm> -->
        <scm>
          <url>https://github.com/correct/repo</url>
        </scm>
      </project>`;
    expect(extractGitHubRepo(pom)).toEqual({ owner: "correct", repo: "repo" });
  });
});

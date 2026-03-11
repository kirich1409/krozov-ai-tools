import { describe, it, expect } from "vitest";
import { matchReleaseToVersion } from "../tag-matcher.js";
import type { GitHubRelease } from "../github-client.js";

function release(tag: string): GitHubRelease {
  return { tag_name: tag, body: "", html_url: `https://github.com/test/repo/releases/tag/${tag}` };
}

describe("matchReleaseToVersion", () => {
  it("returns undefined for empty releases array", () => {
    expect(matchReleaseToVersion([], "1.0.0")).toBeUndefined();
  });

  it("matches exact version tag", () => {
    const releases = [release("1.0.0"), release("2.0.0")];
    const result = matchReleaseToVersion(releases, "1.0.0");
    expect(result).toEqual(releases[0]);
  });

  it("matches v-prefixed tag", () => {
    const releases = [release("v1.0.0"), release("v2.0.0")];
    const result = matchReleaseToVersion(releases, "1.0.0");
    expect(result).toEqual(releases[0]);
  });

  it("matches tag with dash separator suffix", () => {
    const releases = [release("release-1.0.0"), release("release-2.0.0")];
    const result = matchReleaseToVersion(releases, "1.0.0");
    expect(result).toEqual(releases[0]);
  });

  it("matches tag with slash separator suffix", () => {
    const releases = [release("ktor/1.0.0"), release("ktor/2.0.0")];
    const result = matchReleaseToVersion(releases, "1.0.0");
    expect(result).toEqual(releases[0]);
  });

  it("matches ktor-style tag with artifact prefix", () => {
    const releases = [release("ktor-1.0.0")];
    const result = matchReleaseToVersion(releases, "1.0.0");
    expect(result).toEqual(releases[0]);
  });

  it("prefers exact match over v-prefix", () => {
    const releases = [release("v1.0.0"), release("1.0.0")];
    const result = matchReleaseToVersion(releases, "1.0.0");
    expect(result?.tag_name).toBe("1.0.0");
  });

  it("prefers v-prefix over suffix match", () => {
    const releases = [release("release-1.0.0"), release("v1.0.0")];
    const result = matchReleaseToVersion(releases, "1.0.0");
    expect(result?.tag_name).toBe("v1.0.0");
  });

  it("does not match tag where version appears mid-string without separator", () => {
    const releases = [release("prefix1.0.0")];
    const result = matchReleaseToVersion(releases, "1.0.0");
    expect(result).toBeUndefined();
  });

  it("does not match partial version in longer tag", () => {
    const releases = [release("1.0.0-beta")];
    const result = matchReleaseToVersion(releases, "1.0.0");
    expect(result).toBeUndefined();
  });

  it("returns undefined when no tag matches", () => {
    const releases = [release("3.0.0"), release("v2.0.0")];
    const result = matchReleaseToVersion(releases, "1.0.0");
    expect(result).toBeUndefined();
  });
});

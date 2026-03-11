import { describe, it, expect } from "vitest";
import { guessGitHubRepo } from "../guess-repo.js";

describe("guessGitHubRepo", () => {
  it("returns owner and repo for com.github.{owner}", () => {
    const result = guessGitHubRepo("com.github.johnsmith", "my-library");
    expect(result).toEqual({ owner: "johnsmith", repo: "my-library" });
  });

  it("returns owner and repo for io.github.{owner}", () => {
    const result = guessGitHubRepo("io.github.janedoe", "cool-lib");
    expect(result).toEqual({ owner: "janedoe", repo: "cool-lib" });
  });

  it("returns null for non-github groupId", () => {
    expect(guessGitHubRepo("org.apache.commons", "commons-lang3")).toBeNull();
  });

  it("returns null for com.google groupId", () => {
    expect(guessGitHubRepo("com.google.guava", "guava")).toBeNull();
  });

  it("returns null for groupId that is just com.github without owner", () => {
    expect(guessGitHubRepo("com.github", "some-lib")).toBeNull();
  });

  it("returns null for groupId that is just io.github without owner", () => {
    expect(guessGitHubRepo("io.github", "some-lib")).toBeNull();
  });

  it("handles nested groupId under com.github.{owner}", () => {
    const result = guessGitHubRepo("com.github.owner.subpackage", "artifact");
    expect(result).toEqual({ owner: "owner", repo: "artifact" });
  });

  it("handles nested groupId under io.github.{owner}", () => {
    const result = guessGitHubRepo("io.github.owner.sub.deep", "artifact");
    expect(result).toEqual({ owner: "owner", repo: "artifact" });
  });
});

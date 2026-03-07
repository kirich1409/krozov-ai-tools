import { describe, it, expect, vi, beforeEach } from "vitest";
import { findProjectRoot } from "../find-project-root.js";
import * as fs from "node:fs";

vi.mock("node:fs");

const mockedFs = vi.mocked(fs);

describe("findProjectRoot", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("finds project root with settings.gradle.kts", () => {
    mockedFs.existsSync.mockImplementation((p) => {
      return p === "/home/user/project/settings.gradle.kts";
    });

    const result = findProjectRoot("/home/user/project/src/main");
    expect(result).toBe("/home/user/project");
  });

  it("walks up directories to find project root", () => {
    mockedFs.existsSync.mockImplementation((p) => {
      return p === "/home/user/project/build.gradle.kts";
    });

    const result = findProjectRoot("/home/user/project/src/main/kotlin");
    expect(result).toBe("/home/user/project");
  });

  it("returns null when no build files found", () => {
    mockedFs.existsSync.mockReturnValue(false);

    const result = findProjectRoot("/home/user/random");
    expect(result).toBeNull();
  });

  it("prefers settings.gradle.kts over build.gradle.kts", () => {
    mockedFs.existsSync.mockImplementation((p) => {
      return (
        p === "/home/user/project/settings.gradle.kts" ||
        p === "/home/user/project/build.gradle.kts"
      );
    });

    const result = findProjectRoot("/home/user/project");
    expect(result).toBe("/home/user/project");
  });

  it("finds pom.xml project", () => {
    mockedFs.existsSync.mockImplementation((p) => {
      return p === "/home/user/maven-project/pom.xml";
    });

    const result = findProjectRoot("/home/user/maven-project/src");
    expect(result).toBe("/home/user/maven-project");
  });
});

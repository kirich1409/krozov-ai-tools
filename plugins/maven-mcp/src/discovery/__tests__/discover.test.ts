import { describe, it, expect, vi, beforeEach } from "vitest";
import { discoverRepositories } from "../discover.js";
import * as fs from "node:fs";

vi.mock("node:fs");

const mockedFs = vi.mocked(fs);

describe("discoverRepositories", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("discovers repositories from settings.gradle.kts", () => {
    mockedFs.existsSync.mockImplementation((p) => {
      return p === "/project/settings.gradle.kts";
    });
    mockedFs.readFileSync.mockReturnValue(`
      dependencyResolutionManagement {
          repositories {
              google()
              mavenCentral()
          }
      }
    `);

    const result = discoverRepositories("/project");
    expect(result.buildSystem).toBe("gradle");
    expect(result.repositories).toContainEqual({
      name: "Google",
      url: "https://maven.google.com",
    });
    expect(result.repositories).toContainEqual({
      name: "Maven Central",
      url: "https://repo1.maven.org/maven2",
    });
  });

  it("discovers repositories from build.gradle.kts", () => {
    mockedFs.existsSync.mockImplementation((p) => {
      return p === "/project/build.gradle.kts";
    });
    mockedFs.readFileSync.mockReturnValue(`
      repositories {
          mavenCentral()
          maven("https://jitpack.io")
      }
    `);

    const result = discoverRepositories("/project");
    expect(result.buildSystem).toBe("gradle");
    expect(result.repositories).toHaveLength(2);
  });

  it("discovers repositories from pom.xml", () => {
    mockedFs.existsSync.mockImplementation((p) => {
      return p === "/project/pom.xml";
    });
    mockedFs.readFileSync.mockReturnValue(`
      <project>
        <repositories>
          <repository>
            <id>spring</id>
            <url>https://repo.spring.io/milestone</url>
          </repository>
        </repositories>
      </project>
    `);

    const result = discoverRepositories("/project");
    expect(result.buildSystem).toBe("maven");
    expect(result.repositories).toContainEqual({
      name: "spring",
      url: "https://repo.spring.io/milestone",
    });
  });

  it("returns unknown build system when no build files found", () => {
    mockedFs.existsSync.mockReturnValue(false);

    const result = discoverRepositories("/project");
    expect(result.buildSystem).toBe("unknown");
    expect(result.repositories).toEqual([]);
  });

  it("merges repositories from settings and build files", () => {
    mockedFs.existsSync.mockImplementation((p) => {
      return (
        p === "/project/settings.gradle.kts" ||
        p === "/project/build.gradle.kts"
      );
    });
    mockedFs.readFileSync.mockImplementation((p) => {
      if (String(p).endsWith("settings.gradle.kts")) {
        return `
          dependencyResolutionManagement {
              repositories {
                  google()
              }
          }
        `;
      }
      return `
        repositories {
            mavenCentral()
        }
      `;
    });

    const result = discoverRepositories("/project");
    expect(result.repositories).toHaveLength(2);
  });

  it("deduplicates across files", () => {
    mockedFs.existsSync.mockImplementation((p) => {
      return (
        p === "/project/settings.gradle.kts" ||
        p === "/project/build.gradle.kts"
      );
    });
    mockedFs.readFileSync.mockReturnValue(`
      repositories {
          mavenCentral()
      }
    `);

    const result = discoverRepositories("/project");
    expect(result.repositories).toHaveLength(1);
  });
});

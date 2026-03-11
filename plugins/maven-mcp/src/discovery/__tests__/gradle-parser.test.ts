import { describe, it, expect } from "vitest";
import { parseGradleRepositories } from "../gradle-parser.js";

describe("parseGradleRepositories", () => {
  describe("Kotlin DSL", () => {
    it("parses mavenCentral()", () => {
      const content = `
        repositories {
            mavenCentral()
        }
      `;
      const repos = parseGradleRepositories(content);
      expect(repos).toContainEqual({
        name: "Maven Central",
        url: "https://repo1.maven.org/maven2",
      });
    });

    it("parses google()", () => {
      const content = `
        repositories {
            google()
        }
      `;
      const repos = parseGradleRepositories(content);
      expect(repos).toContainEqual({
        name: "Google",
        url: "https://maven.google.com",
      });
    });

    it("parses gradlePluginPortal()", () => {
      const content = `
        repositories {
            gradlePluginPortal()
        }
      `;
      const repos = parseGradleRepositories(content);
      expect(repos).toContainEqual({
        name: "Gradle Plugin Portal",
        url: "https://plugins.gradle.org/m2",
      });
    });

    it("parses maven(\"url\")", () => {
      const content = `
        repositories {
            maven("https://jitpack.io")
        }
      `;
      const repos = parseGradleRepositories(content);
      expect(repos).toContainEqual({
        name: "https://jitpack.io",
        url: "https://jitpack.io",
      });
    });

    it("parses maven(url = \"...\")", () => {
      const content = `
        repositories {
            maven(url = "https://maven.pkg.jetbrains.space/public/p/compose/dev")
        }
      `;
      const repos = parseGradleRepositories(content);
      expect(repos).toContainEqual({
        name: "https://maven.pkg.jetbrains.space/public/p/compose/dev",
        url: "https://maven.pkg.jetbrains.space/public/p/compose/dev",
      });
    });

    it("parses maven { url = uri(\"...\") }", () => {
      const content = `
        repositories {
            maven {
                url = uri("https://repo.spring.io/milestone")
            }
        }
      `;
      const repos = parseGradleRepositories(content);
      expect(repos).toContainEqual({
        name: "https://repo.spring.io/milestone",
        url: "https://repo.spring.io/milestone",
      });
    });

    it("parses multiple repositories", () => {
      const content = `
        repositories {
            google()
            mavenCentral()
            maven("https://jitpack.io")
        }
      `;
      const repos = parseGradleRepositories(content);
      expect(repos).toHaveLength(3);
    });
  });

  describe("Groovy DSL", () => {
    it("parses maven { url 'https://...' }", () => {
      const content = `
        repositories {
            maven { url 'https://repo.spring.io/milestone' }
        }
      `;
      const repos = parseGradleRepositories(content);
      expect(repos).toContainEqual({
        name: "https://repo.spring.io/milestone",
        url: "https://repo.spring.io/milestone",
      });
    });

    it("parses maven { url \"https://...\" }", () => {
      const content = `
        repositories {
            maven { url "https://jitpack.io" }
        }
      `;
      const repos = parseGradleRepositories(content);
      expect(repos).toContainEqual({
        name: "https://jitpack.io",
        url: "https://jitpack.io",
      });
    });
  });

  it("deduplicates repositories", () => {
    const content = `
      repositories {
          mavenCentral()
          mavenCentral()
      }
    `;
    const repos = parseGradleRepositories(content);
    expect(repos).toHaveLength(1);
  });

  it("returns empty array for content without repositories", () => {
    const content = `
      plugins {
          id("org.jetbrains.kotlin.jvm")
      }
    `;
    const repos = parseGradleRepositories(content);
    expect(repos).toEqual([]);
  });
});

import { describe, it, expect } from "vitest";
import { parseChangelogSections } from "../changelog-parser.js";

describe("parseChangelogSections", () => {
  it("parses heading with brackets and date", () => {
    const content = `# Changelog

## [2.0.0] - 2024-01-15

### Breaking Changes
- Removed deprecated API

### Features
- New plugin system

## [1.0.0] - 2023-06-01

- Initial release
`;
    const result = parseChangelogSections(content);
    expect(result.size).toBe(2);
    expect(result.has("2.0.0")).toBe(true);
    expect(result.has("1.0.0")).toBe(true);
    expect(result.get("2.0.0")).toContain("Removed deprecated API");
    expect(result.get("2.0.0")).toContain("New plugin system");
    expect(result.get("1.0.0")).toContain("Initial release");
  });

  it("parses heading without brackets", () => {
    const content = `## 1.5.0

- Bug fixes

## 1.4.0

- Performance improvements
`;
    const result = parseChangelogSections(content);
    expect(result.size).toBe(2);
    expect(result.has("1.5.0")).toBe(true);
    expect(result.has("1.4.0")).toBe(true);
    expect(result.get("1.5.0")).toContain("Bug fixes");
    expect(result.get("1.4.0")).toContain("Performance improvements");
  });

  it("strips v prefix from version numbers", () => {
    const content = `## v3.0.0

- Major update

## v2.0.0

- Previous major
`;
    const result = parseChangelogSections(content);
    expect(result.size).toBe(2);
    expect(result.has("3.0.0")).toBe(true);
    expect(result.has("2.0.0")).toBe(true);
    expect(result.get("3.0.0")).toContain("Major update");
  });

  it("handles brackets with v prefix", () => {
    const content = `## [v1.2.3] - 2024-03-01

- Some change
`;
    const result = parseChangelogSections(content);
    expect(result.size).toBe(1);
    expect(result.has("1.2.3")).toBe(true);
    expect(result.get("1.2.3")).toContain("Some change");
  });

  it("returns empty Map for non-changelog content", () => {
    const content = `# README

This is a project readme.

## Installation

Run npm install.

## Usage

Import the module.
`;
    const result = parseChangelogSections(content);
    expect(result.size).toBe(0);
  });

  it("returns empty Map for empty string", () => {
    const result = parseChangelogSections("");
    expect(result.size).toBe(0);
  });

  it("handles pre-release version numbers", () => {
    const content = `## [2.0.0-beta.1] - 2024-01-10

- Beta feature

## [1.0.0-rc.1] - 2023-12-01

- Release candidate
`;
    const result = parseChangelogSections(content);
    expect(result.size).toBe(2);
    expect(result.has("2.0.0-beta.1")).toBe(true);
    expect(result.has("1.0.0-rc.1")).toBe(true);
  });

  it("trims body whitespace", () => {
    const content = `## 1.0.0

- A change

`;
    const result = parseChangelogSections(content);
    const body = result.get("1.0.0")!;
    expect(body).not.toMatch(/^\n/);
    expect(body).not.toMatch(/\n$/);
  });
});

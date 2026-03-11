import { describe, it, expect } from "vitest";
import { parseAgpReleaseNotes } from "../release-notes-parser.js";

describe("parseAgpReleaseNotes", () => {
  it("parses version sections from data-text attributes", () => {
    const html = `
      <h3 id="fixed-issues-agp-8.5.2" data-text="Android Gradle plugin 8.5.2" tabindex="-1">Android Gradle plugin 8.5.2</h3>
      <p>Bug fixes for 8.5.2.</p>
      <h3 id="fixed-issues-agp-8.5.1" data-text="Android Gradle plugin 8.5.1" tabindex="-1">Android Gradle plugin 8.5.1</h3>
      <p>Bug fixes for 8.5.1.</p>
    `;
    const result = parseAgpReleaseNotes(html);
    expect(result.size).toBe(2);
    expect(result.has("8.5.2")).toBe(true);
    expect(result.has("8.5.1")).toBe(true);
    expect(result.get("8.5.2")).toContain("Bug fixes for 8.5.2");
    expect(result.get("8.5.1")).toContain("Bug fixes for 8.5.1");
  });

  it("handles pre-release versions (alpha, beta, rc)", () => {
    const html = `
      <h3 id="fixed-issues-agp-9.1.0-rc01" data-text="Android Gradle plugin 9.1.0-rc01" tabindex="-1">Android Gradle plugin 9.1.0-rc01</h3>
      <p>Release candidate fixes.</p>
    `;
    const result = parseAgpReleaseNotes(html);
    expect(result.size).toBe(1);
    expect(result.has("9.1.0-rc01")).toBe(true);
  });

  it("strips HTML tags from body", () => {
    const html = `
      <h3 id="fixed-issues-agp-8.5.0" data-text="Android Gradle plugin 8.5.0" tabindex="-1">Android Gradle plugin 8.5.0</h3>
      <p><b>Important:</b> New <code>dslOption</code> added.</p>
      <ul><li>Fixed build issue</li></ul>
    `;
    const result = parseAgpReleaseNotes(html);
    const body = result.get("8.5.0")!;
    expect(body).not.toContain("<p>");
    expect(body).not.toContain("<b>");
    expect(body).toContain("dslOption");
    expect(body).toContain("Fixed build issue");
  });

  it("ignores h3 headings without AGP data-text", () => {
    const html = `
      <h3 class="devsite-footer-linkbox-heading no-link">More Android</h3>
      <p>Footer content</p>
      <h3 id="fixed-issues-agp-8.5.0" data-text="Android Gradle plugin 8.5.0" tabindex="-1">Android Gradle plugin 8.5.0</h3>
      <p>Real release notes.</p>
    `;
    const result = parseAgpReleaseNotes(html);
    expect(result.size).toBe(1);
    expect(result.has("8.5.0")).toBe(true);
  });

  it("returns empty map for HTML with no AGP headings", () => {
    const html = `<h1>Some Page</h1><p>No versions here.</p>`;
    const result = parseAgpReleaseNotes(html);
    expect(result.size).toBe(0);
  });

  it("returns empty map for empty string", () => {
    expect(parseAgpReleaseNotes("").size).toBe(0);
  });

  it("stops section at next AGP heading", () => {
    const html = `
      <h3 id="fixed-issues-agp-8.5.2" data-text="Android Gradle plugin 8.5.2" tabindex="-1">Android Gradle plugin 8.5.2</h3>
      <p>Notes for 8.5.2</p>
      <h3 id="fixed-issues-agp-8.5.1" data-text="Android Gradle plugin 8.5.1" tabindex="-1">Android Gradle plugin 8.5.1</h3>
      <p>Notes for 8.5.1</p>
    `;
    const result = parseAgpReleaseNotes(html);
    expect(result.get("8.5.2")).not.toContain("Notes for 8.5.1");
    expect(result.get("8.5.1")).not.toContain("Notes for 8.5.2");
  });
});

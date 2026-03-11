import { describe, it, expect } from "vitest";
import { parseAndroidXReleaseNotes } from "../release-notes-parser.js";

describe("parseAndroidXReleaseNotes", () => {
  it("parses version sections from HTML", () => {
    const html = `
      <h3 id="1.2.0">Version 1.2.0</h3>
      <p>January 15, 2025</p>
      <p>Bug fixes and improvements.</p>
      <ul><li>Fixed crash on startup</li></ul>
      <h3 id="1.1.0">Version 1.1.0</h3>
      <p>December 01, 2024</p>
      <p>New features added.</p>
    `;
    const result = parseAndroidXReleaseNotes(html);
    expect(result.size).toBe(2);
    expect(result.has("1.2.0")).toBe(true);
    expect(result.has("1.1.0")).toBe(true);
    expect(result.get("1.2.0")).toContain("Bug fixes and improvements");
    expect(result.get("1.2.0")).toContain("Fixed crash on startup");
    expect(result.get("1.1.0")).toContain("New features added");
  });

  it("handles pre-release versions (alpha, beta, rc)", () => {
    const html = `
      <h3 id="1.0.0-alpha01">Version 1.0.0-alpha01</h3>
      <p>March 01, 2025</p>
      <p>First alpha release.</p>
    `;
    const result = parseAndroidXReleaseNotes(html);
    expect(result.size).toBe(1);
    expect(result.has("1.0.0-alpha01")).toBe(true);
    expect(result.get("1.0.0-alpha01")).toContain("First alpha release");
  });

  it("strips HTML tags from body, preserving text content", () => {
    const html = `
      <h3 id="2.0.0">Version 2.0.0</h3>
      <p><code>androidx.core:core:2.0.0</code> is released.</p>
      <p><b>New features</b></p>
      <ul>
        <li>Added <code>newApi()</code> method</li>
        <li>Improved performance</li>
      </ul>
    `;
    const result = parseAndroidXReleaseNotes(html);
    expect(result.has("2.0.0")).toBe(true);
    const body = result.get("2.0.0")!;
    expect(body).not.toContain("<p>");
    expect(body).not.toContain("<code>");
    expect(body).not.toContain("<ul>");
    expect(body).toContain("newApi()");
    expect(body).toContain("Improved performance");
  });

  it("returns empty map for HTML with no version headings", () => {
    const html = `<h1>Some Page</h1><p>No versions here.</p>`;
    const result = parseAndroidXReleaseNotes(html);
    expect(result.size).toBe(0);
  });

  it("returns empty map for empty string", () => {
    const result = parseAndroidXReleaseNotes("");
    expect(result.size).toBe(0);
  });

  it("handles h2 version headings too", () => {
    const html = `
      <h2 id="1.5.0">Version 1.5.0</h2>
      <p>Release notes content.</p>
    `;
    const result = parseAndroidXReleaseNotes(html);
    expect(result.size).toBe(1);
    expect(result.has("1.5.0")).toBe(true);
  });

  it("preserves h4 subheadings as content within a version section", () => {
    const html = `
      <h3 id="1.0.0">Version 1.0.0</h3>
      <h4>Bug Fixes</h4>
      <p>Fixed a crash.</p>
      <h4>New Features</h4>
      <p>Added new API.</p>
    `;
    const result = parseAndroidXReleaseNotes(html);
    expect(result.size).toBe(1);
    const body = result.get("1.0.0")!;
    expect(body).toContain("Bug Fixes");
    expect(body).toContain("Fixed a crash");
    expect(body).toContain("New Features");
    expect(body).toContain("Added new API");
  });

  it("stops section at next version heading", () => {
    const html = `
      <h3 id="2.0.0">Version 2.0.0</h3>
      <p>Second version notes.</p>
      <h3 id="1.0.0">Version 1.0.0</h3>
      <p>First version notes.</p>
    `;
    const result = parseAndroidXReleaseNotes(html);
    expect(result.get("2.0.0")).not.toContain("First version notes");
    expect(result.get("1.0.0")).not.toContain("Second version notes");
  });
});

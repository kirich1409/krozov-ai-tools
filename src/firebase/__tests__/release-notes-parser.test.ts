import { describe, it, expect } from "vitest";
import { parseFirebaseReleaseNotes } from "../release-notes-parser.js";

describe("parseFirebaseReleaseNotes", () => {
  it("parses version sections matching the given slug", () => {
    const html = `
      <h3 id="firestore_v26-1-1" data-text="Cloud Firestore version 26.1.1">
        <span class="notranslate">Cloud Firestore</span> version 26.1.1</h3>
      <p>Bug fixes for Firestore.</p>
      <h3 id="firestore_v26-1-0" data-text="Cloud Firestore version 26.1.0">
        <span class="notranslate">Cloud Firestore</span> version 26.1.0</h3>
      <p>New features for Firestore.</p>
    `;
    const result = parseFirebaseReleaseNotes(html, "firestore");
    expect(result.size).toBe(2);
    expect(result.has("26.1.1")).toBe(true);
    expect(result.has("26.1.0")).toBe(true);
    expect(result.get("26.1.1")).toContain("Bug fixes for Firestore");
    expect(result.get("26.1.0")).toContain("New features for Firestore");
  });

  it("filters out headings for other slugs", () => {
    const html = `
      <h3 id="firestore_v26-1-1" data-text="Cloud Firestore version 26.1.1">Cloud Firestore version 26.1.1</h3>
      <p>Firestore notes.</p>
      <h3 id="analytics_v22-1-0" data-text="Analytics version 22.1.0">Analytics version 22.1.0</h3>
      <p>Analytics notes.</p>
    `;
    const result = parseFirebaseReleaseNotes(html, "firestore");
    expect(result.size).toBe(1);
    expect(result.has("26.1.1")).toBe(true);
  });

  it("handles pre-release versions (beta, rc)", () => {
    const html = `
      <h4 id="ai-ondevice_v16-0-0-beta01" data-text="Firebase AI Logic On-Device version 16.0.0-beta01">
        Firebase AI Logic On-Device version 16.0.0-beta01</h4>
      <p>First beta release.</p>
    `;
    const result = parseFirebaseReleaseNotes(html, "ai-ondevice");
    expect(result.size).toBe(1);
    expect(result.has("16.0.0-beta01")).toBe(true);
  });

  it("handles h4 headings", () => {
    const html = `
      <h4 id="appcheck-debug_v19-0-2" data-text="App Check Debug version 19.0.2">
        App Check Debug version 19.0.2</h4>
      <p>Debug provider update.</p>
    `;
    const result = parseFirebaseReleaseNotes(html, "appcheck-debug");
    expect(result.size).toBe(1);
    expect(result.has("19.0.2")).toBe(true);
  });

  it("strips HTML tags from body", () => {
    const html = `
      <h3 id="auth_v23-1-0" data-text="Auth version 23.1.0">Auth version 23.1.0</h3>
      <p><b>New:</b> Added <code>signInAnonymously()</code> support.</p>
      <ul><li>Bug fix for token refresh</li></ul>
    `;
    const result = parseFirebaseReleaseNotes(html, "auth");
    const body = result.get("23.1.0")!;
    expect(body).not.toContain("<p>");
    expect(body).not.toContain("<b>");
    expect(body).toContain("signInAnonymously()");
    expect(body).toContain("Bug fix for token refresh");
  });

  it("returns empty map when slug has no matches", () => {
    const html = `
      <h3 id="firestore_v26-1-1" data-text="Cloud Firestore version 26.1.1">Cloud Firestore version 26.1.1</h3>
      <p>Notes.</p>
    `;
    const result = parseFirebaseReleaseNotes(html, "nonexistent");
    expect(result.size).toBe(0);
  });

  it("returns empty map for empty HTML", () => {
    expect(parseFirebaseReleaseNotes("", "firestore").size).toBe(0);
  });

  it("handles content between matching and non-matching headings", () => {
    const html = `
      <h3 id="crashlytics_v20-0-4" data-text="Crashlytics version 20.0.4">Crashlytics version 20.0.4</h3>
      <p>Crashlytics notes.</p>
      <h3 id="crashlytics-ndk_v20-0-4" data-text="Crashlytics NDK version 20.0.4">Crashlytics NDK version 20.0.4</h3>
      <p>NDK notes.</p>
      <h3 id="data-connect_v17-1-3" data-text="Data Connect version 17.1.3">Data Connect version 17.1.3</h3>
      <p>Data Connect notes.</p>
    `;
    const crashlytics = parseFirebaseReleaseNotes(html, "crashlytics");
    expect(crashlytics.size).toBe(1);
    expect(crashlytics.get("20.0.4")).toContain("Crashlytics notes");
    expect(crashlytics.get("20.0.4")).not.toContain("NDK notes");

    const ndk = parseFirebaseReleaseNotes(html, "crashlytics-ndk");
    expect(ndk.size).toBe(1);
    expect(ndk.get("20.0.4")).toContain("NDK notes");
    expect(ndk.get("20.0.4")).not.toContain("Data Connect notes");
  });
});

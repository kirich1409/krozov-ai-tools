import { describe, it, expect, vi, beforeEach } from "vitest";
import { FirebaseChangelogProvider } from "../firebase-provider.js";

vi.mock("node:fs/promises");

const FIREBASE_HTML = `
  <h2 id="2026-02-26">Update - February 26, 2026</h2>
  <h3 id="firestore_v26-1-1" data-text="Cloud Firestore version 26.1.1">Cloud Firestore version 26.1.1</h3>
  <p>Bug fixes for Firestore.</p>
  <h3 id="auth_v23-1-0" data-text="Auth version 23.1.0">Auth version 23.1.0</h3>
  <p>Auth improvements.</p>
  <h2 id="2026-01-15">Update - January 15, 2026</h2>
  <h3 id="firestore_v26-1-0" data-text="Cloud Firestore version 26.1.0">Cloud Firestore version 26.1.0</h3>
  <p>New Firestore features.</p>
`;

describe("FirebaseChangelogProvider", () => {
  let provider: FirebaseChangelogProvider;

  beforeEach(() => {
    provider = new FirebaseChangelogProvider();
    vi.restoreAllMocks();
  });

  it("canHandle returns true for com.google.firebase", () => {
    expect(provider.canHandle("com.google.firebase")).toBe(true);
  });

  it("canHandle returns false for other groupIds", () => {
    expect(provider.canHandle("androidx.core")).toBe(false);
    expect(provider.canHandle("com.google.android.gms")).toBe(false);
  });

  it("fetches and parses Firebase release notes for firestore", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(FIREBASE_HTML, { status: 200 }),
    );

    const result = await provider.fetchChangelog(
      "com.google.firebase", "firebase-firestore", "26.1.1", [],
    );

    expect(result).not.toBeNull();
    expect(result!.entries.size).toBe(2);
    expect(result!.entries.has("26.1.1")).toBe(true);
    expect(result!.entries.has("26.1.0")).toBe(true);
    expect(result!.entries.get("26.1.1")!.body).toContain("Bug fixes for Firestore");
    expect(result!.entries.get("26.1.1")!.releaseUrl).toContain("#firestore_v26-1-1");
    expect(result!.repositoryUrl).toContain("release-notes/android");
  });

  it("returns null when slug has no matches", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(FIREBASE_HTML, { status: 200 }),
    );

    const result = await provider.fetchChangelog(
      "com.google.firebase", "firebase-nonexistent", "1.0.0", [],
    );
    expect(result).toBeNull();
  });

  it("returns null on fetch failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("", { status: 500 }),
    );
    const result = await provider.fetchChangelog(
      "com.google.firebase", "firebase-firestore", "26.1.1", [],
    );
    expect(result).toBeNull();
  });

  it("returns null on network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Network error"));
    const result = await provider.fetchChangelog(
      "com.google.firebase", "firebase-firestore", "26.1.1", [],
    );
    expect(result).toBeNull();
  });
});

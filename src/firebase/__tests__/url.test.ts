import { describe, it, expect } from "vitest";
import { isFirebaseArtifact, getFirebaseSlug, getFirebaseReleasesUrl, getFirebaseVersionUrl } from "../url.js";

describe("isFirebaseArtifact", () => {
  it("returns true for com.google.firebase", () => {
    expect(isFirebaseArtifact("com.google.firebase")).toBe(true);
  });

  it("returns false for com.google.android.gms", () => {
    expect(isFirebaseArtifact("com.google.android.gms")).toBe(false);
  });

  it("returns false for androidx.core", () => {
    expect(isFirebaseArtifact("androidx.core")).toBe(false);
  });
});

describe("getFirebaseSlug", () => {
  it("strips firebase- prefix from firebase-firestore", () => {
    expect(getFirebaseSlug("firebase-firestore")).toBe("firestore");
  });

  it("strips firebase- prefix from firebase-analytics", () => {
    expect(getFirebaseSlug("firebase-analytics")).toBe("analytics");
  });

  it("strips firebase- prefix from firebase-crashlytics-ndk", () => {
    expect(getFirebaseSlug("firebase-crashlytics-ndk")).toBe("crashlytics-ndk");
  });

  it("returns artifactId as-is when no firebase- prefix", () => {
    expect(getFirebaseSlug("firebase-bom")).toBe("bom");
  });
});

describe("getFirebaseReleasesUrl", () => {
  it("returns the Firebase Android release notes URL", () => {
    expect(getFirebaseReleasesUrl()).toBe(
      "https://firebase.google.com/support/release-notes/android",
    );
  });
});

describe("getFirebaseVersionUrl", () => {
  it("builds anchor URL for firestore 26.1.1", () => {
    expect(getFirebaseVersionUrl("firebase-firestore", "26.1.1")).toBe(
      "https://firebase.google.com/support/release-notes/android#firestore_v26-1-1",
    );
  });

  it("builds anchor URL for crashlytics-ndk 20.0.4", () => {
    expect(getFirebaseVersionUrl("firebase-crashlytics-ndk", "20.0.4")).toBe(
      "https://firebase.google.com/support/release-notes/android#crashlytics-ndk_v20-0-4",
    );
  });

  it("builds anchor URL for pre-release version", () => {
    expect(getFirebaseVersionUrl("firebase-ai", "16.0.0-beta01")).toBe(
      "https://firebase.google.com/support/release-notes/android#ai_v16-0-0-beta01",
    );
  });
});

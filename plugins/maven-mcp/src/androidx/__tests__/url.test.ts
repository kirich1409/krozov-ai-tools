import { describe, it, expect } from "vitest";
import { isAndroidXArtifact, getAndroidXReleasesUrl, getAndroidXVersionUrl } from "../url.js";

describe("isAndroidXArtifact", () => {
  it("returns true for androidx.core", () => {
    expect(isAndroidXArtifact("androidx.core")).toBe(true);
  });

  it("returns true for androidx.compose.material3", () => {
    expect(isAndroidXArtifact("androidx.compose.material3")).toBe(true);
  });

  it("returns false for io.ktor", () => {
    expect(isAndroidXArtifact("io.ktor")).toBe(false);
  });

  it("returns false for com.google.android.material", () => {
    expect(isAndroidXArtifact("com.google.android.material")).toBe(false);
  });
});

describe("getAndroidXReleasesUrl", () => {
  it("maps androidx.core to /releases/core", () => {
    expect(getAndroidXReleasesUrl("androidx.core")).toBe(
      "https://developer.android.com/jetpack/androidx/releases/core",
    );
  });

  it("maps androidx.compose.material3 to /releases/compose-material3", () => {
    expect(getAndroidXReleasesUrl("androidx.compose.material3")).toBe(
      "https://developer.android.com/jetpack/androidx/releases/compose-material3",
    );
  });

  it("maps androidx.compose.ui to /releases/compose-ui", () => {
    expect(getAndroidXReleasesUrl("androidx.compose.ui")).toBe(
      "https://developer.android.com/jetpack/androidx/releases/compose-ui",
    );
  });

  it("maps androidx.lifecycle to /releases/lifecycle", () => {
    expect(getAndroidXReleasesUrl("androidx.lifecycle")).toBe(
      "https://developer.android.com/jetpack/androidx/releases/lifecycle",
    );
  });
});

describe("getAndroidXVersionUrl", () => {
  it("appends version anchor", () => {
    expect(getAndroidXVersionUrl("androidx.core", "1.17.0")).toBe(
      "https://developer.android.com/jetpack/androidx/releases/core#1.17.0",
    );
  });
});

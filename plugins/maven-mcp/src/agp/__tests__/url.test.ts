import { describe, it, expect } from "vitest";
import { isAgpArtifact, getAgpReleasesUrl, getAgpVersionUrl } from "../url.js";

describe("isAgpArtifact", () => {
  it("returns true for com.android.tools.build", () => {
    expect(isAgpArtifact("com.android.tools.build")).toBe(true);
  });

  it("returns false for androidx.core", () => {
    expect(isAgpArtifact("androidx.core")).toBe(false);
  });

  it("returns false for com.android.tools", () => {
    expect(isAgpArtifact("com.android.tools")).toBe(false);
  });
});

describe("getAgpReleasesUrl", () => {
  it("builds URL for version 8.5.1", () => {
    expect(getAgpReleasesUrl("8.5.1")).toBe(
      "https://developer.android.com/build/releases/agp-8-5-0-release-notes",
    );
  });

  it("builds URL for version 9.1.0-alpha03", () => {
    expect(getAgpReleasesUrl("9.1.0-alpha03")).toBe(
      "https://developer.android.com/build/releases/agp-9-1-0-release-notes",
    );
  });

  it("builds URL for version 8.5.0", () => {
    expect(getAgpReleasesUrl("8.5.0")).toBe(
      "https://developer.android.com/build/releases/agp-8-5-0-release-notes",
    );
  });
});

describe("getAgpVersionUrl", () => {
  it("appends version anchor for 8.5.2", () => {
    expect(getAgpVersionUrl("8.5.2")).toBe(
      "https://developer.android.com/build/releases/agp-8-5-0-release-notes#fixed-issues-agp-8.5.2",
    );
  });

  it("appends version anchor for 9.1.0-rc01", () => {
    expect(getAgpVersionUrl("9.1.0-rc01")).toBe(
      "https://developer.android.com/build/releases/agp-9-1-0-release-notes#fixed-issues-agp-9.1.0-rc01",
    );
  });
});

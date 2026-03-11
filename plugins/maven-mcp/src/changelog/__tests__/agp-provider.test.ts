import { describe, it, expect, vi, beforeEach } from "vitest";
import { AgpChangelogProvider } from "../agp-provider.js";

vi.mock("node:fs/promises");

const AGP_HTML = `
  <h3 id="fixed-issues-agp-8.5.2" data-text="Android Gradle plugin 8.5.2" tabindex="-1">Android Gradle plugin 8.5.2</h3>
  <p>Fixed critical build issue.</p>
  <h3 id="fixed-issues-agp-8.5.1" data-text="Android Gradle plugin 8.5.1" tabindex="-1">Android Gradle plugin 8.5.1</h3>
  <p>Minor improvements.</p>
  <h3 id="fixed-issues-agp-8.5.0" data-text="Android Gradle plugin 8.5.0" tabindex="-1">Android Gradle plugin 8.5.0</h3>
  <p>Initial release.</p>
`;

describe("AgpChangelogProvider", () => {
  let provider: AgpChangelogProvider;

  beforeEach(() => {
    provider = new AgpChangelogProvider();
    vi.restoreAllMocks();
  });

  it("canHandle returns true for com.android.tools.build", () => {
    expect(provider.canHandle("com.android.tools.build")).toBe(true);
  });

  it("canHandle returns false for other groupIds", () => {
    expect(provider.canHandle("androidx.core")).toBe(false);
    expect(provider.canHandle("com.android.tools")).toBe(false);
  });

  it("fetches and parses AGP release notes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(AGP_HTML, { status: 200 }),
    );

    const result = await provider.fetchChangelog(
      "com.android.tools.build", "gradle", "8.5.1", [],
    );

    expect(result).not.toBeNull();
    expect(result!.entries.size).toBe(3);
    expect(result!.entries.has("8.5.2")).toBe(true);
    expect(result!.entries.has("8.5.1")).toBe(true);
    expect(result!.entries.has("8.5.0")).toBe(true);
    expect(result!.entries.get("8.5.2")!.body).toContain("Fixed critical build issue");
    expect(result!.entries.get("8.5.2")!.releaseUrl).toContain("#fixed-issues-agp-8.5.2");
    expect(result!.repositoryUrl).toContain("agp-8-5-0-release-notes");
  });

  it("returns null on fetch failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("", { status: 500 }),
    );
    const result = await provider.fetchChangelog(
      "com.android.tools.build", "gradle", "8.5.0", [],
    );
    expect(result).toBeNull();
  });

  it("returns null on 404 (cached as empty)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Not found", { status: 404 }),
    );
    const result = await provider.fetchChangelog(
      "com.android.tools.build", "gradle", "99.0.0", [],
    );
    expect(result).toBeNull();
  });

  it("returns null on network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Network error"));
    const result = await provider.fetchChangelog(
      "com.android.tools.build", "gradle", "8.5.0", [],
    );
    expect(result).toBeNull();
  });
});

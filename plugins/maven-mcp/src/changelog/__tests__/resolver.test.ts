import { describe, it, expect, vi } from "vitest";
import { resolveChangelog } from "../resolver.js";
import type { ChangelogProvider, ChangelogResult } from "../types.js";

function mockProvider(
  handles: boolean,
  result: ChangelogResult | null,
): ChangelogProvider {
  return {
    canHandle: vi.fn().mockReturnValue(handles),
    fetchChangelog: vi.fn().mockResolvedValue(result),
  };
}

describe("resolveChangelog", () => {
  it("returns result from first matching provider", async () => {
    const expected: ChangelogResult = {
      repositoryUrl: "https://example.com",
      entries: new Map([["1.0.0", { body: "Notes" }]]),
    };
    const p1 = mockProvider(true, expected);
    const p2 = mockProvider(true, { repositoryUrl: "other", entries: new Map() });

    const result = await resolveChangelog([p1, p2], [], "g", "a", "1.0.0");
    expect(result).toBe(expected);
    expect(p2.fetchChangelog).not.toHaveBeenCalled();
  });

  it("skips providers that cannot handle the artifact", async () => {
    const p1 = mockProvider(false, null);
    const expected: ChangelogResult = {
      repositoryUrl: "https://example.com",
      entries: new Map([["1.0.0", { body: "Notes" }]]),
    };
    const p2 = mockProvider(true, expected);

    const result = await resolveChangelog([p1, p2], [], "g", "a", "1.0.0");
    expect(result).toBe(expected);
    expect(p1.fetchChangelog).not.toHaveBeenCalled();
  });

  it("falls through to next provider when first returns null", async () => {
    const p1 = mockProvider(true, null);
    const expected: ChangelogResult = {
      repositoryUrl: "https://example.com",
      entries: new Map([["1.0.0", { body: "Notes" }]]),
    };
    const p2 = mockProvider(true, expected);

    const result = await resolveChangelog([p1, p2], [], "g", "a", "1.0.0");
    expect(result).toBe(expected);
  });

  it("returns null when no providers match", async () => {
    const p1 = mockProvider(false, null);

    const result = await resolveChangelog([p1], [], "g", "a", "1.0.0");
    expect(result).toBeNull();
  });

  it("returns null when all providers return null", async () => {
    const p1 = mockProvider(true, null);
    const p2 = mockProvider(true, null);

    const result = await resolveChangelog([p1, p2], [], "g", "a", "1.0.0");
    expect(result).toBeNull();
  });

  it("returns null for empty providers list", async () => {
    const result = await resolveChangelog([], [], "g", "a", "1.0.0");
    expect(result).toBeNull();
  });
});

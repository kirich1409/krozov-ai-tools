import { describe, it, expect } from "vitest";
import { getUpgradeType, compareVersions } from "../compare.js";

describe("getUpgradeType", () => {
  it("detects major upgrade", () => {
    expect(getUpgradeType("1.0.0", "2.0.0")).toBe("major");
  });

  it("detects minor upgrade", () => {
    expect(getUpgradeType("1.0.0", "1.1.0")).toBe("minor");
  });

  it("detects patch upgrade", () => {
    expect(getUpgradeType("1.0.0", "1.0.1")).toBe("patch");
  });

  it("detects no upgrade", () => {
    expect(getUpgradeType("1.0.0", "1.0.0")).toBe("none");
  });

  it("returns none for downgrades", () => {
    expect(getUpgradeType("2.0.0", "1.5.0")).toBe("none");
    expect(getUpgradeType("1.5.0", "1.3.9")).toBe("none");
  });

  it("handles two-segment versions", () => {
    expect(getUpgradeType("1.0", "2.0")).toBe("major");
    expect(getUpgradeType("1.0", "1.1")).toBe("minor");
  });

  it("classifies pre-release → stable as patch", () => {
    expect(getUpgradeType("2.0.0-beta-1", "2.0.0")).toBe("patch");
    expect(getUpgradeType("2.0.0-rc-1", "2.0.0")).toBe("patch");
  });

  it("classifies pre-release → higher pre-release as patch", () => {
    expect(getUpgradeType("2.0.0-beta-1", "2.0.0-beta-2")).toBe("patch");
    expect(getUpgradeType("2.0.0-beta-1", "2.0.0-rc-1")).toBe("patch");
    expect(getUpgradeType("2.0.0-alpha", "2.0.0-beta")).toBe("patch");
  });

  it("returns none for stable → pre-release of same core (downgrade)", () => {
    expect(getUpgradeType("2.0.0", "2.0.0-beta-1")).toBe("none");
    expect(getUpgradeType("2.0.0-rc-1", "2.0.0-beta-1")).toBe("none");
  });

  it("still classifies core-level upgrades across pre-release suffixes", () => {
    expect(getUpgradeType("1.9.0", "2.0.0-beta-1")).toBe("major");
    expect(getUpgradeType("1.3.2-1.4.0-rc", "1.3.2")).toBe("patch");
  });
});

describe("compareVersions", () => {
  it("compares numeric cores", () => {
    expect(compareVersions("1.0.0", "2.0.0")).toBeLessThan(0);
    expect(compareVersions("2.0.0", "1.9.9")).toBeGreaterThan(0);
    expect(compareVersions("1.0.0", "1.0.0")).toBe(0);
  });

  it("orders stable above pre-release of same core", () => {
    expect(compareVersions("2.0.0-beta-1", "2.0.0")).toBeLessThan(0);
    expect(compareVersions("2.0.0-rc-1", "2.0.0")).toBeLessThan(0);
  });

  it("orders pre-release tiers: snapshot < alpha < beta < milestone < rc < stable", () => {
    const chain = [
      "1.0.0-SNAPSHOT",
      "1.0.0-alpha",
      "1.0.0-beta",
      "1.0.0-M1",
      "1.0.0-rc-1",
      "1.0.0",
    ];
    for (let i = 0; i < chain.length - 1; i++) {
      expect(compareVersions(chain[i], chain[i + 1])).toBeLessThan(0);
    }
  });

  it("orders pre-releases of the same tier by numeric suffix", () => {
    expect(compareVersions("2.0.0-beta-1", "2.0.0-beta-2")).toBeLessThan(0);
    expect(compareVersions("2.0.0-alpha-10", "2.0.0-alpha-2")).toBeGreaterThan(0);
  });

  it("is suitable for Array.sort", () => {
    const sorted = ["3.0.0", "1.0.0", "2.0.0-beta-1", "2.0.0"].sort(compareVersions);
    expect(sorted).toEqual(["1.0.0", "2.0.0-beta-1", "2.0.0", "3.0.0"]);
  });
});

import { describe, it, expect } from "vitest";
import { getUpgradeType } from "../compare.js";

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
});

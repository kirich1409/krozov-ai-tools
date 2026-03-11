import { describe, it, expect } from "vitest";
import { classifyVersion, findLatestVersionForCurrent } from "../classify.js";

describe("classifyVersion", () => {
  it("classifies stable versions", () => {
    expect(classifyVersion("3.5.11")).toBe("stable");
    expect(classifyVersion("1.0")).toBe("stable");
    expect(classifyVersion("2.0.0")).toBe("stable");
  });

  it("classifies snapshot versions", () => {
    expect(classifyVersion("1.0-SNAPSHOT")).toBe("snapshot");
    expect(classifyVersion("2.0.0-SNAPSHOT")).toBe("snapshot");
  });

  it("classifies alpha versions", () => {
    expect(classifyVersion("1.0-alpha-1")).toBe("alpha");
    expect(classifyVersion("1.0.0-alpha1")).toBe("alpha");
    expect(classifyVersion("1.0-a1")).toBe("alpha");
  });

  it("classifies beta versions", () => {
    expect(classifyVersion("1.0-beta-1")).toBe("beta");
    expect(classifyVersion("1.0.0-beta1")).toBe("beta");
    expect(classifyVersion("1.0-b1")).toBe("beta");
  });

  it("classifies RC versions", () => {
    expect(classifyVersion("1.0-RC1")).toBe("rc");
    expect(classifyVersion("1.0-rc-2")).toBe("rc");
    expect(classifyVersion("1.0-CR1")).toBe("rc");
  });

  it("does not false-positive on short-form patterns", () => {
    expect(classifyVersion("1.0-bar")).toBe("stable");
    expect(classifyVersion("1.0-ace")).toBe("stable");
  });

  it("classifies milestone versions", () => {
    expect(classifyVersion("1.0-M1")).toBe("milestone");
    expect(classifyVersion("1.0-milestone-2")).toBe("milestone");
  });
});

describe("findLatestVersionForCurrent", () => {
  const versions = ["1.0.0", "2.0.0-alpha1", "2.0.0-beta1", "2.0.0-RC1", "2.0.0"];

  it("returns only stable when current is stable", () => {
    expect(findLatestVersionForCurrent(versions, "1.0.0")).toBe("2.0.0");
  });

  it("returns RC or stable when current is RC", () => {
    expect(findLatestVersionForCurrent(versions, "1.0.0-RC1")).toBe("2.0.0");
    // When latest stable is 1.0.0 and there's a newer RC
    const v = ["1.0.0", "1.1.0-RC1"];
    expect(findLatestVersionForCurrent(v, "1.0.0-RC2")).toBe("1.1.0-RC1");
  });

  it("returns beta or higher when current is beta", () => {
    expect(findLatestVersionForCurrent(versions, "1.0.0-beta1")).toBe("2.0.0");
    const v = ["1.0.0", "2.0.0-alpha1", "2.0.0-beta2"];
    expect(findLatestVersionForCurrent(v, "1.0.0-beta1")).toBe("2.0.0-beta2");
  });

  it("returns alpha or higher when current is alpha", () => {
    expect(findLatestVersionForCurrent(versions, "1.0.0-alpha1")).toBe("2.0.0");
    const v = ["1.0.0-alpha1", "1.0.0-alpha2"];
    expect(findLatestVersionForCurrent(v, "1.0.0-alpha1")).toBe("1.0.0-alpha2");
  });

  it("skips less stable versions", () => {
    const v = ["1.0.0", "2.0.0-alpha1", "2.0.0-beta1"];
    // Current is beta — should skip alpha, return beta
    expect(findLatestVersionForCurrent(v, "1.0.0-beta1")).toBe("2.0.0-beta1");
  });

  it("returns undefined when no matching version exists", () => {
    const v = ["1.0.0-SNAPSHOT"];
    expect(findLatestVersionForCurrent(v, "1.0.0")).toBeUndefined();
  });
});

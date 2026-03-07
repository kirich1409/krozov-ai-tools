import { describe, it, expect } from "vitest";
import { classifyVersion } from "../classify.js";

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

  it("classifies milestone versions", () => {
    expect(classifyVersion("1.0-M1")).toBe("milestone");
    expect(classifyVersion("1.0-milestone-2")).toBe("milestone");
  });
});

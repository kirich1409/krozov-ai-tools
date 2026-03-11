import { describe, expect, it } from "vitest";
import { filterVersionRange } from "../range.js";

describe("filterVersionRange", () => {
  const versions = ["1.0.0", "1.1.0", "1.2.0", "1.3.0", "2.0.0-beta1", "2.0.0"];

  it("returns versions between from (exclusive) and to (inclusive)", () => {
    expect(filterVersionRange(versions, "1.0.0", "1.3.0")).toEqual([
      "1.1.0",
      "1.2.0",
      "1.3.0",
    ]);
  });

  it("includes pre-release versions in range", () => {
    expect(filterVersionRange(versions, "1.2.0", "2.0.0")).toEqual([
      "1.3.0",
      "2.0.0-beta1",
      "2.0.0",
    ]);
  });

  it("returns empty array when from and to are the same", () => {
    expect(filterVersionRange(versions, "1.0.0", "1.0.0")).toEqual([]);
  });

  it("returns empty array when fromVersion is not found", () => {
    expect(filterVersionRange(versions, "0.9.0", "1.3.0")).toEqual([]);
  });

  it("returns empty array when toVersion is not found", () => {
    expect(filterVersionRange(versions, "1.0.0", "9.9.9")).toEqual([]);
  });
});

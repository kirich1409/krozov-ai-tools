import { describe, it, expect } from "vitest";
import { parseSettingsGradleModules } from "../settings-gradle-parser.js";

describe("parseSettingsGradleModules", () => {
  it("parses Kotlin DSL include(\":app\", \":lib:core\")", () => {
    const content = `
rootProject.name = "demo"
include(":app", ":lib:core")
`;
    expect(parseSettingsGradleModules(content)).toEqual([":app", ":lib:core"]);
  });

  it("parses Groovy include ':app', ':lib'", () => {
    const content = `
rootProject.name = 'demo'
include ':app', ':lib'
`;
    expect(parseSettingsGradleModules(content)).toEqual([":app", ":lib"]);
  });

  it("returns empty array when no include() calls", () => {
    expect(parseSettingsGradleModules(`rootProject.name = "demo"`)).toEqual([]);
  });

  it("deduplicates repeated module paths", () => {
    const content = `
include(":app")
include(":app", ":lib")
`;
    expect(parseSettingsGradleModules(content)).toEqual([":app", ":lib"]);
  });

  it("handles single-quoted Kotlin-style and mixed include calls", () => {
    const content = `
include(':app')
include ":lib:core", ":feature:auth"
`;
    expect(parseSettingsGradleModules(content)).toEqual([":app", ":lib:core", ":feature:auth"]);
  });

  it("ignores commented-out include calls", () => {
    const content = `
// include(":legacy")
/* include(":blocked") */
include(":app")
`;
    expect(parseSettingsGradleModules(content)).toEqual([":app"]);
  });
});

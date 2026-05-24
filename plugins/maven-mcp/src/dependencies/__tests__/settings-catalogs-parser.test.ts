import { describe, it, expect } from "vitest";
import { parseSettingsCatalogs } from "../settings-catalogs-parser.js";

describe("parseSettingsCatalogs", () => {
  it("returns default libs descriptor when versionCatalogs block absent", () => {
    const content = `
rootProject.name = "demo"
include(":app")
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "libs", tomlPath: "gradle/libs.versions.toml" },
    ]);
  });

  it("returns empty when versionCatalogs block is empty", () => {
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([]);
  });

  it("parses Kotlin DSL versionCatalogs with create block", () => {
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    create("testLibs") {
      from(files("gradle/test.versions.toml"))
    }
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("parses Groovy DSL equivalent", () => {
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    create('testLibs') {
      from files('gradle/test.versions.toml')
    }
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("parses multiple create() blocks", () => {
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    create("libs") {
      from(files("gradle/libs.versions.toml"))
    }
    create("testLibs") {
      from(files("gradle/test.versions.toml"))
    }
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "libs", tomlPath: "gradle/libs.versions.toml" },
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("parses chained create(\"x\").from(files(\"...\"))", () => {
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    create("testLibs").from(files("gradle/test.versions.toml"))
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("parses multi-line create block", () => {
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    create("testLibs") {
      from(
        files("gradle/test.versions.toml")
      )
    }
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("ignores commented blocks", () => {
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    // create("commented") { from(files("gradle/commented.versions.toml")) }
    /* create("blocked") { from(files("gradle/blocked.versions.toml")) } */
    create("testLibs") {
      from(files("gradle/test.versions.toml"))
    }
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("ignores from(\"g:a:v\") form (out of scope)", () => {
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    create("published") {
      from("com.example:catalog:1.0")
    }
    create("local") {
      from(files("gradle/libs.versions.toml"))
    }
  }
}
`;
    // "published" uses from("g:a:v") — not emitted
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "local", tomlPath: "gradle/libs.versions.toml" },
    ]);
  });
});

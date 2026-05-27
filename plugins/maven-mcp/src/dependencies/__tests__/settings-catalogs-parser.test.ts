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

  it("returns default libs descriptor when versionCatalogs block is empty", () => {
    // Empty versionCatalogs {} block — implicit libs catalog still active in Gradle
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "libs", tomlPath: "gradle/libs.versions.toml" },
    ]);
  });

  it("parses Kotlin DSL versionCatalogs with create block — prepends implicit libs", () => {
    // Gradle auto-configures libs from gradle/libs.versions.toml; testLibs is ADDITIONAL
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
      { name: "libs", tomlPath: "gradle/libs.versions.toml" },
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("parses Groovy DSL equivalent — prepends implicit libs", () => {
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
      { name: "libs", tomlPath: "gradle/libs.versions.toml" },
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("parses multiple create() blocks — no duplicate libs when explicit create(\"libs\") present", () => {
    // Explicit create("libs") with a custom path overrides the implicit default
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

  it("parses chained create(\"x\").from(files(\"...\")) — prepends implicit libs", () => {
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    create("testLibs").from(files("gradle/test.versions.toml"))
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "libs", tomlPath: "gradle/libs.versions.toml" },
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("parses multi-line create block — prepends implicit libs", () => {
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
      { name: "libs", tomlPath: "gradle/libs.versions.toml" },
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("ignores commented blocks — active catalog still gets implicit libs prepended", () => {
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
      { name: "libs", tomlPath: "gradle/libs.versions.toml" },
      { name: "testLibs", tomlPath: "gradle/test.versions.toml" },
    ]);
  });

  it("ignores from(\"g:a:v\") form (out of scope) — implicit libs still present", () => {
    // "published" uses from("g:a:v") — not emitted; "local" uses files(); implicit libs prepended
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    create("published") {
      from("com.example:catalog:1.0")
    }
    create("local") {
      from(files("gradle/local.versions.toml"))
    }
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "libs", tomlPath: "gradle/libs.versions.toml" },
      { name: "local", tomlPath: "gradle/local.versions.toml" },
    ]);
  });

  it("explicit create(\"libs\") with a different path overrides the implicit default", () => {
    // Only the explicit path is returned; no duplicate libs entry
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    create("libs") {
      from(files("other.toml"))
    }
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "libs", tomlPath: "other.toml" },
    ]);
  });

  it("versionCatalogs with create(\"testLibs\") → both implicit libs and explicit testLibs", () => {
    const content = `
dependencyResolutionManagement {
  versionCatalogs {
    create("testLibs") {
      from(files("gradle/test-libs.versions.toml"))
    }
  }
}
`;
    expect(parseSettingsCatalogs(content)).toEqual([
      { name: "libs", tomlPath: "gradle/libs.versions.toml" },
      { name: "testLibs", tomlPath: "gradle/test-libs.versions.toml" },
    ]);
  });
});

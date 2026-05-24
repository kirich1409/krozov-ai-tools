import { describe, it, expect } from "vitest";
import { parsePluginsBlock, parseBuildscriptClasspath } from "../plugins-block-parser.js";

describe("parsePluginsBlock", () => {
  it("parses id(\"x\") version \"1.0\"", () => {
    const content = `
plugins {
  id("com.android.application") version "8.5.0"
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "com.android.application", version: "8.5.0" },
    ]);
  });

  it("parses Groovy form id 'x' version '1.0'", () => {
    const content = `
plugins {
  id 'com.android.application' version '8.5.0'
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "com.android.application", version: "8.5.0" },
    ]);
  });

  it("parses id without version", () => {
    const content = `
plugins {
  id("com.android.application")
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "com.android.application", version: null },
    ]);
  });

  it("parses kotlin(\"jvm\") version \"2.0\" → org.jetbrains.kotlin.jvm", () => {
    const content = `
plugins {
  kotlin("jvm") version "2.0.0"
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "org.jetbrains.kotlin.jvm", version: "2.0.0" },
    ]);
  });

  it("parses kotlin(\"plugin.serialization\") → full id", () => {
    const content = `
plugins {
  kotlin("plugin.serialization") version "2.1.0"
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "org.jetbrains.kotlin.plugin.serialization", version: "2.1.0" },
    ]);
  });

  it("parses unknown kotlin(\"foo\") → org.jetbrains.kotlin.foo", () => {
    const content = `
plugins {
  kotlin("foo") version "1.0"
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "org.jetbrains.kotlin.foo", version: "1.0" },
    ]);
  });

  it("returns catalogRef for alias(libs.plugins.foo)", () => {
    const content = `
plugins {
  alias(libs.plugins.foo)
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "(unresolved)", version: null, catalogRef: "libs.plugins.foo" },
    ]);
  });

  it("returns catalogRef for alias(libs.plugins.foo.bar)", () => {
    const content = `
plugins {
  alias(libs.plugins.foo.bar)
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "(unresolved)", version: null, catalogRef: "libs.plugins.foo.bar" },
    ]);
  });

  it("returns catalogRef for alias(testLibs.plugins.x)", () => {
    const content = `
plugins {
  alias(testLibs.plugins.x)
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "(unresolved)", version: null, catalogRef: "testLibs.plugins.x" },
    ]);
  });

  it("parses apply false modifier (still emits)", () => {
    const content = `
plugins {
  id("com.android.application") version "8.5.0" apply false
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "com.android.application", version: "8.5.0" },
    ]);
  });

  it("parses pluginManagement plugins block when opts.settings=true (sets settingsBlock: true)", () => {
    const content = `
pluginManagement {
  plugins {
    id("com.android.application") version "8.5.0"
  }
}
`;
    const result = parsePluginsBlock(content, { settings: true });
    expect(result).toEqual([
      { pluginId: "com.android.application", version: "8.5.0", settingsBlock: true },
    ]);
  });

  it("does NOT parse pluginManagement plugins block when opts.settings=false", () => {
    const content = `
pluginManagement {
  plugins {
    id("com.android.application") version "8.5.0"
  }
}
`;
    expect(parsePluginsBlock(content, { settings: false })).toEqual([]);
  });

  it("does NOT parse top-level plugins block when opts.settings=true", () => {
    const content = `
plugins {
  id("com.android.application") version "8.5.0"
}
`;
    expect(parsePluginsBlock(content, { settings: true })).toEqual([]);
  });

  it("ignores commented plugin declarations", () => {
    const content = `
plugins {
  // id("com.example.commented") version "1.0"
  /* id("com.example.blocked") version "2.0" */
  id("com.android.application") version "8.5.0"
}
`;
    expect(parsePluginsBlock(content)).toEqual([
      { pluginId: "com.android.application", version: "8.5.0" },
    ]);
  });
});

describe("parseBuildscriptClasspath", () => {
  it("parses classpath(\"g:a:v\") in Kotlin DSL", () => {
    const content = `
buildscript {
  dependencies {
    classpath("com.android.tools.build:gradle:8.5.0")
  }
}
`;
    expect(parseBuildscriptClasspath(content)).toEqual([
      { groupId: "com.android.tools.build", artifactId: "gradle", version: "8.5.0" },
    ]);
  });

  it("parses classpath 'g:a:v' in Groovy DSL", () => {
    const content = `
buildscript {
  dependencies {
    classpath 'com.android.tools.build:gradle:8.5.0'
  }
}
`;
    expect(parseBuildscriptClasspath(content)).toEqual([
      { groupId: "com.android.tools.build", artifactId: "gradle", version: "8.5.0" },
    ]);
  });

  it("parses multiple classpath entries", () => {
    const content = `
buildscript {
  dependencies {
    classpath("com.android.tools.build:gradle:8.5.0")
    classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.1.0")
  }
}
`;
    expect(parseBuildscriptClasspath(content)).toEqual([
      { groupId: "com.android.tools.build", artifactId: "gradle", version: "8.5.0" },
      { groupId: "org.jetbrains.kotlin", artifactId: "kotlin-gradle-plugin", version: "2.1.0" },
    ]);
  });

  it("ignores non-classpath configurations in buildscript.dependencies", () => {
    const content = `
buildscript {
  dependencies {
    implementation("com.example:lib:1.0")
    classpath("com.android.tools.build:gradle:8.5.0")
  }
}
`;
    expect(parseBuildscriptClasspath(content)).toEqual([
      { groupId: "com.android.tools.build", artifactId: "gradle", version: "8.5.0" },
    ]);
  });

  it("ignores classpath outside buildscript block", () => {
    const content = `
dependencies {
  classpath("com.android.tools.build:gradle:8.5.0")
}
buildscript {
  dependencies {
    classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.1.0")
  }
}
`;
    expect(parseBuildscriptClasspath(content)).toEqual([
      { groupId: "org.jetbrains.kotlin", artifactId: "kotlin-gradle-plugin", version: "2.1.0" },
    ]);
  });

  it("ignores commented classpath", () => {
    const content = `
buildscript {
  dependencies {
    // classpath("com.example:commented:1.0")
    /* classpath("com.example:blocked:2.0") */
    classpath("com.android.tools.build:gradle:8.5.0")
  }
}
`;
    expect(parseBuildscriptClasspath(content)).toEqual([
      { groupId: "com.android.tools.build", artifactId: "gradle", version: "8.5.0" },
    ]);
  });
});

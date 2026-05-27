import { describe, it, expect, vi, beforeEach } from "vitest";
import { scanProjectWithSubmodules } from "../scan.js";
import * as fs from "node:fs";

vi.mock("node:fs");
const mockedFs = vi.mocked(fs);

// Mocks a filesystem where only the given file paths exist and return the given content.
function mockFileSystem(files: Record<string, string>) {
  mockedFs.existsSync.mockImplementation((p: fs.PathLike) =>
    Object.prototype.hasOwnProperty.call(files, p.toString()),
  );
  mockedFs.readFileSync.mockImplementation((p: fs.PathOrFileDescriptor) => {
    const key = p.toString();
    if (!Object.prototype.hasOwnProperty.call(files, key)) {
      throw new Error(`ENOENT: no such file '${key}'`);
    }
    return files[key];
  });
}

beforeEach(() => vi.clearAllMocks());

describe("scanProjectWithSubmodules — Gradle catalog entries", () => {
  it("unused catalog library emitted once with kind catalog-library and empty usages", () => {
    mockFileSystem({
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }
`,
    });

    const result = scanProjectWithSubmodules("/project");
    expect(result.buildSystem).toBe("gradle");
    const dep = result.dependencies.find(
      (d) => d.groupId === "io.ktor" && d.artifactId === "ktor-client-core",
    );
    expect(dep).toBeDefined();
    expect(dep!.source).toEqual({ kind: "catalog-library", catalogName: "libs", tomlPath: "gradle/libs.versions.toml", alias: "ktor-core" });
    expect(dep!.usages).toEqual([]);
    // Only one entry, not duplicated
    expect(result.dependencies.filter((d) => d.groupId === "io.ktor")).toHaveLength(1);
  });

  it("used catalog library: usages populated, single entry (no duplicate)", () => {
    mockFileSystem({
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }
`,
      "/project/build.gradle.kts": `
dependencies {
    implementation(libs.ktor.core)
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const deps = result.dependencies.filter((d) => d.groupId === "io.ktor");
    // Only one entry — catalog entry populated with usage, no duplicate module-direct
    expect(deps).toHaveLength(1);
    expect(deps[0].source.kind).toBe("catalog-library");
    expect(deps[0].usages).toHaveLength(1);
    expect(deps[0].usages[0]).toEqual({ module: undefined, configuration: "implementation" });
  });

  it("catalog library used by two modules: one entry, two usages", () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":app", ":lib")`,
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }
`,
      "/project/app/build.gradle.kts": `
dependencies {
    implementation(libs.ktor.core)
}`,
      "/project/lib/build.gradle.kts": `
dependencies {
    api(libs.ktor.core)
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const deps = result.dependencies.filter((d) => d.groupId === "io.ktor" && d.source.kind === "catalog-library");
    expect(deps).toHaveLength(1);
    expect(deps[0].usages).toHaveLength(2);
    expect(deps[0].usages).toContainEqual({ module: ":app", configuration: "implementation" });
    expect(deps[0].usages).toContainEqual({ module: ":lib", configuration: "api" });
  });

  it("direct module dep emitted with kind module-direct", () => {
    mockFileSystem({
      "/project/build.gradle.kts": `
dependencies {
    implementation("com.google.code.gson:gson:2.11.0")
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const dep = result.dependencies.find((d) => d.artifactId === "gson");
    expect(dep).toBeDefined();
    expect(dep!.source.kind).toBe("module-direct");
    expect(dep!.usages).toHaveLength(1);
    expect(dep!.usages[0]).toEqual({ module: undefined, configuration: "implementation" });
  });

  it("catalog version drift: catalog says 1.0, module hardcodes 2.0 → both reported separately", () => {
    mockFileSystem({
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-core = { module = "io.ktor:ktor-client-core", version = "1.0.0" }
`,
      "/project/build.gradle.kts": `
dependencies {
    implementation(libs.ktor.core)
    implementation("io.ktor:ktor-client-core:2.0.0")
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const deps = result.dependencies.filter((d) => d.groupId === "io.ktor" && d.artifactId === "ktor-client-core");
    expect(deps).toHaveLength(2);
    const catalogDep = deps.find((d) => d.source.kind === "catalog-library");
    const directDep = deps.find((d) => d.source.kind === "module-direct");
    expect(catalogDep!.version).toBe("1.0.0");
    expect(directDep!.version).toBe("2.0.0");
  });

  it("multi-catalog: testLibs.x ref in test module resolves to testLibs descriptor", () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `
dependencyResolutionManagement {
    versionCatalogs {
        create("libs") {
            from(files("gradle/libs.versions.toml"))
        }
        create("testLibs") {
            from(files("gradle/test-libs.versions.toml"))
        }
    }
}
include(":app")`,
      "/project/gradle/libs.versions.toml": `
[libraries]
ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }
`,
      "/project/gradle/test-libs.versions.toml": `
[libraries]
mockk = { module = "io.mockk:mockk", version = "1.13.0" }
`,
      "/project/app/build.gradle.kts": `
dependencies {
    implementation(libs.ktor.core)
    testImplementation(testLibs.mockk)
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const mockkDep = result.dependencies.find((d) => d.artifactId === "mockk");
    expect(mockkDep).toBeDefined();
    expect(mockkDep!.source.kind).toBe("catalog-library");
    if (mockkDep!.source.kind === "catalog-library") {
      expect(mockkDep!.source.catalogName).toBe("testLibs");
    }
    expect(mockkDep!.usages).toHaveLength(1);
    expect(mockkDep!.usages[0]).toEqual({ module: ":app", configuration: "testImplementation" });
  });

  it("unused catalog plugin emitted with kind catalog-plugin and plugin marker artifactId", () => {
    mockFileSystem({
      "/project/gradle/libs.versions.toml": `
[plugins]
android-application = { id = "com.android.application", version = "8.5.0" }
`,
    });

    const result = scanProjectWithSubmodules("/project");
    const dep = result.dependencies.find((d) => d.groupId === "com.android.application");
    expect(dep).toBeDefined();
    expect(dep!.artifactId).toBe("com.android.application.gradle.plugin");
    expect(dep!.source.kind).toBe("catalog-plugin");
    expect(dep!.usages).toEqual([]);
  });

  it("root plugins {} block: id(\"x\") version \"1.0\" → kind plugins-dsl, module undefined, settingsBlock false", () => {
    mockFileSystem({
      "/project/build.gradle.kts": `
plugins {
    id("com.android.application") version "8.5.0"
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const dep = result.dependencies.find((d) => d.groupId === "com.android.application");
    expect(dep).toBeDefined();
    expect(dep!.artifactId).toBe("com.android.application.gradle.plugin");
    expect(dep!.version).toBe("8.5.0");
    expect(dep!.source.kind).toBe("plugins-dsl");
    if (dep!.source.kind === "plugins-dsl") {
      expect(dep!.source.module).toBeUndefined();
      expect(dep!.source.settingsBlock).toBeUndefined();
    }
    expect(dep!.usages).toHaveLength(1);
    expect(dep!.usages[0]).toEqual({ module: undefined, configuration: "plugin-dsl" });
  });

  it("pluginManagement { plugins {} } in settings → kind plugins-dsl, settingsBlock true", () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `
pluginManagement {
    plugins {
        id("org.jetbrains.kotlin.android") version "2.0.0"
    }
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const dep = result.dependencies.find((d) => d.groupId === "org.jetbrains.kotlin.android");
    expect(dep).toBeDefined();
    expect(dep!.source.kind).toBe("plugins-dsl");
    if (dep!.source.kind === "plugins-dsl") {
      expect(dep!.source.settingsBlock).toBe(true);
    }
    expect(dep!.usages[0].configuration).toBe("plugin-dsl");
  });

  it("alias(libs.plugins.foo) in root plugins {} → adds usage to catalog plugin entry, does NOT emit new dep", () => {
    mockFileSystem({
      "/project/gradle/libs.versions.toml": `
[plugins]
kotlin-android = { id = "org.jetbrains.kotlin.android", version = "2.0.0" }
`,
      "/project/build.gradle.kts": `
plugins {
    alias(libs.plugins.kotlin.android)
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const deps = result.dependencies.filter((d) => d.groupId === "org.jetbrains.kotlin.android");
    // Only one entry — the catalog plugin entry, no new plugins-dsl dep
    expect(deps).toHaveLength(1);
    expect(deps[0].source.kind).toBe("catalog-plugin");
    expect(deps[0].usages).toHaveLength(1);
    expect(deps[0].usages[0]).toEqual({ module: undefined, configuration: "plugin-dsl" });
  });

  it("kotlin(\"jvm\") version \"2.0\" → resolves to org.jetbrains.kotlin.jvm marker", () => {
    mockFileSystem({
      "/project/build.gradle.kts": `
plugins {
    kotlin("jvm") version "2.0.0"
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const dep = result.dependencies.find((d) => d.groupId === "org.jetbrains.kotlin.jvm");
    expect(dep).toBeDefined();
    expect(dep!.artifactId).toBe("org.jetbrains.kotlin.jvm.gradle.plugin");
    expect(dep!.version).toBe("2.0.0");
    expect(dep!.source.kind).toBe("plugins-dsl");
    expect(dep!.usages[0].configuration).toBe("plugin-dsl");
  });

  it("buildscript classpath → kind buildscript-classpath", () => {
    mockFileSystem({
      "/project/build.gradle.kts": `
buildscript {
    dependencies {
        classpath("com.android.tools.build:gradle:8.0.0")
    }
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const dep = result.dependencies.find((d) => d.artifactId === "gradle" && d.groupId === "com.android.tools.build");
    expect(dep).toBeDefined();
    expect(dep!.source.kind).toBe("buildscript-classpath");
    expect(dep!.usages).toHaveLength(1);
    expect(dep!.usages[0]).toEqual({ module: undefined, configuration: "classpath" });
  });

  it("buildscript classpath in submodule is not scanned", () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":app")`,
      "/project/app/build.gradle.kts": `
buildscript {
    dependencies {
        classpath("com.example:submodule-classpath:1.0")
    }
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const dep = result.dependencies.find((d) => d.artifactId === "submodule-classpath");
    expect(dep).toBeUndefined();
  });

  it("no Gradle settings, only gradle/libs.versions.toml → default libs descriptor still works", () => {
    mockFileSystem({
      "/project/gradle/libs.versions.toml": `
[libraries]
gson = { module = "com.google.code.gson:gson", version = "2.11.0" }
`,
      "/project/build.gradle.kts": `
dependencies {
    implementation(libs.gson)
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    expect(result.buildSystem).toBe("gradle");
    const dep = result.dependencies.find((d) => d.artifactId === "gson");
    expect(dep).toBeDefined();
    expect(dep!.usages).toHaveLength(1);
  });

  it("module-level plugins {} block: id(\"x\") version \"1.0\" in app/build.gradle.kts → kind plugins-dsl, source.module :app, settingsBlock undefined", () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":app")`,
      "/project/app/build.gradle.kts": `
plugins {
    id("com.android.application") version "8.0.0"
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const dep = result.dependencies.find((d) => d.groupId === "com.android.application");
    expect(dep).toBeDefined();
    expect(dep!.artifactId).toBe("com.android.application.gradle.plugin");
    expect(dep!.version).toBe("8.0.0");
    expect(dep!.source.kind).toBe("plugins-dsl");
    if (dep!.source.kind === "plugins-dsl") {
      expect(dep!.source.module).toBe(":app");
      expect(dep!.source.settingsBlock).toBeUndefined();
      expect(dep!.source.file).toBe("build.gradle.kts");
    }
    expect(dep!.usages).toHaveLength(1);
    expect(dep!.usages[0]).toEqual({ module: ":app", configuration: "plugin-dsl" });
  });

  it("alias(libs.plugins.x) in module build.gradle.kts resolves through catalog [plugins] entry — usage appended with module label", () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":app")`,
      "/project/gradle/libs.versions.toml": `
[plugins]
kotlin-android = { id = "org.jetbrains.kotlin.android", version = "2.0.0" }
`,
      "/project/app/build.gradle.kts": `
plugins {
    alias(libs.plugins.kotlin.android)
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const deps = result.dependencies.filter((d) => d.groupId === "org.jetbrains.kotlin.android");
    // Only one entry — the catalog plugin entry, no new plugins-dsl dep
    expect(deps).toHaveLength(1);
    expect(deps[0].source.kind).toBe("catalog-plugin");
    expect(deps[0].usages).toHaveLength(1);
    expect(deps[0].usages[0]).toEqual({ module: ":app", configuration: "plugin-dsl" });
  });

  it("module-level plugin with apply false still emits", () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `include(":lib")`,
      "/project/lib/build.gradle.kts": `
plugins {
    id("com.android.library") version "8.0.0" apply false
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    const dep = result.dependencies.find((d) => d.groupId === "com.android.library");
    expect(dep).toBeDefined();
    expect(dep!.source.kind).toBe("plugins-dsl");
    if (dep!.source.kind === "plugins-dsl") {
      expect(dep!.source.module).toBe(":lib");
    }
    expect(dep!.usages).toHaveLength(1);
  });

  it("settings present but versionCatalogs block empty → no catalog deps emitted", () => {
    mockFileSystem({
      "/project/settings.gradle.kts": `
dependencyResolutionManagement {
    versionCatalogs {
    }
}`,
      "/project/build.gradle.kts": `
dependencies {
    implementation("com.example:lib:1.0")
}`,
    });

    const result = scanProjectWithSubmodules("/project");
    // No catalog entries
    const catalogDeps = result.dependencies.filter((d) =>
      d.source.kind === "catalog-library" || d.source.kind === "catalog-plugin",
    );
    expect(catalogDeps).toHaveLength(0);
    // Direct dep still emitted
    expect(result.dependencies).toHaveLength(1);
  });
});

describe("scanProjectWithSubmodules — Maven", () => {
  it("Maven project: each pom dep → kind module-direct, usages populated", () => {
    mockFileSystem({
      "/project/pom.xml": `
<project>
  <dependencies>
    <dependency>
      <groupId>io.ktor</groupId>
      <artifactId>ktor-core</artifactId>
      <version>3.1.1</version>
    </dependency>
  </dependencies>
</project>`,
    });

    const result = scanProjectWithSubmodules("/project");
    expect(result.buildSystem).toBe("maven");
    expect(result.dependencies).toHaveLength(1);
    const dep = result.dependencies[0];
    expect(dep.source.kind).toBe("module-direct");
    expect(dep.usages).toHaveLength(1);
    expect(dep.usages[0].module).toBeUndefined();
  });

  it("Maven submodule recursion preserved", () => {
    mockFileSystem({
      "/project/pom.xml": `
<project>
  <modules>
    <module>core</module>
  </modules>
</project>`,
      "/project/core/pom.xml": `
<project>
  <dependencies>
    <dependency>
      <groupId>io.ktor</groupId>
      <artifactId>ktor-core</artifactId>
      <version>3.1.1</version>
    </dependency>
  </dependencies>
</project>`,
    });

    const result = scanProjectWithSubmodules("/project");
    expect(result.buildSystem).toBe("maven");
    expect(result.dependencies).toHaveLength(1);
    expect(result.dependencies[0].source.file).toBe("pom.xml");
    expect(result.dependencies[0].usages[0].module).toBe("core");
  });
});

describe("scanProjectWithSubmodules — unknown project", () => {
  it("returns empty for unknown project", () => {
    mockedFs.existsSync.mockReturnValue(false);
    const result = scanProjectWithSubmodules("/empty");
    expect(result.buildSystem).toBe("unknown");
    expect(result.dependencies).toEqual([]);
  });
});

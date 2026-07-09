"""Parser unit tests for server.py.

Mirrors TypeScript tests in:
  src/dependencies/__tests__/gradle-deps-parser.test.ts
  src/dependencies/__tests__/plugins-block-parser.test.ts
  src/dependencies/__tests__/maven-deps-parser.test.ts
  src/dependencies/__tests__/maven-modules-parser.test.ts
  src/dependencies/__tests__/settings-catalogs-parser.test.ts
  src/dependencies/__tests__/toml-parser.test.ts
  src/dependencies/__tests__/scan.test.ts
  src/maven/__tests__/repository.test.ts

Python-vs-TS behavioral differences (documented inline and in test comments):
  1. _parse_settings_catalogs returns [] for absent/empty versionCatalogs block;
     the TS parseSettingsCatalogs returns a default libs descriptor. The fallback
     is handled in scan_project(), not in the parser function itself.
  2. _parse_settings_catalogs parses both old-style Groovy block syntax
     `name { from(files("...")) }` and Kotlin DSL
     `create("name") { from(files("...")) }` (gap closed in #313).
  3. _parse_gradle_plugins_block supports the `kotlin("jvm")` shorthand (mapped to
     org.jetbrains.kotlin.jvm) and the no-paren Groovy `id 'x'` form (gap closed
     in #313).
  4. _parse_gradle_deps return dicts have no "source" key; the source is
     attached by scan_project(). TS parseGradleDependencies includes source
     directly.
  5. parseGradleRepositories (src/discovery/gradle-parser.ts) — custom-repo
     URL discovery — has no Python equivalent. All test cases covering that
     TS module are skipped (divergence guardrail #5).
"""

import datetime
import unittest
import warnings

from _helpers import server, temp_project


# ---------------------------------------------------------------------------
# _parse_metadata_xml
# Mirrors: src/maven/__tests__/repository.test.ts > "parses metadata XML correctly"
# ---------------------------------------------------------------------------

class TestParseMetadataXml(unittest.TestCase):
    """Tests for server._parse_metadata_xml."""

    # Mirrors: repository.test.ts > "parses metadata XML correctly"
    def test_parses_versions_latest_release(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<metadata>\n"
            "  <groupId>io.ktor</groupId>\n"
            "  <artifactId>ktor-server-core</artifactId>\n"
            "  <versioning>\n"
            "    <latest>3.1.1</latest>\n"
            "    <release>3.1.1</release>\n"
            "    <versions>\n"
            "      <version>2.0.0</version>\n"
            "      <version>3.0.0</version>\n"
            "      <version>3.1.1</version>\n"
            "    </versions>\n"
            "    <lastUpdated>20250301</lastUpdated>\n"
            "  </versioning>\n"
            "</metadata>"
        )
        result = server._parse_metadata_xml(xml, "io.ktor", "ktor-server-core")
        self.assertEqual(result["groupId"], "io.ktor")
        self.assertEqual(result["artifactId"], "ktor-server-core")
        self.assertEqual(result["versions"], ["2.0.0", "3.0.0", "3.1.1"])
        self.assertEqual(result["latest"], "3.1.1")
        self.assertEqual(result["release"], "3.1.1")
        self.assertEqual(result["lastUpdated"], "20250301")

    # Mirrors: repository.test.ts > "parses metadata XML correctly" (absent fields)
    def test_missing_latest_release_returns_none(self):
        xml = (
            "<metadata>\n"
            "  <versioning>\n"
            "    <versions><version>1.0.0</version></versions>\n"
            "  </versioning>\n"
            "</metadata>"
        )
        result = server._parse_metadata_xml(xml, "com.example", "lib")
        self.assertEqual(result["versions"], ["1.0.0"])
        self.assertIsNone(result["latest"])
        self.assertIsNone(result["release"])
        self.assertIsNone(result["lastUpdated"])

    # Mirrors: repository.test.ts > "parses metadata XML correctly" (empty)
    def test_empty_xml_returns_empty_fields(self):
        result = server._parse_metadata_xml("<metadata/>", "g", "a")
        self.assertEqual(result["groupId"], "g")
        self.assertEqual(result["artifactId"], "a")
        self.assertEqual(result["versions"], [])
        self.assertIsNone(result["latest"])


# ---------------------------------------------------------------------------
# extract_relocation_from_pom (#284)
# ---------------------------------------------------------------------------

class TestExtractRelocationFromPom(unittest.TestCase):
    """Tests for server.extract_relocation_from_pom."""

    def test_no_relocation_block_returns_none(self):
        pom = "<project><groupId>g</groupId><artifactId>a</artifactId><version>1.0</version></project>"
        self.assertIsNone(server.extract_relocation_from_pom(pom, "g", "a", "1.0"))

    def test_full_relocation_returns_new_gav(self):
        pom = (
            "<project><distributionManagement><relocation>"
            "<groupId>new.group</groupId><artifactId>new-artifact</artifactId>"
            "<version>2.0</version>"
            "</relocation></distributionManagement></project>"
        )
        result = server.extract_relocation_from_pom(pom, "old.group", "old-artifact", "1.0")
        self.assertEqual(result, {"groupId": "new.group", "artifactId": "new-artifact", "version": "2.0"})

    def test_partial_relocation_fills_in_original_group_and_version(self):
        # Only <artifactId> given — Maven's relocation spec treats the absent
        # groupId/version as "unchanged from the original coordinate".
        pom = (
            "<project><distributionManagement><relocation>"
            "<artifactId>new-artifact</artifactId>"
            "</relocation></distributionManagement></project>"
        )
        result = server.extract_relocation_from_pom(pom, "old.group", "old-artifact", "1.0")
        self.assertEqual(result, {"groupId": "old.group", "artifactId": "new-artifact", "version": "1.0"})

    def test_relocation_with_only_message_reports_original_gav(self):
        # A <relocation> block can carry only a human-readable <message> — all
        # three coordinate fields fall back to the original.
        pom = (
            "<project><distributionManagement><relocation>"
            "<message>moved permanently</message>"
            "</relocation></distributionManagement></project>"
        )
        result = server.extract_relocation_from_pom(pom, "old.group", "old-artifact", "1.0")
        self.assertEqual(result, {"groupId": "old.group", "artifactId": "old-artifact", "version": "1.0"})

    def test_relocation_inside_xml_comment_ignored(self):
        pom = (
            "<project><distributionManagement>"
            "<!-- <relocation><groupId>new.group</groupId></relocation> -->"
            "</distributionManagement></project>"
        )
        self.assertIsNone(server.extract_relocation_from_pom(pom, "g", "a", "1.0"))

    def test_shade_plugin_relocations_outside_distribution_management_ignored(self):
        # Maven Shade Plugin's <configuration><relocations><relocation> is an
        # unrelated concept (package relocation for shading, not artifact-
        # coordinate relocation) — a POM using it with no
        # <distributionManagement> block must not false-positive.
        pom = (
            "<project><build><plugins><plugin>"
            "<artifactId>maven-shade-plugin</artifactId>"
            "<configuration><relocations><relocation>"
            "<pattern>org.old</pattern><shadedPattern>org.shaded.old</shadedPattern>"
            "</relocation></relocations></configuration>"
            "</plugin></plugins></build></project>"
        )
        self.assertIsNone(server.extract_relocation_from_pom(pom, "g", "a", "1.0"))


# ---------------------------------------------------------------------------
# _parse_gradle_deps
# Mirrors: src/dependencies/__tests__/gradle-deps-parser.test.ts
# NOTE: Python return dicts have no "source" key (TS includes it).
# ---------------------------------------------------------------------------

class TestParseGradleDeps(unittest.TestCase):
    """Tests for server._parse_gradle_deps."""

    # Mirrors: gradle-deps-parser.test.ts > "parses string notation with version"
    def test_string_notation_with_version(self):
        content = (
            'dependencies {\n'
            '    implementation("io.ktor:ktor-client-core:3.1.1")\n'
            '    testImplementation("org.junit:junit:5.10.0")\n'
            '}'
        )
        deps = server._parse_gradle_deps(content, "build.gradle.kts")
        groups = {(d["groupId"], d["artifactId"]): d for d in deps}
        ktor = groups[("io.ktor", "ktor-client-core")]
        self.assertEqual(ktor["version"], "3.1.1")
        self.assertEqual(ktor["configuration"], "implementation")
        self.assertIsNone(ktor["catalogRef"])
        junit = groups[("org.junit", "junit")]
        self.assertEqual(junit["configuration"], "testImplementation")

    # Mirrors: gradle-deps-parser.test.ts > "parses string notation without version (BOM)"
    def test_string_notation_without_version_returns_none(self):
        deps = server._parse_gradle_deps('implementation("io.ktor:ktor-client-core")', "build.gradle.kts")
        self.assertEqual(len(deps), 1)
        self.assertIsNone(deps[0]["version"])

    # Mirrors: gradle-deps-parser.test.ts > "parses Groovy single-quote notation"
    def test_groovy_single_quote_notation(self):
        deps = server._parse_gradle_deps("implementation 'io.ktor:ktor-client-core:3.1.1'", "build.gradle")
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["groupId"], "io.ktor")
        self.assertEqual(deps[0]["version"], "3.1.1")

    # Mirrors: gradle-deps-parser.test.ts > "parses version catalog references"
    def test_catalog_ref_libs_prefix(self):
        deps = server._parse_gradle_deps("implementation(libs.ktor.client.core)", "build.gradle.kts")
        self.assertEqual(len(deps), 1)
        self.assertIsNone(deps[0]["groupId"])
        self.assertIsNone(deps[0]["artifactId"])
        self.assertIsNone(deps[0]["version"])
        self.assertEqual(deps[0]["configuration"], "implementation")
        self.assertEqual(deps[0]["catalogRef"], "libs.ktor.client.core")

    # Mirrors: gradle-deps-parser.test.ts > "parses non-libs catalog references"
    def test_catalog_ref_non_libs_prefix(self):
        deps = server._parse_gradle_deps("testImplementation(testLibs.mockk.core)", "build.gradle.kts")
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["catalogRef"], "testLibs.mockk.core")
        self.assertEqual(deps[0]["configuration"], "testImplementation")

    # Mirrors: gradle-deps-parser.test.ts > "extracts various configurations"
    def test_various_configurations(self):
        content = (
            'api("com.example:api-lib:1.0")\n'
            'compileOnly("com.example:compile-lib:1.0")\n'
            'runtimeOnly("com.example:runtime-lib:1.0")\n'
        )
        deps = server._parse_gradle_deps(content, "build.gradle.kts")
        configs = [d["configuration"] for d in deps]
        self.assertIn("api", configs)
        self.assertIn("compileOnly", configs)
        self.assertIn("runtimeOnly", configs)

    # Mirrors: gradle-deps-parser.test.ts > "returns empty for no dependencies"
    def test_no_dependencies_returns_empty(self):
        result = server._parse_gradle_deps("plugins { }", "build.gradle.kts")
        self.assertEqual(result, [])

    # Mirrors: gradle-deps-parser.test.ts > "catalog name with underscore: test_libs.foo.bar"
    def test_catalog_name_with_underscore(self):
        deps = server._parse_gradle_deps("testImplementation(test_libs.foo.bar)", "build.gradle.kts")
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["catalogRef"], "test_libs.foo.bar")

    # Additional: kapt/ksp/annotationProcessor configurations
    def test_annotation_processor_configurations(self):
        content = (
            'kapt("com.example:kapt-lib:1.0")\n'
            'ksp("com.example:ksp-lib:1.0")\n'
            'annotationProcessor("com.example:ap-lib:1.0")\n'
        )
        deps = server._parse_gradle_deps(content, "build.gradle.kts")
        configs = {d["configuration"] for d in deps}
        self.assertIn("kapt", configs)
        self.assertIn("ksp", configs)
        self.assertIn("annotationProcessor", configs)

    # #347: classifier / @ext must not be folded into version
    def test_string_notation_strips_classifier_and_extension(self):
        content = (
            'implementation("com.example:lib:1.0:sources")\n'
            'api("com.x:y:2.0@aar")\n'
            'implementation("io.netty:netty-transport-native-epoll:4.1.100.Final:linux-x86_64")\n'
            'api("com.x:y:2.0:sources@aar")\n'
        )
        deps = server._parse_gradle_deps(content, "build.gradle.kts")
        by_ga = {(d["groupId"], d["artifactId"]): d["version"] for d in deps}
        self.assertEqual(by_ga[("com.example", "lib")], "1.0")
        self.assertEqual(by_ga[("com.x", "y")], "2.0")
        self.assertEqual(
            by_ga[("io.netty", "netty-transport-native-epoll")],
            "4.1.100.Final",
        )
        # classifier@ext: same G:A appears twice with clean version
        versions = [d["version"] for d in deps if d["groupId"] == "com.x"]
        self.assertEqual(versions, ["2.0", "2.0"])

    # #346: Android variant/flavor/source-set configurations + platform()/BOM
    def test_android_variant_and_platform_bom(self):
        content = (
            "dependencies {\n"
            '  debugImplementation("a:b:1.0")\n'
            '  androidTestImplementation("e:f:1.0")\n'
            '  testFixturesImplementation("g:h:1.0")\n'
            '  implementation(platform("i:j:1.0"))\n'
            '  implementation(enforcedPlatform("k:l:1.0"))\n'
            '  paidReleaseApi("m:n:2.0")\n'
            '  coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.0.4")\n'
            '  lintChecks("com.example:lint:1.0")\n'
            '  kaptAndroidTest("com.example:kapt-at:1.0")\n'
            '  debugImplementation(libs.foo.bar)\n'
            "}"
        )
        deps = server._parse_gradle_deps(content, "build.gradle.kts")
        by_ga = {(d["groupId"], d["artifactId"]): d for d in deps if d["groupId"]}
        self.assertEqual(by_ga[("a", "b")]["configuration"], "debugImplementation")
        self.assertEqual(by_ga[("e", "f")]["configuration"], "androidTestImplementation")
        self.assertEqual(by_ga[("g", "h")]["configuration"], "testFixturesImplementation")
        self.assertEqual(by_ga[("i", "j")]["version"], "1.0")
        self.assertEqual(by_ga[("i", "j")]["configuration"], "implementation")
        self.assertTrue(by_ga[("i", "j")]["isPlatform"])
        self.assertEqual(by_ga[("i", "j")]["platformKind"], "platform")
        self.assertEqual(by_ga[("k", "l")]["configuration"], "implementation")
        self.assertTrue(by_ga[("k", "l")]["isPlatform"])
        self.assertEqual(by_ga[("k", "l")]["platformKind"], "enforcedPlatform")
        self.assertFalse(by_ga[("a", "b")]["isPlatform"])
        self.assertIsNone(by_ga[("a", "b")]["platformKind"])
        self.assertEqual(by_ga[("m", "n")]["configuration"], "paidReleaseApi")
        self.assertEqual(
            by_ga[("com.android.tools", "desugar_jdk_libs")]["configuration"],
            "coreLibraryDesugaring",
        )
        self.assertEqual(by_ga[("com.example", "lint")]["configuration"], "lintChecks")
        self.assertEqual(
            by_ga[("com.example", "kapt-at")]["configuration"],
            "kaptAndroidTest",
        )
        catalog = [d for d in deps if d["catalogRef"]]
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["configuration"], "debugImplementation")
        self.assertEqual(catalog[0]["catalogRef"], "libs.foo.bar")
        self.assertFalse(catalog[0]["isPlatform"])


# ---------------------------------------------------------------------------
# _parse_gradle_plugins_block
# Mirrors: src/dependencies/__tests__/plugins-block-parser.test.ts
# NOTE: Python does NOT support kotlin("shorthand") syntax.
# ---------------------------------------------------------------------------

class TestParseGradlePluginsBlock(unittest.TestCase):
    """Tests for server._parse_gradle_plugins_block."""

    # Mirrors: plugins-block-parser.test.ts > id + version
    def test_id_with_version(self):
        content = 'plugins {\n    id("org.jetbrains.kotlin.jvm") version "2.1.0"\n}'
        result = server._parse_gradle_plugins_block(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pluginId"], "org.jetbrains.kotlin.jvm")
        self.assertEqual(result[0]["version"], "2.1.0")
        self.assertIsNone(result[0]["catalogRef"])
        self.assertFalse(result[0]["settingsBlock"])

    # Mirrors: plugins-block-parser.test.ts > id without version
    def test_id_without_version(self):
        content = 'plugins {\n    id("com.android.application")\n}'
        result = server._parse_gradle_plugins_block(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pluginId"], "com.android.application")
        self.assertIsNone(result[0]["version"])
        self.assertIsNone(result[0]["catalogRef"])

    # Mirrors: plugins-block-parser.test.ts > alias reference
    def test_alias_plugins_reference(self):
        content = 'plugins {\n    alias(libs.plugins.kotlin.android)\n}'
        result = server._parse_gradle_plugins_block(content)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["pluginId"])
        self.assertIsNone(result[0]["version"])
        self.assertEqual(result[0]["catalogRef"], "libs.plugins.kotlin.android")

    # Mirrors: plugins-block-parser.test.ts > alias with non-libs catalog
    def test_alias_non_libs_catalog(self):
        content = 'plugins {\n    alias(testLibs.plugins.android.lint)\n}'
        result = server._parse_gradle_plugins_block(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["catalogRef"], "testLibs.plugins.android.lint")

    # Mirrors: plugins-block-parser.test.ts > settingsBlock flag true
    def test_settings_block_flag_true(self):
        content = 'plugins {\n    id("com.gradle.plugin") version "1.0"\n}'
        result = server._parse_gradle_plugins_block(content, is_settings=True)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["settingsBlock"])

    # Mirrors: plugins-block-parser.test.ts > settingsBlock flag false by default
    def test_settings_block_flag_false_by_default(self):
        content = 'plugins {\n    id("x") version "1"\n}'
        result = server._parse_gradle_plugins_block(content)
        self.assertFalse(result[0]["settingsBlock"])

    # Mirrors: plugins-block-parser.test.ts > multiple plugins in one block
    def test_multiple_plugins_in_block(self):
        content = (
            'plugins {\n'
            '    id("com.android.application") version "8.5.0"\n'
            '    id("org.jetbrains.kotlin.android") version "2.1.0"\n'
            '    alias(libs.plugins.compose)\n'
            '}'
        )
        result = server._parse_gradle_plugins_block(content)
        self.assertEqual(len(result), 3)
        plugin_ids = [r["pluginId"] for r in result]
        self.assertIn("com.android.application", plugin_ids)
        self.assertIn("org.jetbrains.kotlin.android", plugin_ids)

    # Mirrors: plugins-block-parser.test.ts > apply false is parsed (version captured, apply ignored)
    def test_apply_false_still_parses_plugin(self):
        content = 'plugins {\n    id("com.android.library") version "8.0.0" apply false\n}'
        result = server._parse_gradle_plugins_block(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pluginId"], "com.android.library")
        self.assertEqual(result[0]["version"], "8.0.0")

    # Mirrors: plugins-block-parser.test.ts > empty plugins block
    def test_empty_plugins_block(self):
        result = server._parse_gradle_plugins_block("plugins {}")
        self.assertEqual(result, [])

    # Mirrors: plugins-block-parser.test.ts > no plugins block
    def test_no_plugins_block(self):
        result = server._parse_gradle_plugins_block("dependencies { implementation('x:y:1') }")
        self.assertEqual(result, [])

    # Mirrors: plugins-block-parser.test.ts > Groovy single-quote with parentheses
    # NOTE: Python requires parentheses: id('x') works, but id 'x' (no parens) does not.
    def test_groovy_single_quote_id_with_parens(self):
        content = "plugins {\n    id('com.example.plugin') version '1.0'\n}"
        result = server._parse_gradle_plugins_block(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pluginId"], "com.example.plugin")
        self.assertEqual(result[0]["version"], "1.0")

    # Groovy space-style `id 'plugin' version '1.0'` (no parens) — gap closed in #313.
    # Mirrors: plugins-block-parser.test.ts > Groovy DSL without parens.
    def test_groovy_space_style_without_parens_with_version(self):
        content = "plugins {\n    id 'com.example.plugin' version '1.0'\n}"
        result = server._parse_gradle_plugins_block(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pluginId"], "com.example.plugin")
        self.assertEqual(result[0]["version"], "1.0")

    # No-paren `id 'x'` (single quote) and `id "x"` (double quote) without version.
    def test_groovy_space_style_without_parens_no_version(self):
        single = server._parse_gradle_plugins_block("plugins {\n    id 'com.example.a'\n}")
        self.assertEqual(len(single), 1)
        self.assertEqual(single[0]["pluginId"], "com.example.a")
        self.assertIsNone(single[0]["version"])
        double = server._parse_gradle_plugins_block('plugins {\n    id "com.example.b"\n}')
        self.assertEqual(len(double), 1)
        self.assertEqual(double[0]["pluginId"], "com.example.b")
        self.assertIsNone(double[0]["version"])

    # kotlin("jvm") shorthand — gap closed in #313. Maps to org.jetbrains.kotlin.jvm.
    # Mirrors: plugins-block-parser.test.ts > kotlin() shorthand.
    def test_kotlin_shorthand_jvm(self):
        content = 'plugins {\n    kotlin("jvm") version "2.0.0"\n}'
        result = server._parse_gradle_plugins_block(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pluginId"], "org.jetbrains.kotlin.jvm")
        self.assertEqual(result[0]["version"], "2.0.0")

    # kotlin("plugin.serialization") version "1.9.0" — dotted shorthand with version.
    def test_kotlin_shorthand_plugin_serialization_with_version(self):
        content = 'plugins {\n    kotlin("plugin.serialization") version "1.9.0"\n}'
        result = server._parse_gradle_plugins_block(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pluginId"], "org.jetbrains.kotlin.plugin.serialization")
        self.assertEqual(result[0]["version"], "1.9.0")

    # kotlin("X") with no version, and an unknown arg falling back to the generic form.
    def test_kotlin_shorthand_no_version_and_generic_fallback(self):
        content = 'plugins {\n    kotlin("android")\n    kotlin("foo.bar")\n}'
        result = server._parse_gradle_plugins_block(content)
        ids = {r["pluginId"]: r["version"] for r in result}
        self.assertIsNone(ids["org.jetbrains.kotlin.android"])
        self.assertIn("org.jetbrains.kotlin.foo.bar", ids)


# ---------------------------------------------------------------------------
# _parse_buildscript_classpath
# Mirrors: src/dependencies/__tests__/scan.test.ts > "buildscript classpath"
# ---------------------------------------------------------------------------

class TestParseBuildscriptClasspath(unittest.TestCase):
    """Tests for server._parse_buildscript_classpath."""

    # Mirrors: scan.test.ts > "buildscript classpath → kind buildscript-classpath"
    def test_simple_classpath_with_version(self):
        content = (
            'buildscript {\n'
            '    dependencies {\n'
            '        classpath("com.android.tools.build:gradle:8.0.0")\n'
            '    }\n'
            '}'
        )
        result = server._parse_buildscript_classpath(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["groupId"], "com.android.tools.build")
        self.assertEqual(result[0]["artifactId"], "gradle")
        self.assertEqual(result[0]["version"], "8.0.0")

    # Mirrors: scan.test.ts > buildscript without version
    def test_classpath_without_version_returns_none(self):
        content = (
            'buildscript {\n'
            '    dependencies {\n'
            '        classpath("com.example:lib")\n'
            '    }\n'
            '}'
        )
        result = server._parse_buildscript_classpath(content)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["version"])

    # Mirrors: scan.test.ts > no buildscript block
    def test_no_buildscript_block_returns_empty(self):
        result = server._parse_buildscript_classpath('dependencies { implementation("x:y:1") }')
        self.assertEqual(result, [])

    # Mirrors: scan.test.ts > multiple classpath entries
    def test_multiple_classpath_entries(self):
        content = (
            'buildscript {\n'
            '    dependencies {\n'
            '        classpath("com.android.tools.build:gradle:8.0.0")\n'
            '        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.1.0")\n'
            '    }\n'
            '}'
        )
        result = server._parse_buildscript_classpath(content)
        self.assertEqual(len(result), 2)
        artifacts = {r["artifactId"] for r in result}
        self.assertIn("gradle", artifacts)
        self.assertIn("kotlin-gradle-plugin", artifacts)

    # #344: nested repositories {} must not truncate before classpath
    def test_nested_repositories_before_classpath(self):
        content = (
            'buildscript {\n'
            '    repositories { google() }\n'
            '    dependencies {\n'
            '        classpath("com.android.tools.build:gradle:8.5.0")\n'
            '    }\n'
            '}'
        )
        result = server._parse_buildscript_classpath(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["groupId"], "com.android.tools.build")
        self.assertEqual(result[0]["artifactId"], "gradle")
        self.assertEqual(result[0]["version"], "8.5.0")

    # #347: classifier / @ext must not be folded into classpath version
    def test_classpath_strips_classifier_and_extension(self):
        content = (
            'buildscript {\n'
            '    dependencies {\n'
            '        classpath("com.example:plugin:1.0:sources")\n'
            '        classpath("com.x:y:2.0@jar")\n'
            '    }\n'
            '}'
        )
        result = server._parse_buildscript_classpath(content)
        by_ga = {(d["groupId"], d["artifactId"]): d["version"] for d in result}
        self.assertEqual(by_ga[("com.example", "plugin")], "1.0")
        self.assertEqual(by_ga[("com.x", "y")], "2.0")

    # #344: nested credentials {} inside repositories still reaches classpath
    def test_deeply_nested_braces_before_classpath(self):
        content = (
            'buildscript {\n'
            '    repositories {\n'
            '        maven {\n'
            '            url = uri("https://example.com")\n'
            '            credentials { username = "u"; password = "p" }\n'
            '        }\n'
            '    }\n'
            '    dependencies {\n'
            '        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.1.0")\n'
            '    }\n'
            '}'
        )
        result = server._parse_buildscript_classpath(content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["artifactId"], "kotlin-gradle-plugin")
        self.assertEqual(result[0]["version"], "2.1.0")


# ---------------------------------------------------------------------------
# _parse_settings_modules
# Mirrors: src/dependencies/__tests__/settings-gradle-parser.test.ts
# ---------------------------------------------------------------------------

class TestParseSettingsModules(unittest.TestCase):
    """Tests for server._parse_settings_modules."""

    # Mirrors: settings-gradle-parser.test.ts > single include
    def test_single_module(self):
        result = server._parse_settings_modules('include(":app")')
        self.assertEqual(result, [":app"])

    # Mirrors: settings-gradle-parser.test.ts > multiple includes on one line
    def test_multiple_modules_separate_calls(self):
        content = 'include(":app")\ninclude(":lib")\ninclude(":core")'
        result = server._parse_settings_modules(content)
        self.assertEqual(set(result), {":app", ":lib", ":core"})

    # Mirrors: settings-gradle-parser.test.ts > no include declarations
    def test_no_includes_returns_empty(self):
        result = server._parse_settings_modules('rootProject.name = "demo"')
        self.assertEqual(result, [])

    # Mirrors: settings-gradle-parser.test.ts > single-quote variant
    def test_single_quote_include(self):
        result = server._parse_settings_modules("include(':feature')")
        self.assertEqual(result, [":feature"])

    # #345: Groovy space-form (no parentheses)
    def test_groovy_space_form(self):
        content = "include ':app'\ninclude ':core'"
        result = server._parse_settings_modules(content)
        self.assertEqual(result, [":app", ":core"])

    # #345: multi-module parenthesised statement
    def test_multi_module_parenthesised(self):
        result = server._parse_settings_modules('include(":app", ":core", ":data")')
        self.assertEqual(result, [":app", ":core", ":data"])

    # #345: multi-module Groovy space-form
    def test_multi_module_groovy_space_form(self):
        result = server._parse_settings_modules("include ':app', ':core'")
        self.assertEqual(result, [":app", ":core"])

    # #345: includeBuild must not be treated as include
    def test_include_build_not_matched(self):
        result = server._parse_settings_modules('includeBuild("composite")\ninclude(":app")')
        self.assertEqual(result, [":app"])


# ---------------------------------------------------------------------------
# _parse_settings_catalogs
# Mirrors: src/dependencies/__tests__/settings-catalogs-parser.test.ts
# KEY DIFFERENCE: Python returns [] for absent/empty block; TS returns default.
# Python only parses old-style `name { from(files("...")) }`, not Kotlin DSL
# `create("name") { from(files("...")) }`.
# ---------------------------------------------------------------------------

class TestParseSettingsCatalogs(unittest.TestCase):
    """Tests for server._parse_settings_catalogs.

    Python behavioral difference vs TS parseSettingsCatalogs:
      - No versionCatalogs block  → returns []  (TS returns default libs descriptor)
      - Empty versionCatalogs {}  → returns []  (TS returns default libs descriptor)
      - Kotlin DSL create("name") → returns []  (TS parses it correctly)
      The scan_project() function adds the fallback default descriptor when
      _parse_settings_catalogs returns [].
    """

    # Python-specific: function returns [] for absent block (TS returns default).
    def test_no_version_catalogs_block_returns_empty(self):
        content = 'rootProject.name = "demo"\ninclude(":app")'
        result = server._parse_settings_catalogs(content)
        # Python diverges from TS here: [] not [{name:"libs",...}]
        self.assertEqual(result, [])

    # Python-specific: empty block also returns [] (TS returns default).
    def test_empty_version_catalogs_block_returns_empty(self):
        content = (
            'dependencyResolutionManagement {\n'
            '  versionCatalogs {\n'
            '  }\n'
            '}'
        )
        result = server._parse_settings_catalogs(content)
        # Python diverges from TS here: [] not [{name:"libs",...}]
        self.assertEqual(result, [])

    # Groovy-style `name { from(files("...")) }` is what Python actually parses.
    # This corresponds to old Groovy DSL syntax or Groovy inside versionCatalogs.
    def test_groovy_style_catalog_block(self):
        content = (
            'dependencyResolutionManagement {\n'
            '  versionCatalogs {\n'
            '    testLibs {\n'
            '      from(files("gradle/test.versions.toml"))\n'
            '    }\n'
            '  }\n'
            '}'
        )
        result = server._parse_settings_catalogs(content)
        self.assertEqual(result, [{"name": "testLibs", "tomlPath": "gradle/test.versions.toml"}])

    # Groovy-style multiple catalogs.
    def test_groovy_style_multiple_catalogs(self):
        content = (
            'versionCatalogs {\n'
            '  libs {\n'
            '    from(files("gradle/libs.versions.toml"))\n'
            '  }\n'
            '  testLibs {\n'
            '    from(files("gradle/test.versions.toml"))\n'
            '  }\n'
            '}'
        )
        result = server._parse_settings_catalogs(content)
        names = {r["name"]: r["tomlPath"] for r in result}
        self.assertEqual(names["libs"], "gradle/libs.versions.toml")
        self.assertEqual(names["testLibs"], "gradle/test.versions.toml")

    # Kotlin DSL create("name") syntax — gap closed in #313.
    # Mirrors: settings-catalogs-parser.test.ts > "parses Kotlin DSL versionCatalogs with create block".
    def test_kotlin_dsl_create_syntax(self):
        content = (
            'dependencyResolutionManagement {\n'
            '  versionCatalogs {\n'
            '    create("testLibs") {\n'
            '      from(files("gradle/test.versions.toml"))\n'
            '    }\n'
            '  }\n'
            '}'
        )
        result = server._parse_settings_catalogs(content)
        self.assertEqual(result, [{"name": "testLibs", "tomlPath": "gradle/test.versions.toml"}])

    # Kotlin DSL create("libs") { from(files(...)) } — explicit default-named catalog.
    def test_kotlin_dsl_create_libs_with_body(self):
        content = (
            'dependencyResolutionManagement {\n'
            '  versionCatalogs {\n'
            '    create("libs") {\n'
            '      from(files("gradle/libs.versions.toml"))\n'
            '    }\n'
            '  }\n'
            '}'
        )
        result = server._parse_settings_catalogs(content)
        self.assertEqual(result, [{"name": "libs", "tomlPath": "gradle/libs.versions.toml"}])

    # create("libs") with no body / no from(files(...)) yields no descriptor — the
    # parser only emits catalogs with a resolved tomlPath; scan_project() supplies
    # the implicit default libs catalog (same convention as the empty-block case).
    def test_kotlin_dsl_create_no_body_returns_empty(self):
        content = (
            'dependencyResolutionManagement {\n'
            '  versionCatalogs {\n'
            '    create("libs")\n'
            '  }\n'
            '}'
        )
        result = server._parse_settings_catalogs(content)
        self.assertEqual(result, [])

    # Groovy `name { from(files(...)) }` still works alongside the new create() form.
    def test_groovy_and_kotlin_dsl_mixed(self):
        content = (
            'versionCatalogs {\n'
            '  libs {\n'
            '    from(files("gradle/libs.versions.toml"))\n'
            '  }\n'
            '  create("testLibs") {\n'
            '    from(files("gradle/test.versions.toml"))\n'
            '  }\n'
            '}'
        )
        result = server._parse_settings_catalogs(content)
        names = {r["name"]: r["tomlPath"] for r in result}
        self.assertEqual(names["libs"], "gradle/libs.versions.toml")
        self.assertEqual(names["testLibs"], "gradle/test.versions.toml")


# ---------------------------------------------------------------------------
# _parse_maven_deps
# Mirrors: src/dependencies/__tests__/maven-deps-parser.test.ts
# ---------------------------------------------------------------------------

class TestParseMavenDeps(unittest.TestCase):
    """Tests for server._parse_maven_deps."""

    # Mirrors: maven-deps-parser.test.ts > "parses dependencies with version and scope"
    def test_with_version_no_scope_defaults_to_implementation(self):
        pom = (
            "<dependencies>\n"
            "  <dependency>\n"
            "    <groupId>io.ktor</groupId>\n"
            "    <artifactId>ktor-client-core</artifactId>\n"
            "    <version>3.1.1</version>\n"
            "  </dependency>\n"
            "</dependencies>"
        )
        deps = server._parse_maven_deps(pom)
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["groupId"], "io.ktor")
        self.assertEqual(deps[0]["artifactId"], "ktor-client-core")
        self.assertEqual(deps[0]["version"], "3.1.1")
        self.assertEqual(deps[0]["configuration"], "implementation")

    # Mirrors: maven-deps-parser.test.ts > test scope maps to testImplementation
    def test_test_scope_maps_to_test_implementation(self):
        pom = (
            "<dependency>\n"
            "  <groupId>junit</groupId>\n"
            "  <artifactId>junit</artifactId>\n"
            "  <version>4.13.2</version>\n"
            "  <scope>test</scope>\n"
            "</dependency>"
        )
        deps = server._parse_maven_deps(pom)
        self.assertEqual(deps[0]["configuration"], "testImplementation")

    # Mirrors: maven-deps-parser.test.ts > "parses dependencies without version (BOM)"
    def test_without_version_returns_none(self):
        pom = (
            "<dependency>\n"
            "  <groupId>io.ktor</groupId>\n"
            "  <artifactId>ktor-client-core</artifactId>\n"
            "</dependency>"
        )
        deps = server._parse_maven_deps(pom)
        self.assertIsNone(deps[0]["version"])

    # Mirrors: maven-deps-parser.test.ts > "handles property references as null version"
    def test_property_reference_returns_none(self):
        pom = (
            "<dependency>\n"
            "  <groupId>io.ktor</groupId>\n"
            "  <artifactId>ktor-core</artifactId>\n"
            "  <version>${ktor.version}</version>\n"
            "</dependency>"
        )
        deps = server._parse_maven_deps(pom)
        self.assertIsNone(deps[0]["version"])

    # Mirrors: maven-deps-parser.test.ts > "returns empty for no dependencies"
    def test_empty_project_returns_empty(self):
        result = server._parse_maven_deps("<project></project>")
        self.assertEqual(result, [])

    # Scope mapping: provided → compileOnly
    def test_provided_scope_maps_to_compile_only(self):
        pom = (
            "<dependency>\n"
            "  <groupId>javax.servlet</groupId>\n"
            "  <artifactId>servlet-api</artifactId>\n"
            "  <version>2.5</version>\n"
            "  <scope>provided</scope>\n"
            "</dependency>"
        )
        deps = server._parse_maven_deps(pom)
        self.assertEqual(deps[0]["configuration"], "compileOnly")

    # Scope mapping: runtime → runtimeOnly
    def test_runtime_scope_maps_to_runtime_only(self):
        pom = (
            "<dependency>\n"
            "  <groupId>com.example</groupId>\n"
            "  <artifactId>runtime-lib</artifactId>\n"
            "  <version>1.0</version>\n"
            "  <scope>runtime</scope>\n"
            "</dependency>"
        )
        deps = server._parse_maven_deps(pom)
        self.assertEqual(deps[0]["configuration"], "runtimeOnly")

    # #286: dependencyManagement entries must not appear as regular deps
    def test_skips_dependency_management_entries(self):
        pom = (
            "<project>\n"
            "  <dependencyManagement>\n"
            "    <dependencies>\n"
            "      <dependency>\n"
            "        <groupId>org.springframework.boot</groupId>\n"
            "        <artifactId>spring-boot-dependencies</artifactId>\n"
            "        <version>3.2.0</version>\n"
            "        <type>pom</type>\n"
            "        <scope>import</scope>\n"
            "      </dependency>\n"
            "      <dependency>\n"
            "        <groupId>com.managed</groupId>\n"
            "        <artifactId>pin</artifactId>\n"
            "        <version>9.9.9</version>\n"
            "      </dependency>\n"
            "    </dependencies>\n"
            "  </dependencyManagement>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>com.example</groupId>\n"
            "      <artifactId>lib</artifactId>\n"
            "      <version>1.0</version>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )
        deps = server._parse_maven_deps(pom)
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["groupId"], "com.example")
        self.assertEqual(deps[0]["artifactId"], "lib")


# ---------------------------------------------------------------------------
# _parse_maven_modules
# Mirrors: src/dependencies/__tests__/maven-modules-parser.test.ts
# ---------------------------------------------------------------------------

class TestParseMavenModules(unittest.TestCase):
    """Tests for server._parse_maven_modules."""

    # Mirrors: maven-modules-parser.test.ts > single module
    def test_single_module(self):
        pom = "<project><modules><module>core</module></modules></project>"
        result = server._parse_maven_modules(pom)
        self.assertEqual(result, ["core"])

    # Mirrors: maven-modules-parser.test.ts > multiple modules
    def test_multiple_modules(self):
        pom = (
            "<modules>\n"
            "  <module>core</module>\n"
            "  <module>api</module>\n"
            "  <module>web</module>\n"
            "</modules>"
        )
        result = server._parse_maven_modules(pom)
        self.assertEqual(result, ["core", "api", "web"])

    # Mirrors: maven-modules-parser.test.ts > no modules
    def test_no_modules_returns_empty(self):
        result = server._parse_maven_modules("<project></project>")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# _parse_toml_catalog
# Mirrors: src/dependencies/__tests__/toml-parser.test.ts
# NOTE: Python returns plain dicts, TS returns Maps.
# ---------------------------------------------------------------------------

class TestParseTomlCatalog(unittest.TestCase):
    """Tests for server._parse_toml_catalog."""

    # Mirrors: toml-parser.test.ts > "parses libraries with version.ref"
    def test_libraries_with_version_ref(self):
        toml = (
            "[versions]\n"
            'ktor = "3.1.1"\n'
            'kotlin = "2.1.0"\n'
            "\n"
            "[libraries]\n"
            'ktor-client-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }\n'
            'kotlin-stdlib = { module = "org.jetbrains.kotlin:kotlin-stdlib", version.ref = "kotlin" }\n'
        )
        result = server._parse_toml_catalog(toml)
        libs = result["libraries"]
        self.assertIn("ktor-client-core", libs)
        self.assertEqual(libs["ktor-client-core"]["groupId"], "io.ktor")
        self.assertEqual(libs["ktor-client-core"]["artifactId"], "ktor-client-core")
        self.assertEqual(libs["ktor-client-core"]["version"], "3.1.1")
        self.assertEqual(libs["kotlin-stdlib"]["version"], "2.1.0")

    # Mirrors: toml-parser.test.ts > "parses libraries with inline version"
    def test_libraries_with_inline_version(self):
        toml = (
            "[libraries]\n"
            'gson = { module = "com.google.code.gson:gson", version = "2.11.0" }\n'
        )
        result = server._parse_toml_catalog(toml)
        lib = result["libraries"]["gson"]
        self.assertEqual(lib["groupId"], "com.google.code.gson")
        self.assertEqual(lib["artifactId"], "gson")
        self.assertEqual(lib["version"], "2.11.0")

    # Mirrors: toml-parser.test.ts > "parses libraries with group/name syntax"
    def test_libraries_with_group_name_syntax(self):
        toml = (
            "[versions]\n"
            'ktor = "3.1.1"\n'
            "\n"
            "[libraries]\n"
            'ktor-core = { group = "io.ktor", name = "ktor-client-core", version.ref = "ktor" }\n'
        )
        result = server._parse_toml_catalog(toml)
        lib = result["libraries"]["ktor-core"]
        self.assertEqual(lib["groupId"], "io.ktor")
        self.assertEqual(lib["artifactId"], "ktor-client-core")
        self.assertEqual(lib["version"], "3.1.1")

    # Mirrors: toml-parser.test.ts > "returns null version for libraries without version"
    def test_library_without_version_returns_none(self):
        toml = (
            "[libraries]\n"
            'bom-lib = { module = "io.ktor:ktor-bom" }\n'
        )
        result = server._parse_toml_catalog(toml)
        self.assertIsNone(result["libraries"]["bom-lib"]["version"])

    # Mirrors: toml-parser.test.ts > "returns empty maps for empty content"
    def test_empty_content_returns_empty_dicts(self):
        result = server._parse_toml_catalog("")
        self.assertEqual(result["libraries"], {})
        self.assertEqual(result["plugins"], {})
        self.assertEqual(result.get("versions", {}), {})

    # Mirrors: toml-parser.test.ts > "parses [plugins] with version.ref"
    def test_plugins_with_version_ref(self):
        toml = (
            "[versions]\n"
            'kotlin = "2.1.0"\n'
            "\n"
            "[plugins]\n"
            'kotlin-jvm = { id = "org.jetbrains.kotlin.jvm", version.ref = "kotlin" }\n'
        )
        result = server._parse_toml_catalog(toml)
        plugin = result["plugins"]["kotlin-jvm"]
        self.assertEqual(plugin["id"], "org.jetbrains.kotlin.jvm")
        self.assertEqual(plugin["version"], "2.1.0")

    # Mirrors: toml-parser.test.ts > "parses [plugins] with inline version"
    def test_plugins_with_inline_version(self):
        toml = (
            "[plugins]\n"
            'android-app = { id = "com.android.application", version = "8.5.0" }\n'
        )
        result = server._parse_toml_catalog(toml)
        plugin = result["plugins"]["android-app"]
        self.assertEqual(plugin["id"], "com.android.application")
        self.assertEqual(plugin["version"], "8.5.0")

    # Mirrors: toml-parser.test.ts > "parses [plugins] with no version returns null"
    def test_plugins_without_version_returns_none(self):
        toml = (
            "[plugins]\n"
            'my-plugin = { id = "com.example.plugin" }\n'
        )
        result = server._parse_toml_catalog(toml)
        self.assertIsNone(result["plugins"]["my-plugin"]["version"])

    # Source tracking: catalog returns plain dicts (no source tracking at this layer).
    # Source info (catalogName, tomlPath, alias) is added by scan_project().
    def test_multiple_libraries_dedup_by_alias(self):
        toml = (
            "[libraries]\n"
            'ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }\n'
            'ktor-json = { module = "io.ktor:ktor-serialization-json", version = "3.1.1" }\n'
        )
        result = server._parse_toml_catalog(toml)
        self.assertEqual(len(result["libraries"]), 2)
        self.assertIn("ktor-core", result["libraries"])
        self.assertIn("ktor-json", result["libraries"])


# ---------------------------------------------------------------------------
# _detect_build_system
# Mirrors: src/dependencies/__tests__/scan.test.ts (build system detection)
# ---------------------------------------------------------------------------

class TestDetectBuildSystem(unittest.TestCase):
    """Tests for server._detect_build_system via temp_project."""

    # Mirrors: scan.test.ts > buildSystem is "gradle" when build.gradle.kts present
    def test_gradle_from_build_gradle_kts(self):
        with temp_project({"build.gradle.kts": ""}) as root:
            self.assertEqual(server._detect_build_system(root), "gradle")

    # Mirrors: scan.test.ts > buildSystem is "gradle" when build.gradle present
    def test_gradle_from_build_gradle(self):
        with temp_project({"build.gradle": ""}) as root:
            self.assertEqual(server._detect_build_system(root), "gradle")

    # Mirrors: scan.test.ts > buildSystem is "gradle" when settings.gradle.kts present
    def test_gradle_from_settings_gradle_kts(self):
        with temp_project({"settings.gradle.kts": ""}) as root:
            self.assertEqual(server._detect_build_system(root), "gradle")

    # Mirrors: scan.test.ts > buildSystem is "gradle" via toml only
    def test_gradle_from_toml_only(self):
        with temp_project({"gradle/libs.versions.toml": ""}) as root:
            self.assertEqual(server._detect_build_system(root), "gradle")

    # Mirrors: scan.test.ts > buildSystem is "maven" when pom.xml present
    def test_maven_from_pom_xml(self):
        with temp_project({"pom.xml": "<project/>"}) as root:
            self.assertEqual(server._detect_build_system(root), "maven")

    # Mirrors: scan.test.ts > "returns empty for unknown project"
    def test_unknown_for_empty_directory(self):
        with temp_project({}) as root:
            self.assertEqual(server._detect_build_system(root), "unknown")


# ---------------------------------------------------------------------------
# scan_project — Gradle (end-to-end via temp_project)
# Mirrors: src/dependencies/__tests__/scan.test.ts (Gradle sections)
# ---------------------------------------------------------------------------

class TestScanProjectDeadRepositoryHints(unittest.TestCase):
    """Tests for server.scan_project()'s deadRepositoryHints signal (#284):
    jcenter() has been read-only since 2021 and fully sunset 15 Aug 2024."""

    def test_root_build_file_jcenter_flagged(self):
        files = {"build.gradle.kts": "repositories {\n    jcenter()\n    mavenCentral()\n}"}
        with temp_project(files) as root:
            result = server.scan_project(root)
        hints = result["deadRepositoryHints"]
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["repository"], "jcenter")
        self.assertEqual(hints[0]["file"], "build.gradle.kts")
        self.assertIsNone(hints[0]["module"])

    def test_settings_file_jcenter_flagged(self):
        files = {
            "settings.gradle.kts": (
                "dependencyResolutionManagement { repositories { jcenter() } }"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        hints = result["deadRepositoryHints"]
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["repository"], "jcenter")
        self.assertEqual(hints[0]["file"], "settings.gradle.kts")

    def test_module_build_file_jcenter_flagged_with_module_label(self):
        files = {
            "settings.gradle.kts": 'include(":app")',
            "app/build.gradle.kts": "repositories {\n    jcenter()\n}",
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        hints = result["deadRepositoryHints"]
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["module"], ":app")

    def test_no_jcenter_not_flagged(self):
        files = {"build.gradle.kts": "repositories {\n    mavenCentral()\n    google()\n}"}
        with temp_project(files) as root:
            result = server.scan_project(root)
        self.assertEqual(result["deadRepositoryHints"], [])

    def test_flatten_scan_result_preserves_dead_repository_hints(self):
        files = {"build.gradle.kts": "repositories {\n    jcenter()\n}"}
        with temp_project(files) as root:
            flattened = server.flatten_scan_result(server.scan_project(root))
        self.assertEqual(len(flattened["deadRepositoryHints"]), 1)
        self.assertEqual(flattened["deadRepositoryHints"][0]["repository"], "jcenter")


class TestScanProjectGradle(unittest.TestCase):
    """End-to-end tests for server.scan_project() on Gradle projects."""

    # Mirrors: scan.test.ts > "unused catalog library emitted once with kind catalog-library and empty usages"
    def test_unused_catalog_library_emitted_once_with_empty_usages(self):
        files = {
            "gradle/libs.versions.toml": (
                "[libraries]\n"
                'ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }\n'
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        self.assertEqual(result["buildSystem"], "gradle")
        deps = [d for d in result["dependencies"]
                if d["groupId"] == "io.ktor" and d["artifactId"] == "ktor-client-core"]
        self.assertEqual(len(deps), 1)
        dep = deps[0]
        self.assertEqual(dep["source"]["kind"], "catalog-library")
        self.assertEqual(dep["source"]["catalogName"], "libs")
        self.assertEqual(dep["source"]["tomlPath"], "gradle/libs.versions.toml")
        self.assertEqual(dep["source"]["alias"], "ktor-core")
        self.assertEqual(dep["usages"], [])

    # Mirrors: scan.test.ts > "used catalog library: usages populated, single entry (no duplicate)"
    def test_used_catalog_library_has_usage_and_no_duplicate(self):
        files = {
            "gradle/libs.versions.toml": (
                "[libraries]\n"
                'ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }\n'
            ),
            "build.gradle.kts": (
                "dependencies {\n"
                "    implementation(libs.ktor.core)\n"
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        deps = [d for d in result["dependencies"] if d.get("groupId") == "io.ktor"]
        # Only one entry — catalog entry populated with usage, no duplicate module-direct
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["source"]["kind"], "catalog-library")
        self.assertEqual(len(deps[0]["usages"]), 1)
        self.assertEqual(deps[0]["usages"][0]["module"], None)
        self.assertEqual(deps[0]["usages"][0]["configuration"], "implementation")

    # Mirrors: scan.test.ts > "catalog library used by two modules: one entry, two usages"
    def test_catalog_library_two_modules_two_usages(self):
        files = {
            "settings.gradle.kts": 'include(":app")\ninclude(":lib")',
            "gradle/libs.versions.toml": (
                "[libraries]\n"
                'ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }\n'
            ),
            "app/build.gradle.kts": (
                "dependencies {\n"
                "    implementation(libs.ktor.core)\n"
                "}"
            ),
            "lib/build.gradle.kts": (
                "dependencies {\n"
                "    api(libs.ktor.core)\n"
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        deps = [d for d in result["dependencies"]
                if d.get("groupId") == "io.ktor" and d["source"]["kind"] == "catalog-library"]
        self.assertEqual(len(deps), 1)
        self.assertEqual(len(deps[0]["usages"]), 2)
        configurations = {u["configuration"] for u in deps[0]["usages"]}
        self.assertIn("implementation", configurations)
        self.assertIn("api", configurations)

    # Mirrors: scan.test.ts > "catalog version drift: catalog says 1.0, module hardcodes 2.0"
    def test_catalog_version_drift_both_reported_separately(self):
        files = {
            "gradle/libs.versions.toml": (
                "[libraries]\n"
                'ktor-core = { module = "io.ktor:ktor-client-core", version = "1.0.0" }\n'
            ),
            "build.gradle.kts": (
                "dependencies {\n"
                "    implementation(libs.ktor.core)\n"
                '    implementation("io.ktor:ktor-client-core:2.0.0")\n'
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        deps = [d for d in result["dependencies"]
                if d.get("groupId") == "io.ktor" and d.get("artifactId") == "ktor-client-core"]
        self.assertEqual(len(deps), 2)
        catalog_dep = next(d for d in deps if d["source"]["kind"] == "catalog-library")
        direct_dep = next(d for d in deps if d["source"]["kind"] == "module-direct")
        self.assertEqual(catalog_dep["version"], "1.0.0")
        self.assertEqual(direct_dep["version"], "2.0.0")

    # Mirrors: scan.test.ts > "unused catalog plugin emitted with kind catalog-plugin and plugin marker artifactId"
    def test_unused_catalog_plugin_emitted(self):
        files = {
            "gradle/libs.versions.toml": (
                "[plugins]\n"
                'android-application = { id = "com.android.application", version = "8.5.0" }\n'
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("groupId") == "com.android.application"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["artifactId"], "com.android.application.gradle.plugin")
        self.assertEqual(dep["source"]["kind"], "catalog-plugin")
        self.assertEqual(dep["usages"], [])

    # Mirrors: scan.test.ts > "root plugins {} block: id("x") version "1.0" → kind plugins-dsl"
    def test_root_plugins_block_kind_plugins_dsl(self):
        files = {
            "build.gradle.kts": (
                'plugins {\n'
                '    id("com.android.application") version "8.5.0"\n'
                '}'
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("groupId") == "com.android.application"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["artifactId"], "com.android.application.gradle.plugin")
        self.assertEqual(dep["version"], "8.5.0")
        self.assertEqual(dep["source"]["kind"], "plugins-dsl")
        self.assertIsNone(dep["source"]["module"])
        self.assertNotIn("settingsBlock", dep["source"])
        self.assertEqual(len(dep["usages"]), 1)
        self.assertEqual(dep["usages"][0]["configuration"], "plugin-dsl")

    # Mirrors: scan.test.ts > "module-level plugins {} block → source.module :app"
    def test_module_level_plugins_block_has_module_label(self):
        files = {
            "settings.gradle.kts": 'include(":app")',
            "app/build.gradle.kts": (
                'plugins {\n'
                '    id("com.android.application") version "8.0.0"\n'
                '}'
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("groupId") == "com.android.application"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["source"]["kind"], "plugins-dsl")
        self.assertEqual(dep["source"]["module"], ":app")
        self.assertNotIn("settingsBlock", dep["source"])

    # Mirrors: scan.test.ts > "buildscript classpath → kind buildscript-classpath"
    def test_buildscript_classpath_kind(self):
        files = {
            "build.gradle.kts": (
                'buildscript {\n'
                '    dependencies {\n'
                '        classpath("com.android.tools.build:gradle:8.0.0")\n'
                '    }\n'
                '}'
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("artifactId") == "gradle"
                    and d.get("groupId") == "com.android.tools.build"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["source"]["kind"], "buildscript-classpath")
        self.assertEqual(len(dep["usages"]), 1)
        self.assertEqual(dep["usages"][0]["configuration"], "classpath")
        self.assertIsNone(dep["usages"][0]["module"])

    # Mirrors: scan.test.ts > "buildscript classpath in submodule is not scanned"
    def test_buildscript_classpath_in_submodule_not_scanned(self):
        files = {
            "settings.gradle.kts": 'include(":app")',
            "app/build.gradle.kts": (
                'buildscript {\n'
                '    dependencies {\n'
                '        classpath("com.example:submodule-classpath:1.0")\n'
                '    }\n'
                '}'
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("artifactId") == "submodule-classpath"), None)
        self.assertIsNone(dep)

    # Mirrors: scan.test.ts > "settings plugins block → settingsBlock: true in source"
    def test_settings_plugins_block_has_settings_block_flag(self):
        files = {
            "settings.gradle.kts": (
                'pluginManagement {\n'
                '    plugins {\n'
                '        id("com.gradle.plugin") version "1.0"\n'
                '    }\n'
                '}'
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("groupId") == "com.gradle.plugin"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["source"]["kind"], "plugins-dsl")
        self.assertTrue(dep["source"].get("settingsBlock"))

    # Mirrors: scan.test.ts > "no Gradle settings, only gradle/libs.versions.toml → default libs descriptor"
    def test_no_settings_file_default_catalog_used(self):
        files = {
            "gradle/libs.versions.toml": (
                "[libraries]\n"
                'gson = { module = "com.google.code.gson:gson", version = "2.11.0" }\n'
            ),
            "build.gradle.kts": (
                "dependencies {\n"
                "    implementation(libs.gson)\n"
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        self.assertEqual(result["buildSystem"], "gradle")
        dep = next((d for d in result["dependencies"]
                    if d.get("artifactId") == "gson"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(len(dep["usages"]), 1)

    # Mirrors: scan.test.ts > "alias(libs.plugins.x) in module resolves through catalog [plugins]"
    def test_alias_plugins_ref_in_module_resolves_catalog_plugin(self):
        files = {
            "settings.gradle.kts": 'include(":app")',
            "gradle/libs.versions.toml": (
                "[plugins]\n"
                'kotlin-android = { id = "org.jetbrains.kotlin.android", version = "2.0.0" }\n'
            ),
            "app/build.gradle.kts": (
                "plugins {\n"
                "    alias(libs.plugins.kotlin.android)\n"
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        deps = [d for d in result["dependencies"]
                if d.get("groupId") == "org.jetbrains.kotlin.android"]
        # Only one entry — the catalog plugin entry, no extra plugins-dsl dep
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["source"]["kind"], "catalog-plugin")
        self.assertEqual(len(deps[0]["usages"]), 1)
        self.assertEqual(deps[0]["usages"][0]["module"], ":app")
        self.assertEqual(deps[0]["usages"][0]["configuration"], "plugin-dsl")

    # Mirrors: scan.test.ts > "module-level plugin with apply false still emits"
    def test_module_level_plugin_apply_false_still_emits(self):
        files = {
            "settings.gradle.kts": 'include(":lib")',
            "lib/build.gradle.kts": (
                "plugins {\n"
                '    id("com.android.library") version "8.0.0" apply false\n'
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("groupId") == "com.android.library"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["source"]["kind"], "plugins-dsl")
        self.assertEqual(dep["source"]["module"], ":lib")

    # Gradle .gradle (Groovy) single-module end-to-end
    def test_gradle_groovy_single_module(self):
        files = {
            "build.gradle": (
                "dependencies {\n"
                "    implementation 'io.ktor:ktor-client-core:3.1.1'\n"
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        self.assertEqual(result["buildSystem"], "gradle")
        dep = next((d for d in result["dependencies"]
                    if d.get("artifactId") == "ktor-client-core"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["version"], "3.1.1")
        self.assertEqual(dep["source"]["kind"], "module-direct")

    # Gradle.kts multi-module end-to-end
    def test_gradle_kts_multi_module_submodule_deps(self):
        files = {
            "settings.gradle.kts": 'include(":core")\ninclude(":feature")',
            "core/build.gradle.kts": (
                "dependencies {\n"
                '    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")\n'
                "}"
            ),
            "feature/build.gradle.kts": (
                "dependencies {\n"
                '    implementation("com.squareup.retrofit2:retrofit:2.11.0")\n'
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        self.assertEqual(result["buildSystem"], "gradle")
        core_dep = next(
            (d for d in result["dependencies"] if d.get("artifactId") == "kotlinx-coroutines-core"),
            None,
        )
        feature_dep = next(
            (d for d in result["dependencies"] if d.get("artifactId") == "retrofit"),
            None,
        )
        self.assertIsNotNone(core_dep)
        self.assertEqual(core_dep["usages"][0]["module"], ":core")
        self.assertIsNotNone(feature_dep)
        self.assertEqual(feature_dep["usages"][0]["module"], ":feature")


# ---------------------------------------------------------------------------
# scan_project — buildSrc/ and build-logic/ convention-plugin discovery (#292)
# ---------------------------------------------------------------------------

class TestScanProjectBuildSrc(unittest.TestCase):
    """End-to-end tests for buildSrc/ and build-logic/ discovery in scan_project()."""

    def test_buildsrc_own_build_file_kind_buildsrc(self):
        files = {
            "settings.gradle.kts": "",
            "buildSrc/build.gradle.kts": (
                "dependencies {\n"
                '    implementation("com.squareup:javapoet:1.13.0")\n'
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("artifactId") == "javapoet"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["groupId"], "com.squareup")
        self.assertEqual(dep["source"]["kind"], "buildsrc")
        self.assertEqual(dep["source"]["file"], "buildSrc/build.gradle.kts")

    def test_buildsrc_convention_plugin_script_kind_convention_plugin(self):
        files = {
            "settings.gradle.kts": "",
            "buildSrc/src/main/kotlin/some-convention.gradle.kts": (
                "dependencies {\n"
                '    implementation("io.ktor:ktor-client-core:3.1.1")\n'
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("artifactId") == "ktor-client-core"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["source"]["kind"], "convention-plugin")
        self.assertEqual(
            dep["source"]["file"], "buildSrc/src/main/kotlin/some-convention.gradle.kts"
        )

    def test_build_logic_subproject_build_file_kind_convention_plugin(self):
        files = {
            "settings.gradle.kts": "",
            "build-logic/convention/build.gradle.kts": (
                "dependencies {\n"
                '    implementation("com.squareup:javapoet:1.13.0")\n'
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("artifactId") == "javapoet"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["source"]["kind"], "convention-plugin")
        self.assertEqual(dep["source"]["file"], "build-logic/convention/build.gradle.kts")

    def test_build_logic_convention_plugin_script_kind_convention_plugin(self):
        files = {
            "settings.gradle.kts": "",
            "build-logic/convention/src/main/kotlin/foo-convention.gradle.kts": (
                "dependencies {\n"
                '    implementation("io.ktor:ktor-client-core:3.1.1")\n'
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        dep = next((d for d in result["dependencies"]
                    if d.get("artifactId") == "ktor-client-core"), None)
        self.assertIsNotNone(dep)
        self.assertEqual(dep["source"]["kind"], "convention-plugin")
        self.assertEqual(
            dep["source"]["file"],
            "build-logic/convention/src/main/kotlin/foo-convention.gradle.kts",
        )

    def test_no_buildsrc_or_build_logic_no_new_kinds_emitted(self):
        files = {
            "build.gradle.kts": (
                "dependencies {\n"
                '    implementation("io.ktor:ktor-client-core:3.1.1")\n'
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        kinds = {d["source"]["kind"] for d in result["dependencies"]}
        self.assertNotIn("buildsrc", kinds)
        self.assertNotIn("convention-plugin", kinds)
        self.assertEqual(len(result["dependencies"]), 1)

    def test_module_and_buildsrc_each_counted_once_no_double_scan(self):
        files = {
            "settings.gradle.kts": 'include(":app")',
            "app/build.gradle.kts": (
                "dependencies {\n"
                '    implementation("io.ktor:ktor-client-core:3.1.1")\n'
                "}"
            ),
            "buildSrc/build.gradle.kts": (
                "dependencies {\n"
                '    implementation("com.squareup:javapoet:1.13.0")\n'
                "}"
            ),
        }
        with temp_project(files) as root:
            result = server.scan_project(root)
        ktor_deps = [d for d in result["dependencies"] if d.get("artifactId") == "ktor-client-core"]
        javapoet_deps = [d for d in result["dependencies"] if d.get("artifactId") == "javapoet"]
        self.assertEqual(len(ktor_deps), 1)
        self.assertEqual(ktor_deps[0]["source"]["kind"], "module-direct")
        self.assertEqual(ktor_deps[0]["source"]["module"], ":app")
        self.assertEqual(len(javapoet_deps), 1)
        self.assertEqual(javapoet_deps[0]["source"]["kind"], "buildsrc")
        buildsrc_file_entries = [
            d for d in result["dependencies"]
            if d["source"].get("file") == "buildSrc/build.gradle.kts"
        ]
        self.assertEqual(len(buildsrc_file_entries), 1)


# ---------------------------------------------------------------------------
# scan_project — Maven (end-to-end via temp_project)
# Mirrors: src/dependencies/__tests__/scan.test.ts (Maven sections)
# ---------------------------------------------------------------------------

class TestScanProjectMaven(unittest.TestCase):
    """End-to-end tests for server.scan_project() on Maven projects."""

    # Mirrors: scan.test.ts > "Maven project: each pom dep → kind module-direct, usages populated"
    def test_single_pom_dep_kind_module_direct(self):
        pom = (
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>io.ktor</groupId>\n"
            "      <artifactId>ktor-core</artifactId>\n"
            "      <version>3.1.1</version>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )
        with temp_project({"pom.xml": pom}) as root:
            result = server.scan_project(root)
        self.assertEqual(result["buildSystem"], "maven")
        self.assertEqual(len(result["dependencies"]), 1)
        dep = result["dependencies"][0]
        self.assertEqual(dep["groupId"], "io.ktor")
        self.assertEqual(dep["artifactId"], "ktor-core")
        self.assertEqual(dep["source"]["kind"], "module-direct")
        self.assertIsNone(dep["source"]["module"])
        self.assertEqual(len(dep["usages"]), 1)
        self.assertIsNone(dep["usages"][0]["module"])

    # Mirrors: scan.test.ts > "Maven submodule recursion preserved"
    def test_maven_multi_module_recursion(self):
        root_pom = (
            "<project>\n"
            "  <modules>\n"
            "    <module>core</module>\n"
            "  </modules>\n"
            "</project>"
        )
        core_pom = (
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>io.ktor</groupId>\n"
            "      <artifactId>ktor-core</artifactId>\n"
            "      <version>3.1.1</version>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )
        with temp_project({"pom.xml": root_pom, "core/pom.xml": core_pom}) as root:
            result = server.scan_project(root)
        self.assertEqual(result["buildSystem"], "maven")
        self.assertEqual(len(result["dependencies"]), 1)
        dep = result["dependencies"][0]
        self.assertEqual(dep["source"]["file"], "pom.xml")
        self.assertEqual(dep["usages"][0]["module"], "core")

    # Mirrors: scan.test.ts > "returns empty for unknown project"
    def test_unknown_project_returns_empty(self):
        with temp_project({}) as root:
            result = server.scan_project(root)
        self.assertEqual(result["buildSystem"], "unknown")
        self.assertEqual(result["dependencies"], [])


# ---------------------------------------------------------------------------
# _months_since — datetime.utcnow() deprecation (gap closed in #313)
# ---------------------------------------------------------------------------

class TestMonthsSince(unittest.TestCase):
    """Tests for server._months_since after the utcnow() -> now(timezone.utc)
    migration. The 3.13 CI leg promotes DeprecationWarning, so utcnow() must be
    gone, and the naive-UTC arithmetic semantics must be preserved exactly."""

    # The removed utcnow() emitted a DeprecationWarning on Python 3.12+; with the
    # warning promoted to an error, any residual utcnow() call would raise here.
    def test_no_deprecation_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            iso = "2020-01-01T00:00:00Z"
            result = server._months_since(iso)
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    # Semantics unchanged: the result is the integer-month delta between the
    # current naive-UTC clock and the parsed timestamp, identical to the old
    # utcnow()-based computation. Cross-check against an independent naive-UTC
    # reference using the same formula.
    def test_output_matches_naive_utc_reference(self):
        iso = "2021-06-15T12:00:00Z"
        result = server._months_since(iso)
        ref_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        ref_dt = datetime.datetime(2021, 6, 15, 12, 0, 0)
        expected = int((ref_now - ref_dt).days / 30)
        # Allow a 1-month tolerance for clock advance between the two reads.
        self.assertLessEqual(abs(result - expected), 1)

    # A recent timestamp yields a 0-month delta (not negative, not a crash).
    def test_recent_timestamp_returns_zero(self):
        recent = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        iso = recent.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(server._months_since(iso), 0)

    # None / unparseable input degrades to None (unchanged contract).
    def test_none_and_invalid_input(self):
        self.assertIsNone(server._months_since(None))
        self.assertIsNone(server._months_since("not-a-date"))


if __name__ == "__main__":
    unittest.main()

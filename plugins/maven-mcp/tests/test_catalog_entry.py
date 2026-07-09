"""Tests for catalog_entry generate/validate (#288).

Covers Gradle version-catalog rules: kebab→accessor mapping, reserved alias
names/first segments, plugin alias() vs id() misuse, and minimal diffs.
"""

import os
import tempfile
import unittest

from _helpers import server


class CatalogAliasHelpersTest(unittest.TestCase):
    def test_kebab_to_accessor_mapping(self):
        self.assertEqual(
            server._catalog_normalize_accessor_key("ktor-client-core"),
            "ktor.client.core",
        )
        self.assertEqual(server._library_accessor("ktor-client-core"), "libs.ktor.client.core")
        self.assertEqual(
            server._plugin_accessor("kotlin-android"),
            "alias(libs.plugins.kotlin.android)",
        )

    def test_camel_case_avoids_subgroup(self):
        # groovyCore → libs.groovyCore (single segment), not libs.groovy.core
        self.assertEqual(server._catalog_normalize_accessor_key("groovyCore"), "groovyCore")
        self.assertEqual(server._library_accessor("groovyCore"), "libs.groovyCore")

    def test_clash_key_merges_camel_and_kebab(self):
        self.assertEqual(server._catalog_clash_key("someAlias"), "some.alias")
        self.assertEqual(server._catalog_clash_key("some-alias"), "some.alias")

    def test_sanitize_rewrites_reserved_first_segment(self):
        # versions-dependency → versionsDependency (docs-approved form)
        self.assertEqual(
            server._sanitize_catalog_alias("versions-dependency"),
            "versionsDependency",
        )
        self.assertEqual(server._sanitize_catalog_alias("plugins"), "dep-plugins")
        self.assertEqual(server._sanitize_catalog_alias("class"), "dep-class")


class CatalogGenerateTest(unittest.TestCase):
    def test_generate_library_kebab_alias_and_accessor(self):
        result = server.handle_catalog_entry({
            "mode": "generate",
            "kind": "library",
            "coordinate": {
                "groupId": "io.ktor",
                "artifactId": "ktor-client-core",
                "version": "3.1.0",
            },
        })
        self.assertEqual(result["alias"], "ktor-client-core")
        self.assertEqual(result["accessor"], "libs.ktor.client.core")
        self.assertEqual(result["entry"]["section"], "libraries")
        self.assertEqual(result["entry"]["updateKind"], "add")
        self.assertIn('ktor-client-core = "3.1.0"', result["suggestedDiff"])
        self.assertIn(
            'ktor-client-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor-client-core" }',
            result["suggestedDiff"],
        )
        self.assertIn("implementation(libs.ktor.client.core)", result["suggestedDiff"])
        # Minimal snippet — not a full-file rewrite of unrelated sections.
        self.assertNotIn("[bundles]", result["suggestedDiff"])

    def test_generate_plugin_uses_alias_accessor(self):
        result = server.handle_catalog_entry({
            "mode": "generate",
            "kind": "plugin",
            "coordinate": {
                "groupId": "org.jetbrains.kotlin.android",
                "artifactId": "org.jetbrains.kotlin.android.gradle.plugin",
                "version": "2.0.21",
            },
        })
        self.assertEqual(result["alias"], "kotlin-android")
        self.assertEqual(result["accessor"], "alias(libs.plugins.kotlin.android)")
        self.assertEqual(result["entry"]["id"], "org.jetbrains.kotlin.android")
        self.assertIn("alias(libs.plugins.kotlin.android)", result["suggestedDiff"])
        self.assertIn("Do NOT write id(libs.plugins.kotlin.android)", result["suggestedDiff"])

    def test_generate_sanitizes_reserved_alias(self):
        result = server.handle_catalog_entry({
            "mode": "generate",
            "kind": "library",
            "alias": "versions-dependency",
            "coordinate": {
                "groupId": "org.sample",
                "artifactId": "lib",
                "version": "1.0",
            },
        })
        self.assertEqual(result["alias"], "versionsDependency")
        self.assertEqual(result["accessor"], "libs.versionsDependency")
        rules = {v["rule"] for v in result["violations"]}
        self.assertIn("alias_sanitized", rules)
        self.assertIn("reserved_first_segment", rules)

    def test_generate_version_ref_bump_is_minimal(self):
        catalog = (
            "[versions]\n"
            'ktor = "3.0.0"\n'
            "\n"
            "[libraries]\n"
            'ktor-client-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }\n'
        )
        result = server.handle_catalog_entry({
            "mode": "generate",
            "kind": "library",
            "alias": "ktor-client-core",
            "catalogToml": catalog,
            "coordinate": {
                "groupId": "io.ktor",
                "artifactId": "ktor-client-core",
                "version": "3.1.0",
            },
        })
        self.assertEqual(result["entry"]["updateKind"], "version_ref_bump")
        self.assertEqual(
            result["suggestedDiff"].strip(),
            '# Update existing [versions] key only\nktor = "3.1.0"',
        )
        self.assertNotIn("[libraries]", result["suggestedDiff"])

    def test_generate_avoids_existing_alias_clash(self):
        catalog = (
            "[libraries]\n"
            'ktor-client-core = { module = "io.ktor:ktor-client-core", version = "3.0.0" }\n'
        )
        result = server.handle_catalog_entry({
            "mode": "generate",
            "kind": "library",
            "catalogToml": catalog,
            "coordinate": {
                "groupId": "io.ktor",
                "artifactId": "ktor-client-core",
                "version": "3.1.0",
            },
        })
        # Existing alias → version bump path (same alias), not a second clashing alias.
        self.assertEqual(result["alias"], "ktor-client-core")
        self.assertEqual(result["entry"]["updateKind"], "inline_or_line_replace")


class CatalogValidateTest(unittest.TestCase):
    def test_validate_flags_reserved_and_first_segment(self):
        result = server.handle_catalog_entry({
            "mode": "validate",
            "catalogToml": (
                "[libraries]\n"
                'versions-dependency = { module = "org.sample:lib", version = "1.0" }\n'
                'class = { module = "org.sample:x", version = "1.0" }\n'
            ),
            "catalogPath": "gradle/libs.versions.toml",
        })
        rules = {v["rule"] for v in result["violations"]}
        self.assertIn("reserved_first_segment", rules)
        self.assertIn("reserved_alias", rules)

    def test_validate_flags_accessor_clash(self):
        result = server.handle_catalog_entry({
            "mode": "validate",
            "catalogToml": (
                "[libraries]\n"
                'someAlias = { module = "org.sample:a", version = "1.0" }\n'
                'some-alias = { module = "org.sample:b", version = "2.0" }\n'
            ),
        })
        rules = {v["rule"] for v in result["violations"]}
        self.assertIn("accessor_clash", rules)

    def test_validate_flags_undefined_version_ref(self):
        result = server.handle_catalog_entry({
            "mode": "validate",
            "catalogToml": (
                "[libraries]\n"
                'lib = { module = "org.sample:lib", version.ref = "missing" }\n'
            ),
        })
        rules = {v["rule"] for v in result["violations"]}
        self.assertIn("undefined_version_ref", rules)

    def test_validate_flags_plugin_id_misuse(self):
        result = server.handle_catalog_entry({
            "mode": "validate",
            "catalogToml": (
                "[plugins]\n"
                'android = { id = "com.android.application", version = "8.7.0" }\n'
            ),
            "buildContent": 'plugins {\n    id(libs.plugins.android)\n}\n',
        })
        rules = {v["rule"] for v in result["violations"]}
        self.assertIn("plugin_id_accessor_misuse", rules)
        detail = next(v["detail"] for v in result["violations"] if v["rule"] == "plugin_id_accessor_misuse")
        self.assertIn("alias(libs.plugins.android)", detail)

    def test_validate_flags_libs_in_subprojects(self):
        result = server.handle_catalog_entry({
            "mode": "validate",
            "catalogToml": "[libraries]\n",
            "buildContent": (
                "subprojects {\n"
                "    dependencies {\n"
                "        implementation(libs.foo.bar)\n"
                "    }\n"
                "}\n"
            ),
        })
        rules = {v["rule"] for v in result["violations"]}
        self.assertIn("libs_accessor_unavailable_in_block", rules)

    def test_validate_flags_wrong_default_catalog_path(self):
        result = server.handle_catalog_entry({
            "mode": "validate",
            "catalogToml": "[libraries]\n",
            "catalogPath": "libs.versions.toml",
        })
        rules = {v["rule"] for v in result["violations"]}
        self.assertIn("catalog_path", rules)

    def test_validate_clean_catalog(self):
        result = server.handle_catalog_entry({
            "mode": "validate",
            "catalogToml": (
                "[versions]\n"
                'ktor = "3.1.0"\n'
                "\n"
                "[libraries]\n"
                'ktor-client-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }\n'
                "\n"
                "[plugins]\n"
                'android-application = { id = "com.android.application", version = "8.7.0" }\n'
            ),
            "buildContent": (
                "plugins {\n"
                "    alias(libs.plugins.android.application)\n"
                "}\n"
                "dependencies {\n"
                "    implementation(libs.ktor.client.core)\n"
                "}\n"
            ),
            "catalogPath": "gradle/libs.versions.toml",
        })
        self.assertEqual(result["violations"], [])

    def test_validate_reads_project_default_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            gradle_dir = os.path.join(tmp, "gradle")
            os.makedirs(gradle_dir)
            with open(os.path.join(gradle_dir, "libs.versions.toml"), "w", encoding="utf-8") as fh:
                fh.write(
                    "[libraries]\n"
                    'class = { module = "org.sample:x", version = "1.0" }\n'
                )
            result = server.handle_catalog_entry({
                "mode": "validate",
                "projectPath": tmp,
            })
            rules = {v["rule"] for v in result["violations"]}
            self.assertIn("reserved_alias", rules)


class CatalogHandlerErrorsTest(unittest.TestCase):
    def test_invalid_mode(self):
        result = server.handle_catalog_entry({"mode": "rewrite"})
        self.assertIn("error", result)
        self.assertEqual(result["violations"][0]["rule"], "invalid_mode")

    def test_generate_requires_coordinate(self):
        result = server.handle_catalog_entry({"mode": "generate"})
        self.assertIn("error", result)
        self.assertEqual(result["violations"][0]["rule"], "missing_coordinate")


if __name__ == "__main__":
    unittest.main()

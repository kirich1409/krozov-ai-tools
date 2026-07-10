"""Gradle-resolved dependency scanning (#392 / #393 / #394)."""

import os
import subprocess
import unittest
import unittest.mock

from _helpers import mock_gradle_resolve, server, temp_project, write_fake_gradlew


RUNTIME_CLASSPATH_FIXTURE = """
------------------------------------------------------------
Project ':app'
------------------------------------------------------------

releaseRuntimeClasspath - Runtime classpath of source set 'main'.

+--- io.ktor:ktor-client-core:3.1.1 -> 3.1.2
\\--- com.squareup.okhttp3:okhttp:4.12.0
"""

BUILD_ENVIRONMENT_FIXTURE = """
------------------------------------------------------------
Root project 'demo'
------------------------------------------------------------

classpath
+--- com.android.tools.build:gradle:8.0.0
\\--- org.jetbrains.kotlin:kotlin-gradle-plugin:2.0.0
"""

KMP_PROBE_FIXTURE = """
releaseRuntimeClasspath - Runtime classpath of source set 'main'.
debugRuntimeClasspath - Runtime classpath of source set 'main'.
releaseCompileClasspath - Compile classpath of source set 'main'.
compileClasspath - Compile classpath of source set 'main'.
runtimeClasspath - Runtime classpath of 'main'.
testRuntimeClasspath - Runtime classpath of source set 'test'.
"""

PROJECTS_FIXTURE = """
Root project 'demo'
\\--- Project ':app'
"""


def _default_integration_mapping():
    """Gradle command stdout mapping for probe-based resolve integration tests."""
    return {
        ("-q", "projects"): PROJECTS_FIXTURE,
        ("-q", ":app:dependencies"): KMP_PROBE_FIXTURE,
        ("-q", "dependencies"): "",
        ("-q", ":app:dependencies", "--configuration", "releaseRuntimeClasspath"): RUNTIME_CLASSPATH_FIXTURE,
        ("-q", ":app:dependencies", "--configuration", "debugRuntimeClasspath"): "",
        ("-q", ":app:dependencies", "--configuration", "runtimeClasspath"): "",
        ("-q", "dependencies", "--configuration", "releaseRuntimeClasspath"): "",
        ("-q", "dependencies", "--configuration", "runtimeClasspath"): "",
        ("-q", "buildEnvironment"): "",
    }


class TestParseGavFromDependencyLine(unittest.TestCase):
    def test_plain_gav(self):
        self.assertEqual(
            server._parse_gav_from_dependency_line("io.ktor:ktor-client-core:3.1.1"),
            ("io.ktor", "ktor-client-core", "3.1.1"),
        )

    def test_version_substitution(self):
        self.assertEqual(
            server._parse_gav_from_dependency_line("io.ktor:ktor-client-core:3.1.1 -> 3.1.2"),
            ("io.ktor", "ktor-client-core", "3.1.2"),
        )

    def test_constraint_suffix(self):
        self.assertEqual(
            server._parse_gav_from_dependency_line("org.jetbrains.kotlin:kotlin-stdlib:1.9.0 (c)"),
            ("org.jetbrains.kotlin", "kotlin-stdlib", "1.9.0"),
        )

    def test_unresolved_suffix(self):
        self.assertEqual(
            server._parse_gav_from_dependency_line("com.example:missing:1.0 (n)"),
            ("com.example", "missing", "1.0"),
        )

    def test_repeated_subtree_suffix(self):
        self.assertEqual(
            server._parse_gav_from_dependency_line("com.example:lib:1.0 (*)"),
            ("com.example", "lib", "1.0"),
        )

    def test_project_dependency_skipped(self):
        self.assertIsNone(server._parse_gav_from_dependency_line("project :core"))


class TestParseGradleDependenciesStdout(unittest.TestCase):
    def test_direct_dependencies_only(self):
        stdout = (
            "releaseRuntimeClasspath\n"
            "+--- io.ktor:ktor-client-core:3.1.1\n"
            "|    \\--- org.jetbrains.kotlin:kotlin-stdlib:1.9.0\n"
            "\\--- com.squareup.okhttp3:okhttp:4.12.0\n"
        )
        deps = server._parse_gradle_dependencies_stdout(stdout, ":app", "releaseRuntimeClasspath")
        gas = {(d["groupId"], d["artifactId"], d["version"]) for d in deps}
        self.assertEqual(
            gas,
            {
                ("io.ktor", "ktor-client-core", "3.1.1"),
                ("com.squareup.okhttp3", "okhttp", "4.12.0"),
            },
        )
        self.assertTrue(all(d["resolvedBy"] == "gradle" for d in deps))

    def test_skips_unresolved_n_suffix(self):
        stdout = (
            "releaseRuntimeClasspath\n"
            "+--- com.example:present:1.0\n"
            "\\--- com.example:missing:2.0 (n)\n"
        )
        deps = server._parse_gradle_dependencies_stdout(stdout, ":app", "releaseRuntimeClasspath")
        gas = {(d["groupId"], d["artifactId"]) for d in deps}
        self.assertEqual(gas, {("com.example", "present")})

    def test_fixture_runtime_classpath(self):
        deps = server._parse_gradle_dependencies_stdout(
            RUNTIME_CLASSPATH_FIXTURE, ":app", "releaseRuntimeClasspath"
        )
        by_ga = {(d["groupId"], d["artifactId"]): d for d in deps}
        self.assertEqual(by_ga[("io.ktor", "ktor-client-core")]["version"], "3.1.2")
        self.assertEqual(by_ga[("com.squareup.okhttp3", "okhttp")]["version"], "4.12.0")

    def test_build_environment_classpath(self):
        deps = server._parse_build_environment_classpath(BUILD_ENVIRONMENT_FIXTURE)
        gas = {(d["groupId"], d["artifactId"]) for d in deps}
        self.assertEqual(
            gas,
            {
                ("com.android.tools.build", "gradle"),
                ("org.jetbrains.kotlin", "kotlin-gradle-plugin"),
            },
        )
        self.assertTrue(all(d["usages"][0]["configuration"] == "classpath" for d in deps))


class TestGradleConfigurationSelection(unittest.TestCase):
    def test_probe_based_config_selection_prefers_release_runtime(self):
        selected = server._select_configurations_to_resolve(
            server._parse_gradle_configuration_headers(KMP_PROBE_FIXTURE)
        )
        self.assertIn("releaseRuntimeClasspath", selected)
        self.assertIn("debugRuntimeClasspath", selected)
        self.assertNotIn("runtimeClasspath", selected)
        self.assertNotIn("compileClasspath", selected)
        self.assertNotIn("releaseCompileClasspath", selected)
        self.assertNotIn("testRuntimeClasspath", selected)


class TestRunGradleCommand(unittest.TestCase):
    def test_timeout_expired_returns_124(self):
        def _raise_timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="gradlew", timeout=1)

        with unittest.mock.patch.object(server, "_gradle_run", side_effect=_raise_timeout):
            code, stdout, stderr = server._run_gradle_command("/tmp", "gradlew", ["-q", "projects"])
        self.assertEqual(code, 124)
        self.assertEqual(stdout, "")
        self.assertIn("timed out", stderr)


class TestMergeGradleWithProvenance(unittest.TestCase):
    def test_provenance_only_plugin_included(self):
        resolved = [{
            "groupId": "io.ktor",
            "artifactId": "ktor-client-core",
            "version": "3.1.2",
            "usages": [{"module": ":app", "configuration": "releaseRuntimeClasspath"}],
        }]
        provenance = [
            {
                "groupId": "io.ktor",
                "artifactId": "ktor-client-core",
                "version": "3.1.1",
                "source": {"kind": "catalog-library", "alias": "ktor-core"},
                "usages": [{"module": ":app", "configuration": "implementation"}],
            },
            {
                "groupId": "org.jetbrains.kotlin.android",
                "artifactId": "org.jetbrains.kotlin.android.gradle.plugin",
                "version": "2.0.0",
                "source": {"kind": "plugins-dsl", "file": "build.gradle.kts"},
                "usages": [{"module": None, "configuration": "plugin-dsl"}],
            },
        ]
        merged = server._merge_gradle_with_provenance(resolved, provenance)
        plugin = next(
            d for d in merged
            if d["artifactId"] == "org.jetbrains.kotlin.android.gradle.plugin"
        )
        self.assertEqual(plugin["resolvedBy"], "provenance")
        self.assertEqual(plugin["source"]["kind"], "plugins-dsl")

    def test_unused_catalog_entry_preserved_when_ga_resolved(self):
        resolved = [{
            "groupId": "com.example",
            "artifactId": "lib",
            "version": "2.0",
            "usages": [{"module": ":app", "configuration": "releaseRuntimeClasspath"}],
        }]
        provenance = [
            {
                "groupId": "com.example",
                "artifactId": "lib",
                "version": "1.0",
                "source": {
                    "kind": "catalog-library",
                    "alias": "unused-lib",
                    "tomlPath": "gradle/libs.versions.toml",
                },
                "usages": [],
            },
        ]
        merged = server._merge_gradle_with_provenance(resolved, provenance)
        self.assertEqual(len(merged), 2)
        unused = next(
            d for d in merged
            if d.get("source", {}).get("alias") == "unused-lib"
        )
        self.assertEqual(unused["resolvedBy"], "provenance")
        self.assertEqual(unused["version"], "1.0")
        gradle_entry = next(d for d in merged if d.get("resolvedBy") == "gradle")
        self.assertEqual(gradle_entry["source"]["kind"], "gradle-resolved")


class TestGradleConflictDetection(unittest.TestCase):
    def test_detect_conflicts_from_gradle_scan_usages(self):
        scan = {
            "buildSystem": "gradle",
            "resolvedBy": "gradle",
            "dependencies": [
                {
                    "groupId": "com.example",
                    "artifactId": "lib",
                    "version": "2.0",
                    "usages": [{"module": ":app", "configuration": "releaseRuntimeClasspath"}],
                },
                {
                    "groupId": "com.example",
                    "artifactId": "lib",
                    "version": "1.0",
                    "usages": [{"module": ":core", "configuration": "releaseRuntimeClasspath"}],
                },
            ],
        }
        out = server._detect_conflicts_from_gradle_scan(scan)
        self.assertEqual(len(out["conflicts"]), 1)
        conflict = out["conflicts"][0]
        self.assertEqual(conflict["resolvedTo"], "2.0")
        self.assertEqual(conflict["strategy"], "highest-wins")
        self.assertTrue(any("Gradle-resolved" in n for n in out["notes"]))


class TestGradleResolveIntegration(unittest.TestCase):
    def _mock_run(self, mapping):
        def _fake_run(project_root, gradlew, args, timeout=server.GRADLE_RESOLVE_TIMEOUT):
            key = tuple(args)
            if key not in mapping:
                return 1, "", "task failed"
            return 0, mapping[key], ""

        return unittest.mock.patch.object(server, "_run_gradle_command", _fake_run)

    def test_scan_project_merges_gradle_with_provenance(self):
        files = {
            "settings.gradle.kts": 'include(":app")',
            "gradle/libs.versions.toml": (
                "[libraries]\n"
                'ktor-core = { module = "io.ktor:ktor-client-core", version = "3.1.1" }\n'
            ),
            "app/build.gradle.kts": (
                "dependencies {\n"
                "    implementation(libs.ktor.core)\n"
                "}"
            ),
        }
        with temp_project(files) as root:
            write_fake_gradlew(root)
            with self._mock_run(_default_integration_mapping()):
                result = server.scan_project(root)
        dep = next(
            d for d in result["dependencies"]
            if d["groupId"] == "io.ktor" and d["artifactId"] == "ktor-client-core"
            and d.get("resolvedBy") == "gradle"
        )
        self.assertEqual(dep["version"], "3.1.2")
        self.assertEqual(dep["source"]["kind"], "catalog-library")
        self.assertEqual(dep["source"]["alias"], "ktor-core")
        self.assertEqual(result["resolvedBy"], "gradle")

    def test_missing_gradlew_raises_clear_error(self):
        files = {"build.gradle.kts": 'plugins { id("java") }'}
        with temp_project(files) as root:
            with self.assertRaises(ValueError) as ctx:
                server.scan_project(root)
        self.assertIn("Gradle wrapper", str(ctx.exception))

    def test_resolution_errors_raise_when_no_dependencies(self):
        files = {"build.gradle.kts": 'plugins { id("java") }'}
        with temp_project(files) as root:
            write_fake_gradlew(root)
            with mock_gradle_resolve(errors=["Gradle daemon unavailable"], dependencies=[]):
                with self.assertRaises(ValueError) as ctx:
                    server.scan_project(root)
        self.assertIn("Gradle dependency resolution failed", str(ctx.exception))

    def test_only_classpath_deps_raises(self):
        files = {"build.gradle.kts": 'plugins { id("java") }'}
        mapping = {
            ("-q", "projects"): "Root project 'demo'\n",
            ("-q", "dependencies"): "",
            ("-q", "dependencies", "--configuration", "releaseRuntimeClasspath"): "",
            ("-q", "dependencies", "--configuration", "runtimeClasspath"): "",
            ("-q", "buildEnvironment"): BUILD_ENVIRONMENT_FIXTURE,
        }
        with temp_project(files) as root:
            write_fake_gradlew(root)
            with self._mock_run(mapping):
                with self.assertRaises(ValueError) as ctx:
                    server.scan_project(root)
        self.assertIn("No production runtime dependencies resolved", str(ctx.exception))

    def test_all_silent_task_failures_raise(self):
        files = {"build.gradle.kts": 'plugins { id("java") }'}
        with temp_project(files) as root:
            write_fake_gradlew(root)
            with unittest.mock.patch.object(
                server, "_run_gradle_command", return_value=(1, "", "")
            ):
                with self.assertRaises(ValueError) as ctx:
                    server.scan_project(root)
        self.assertIn("Gradle dependency resolution failed", str(ctx.exception))

    def test_partial_failure_surfaces_gradle_errors(self):
        files = {
            "settings.gradle.kts": 'include(":app")',
            "app/build.gradle.kts": (
                "dependencies {\n"
                '    implementation("io.ktor:ktor-client-core:3.1.1")\n'
                "}"
            ),
        }
        mapping = dict(_default_integration_mapping())
        mapping[("-q", ":app:dependencies", "--configuration", "debugRuntimeClasspath")] = (
            "Configuration debugRuntimeClasspath not found"
        )

        def _fake_run(project_root, gradlew, args, timeout=server.GRADLE_RESOLVE_TIMEOUT):
            key = tuple(args)
            if key == ("-q", ":app:dependencies", "--configuration", "debugRuntimeClasspath"):
                return 1, "", "Configuration debugRuntimeClasspath not found"
            if key not in mapping:
                return 1, "", "task failed"
            return 0, mapping[key], ""

        with temp_project(files) as root:
            write_fake_gradlew(root)
            with unittest.mock.patch.object(server, "_run_gradle_command", _fake_run):
                result = server.scan_project(root)
        self.assertTrue(any("debugRuntimeClasspath" in e for e in result.get("gradleErrors", [])))
        flat = server.flatten_scan_result(result)
        self.assertIn("gradleErrors", flat)


class TestFlattenScanResultResolvedBy(unittest.TestCase):
    def test_top_level_and_entry_resolved_by(self):
        scan = {
            "buildSystem": "gradle",
            "resolvedBy": "gradle",
            "dependencies": [{
                "groupId": "com.example",
                "artifactId": "lib",
                "version": "1.0",
                "resolvedBy": "gradle",
                "source": {"kind": "gradle-resolved"},
                "usages": [{"module": None, "configuration": "releaseRuntimeClasspath"}],
            }],
            "deadRepositoryHints": [],
        }
        flat = server.flatten_scan_result(scan)
        self.assertEqual(flat["resolvedBy"], "gradle")
        self.assertEqual(flat["dependencies"][0]["resolvedBy"], "gradle")


if __name__ == "__main__":
    unittest.main()

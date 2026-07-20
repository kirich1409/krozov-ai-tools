"""Gradle-resolved dependency scanning (#392 / #393 / #394 / #401).

#401 collapsed the previous "1 probe + P*(1+C) `gradlew` invocations" model
into a single ``--init-script`` invocation whose Groovy script dumps resolved
first-level GAVs for every project/configuration plus the buildscript
classpath in one configuration phase. These tests exercise: the init-script
generator, the single-invocation output parser, and the end-to-end
``_gradle_resolve_dependencies``/``scan_project`` behavior against mocked
``_run_gradle_command`` output shaped like a real init-script dump.
"""

import os
import subprocess
import unittest
import unittest.mock

from _helpers import (
    mock_gradle_resolve,
    server,
    temp_project,
    write_fake_gradlew,
    write_smart_gradlew,
)


# A two-module (root ":" + ":app") single-invocation dump: ":app" resolves
# io.ktor via releaseRuntimeClasspath (with conflict-resolution substitution
# already applied, matching what `resolutionResult` reports — no "->" text to
# parse), plus a root buildscript classpath entry.
SINGLE_INVOCATION_FIXTURE = (
    "===MAVEN_MCP_MODULE=== :\n"
    "===MAVEN_MCP_MODULE_END===\n"
    "===MAVEN_MCP_MODULE=== :app\n"
    "===MAVEN_MCP_CONFIG=== releaseRuntimeClasspath\n"
    "io.ktor:ktor-client-core:3.1.2\n"
    "com.squareup.okhttp3:okhttp:4.12.0\n"
    "===MAVEN_MCP_CONFIG_END===\n"
    "===MAVEN_MCP_CONFIG=== compileClasspath\n"
    "io.ktor:ktor-client-core:3.1.2\n"
    "===MAVEN_MCP_CONFIG_END===\n"
    "===MAVEN_MCP_MODULE_END===\n"
    "===MAVEN_MCP_BUILDENV===\n"
    "com.android.tools.build:gradle:8.0.0\n"
    "org.jetbrains.kotlin:kotlin-gradle-plugin:2.0.0\n"
    "===MAVEN_MCP_BUILDENV_END===\n"
)

CONFIG_ERROR_FIXTURE = (
    "===MAVEN_MCP_MODULE=== :app\n"
    "===MAVEN_MCP_CONFIG=== releaseRuntimeClasspath\n"
    "io.ktor:ktor-client-core:3.1.2\n"
    "===MAVEN_MCP_CONFIG_END===\n"
    "===MAVEN_MCP_CONFIG=== debugRuntimeClasspath\n"
    "===MAVEN_MCP_CONFIG_ERROR=== org.gradle.api.internal.artifacts.ivyservice.ResolveException: Could not resolve all dependencies\n"
    "===MAVEN_MCP_CONFIG_END===\n"
    "===MAVEN_MCP_MODULE_END===\n"
    "===MAVEN_MCP_BUILDENV===\n"
    "===MAVEN_MCP_BUILDENV_END===\n"
)

ONLY_BUILDENV_FIXTURE = (
    "===MAVEN_MCP_MODULE=== :\n"
    "===MAVEN_MCP_MODULE_END===\n"
    "===MAVEN_MCP_BUILDENV===\n"
    "com.android.tools.build:gradle:8.0.0\n"
    "===MAVEN_MCP_BUILDENV_END===\n"
)


class TestGenerateGradleResolveInitScript(unittest.TestCase):
    def test_script_contains_expected_markers_and_apis(self):
        script = server._generate_gradle_resolve_init_script()
        # Marker protocol the parser depends on.
        for marker in (
            "===MAVEN_MCP_MODULE===",
            "===MAVEN_MCP_MODULE_END===",
            "===MAVEN_MCP_CONFIG===",
            "===MAVEN_MCP_CONFIG_ERROR===",
            "===MAVEN_MCP_CONFIG_END===",
            "===MAVEN_MCP_BUILDENV===",
            "===MAVEN_MCP_BUILDENV_ERROR===",
            "===MAVEN_MCP_BUILDENV_END===",
        ):
            self.assertIn(marker, script)
        # Modern resolutionResult API (never throws ResolveException) and the
        # project-vs-module distinction that excludes project(":x") deps.
        self.assertIn("resolutionResult", script)
        self.assertIn("ResolvedDependencyResult", script)
        self.assertIn("ModuleComponentIdentifier", script)
        self.assertIn("canBeResolved", script)
        self.assertIn("projectsEvaluated", script)

    def test_no_untrusted_interpolation(self):
        # Static script string, not an f-string / .format() with project data.
        script = server._generate_gradle_resolve_init_script()
        self.assertNotIn("{project_root}", script)


class TestParseSingleInvocationGradleOutput(unittest.TestCase):
    def test_multi_module_parse(self):
        modules, errors, buildenv, buildenv_error = server._parse_single_invocation_gradle_output(
            SINGLE_INVOCATION_FIXTURE
        )
        self.assertEqual(set(modules.keys()), {":", ":app"})
        self.assertEqual(modules[":"], {})
        self.assertEqual(
            set(modules[":app"].keys()), {"releaseRuntimeClasspath", "compileClasspath"}
        )
        self.assertEqual(
            modules[":app"]["releaseRuntimeClasspath"],
            [("io.ktor", "ktor-client-core", "3.1.2"), ("com.squareup.okhttp3", "okhttp", "4.12.0")],
        )
        self.assertEqual(errors, [])
        self.assertEqual(
            set(buildenv),
            {
                ("com.android.tools.build", "gradle", "8.0.0"),
                ("org.jetbrains.kotlin", "kotlin-gradle-plugin", "2.0.0"),
            },
        )
        self.assertIsNone(buildenv_error)

    def test_per_config_error_isolated_from_sibling_config(self):
        modules, errors, _buildenv, _buildenv_error = server._parse_single_invocation_gradle_output(
            CONFIG_ERROR_FIXTURE
        )
        # The failing debugRuntimeClasspath config must not blank out the
        # sibling releaseRuntimeClasspath config resolved in the same module.
        self.assertEqual(
            modules[":app"]["releaseRuntimeClasspath"],
            [("io.ktor", "ktor-client-core", "3.1.2")],
        )
        self.assertEqual(modules[":app"]["debugRuntimeClasspath"], [])
        self.assertTrue(any(":app:debugRuntimeClasspath resolution error:" in e for e in errors))

    def test_buildenv_error_marker(self):
        stdout = (
            "===MAVEN_MCP_MODULE=== :\n"
            "===MAVEN_MCP_MODULE_END===\n"
            "===MAVEN_MCP_BUILDENV===\n"
            "===MAVEN_MCP_BUILDENV_ERROR=== java.lang.Exception: boom\n"
            "===MAVEN_MCP_BUILDENV_END===\n"
        )
        _modules, _errors, buildenv, buildenv_error = server._parse_single_invocation_gradle_output(stdout)
        self.assertEqual(buildenv, [])
        self.assertIn("boom", buildenv_error)


class TestGradleConfigurationSelection(unittest.TestCase):
    def test_selection_prefers_release_runtime(self):
        available = [
            "releaseRuntimeClasspath",
            "debugRuntimeClasspath",
            "releaseCompileClasspath",
            "compileClasspath",
            "runtimeClasspath",
            "testRuntimeClasspath",
        ]
        selected = server._select_configurations_to_resolve(available)
        self.assertIn("releaseRuntimeClasspath", selected)
        self.assertIn("debugRuntimeClasspath", selected)
        self.assertNotIn("runtimeClasspath", selected)
        self.assertNotIn("compileClasspath", selected)
        self.assertNotIn("releaseCompileClasspath", selected)
        self.assertNotIn("testRuntimeClasspath", selected)


class TestGradleResolveTimeoutOverride(unittest.TestCase):
    """MAVEN_MCP_GRADLE_TIMEOUT override for the single-invocation timeout scope
    change (#401 code review follow-up): the timeout now bounds ONE invocation
    resolving every project/configuration, not one subprocess call per config,
    so it must be overridable for very large multi-module projects."""

    def test_default_when_unset(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAVEN_MCP_GRADLE_TIMEOUT", None)
            self.assertEqual(server._gradle_resolve_timeout_seconds(), server.GRADLE_RESOLVE_TIMEOUT)

    def test_valid_override_used(self):
        with unittest.mock.patch.dict(os.environ, {"MAVEN_MCP_GRADLE_TIMEOUT": "600"}):
            self.assertEqual(server._gradle_resolve_timeout_seconds(), 600)

    def test_non_integer_falls_back_to_default(self):
        with unittest.mock.patch.dict(os.environ, {"MAVEN_MCP_GRADLE_TIMEOUT": "not-a-number"}):
            self.assertEqual(server._gradle_resolve_timeout_seconds(), server.GRADLE_RESOLVE_TIMEOUT)

    def test_non_positive_falls_back_to_default(self):
        with unittest.mock.patch.dict(os.environ, {"MAVEN_MCP_GRADLE_TIMEOUT": "0"}):
            self.assertEqual(server._gradle_resolve_timeout_seconds(), server.GRADLE_RESOLVE_TIMEOUT)
        with unittest.mock.patch.dict(os.environ, {"MAVEN_MCP_GRADLE_TIMEOUT": "-5"}):
            self.assertEqual(server._gradle_resolve_timeout_seconds(), server.GRADLE_RESOLVE_TIMEOUT)

    def test_gradle_resolve_dependencies_passes_override_as_timeout(self):
        captured = {}

        def _fake_run(project_root, gradlew, args, timeout=server.GRADLE_RESOLVE_TIMEOUT):
            captured["timeout"] = timeout
            return 0, SINGLE_INVOCATION_FIXTURE, ""

        with temp_project({}) as root:
            write_fake_gradlew(root)
            with unittest.mock.patch.dict(os.environ, {"MAVEN_MCP_GRADLE_TIMEOUT": "900"}):
                with unittest.mock.patch.object(server, "_run_gradle_command", _fake_run):
                    server._gradle_resolve_dependencies(root)
        self.assertEqual(captured["timeout"], 900)


class TestRunGradleCommand(unittest.TestCase):
    def test_timeout_expired_returns_124(self):
        def _raise_timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="gradlew", timeout=1)

        with unittest.mock.patch.object(server, "_gradle_run", side_effect=_raise_timeout):
            code, stdout, stderr = server._run_gradle_command("/tmp", "gradlew", ["--init-script", "x"])
        self.assertEqual(code, 124)
        self.assertEqual(stdout, "")
        self.assertIn("timed out", stderr)

    def test_secret_env_scrubbed_from_subprocess_call(self):
        # GHSA-4778-r7hp-92v7: the scanned project's OWN Gradle build scripts
        # (buildSrc, convention plugins) run arbitrary code that can read
        # System.getenv() — credential-bearing vars must never be passed to
        # that subprocess, including the now-single init-script invocation.
        captured = {}

        def _capture_env(cmd, cwd=None, capture_output=None, text=None, timeout=None, env=None):
            captured["env"] = env
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with unittest.mock.patch.dict(
            os.environ,
            {
                "MAVEN_REPO_TESTREPO_TOKEN": "supersecret",
                "MAVEN_REPO_TESTREPO_USER": "alice",
                "GITHUB_TOKEN": "ghsecret",
                "JAVA_HOME": "/usr/lib/jvm/test",
            },
            clear=False,
        ):
            with unittest.mock.patch.object(server, "_gradle_run", side_effect=_capture_env):
                server._run_gradle_command("/tmp", "gradlew", ["--init-script", "x", "-q", "help"])
        env = captured["env"]
        self.assertIsNotNone(env)
        self.assertNotIn("MAVEN_REPO_TESTREPO_TOKEN", env)
        self.assertNotIn("MAVEN_REPO_TESTREPO_USER", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        # Non-secret env (JAVA_HOME, PATH, ...) must still reach the subprocess.
        self.assertEqual(env.get("JAVA_HOME"), "/usr/lib/jvm/test")

    def test_proxy_userinfo_redacted_not_dropped(self):
        # R2a follow-up to GHSA-4778-r7hp-92v7: HTTP(S)_PROXY/ALL_PROXY
        # routinely embed user:pass@host (#298) — a scanned build's own code
        # could read them via System.getenv() and exfiltrate the proxy
        # password. The var must NOT be dropped (Gradle needs host:port to
        # route through the proxy at all) — only the userinfo is redacted,
        # via the same _strip_userinfo used for #317 tool-output redaction
        # (produces "***@host", not a bare host — see test_resolution.py's
        # REDACTED_URL contract).
        captured = {}

        def _capture_env(cmd, cwd=None, capture_output=None, text=None, timeout=None, env=None):
            captured["env"] = env
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with unittest.mock.patch.dict(
            os.environ,
            {
                "HTTPS_PROXY": "http://proxyuser:proxypass@proxy.corp.example:8080",
                "http_proxy": "http://otheruser:otherpass@proxy2.corp.example:3128",
                "MAVEN_MCP_REPOSITORY_BASE": "https://repouser:repopass@nexus.corp.example/repo",
            },
            clear=False,
        ):
            with unittest.mock.patch.object(server, "_gradle_run", side_effect=_capture_env):
                server._run_gradle_command("/tmp", "gradlew", ["--init-script", "x", "-q", "help"])
        env = captured["env"]
        self.assertEqual(env["HTTPS_PROXY"], "http://***@proxy.corp.example:8080")
        self.assertEqual(env["http_proxy"], "http://***@proxy2.corp.example:3128")
        self.assertEqual(
            env["MAVEN_MCP_REPOSITORY_BASE"], "https://***@nexus.corp.example/repo"
        )
        # Host:port must survive the redaction — Gradle still needs the address.
        self.assertIn("proxy.corp.example:8080", env["HTTPS_PROXY"])
        self.assertIn("proxy2.corp.example:3128", env["http_proxy"])
        dump = repr(env)
        self.assertNotIn("proxyuser", dump)
        self.assertNotIn("proxypass", dump)
        self.assertNotIn("otheruser", dump)
        self.assertNotIn("otherpass", dump)
        self.assertNotIn("repouser", dump)
        self.assertNotIn("repopass", dump)

    def test_proxy_userinfo_not_visible_to_real_gradlew_subprocess(self):
        # End-to-end companion to the capture-based test above: a real
        # subprocess.run call, no mocking of _gradle_run — proves the
        # redacted (not dropped) value is what the child process actually
        # sees, not merely what is captured at the call-arg boundary.
        with temp_project({}) as root:
            gradlew = os.path.join(root, "gradlew")
            with open(gradlew, "w", encoding="utf-8") as fh:
                fh.write('#!/bin/sh\necho "PROXY=[${HTTPS_PROXY}]"\n')
            os.chmod(gradlew, 0o700)
            with unittest.mock.patch.dict(
                os.environ,
                {"HTTPS_PROXY": "http://proxyuser:proxypass@proxy.corp.example:8080"},
                clear=False,
            ):
                code, stdout, _stderr = server._run_gradle_command(
                    root, gradlew, ["-q", "noop"]
                )
        self.assertEqual(code, 0)
        self.assertNotIn("proxyuser", stdout)
        self.assertNotIn("proxypass", stdout)
        self.assertIn("PROXY=[http://***@proxy.corp.example:8080]", stdout)

    def test_secret_env_not_visible_to_real_gradlew_subprocess(self):
        # End-to-end (real subprocess.run, no mocking of _gradle_run): a fake
        # gradlew script that echoes the env vars back proves they are
        # genuinely absent from the child process, not merely from a mocked
        # call-arg capture.
        with temp_project({}) as root:
            gradlew = os.path.join(root, "gradlew")
            with open(gradlew, "w", encoding="utf-8") as fh:
                fh.write(
                    "#!/bin/sh\n"
                    'echo "TOKEN=[${MAVEN_REPO_TESTREPO_TOKEN}][${GITHUB_TOKEN}]"\n'
                )
            os.chmod(gradlew, 0o700)
            with unittest.mock.patch.dict(
                os.environ,
                {
                    "MAVEN_REPO_TESTREPO_TOKEN": "supersecret",
                    "GITHUB_TOKEN": "ghsecret",
                },
                clear=False,
            ):
                code, stdout, _stderr = server._run_gradle_command(
                    root, gradlew, ["-q", "noop"]
                )
        self.assertEqual(code, 0)
        self.assertNotIn("supersecret", stdout)
        self.assertNotIn("ghsecret", stdout)
        self.assertIn("TOKEN=[][]", stdout)


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
    """scan_project against a mocked single-invocation `_run_gradle_command`."""

    def _mock_run(self, stdout, code=0, stderr=""):
        def _fake_run(project_root, gradlew, args, timeout=server.GRADLE_RESOLVE_TIMEOUT):
            return code, stdout, stderr

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
            with self._mock_run(SINGLE_INVOCATION_FIXTURE):
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
        with temp_project(files) as root:
            write_fake_gradlew(root)
            with self._mock_run(ONLY_BUILDENV_FIXTURE):
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
        # Per-module, per-configuration failure isolation (#401): one
        # configuration's resolution error must not blank out a sibling
        # configuration's successfully-resolved dependencies in the same
        # module, and must still surface in gradleErrors.
        files = {
            "settings.gradle.kts": 'include(":app")',
            "app/build.gradle.kts": (
                "dependencies {\n"
                '    implementation("io.ktor:ktor-client-core:3.1.1")\n'
                "}"
            ),
        }
        with temp_project(files) as root:
            write_fake_gradlew(root)
            with self._mock_run(CONFIG_ERROR_FIXTURE):
                result = server.scan_project(root)
        self.assertTrue(any("debugRuntimeClasspath" in e for e in result.get("gradleErrors", [])))
        dep = next(
            d for d in result["dependencies"]
            if d["groupId"] == "io.ktor" and d["artifactId"] == "ktor-client-core"
        )
        self.assertEqual(dep["version"], "3.1.2")
        flat = server.flatten_scan_result(result)
        self.assertIn("gradleErrors", flat)


class TestGradleResolveSubprocessE2E(unittest.TestCase):
    """End-to-end: real subprocess to smart gradlew stub (no JVM)."""

    def test_scan_project_via_subprocess_stub(self):
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
            write_smart_gradlew(root)
            result = server.scan_project(root)
        dep = next(
            d for d in result["dependencies"]
            if d["groupId"] == "io.ktor"
            and d["artifactId"] == "ktor-client-core"
            and d["version"] == "3.1.2"
        )
        self.assertEqual(dep["version"], "3.1.2")
        self.assertEqual(dep["source"]["kind"], "catalog-library")
        self.assertEqual(result["resolvedBy"], "gradle")


class TestPickBestProvenance(unittest.TestCase):
    def test_catalog_wins_over_module_direct(self):
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
                "source": {"kind": "module-direct", "file": "app/build.gradle.kts"},
                "usages": [],
            },
            {
                "groupId": "io.ktor",
                "artifactId": "ktor-client-core",
                "version": "3.1.1",
                "source": {"kind": "catalog-library", "alias": "ktor-core"},
                "usages": [{"module": ":app", "configuration": "implementation"}],
            },
        ]
        merged = server._merge_gradle_with_provenance(resolved, provenance)
        gradle_dep = next(d for d in merged if d.get("resolvedBy") == "gradle")
        self.assertEqual(gradle_dep["source"]["kind"], "catalog-library")


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

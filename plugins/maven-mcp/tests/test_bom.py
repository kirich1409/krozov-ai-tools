"""Tests for BOM / platform expansion (#286)."""

import unittest
import unittest.mock

from _helpers import empty_ctx, mock_gradle_resolve, mock_urlopen, server, temp_project, write_fake_gradlew


def _bom_pom(managed_xml: str, properties_xml: str = "", parent_xml: str = "") -> bytes:
    return (
        "<project>"
        f"{parent_xml}"
        f"{properties_xml}"
        "<dependencyManagement><dependencies>"
        f"{managed_xml}"
        "</dependencies></dependencyManagement>"
        "</project>"
    ).encode()


def _dep(
    group_id: str,
    artifact_id: str,
    version: str,
    *,
    scope: str = "compile",
    dep_type: str = "jar",
) -> str:
    return (
        "<dependency>"
        f"<groupId>{group_id}</groupId>"
        f"<artifactId>{artifact_id}</artifactId>"
        f"<version>{version}</version>"
        f"<scope>{scope}</scope>"
        f"<type>{dep_type}</type>"
        "</dependency>"
    )


class TestParseDependencyManagement(unittest.TestCase):
    def test_extracts_managed_and_import_bom(self):
        pom = (
            "<project><dependencyManagement><dependencies>"
            + _dep("com.example", "lib-a", "1.0.0")
            + _dep(
                "org.springframework.boot",
                "spring-boot-dependencies",
                "3.2.0",
                scope="import",
                dep_type="pom",
            )
            + "</dependencies></dependencyManagement></project>"
        )
        entries = server.parse_dependency_management(pom)
        self.assertEqual(len(entries), 2)
        self.assertFalse(entries[0]["isImportBom"])
        self.assertEqual(entries[0]["groupId"], "com.example")
        self.assertEqual(entries[0]["version"], "1.0.0")
        self.assertTrue(entries[1]["isImportBom"])
        self.assertEqual(entries[1]["type"], "pom")
        self.assertEqual(entries[1]["scope"], "import")

    def test_property_interpolation(self):
        pom = (
            "<project>"
            "<properties><lib.version>2.5.0</lib.version></properties>"
            "<dependencyManagement><dependencies>"
            "<dependency>"
            "<groupId>com.example</groupId>"
            "<artifactId>lib</artifactId>"
            "<version>${lib.version}</version>"
            "</dependency>"
            "</dependencies></dependencyManagement>"
            "</project>"
        )
        entries = server.parse_dependency_management(pom)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["version"], "2.5.0")

    def test_unresolved_property_version_becomes_none(self):
        pom = (
            "<project><dependencyManagement><dependencies>"
            "<dependency>"
            "<groupId>com.example</groupId>"
            "<artifactId>lib</artifactId>"
            "<version>${missing.version}</version>"
            "</dependency>"
            "</dependencies></dependencyManagement></project>"
        )
        entries = server.parse_dependency_management(pom)
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0]["version"])


class TestExpandBom(unittest.TestCase):
    def test_nested_import_first_wins(self):
        # Outer BOM imports inner first, then pins the same GA — first-wins
        # means the imported version sticks; the later direct pin is ignored.
        outer = _bom_pom(
            _dep("org.inner", "inner-bom", "1.0", scope="import", dep_type="pom")
            + _dep("com.example", "lib", "9.9.9")
        )
        inner = _bom_pom(_dep("com.example", "lib", "1.2.3"))
        ctx = empty_ctx()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, outer), (200, inner)]),
        ):
            managed = server.expand_bom("org.outer", "outer-bom", "1.0", ctx)
        by_ga = {(m["groupId"], m["artifactId"]): m["version"] for m in managed}
        self.assertEqual(by_ga[("com.example", "lib")], "1.2.3")

    def test_direct_before_import_wins(self):
        outer = _bom_pom(
            _dep("com.example", "lib", "2.0.0")
            + _dep("org.inner", "inner-bom", "1.0", scope="import", dep_type="pom")
        )
        inner = _bom_pom(_dep("com.example", "lib", "1.0.0"))
        ctx = empty_ctx()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, outer), (200, inner)]),
        ):
            managed = server.expand_bom("org.outer", "outer-bom", "1.0", ctx)
        by_ga = {(m["groupId"], m["artifactId"]): m["version"] for m in managed}
        self.assertEqual(by_ga[("com.example", "lib")], "2.0.0")

    def test_missing_pom_returns_empty(self):
        ctx = empty_ctx()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(404, b"")]),
        ):
            managed = server.expand_bom("org.missing", "bom", "1.0", ctx)
        self.assertEqual(managed, [])

    def test_handle_expand_bom_echoes_coordinate(self):
        bom = _bom_pom(_dep("com.example", "lib", "1.0.0"))
        with temp_project({"README.md": "x"}) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, bom)]),
            ):
                out = server.handle_expand_bom({
                    "groupId": "org.example",
                    "artifactId": "bom",
                    "version": "1.0",
                    "projectPath": root,
                })
        self.assertEqual(out["groupId"], "org.example")
        self.assertEqual(out["artifactId"], "bom")
        self.assertEqual(out["version"], "1.0")
        self.assertEqual(
            out["managed"],
            [{"groupId": "com.example", "artifactId": "lib", "version": "1.0.0"}],
        )


class TestApplyBomManagedVersions(unittest.TestCase):
    def test_local_pin_overrides_imported_bom(self):
        bom = _bom_pom(_dep("com.example", "lib", "1.0.0"))
        scan = {
            "buildSystem": "maven",
            "dependencies": [
                {
                    "groupId": "org.example",
                    "artifactId": "bom",
                    "version": "1.0",
                    "isPlatform": True,
                    "platformKind": "platform",
                    "source": {"kind": "module-direct", "file": "pom.xml", "module": None},
                    "usages": [{"module": None, "configuration": "import"}],
                },
                {
                    "groupId": "com.example",
                    "artifactId": "lib",
                    "version": None,
                    "source": {"kind": "module-direct", "file": "pom.xml", "module": None},
                    "usages": [{"module": None, "configuration": "implementation"}],
                },
            ],
            "managedPins": [
                {
                    "groupId": "com.example",
                    "artifactId": "lib",
                    "version": "2.0.0",
                    "module": None,
                }
            ],
            "deadRepositoryHints": [],
        }
        ctx = empty_ctx()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, bom)]),
        ):
            server.apply_bom_managed_versions(scan, ctx)
        lib = scan["dependencies"][1]
        self.assertEqual(lib["effectiveVersion"], "2.0.0")
        self.assertEqual(lib["managedBy"]["version"], "2.0.0")

    def test_explicit_version_not_overwritten_by_platform(self):
        bom = _bom_pom(_dep("com.example", "lib", "1.0.0"))
        scan = {
            "buildSystem": "gradle",
            "dependencies": [
                {
                    "groupId": "org.example",
                    "artifactId": "bom",
                    "version": "1.0",
                    "isPlatform": True,
                    "platformKind": "platform",
                    "source": {"kind": "module-direct", "file": "build.gradle.kts", "module": None},
                    "usages": [{"module": None, "configuration": "implementation"}],
                },
                {
                    "groupId": "com.example",
                    "artifactId": "lib",
                    "version": "9.9.9",
                    "source": {"kind": "module-direct", "file": "build.gradle.kts", "module": None},
                    "usages": [{"module": None, "configuration": "implementation"}],
                },
            ],
            "managedPins": [],
            "deadRepositoryHints": [],
        }
        ctx = empty_ctx()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, bom)]),
        ):
            server.apply_bom_managed_versions(scan, ctx)
        lib = scan["dependencies"][1]
        self.assertNotIn("effectiveVersion", lib)


class TestScanAuditBomIntegration(unittest.TestCase):
    def test_gradle_platform_versionless_scan(self):
        files = {
            "settings.gradle.kts": "rootProject.name = \"app\"\n",
            "build.gradle.kts": (
                "dependencies {\n"
                '  implementation(platform("org.example:bom:1.0"))\n'
                '  implementation("com.example:lib")\n'
                "}\n"
            ),
        }
        resolved = [
            {
                "groupId": "org.example",
                "artifactId": "bom",
                "version": "1.0",
                "resolvedBy": "gradle",
                "isPlatform": True,
                "usages": [{"module": None, "configuration": "implementation"}],
            },
            {
                "groupId": "com.example",
                "artifactId": "lib",
                "version": "1.2.3",
                "resolvedBy": "gradle",
                "usages": [{"module": None, "configuration": "implementation"}],
            },
        ]
        with temp_project(files) as root:
            write_fake_gradlew(root)
            with mock_gradle_resolve(resolved):
                out = server.handle_scan_project_dependencies({"projectPath": root})
        by_ga = {(d["groupId"], d["artifactId"]): d for d in out["dependencies"]}
        self.assertTrue(by_ga[("org.example", "bom")]["isPlatform"])
        lib = by_ga[("com.example", "lib")]
        self.assertEqual(lib["version"], "1.2.3")
        self.assertEqual(out["resolvedBy"], "gradle")

    def test_maven_import_bom_versionless_scan(self):
        bom = _bom_pom(_dep("com.example", "lib", "4.5.6"))
        pom = (
            "<project>\n"
            "  <dependencyManagement>\n"
            "    <dependencies>\n"
            "      <dependency>\n"
            "        <groupId>org.example</groupId>\n"
            "        <artifactId>bom</artifactId>\n"
            "        <version>1.0</version>\n"
            "        <type>pom</type>\n"
            "        <scope>import</scope>\n"
            "      </dependency>\n"
            "    </dependencies>\n"
            "  </dependencyManagement>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>com.example</groupId>\n"
            "      <artifactId>lib</artifactId>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )
        with temp_project({"pom.xml": pom}) as root:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, bom)]),
            ):
                out = server.handle_scan_project_dependencies({"projectPath": root})
        by_ga = {(d["groupId"], d["artifactId"]): d for d in out["dependencies"]}
        self.assertTrue(by_ga[("org.example", "bom")].get("isPlatform"))
        lib = by_ga[("com.example", "lib")]
        self.assertEqual(lib["effectiveVersion"], "4.5.6")
        self.assertEqual(lib["managedBy"]["artifactId"], "bom")

    def test_audit_uses_effective_version(self):
        meta = (
            b'<?xml version="1.0"?>'
            b"<metadata><versioning><versions>"
            b"<version>1.0.0</version><version>1.1.0</version>"
            b"</versions></versioning></metadata>"
        )
        files = {
            "settings.gradle.kts": "rootProject.name = \"app\"\n",
            "build.gradle.kts": (
                "dependencies {\n"
                '  implementation(platform("org.example:bom:1.0"))\n'
                '  implementation("com.example:lib")\n'
                "}\n"
            ),
        }
        resolved = [
            {
                "groupId": "org.example",
                "artifactId": "bom",
                "version": "1.0",
                "resolvedBy": "gradle",
                "usages": [{"module": None, "configuration": "implementation"}],
            },
            {
                "groupId": "com.example",
                "artifactId": "lib",
                "version": "1.0.0",
                "resolvedBy": "gradle",
                "usages": [{"module": None, "configuration": "implementation"}],
            },
        ]
        responses = [
            (200, meta),  # metadata for org.example:bom
            (200, meta),  # metadata for com.example:lib
        ]
        with temp_project(files) as root:
            write_fake_gradlew(root)
            with mock_gradle_resolve(resolved):
                with unittest.mock.patch(
                    "urllib.request.urlopen",
                    side_effect=mock_urlopen(responses),
                ):
                    out = server.handle_audit_project_dependencies({
                        "projectPath": root,
                        "includeVulnerabilities": False,
                    })
        by_ga = {(d["groupId"], d["artifactId"]): d for d in out["dependencies"]}
        lib = by_ga[("com.example", "lib")]
        self.assertEqual(lib["currentVersion"], "1.0.0")
        self.assertEqual(lib["upgradeType"], "minor")


if __name__ == "__main__":
    unittest.main()

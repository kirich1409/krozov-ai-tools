"""Tests for check_version_compatibility (#285)."""

import json
import os
import unittest
import unittest.mock

from _helpers import empty_ctx, mock_urlopen, server


def _bom_pom(managed_xml: str) -> bytes:
    return (
        "<project><dependencyManagement><dependencies>"
        f"{managed_xml}"
        "</dependencies></dependencyManagement></project>"
    ).encode()


def _managed(group_id: str, artifact_id: str, version: str) -> str:
    return (
        "<dependency>"
        f"<groupId>{group_id}</groupId>"
        f"<artifactId>{artifact_id}</artifactId>"
        f"<version>{version}</version>"
        "</dependency>"
    )


class TestCompatMatricesFile(unittest.TestCase):
    def test_shipped_file_has_refresh_procedure(self):
        matrices = server._load_compat_matrices()
        meta = matrices["_meta"]
        self.assertIsInstance(meta.get("refreshProcedure"), list)
        self.assertGreaterEqual(len(meta["refreshProcedure"]), 3)
        self.assertTrue(matrices.get("agpEntries"))
        self.assertTrue(matrices.get("kotlinGradlePluginEntries"))
        self.assertIn(
            "javax.persistence:javax.persistence-api",
            matrices["jakartaMap"],
        )
        # File lives next to server.py so the plugin bundle ships it.
        self.assertTrue(os.path.isfile(server.COMPAT_MATRICES_PATH))


class TestAndroidMatrix(unittest.TestCase):
    def test_agp_gradle_jdk_conflict_and_suggestion(self):
        conflicts, _notes = server.check_android_kotlin_compatibility(
            {"agp": "8.7.2", "gradle": "8.5", "jdk": 11},
            server._load_compat_matrices(),
        )
        kinds = {c["kind"] for c in conflicts}
        self.assertIn("agp_gradle", kinds)
        self.assertIn("agp_jdk", kinds)
        gradle_c = next(c for c in conflicts if c["kind"] == "agp_gradle")
        self.assertEqual(gradle_c["expected"]["minGradle"], "8.9")
        self.assertEqual(gradle_c["suggestion"]["gradle"], "8.9")
        self.assertIn("developer.android.com", gradle_c["reference"])

    def test_compatible_agp_gradle_jdk(self):
        conflicts, _notes = server.check_android_kotlin_compatibility(
            {"agp": "8.7.0", "gradle": "8.9", "jdk": 17},
            server._load_compat_matrices(),
        )
        self.assertEqual(conflicts, [])

    def test_kotlin_gradle_out_of_range(self):
        conflicts, _notes = server.check_android_kotlin_compatibility(
            {"kotlin": "2.1.20", "gradle": "9.0.0"},
            server._load_compat_matrices(),
        )
        kinds = {c["kind"] for c in conflicts}
        self.assertIn("kotlin_gradle", kinds)
        kc = next(c for c in conflicts if c["kind"] == "kotlin_gradle")
        self.assertEqual(kc["expected"]["gradleMax"], "8.12.1")
        self.assertIn("kotlinlang.org", kc["reference"])

    def test_kotlin_agp_out_of_range(self):
        conflicts, _notes = server.check_android_kotlin_compatibility(
            {"kotlin": "2.0.0", "agp": "8.7.0"},
            server._load_compat_matrices(),
        )
        kinds = {c["kind"] for c in conflicts}
        self.assertIn("kotlin_agp", kinds)

    def test_compatible_kotlin_band(self):
        conflicts, _notes = server.check_android_kotlin_compatibility(
            {
                "agp": "8.7.2",
                "gradle": "8.9",
                "kotlin": "2.1.20",
                "jdk": 17,
            },
            server._load_compat_matrices(),
        )
        self.assertEqual(conflicts, [])

    def test_unknown_agp_suggests_nearest(self):
        conflicts, _notes = server.check_android_kotlin_compatibility(
            {"agp": "99.0.0", "gradle": "8.0"},
            server._load_compat_matrices(),
        )
        self.assertTrue(any(c["kind"] == "agp_unknown" for c in conflicts))
        unk = next(c for c in conflicts if c["kind"] == "agp_unknown")
        self.assertIsNotNone(unk["suggestion"])


class TestJakartaMap(unittest.TestCase):
    def test_boot3_flags_javax_persistence(self):
        conflicts, _notes = server.check_javax_jakarta_migration(
            "3.2.0",
            [
                {
                    "groupId": "javax.persistence",
                    "artifactId": "javax.persistence-api",
                    "version": "2.2",
                }
            ],
            server._load_compat_matrices(),
        )
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["kind"], "javax_to_jakarta")
        self.assertEqual(
            conflicts[0]["suggestion"],
            {
                "groupId": "jakarta.persistence",
                "artifactId": "jakarta.persistence-api",
            },
        )

    def test_boot2_does_not_flag(self):
        conflicts, _notes = server.check_javax_jakarta_migration(
            "2.7.18",
            [
                {
                    "groupId": "javax.persistence",
                    "artifactId": "javax.persistence-api",
                    "version": "2.2",
                }
            ],
            server._load_compat_matrices(),
        )
        self.assertEqual(conflicts, [])


class TestSpringBootBomCompat(unittest.TestCase):
    def test_conflicting_managed_version(self):
        pom = _bom_pom(
            _managed("org.springframework", "spring-core", "6.1.5")
            + _managed("com.fasterxml.jackson.core", "jackson-databind", "2.15.4")
        )
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, pom)]),
        ):
            conflicts, notes = server.check_spring_boot_bom_compatibility(
                "3.2.0",
                [
                    {
                        "groupId": "org.springframework",
                        "artifactId": "spring-core",
                        "version": "5.3.31",
                    },
                    {
                        "groupId": "com.fasterxml.jackson.core",
                        "artifactId": "jackson-databind",
                        "version": "2.15.4",
                    },
                    {
                        "groupId": "com.example",
                        "artifactId": "unmanaged",
                        "version": "1.0",
                    },
                ],
                empty_ctx(),
            )
        self.assertEqual(notes, [])
        self.assertEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c["kind"], "spring_boot_bom")
        self.assertEqual(c["requested"]["version"], "5.3.31")
        self.assertEqual(c["expected"]["version"], "6.1.5")
        self.assertEqual(c["suggestion"]["version"], "6.1.5")

    def test_missing_bom_notes_and_skips(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(404, b"")]),
        ):
            conflicts, notes = server.check_spring_boot_bom_compatibility(
                "3.2.0",
                [
                    {
                        "groupId": "org.springframework",
                        "artifactId": "spring-core",
                        "version": "5.3.31",
                    }
                ],
                empty_ctx(),
            )
        self.assertEqual(conflicts, [])
        self.assertTrue(any("Could not expand" in n for n in notes))


class TestCheckVersionCompatibilityTool(unittest.TestCase):
    def test_mixed_compatible_and_incompatible(self):
        pom = _bom_pom(_managed("org.springframework", "spring-core", "6.1.5"))
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, pom)]),
        ):
            result = server.handle_check_version_compatibility(
                {
                    "springBoot": "3.2.0",
                    "android": {
                        "agp": "8.7.2",
                        "gradle": "8.5",
                        "kotlin": "2.1.20",
                        "jdk": 17,
                    },
                    "dependencies": [
                        {
                            "groupId": "org.springframework",
                            "artifactId": "spring-core",
                            "version": "5.3.31",
                        },
                        {
                            "groupId": "javax.servlet",
                            "artifactId": "javax.servlet-api",
                            "version": "4.0.1",
                        },
                    ],
                }
            )
        self.assertFalse(result["compatible"])
        kinds = {c["kind"] for c in result["conflicts"]}
        self.assertIn("spring_boot_bom", kinds)
        self.assertIn("agp_gradle", kinds)
        self.assertIn("javax_to_jakarta", kinds)
        self.assertIsInstance(result["notes"], list)
        self.assertTrue(result["notes"])  # includes matrix limitations

    def test_all_compatible(self):
        pom = _bom_pom(_managed("org.springframework", "spring-core", "6.1.5"))
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, pom)]),
        ):
            result = server.handle_check_version_compatibility(
                {
                    "springBoot": "3.2.0",
                    "android": {
                        "agp": "8.7.2",
                        "gradle": "8.9",
                        "kotlin": "2.1.20",
                        "jdk": 17,
                    },
                    "dependencies": [
                        {
                            "groupId": "org.springframework",
                            "artifactId": "spring-core",
                            "version": "6.1.5",
                        },
                        {
                            "groupId": "jakarta.persistence",
                            "artifactId": "jakarta.persistence-api",
                            "version": "3.1.0",
                        },
                    ],
                }
            )
        self.assertTrue(result["compatible"])
        self.assertEqual(result["conflicts"], [])

    def test_registered_in_tools(self):
        names = [t["name"] for t in server.TOOLS]
        self.assertIn("check_version_compatibility", names)
        self.assertEqual(
            set(names), set(server.TOOL_HANDLERS.keys())
        )


if __name__ == "__main__":
    unittest.main()

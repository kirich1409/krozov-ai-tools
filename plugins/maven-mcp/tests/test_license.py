"""License intelligence tests (#300).

Covers SPDX normalization, categorization, POM license extraction (name+url),
``get_dependency_license``, and ``audit_project_dependencies`` with
``includeLicenses``.
"""

import json
import unittest
import unittest.mock

from _helpers import server, mock_urlopen, http_error, temp_project


def _meta(versions, last_updated="20240101000000"):
    vers = "".join(f"<version>{v}</version>" for v in versions)
    xml = (
        "<metadata><versioning>"
        f"<lastUpdated>{last_updated}</lastUpdated>"
        f"<versions>{vers}</versions>"
        "</versioning></metadata>"
    )
    return xml.encode("utf-8")


def _json(obj):
    return json.dumps(obj).encode("utf-8")


def _patch_urlopen(responses):
    return unittest.mock.patch(
        "urllib.request.urlopen", side_effect=mock_urlopen(responses)
    )


# --- pure helpers -----------------------------------------------------------

class TestLicenseNormalization(unittest.TestCase):
    def test_apache_long_form_to_spdx(self):
        self.assertEqual(
            server.normalize_license_to_spdx(
                "The Apache Software License, Version 2.0"
            ),
            "Apache-2.0",
        )

    def test_mit_variants(self):
        self.assertEqual(server.normalize_license_to_spdx("MIT License"), "MIT")
        self.assertEqual(server.normalize_license_to_spdx("MIT"), "MIT")

    def test_gpl_and_agpl(self):
        self.assertEqual(
            server.normalize_license_to_spdx("GNU General Public License, Version 3"),
            "GPL-3.0-only",
        )
        # Bare SPDX tokens already in the category table are returned as-is.
        self.assertEqual(server.normalize_license_to_spdx("AGPL-3.0"), "AGPL-3.0")
        self.assertEqual(
            server.normalize_license_to_spdx("agplv3"),
            "AGPL-3.0-only",
        )

    def test_noassertion_and_empty(self):
        self.assertIsNone(server.normalize_license_to_spdx("NOASSERTION"))
        self.assertIsNone(server.normalize_license_to_spdx(""))
        self.assertIsNone(server.normalize_license_to_spdx(None))

    def test_categorize_known_and_unknown(self):
        self.assertEqual(server.categorize_license("Apache-2.0"), "permissive")
        self.assertEqual(server.categorize_license("LGPL-2.1-only"), "weak-copyleft")
        self.assertEqual(server.categorize_license("GPL-3.0-only"), "strong-copyleft")
        self.assertEqual(server.categorize_license("AGPL-3.0-only"), "network-copyleft")
        self.assertEqual(server.categorize_license(None, "Acme Proprietary"), "proprietary")
        self.assertEqual(server.categorize_license(None, None), "unknown")

    def test_notes_are_non_empty(self):
        for cat in (
            "permissive", "weak-copyleft", "strong-copyleft",
            "network-copyleft", "proprietary", "unknown",
        ):
            notes = server.license_category_notes(cat)
            self.assertIsInstance(notes, str)
            self.assertGreater(len(notes), 20)


class TestExtractLicensesFromPom(unittest.TestCase):
    def test_name_and_url(self):
        pom = (
            "<project><licenses><license>"
            "<name>The Apache Software License, Version 2.0</name>"
            "<url>https://www.apache.org/licenses/LICENSE-2.0.txt</url>"
            "</license></licenses></project>"
        )
        entries = server.extract_licenses_from_pom(pom)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "The Apache Software License, Version 2.0")
        self.assertEqual(
            entries[0]["url"],
            "https://www.apache.org/licenses/LICENSE-2.0.txt",
        )

    def test_name_only_and_empty(self):
        self.assertEqual(
            server.extract_licenses_from_pom(
                "<project><licenses><license><name>MIT</name></license></licenses></project>"
            ),
            [{"name": "MIT", "url": None}],
        )
        self.assertEqual(server.extract_licenses_from_pom("<project/>"), [])


# --- get_dependency_license -------------------------------------------------

class TestGetDependencyLicense(unittest.TestCase):
    def test_pom_license_normalized(self):
        pom = (
            "<project>"
            "<licenses><license>"
            "<name>The Apache Software License, Version 2.0</name>"
            "<url>https://www.apache.org/licenses/LICENSE-2.0.txt</url>"
            "</license></licenses>"
            "</project>"
        )
        # metadata + pom; no GitHub SCM → no gh calls.
        responses = [
            (200, _meta(["1.0.0"])),
            (200, pom.encode("utf-8")),
        ]
        with _patch_urlopen(responses):
            out = server.handle_get_dependency_license({
                "dependencies": [{
                    "groupId": "com.example",
                    "artifactId": "lib",
                    "version": "1.0.0",
                }],
            })
        result = out["results"][0]
        self.assertEqual(result["spdxId"], "Apache-2.0")
        self.assertEqual(result["category"], "permissive")
        self.assertEqual(result["source"], "spdx-normalized")
        self.assertEqual(
            result["url"],
            "https://www.apache.org/licenses/LICENSE-2.0.txt",
        )
        self.assertIn("Permissive", result["notes"])
        self.assertNotIn("error", result)

    def test_github_license_preferred(self):
        pom = (
            "<project>"
            "<scm><url>https://github.com/acme/widget</url></scm>"
            "<licenses><license><name>MIT License</name></license></licenses>"
            "</project>"
        )
        repo = {"license": {"spdx_id": "Apache-2.0"}, "owner": {"login": "acme"}}
        responses = [
            (200, _meta(["1.0.0"])),
            (200, pom.encode("utf-8")),
            (200, _json(repo)),
        ]
        with _patch_urlopen(responses):
            out = server.handle_get_dependency_license({
                "dependencies": [{
                    "groupId": "com.example",
                    "artifactId": "widget",
                    "version": "1.0.0",
                }],
            })
        result = out["results"][0]
        self.assertEqual(result["spdxId"], "Apache-2.0")
        self.assertEqual(result["source"], "github")
        self.assertEqual(result["category"], "permissive")

    def test_unknown_when_no_license(self):
        pom = "<project><scm><url>https://example.com/scm</url></scm></project>"
        responses = [
            (200, _meta(["1.0.0"])),
            (200, pom.encode("utf-8")),
        ]
        with _patch_urlopen(responses):
            out = server.handle_get_dependency_license({
                "dependencies": [{
                    "groupId": "com.example",
                    "artifactId": "nolicense",
                    "version": "1.0.0",
                }],
            })
        result = out["results"][0]
        self.assertIsNone(result["spdxId"])
        self.assertEqual(result["category"], "unknown")
        self.assertIsNone(result["source"])

    def test_proprietary_unrecognized_name(self):
        pom = (
            "<project><licenses><license>"
            "<name>Acme Internal License 1.0</name>"
            "</license></licenses></project>"
        )
        responses = [
            (200, _meta(["1.0.0"])),
            (200, pom.encode("utf-8")),
        ]
        with _patch_urlopen(responses):
            out = server.handle_get_dependency_license({
                "dependencies": [{
                    "groupId": "com.acme",
                    "artifactId": "secret",
                    "version": "1.0.0",
                }],
            })
        result = out["results"][0]
        self.assertIsNone(result["spdxId"])
        self.assertEqual(result["category"], "proprietary")
        self.assertEqual(result["source"], "pom")

    def test_batch_cap_truncates(self):
        # Cap is enforced before network I/O — over-long batch is truncated.
        deps = [
            {"groupId": f"g{i}", "artifactId": f"a{i}", "version": "1.0.0"}
            for i in range(server.MAX_LICENSE_DEPENDENCIES + 5)
        ]
        # Each truncated dep: metadata + pom 404.
        responses = []
        for _ in range(server.MAX_LICENSE_DEPENDENCIES):
            responses.append((200, _meta(["1.0.0"])))
            responses.append(http_error("https://repo/pom", 404, "Not Found"))
        with _patch_urlopen(responses):
            out = server.handle_get_dependency_license({"dependencies": deps})
        self.assertEqual(len(out["results"]), server.MAX_LICENSE_DEPENDENCIES)


# --- audit includeLicenses --------------------------------------------------

class TestAuditIncludeLicenses(unittest.TestCase):
    def test_license_section_and_new_categories(self):
        # Two Apache deps + one AGPL → newLicenseCategories includes network-copyleft
        # (and not permissive, which appears twice).
        pom = (
            "<project><dependencies>"
            "<dependency><groupId>com.a</groupId><artifactId>one</artifactId>"
            "<version>1.0.0</version></dependency>"
            "<dependency><groupId>com.a</groupId><artifactId>two</artifactId>"
            "<version>1.0.0</version></dependency>"
            "<dependency><groupId>com.b</groupId><artifactId>agpl</artifactId>"
            "<version>1.0.0</version></dependency>"
            "</dependencies></project>"
        )
        apache_pom = (
            "<project><licenses><license>"
            "<name>Apache-2.0</name>"
            "</license></licenses></project>"
        ).encode()
        agpl_pom = (
            "<project><licenses><license>"
            "<name>AGPL-3.0</name>"
            "</license></licenses></project>"
        ).encode()
        # Per dep with version: fetch_metadata (Central) then resolve license
        # (fetch_metadata again + fetch_pom). includeVulnerabilities=False.
        # #400: both the metadata loop and the license loop now run on a
        # ThreadPoolExecutor, so urlopen calls are no longer guaranteed to
        # happen in input order -- route by URL (which embeds the
        # artifactId and, for the license pass, the "maven-metadata.xml"
        # vs ".pom" suffix) instead of a position-based queue.
        def _route(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if not url.endswith(".pom"):
                return mock_urlopen([(200, _meta(["1.0.0"]))])(req, *args, **kwargs)
            if "/agpl/" in url:
                return mock_urlopen([(200, agpl_pom)])(req, *args, **kwargs)
            return mock_urlopen([(200, apache_pom)])(req, *args, **kwargs)

        with temp_project({"pom.xml": pom}) as root:
            with unittest.mock.patch("urllib.request.urlopen", side_effect=_route):
                out = server.handle_audit_project_dependencies({
                    "projectPath": root,
                    "includeVulnerabilities": False,
                    "includeLicenses": True,
                })
        self.assertIn("licenses", out)
        lic = out["licenses"]
        self.assertEqual(lic["summary"]["byCategory"].get("permissive"), 2)
        self.assertEqual(lic["summary"]["byCategory"].get("network-copyleft"), 1)
        self.assertIn("Apache-2.0", lic["summary"]["uniqueSpdxIds"])
        self.assertTrue(lic["summary"]["hasProprietaryOrCopyleft"])
        self.assertIn("network-copyleft", out["newLicenseCategories"])
        self.assertNotIn("permissive", out["newLicenseCategories"])
        # Signals on the AGPL entry
        agpl_entries = [d for d in out["dependencies"] if d["artifactId"] == "agpl"]
        self.assertEqual(len(agpl_entries), 1)
        # proprietary/unknown signals only — AGPL is categorized, no unknown signal
        self.assertNotIn("unknown license", agpl_entries[0].get("signals", []))

    def test_default_skips_license_section(self):
        pom = (
            "<project><dependencies><dependency>"
            "<groupId>com.example</groupId>"
            "<artifactId>lib</artifactId>"
            "<version>1.0.0</version>"
            "</dependency></dependencies></project>"
        )
        responses = [
            (200, _meta(["1.0.0", "1.1.0"])),
        ]
        with temp_project({"pom.xml": pom}) as root:
            with _patch_urlopen(responses):
                out = server.handle_audit_project_dependencies({
                    "projectPath": root,
                    "includeVulnerabilities": False,
                })
        self.assertNotIn("licenses", out)
        self.assertNotIn("newLicenseCategories", out)

    def test_unknown_license_signal(self):
        pom = (
            "<project><dependencies><dependency>"
            "<groupId>com.example</groupId>"
            "<artifactId>lib</artifactId>"
            "<version>1.0.0</version>"
            "</dependency></dependencies></project>"
        )
        empty_pom = b"<project/>"
        responses = [
            (200, _meta(["1.0.0"])),
            (200, _meta(["1.0.0"])),
            (200, empty_pom),
        ]
        with temp_project({"pom.xml": pom}) as root:
            with _patch_urlopen(responses):
                out = server.handle_audit_project_dependencies({
                    "projectPath": root,
                    "includeVulnerabilities": False,
                    "includeLicenses": True,
                })
        dep = out["dependencies"][0]
        self.assertIn("unknown license", dep.get("signals", []))
        self.assertTrue(out["licenses"]["summary"]["hasUnknown"])


class TestNewLicenseCategoryDetection(unittest.TestCase):
    def test_singleton_categories(self):
        entries = [
            {"category": "permissive"},
            {"category": "permissive"},
            {"category": "network-copyleft"},
        ]
        self.assertEqual(
            server._detect_new_license_categories(entries),
            ["network-copyleft"],
        )

    def test_too_few_entries(self):
        self.assertEqual(
            server._detect_new_license_categories([{"category": "permissive"}]),
            [],
        )


if __name__ == "__main__":
    unittest.main()

"""Maven settings.xml mirrors + closed/offline mode (#294).

Covers mirrorOf matching (*, external:*, explicit lists, !exclusions), URL
rewrite, MAVEN_MCP_OFFLINE / MAVEN_MCP_REPOSITORY_BASE, and the end-to-end
guarantee that public hosts are never contacted in closed mode.
"""

import os
import tempfile
import unittest
import unittest.mock

from _helpers import server, mock_urlopen, temp_project


MIRROR_URL = "https://nexus.example.com/repository/maven-public"
CUSTOM_URL = "https://corp.example.com/m2"


def _meta(versions):
    vers = "".join(f"<version>{v}</version>" for v in versions)
    return (
        f"<metadata><versioning><versions>{vers}</versions>"
        f"</versioning></metadata>"
    ).encode("utf-8")


def _urls(mock):
    return [c.args[0].full_url for c in mock.call_args_list]


def _settings_xml(mirror_of, mirror_url=MIRROR_URL, mirror_id="nexus"):
    return (
        "<settings><mirrors><mirror>"
        f"<id>{mirror_id}</id>"
        f"<url>{mirror_url}</url>"
        f"<mirrorOf>{mirror_of}</mirrorOf>"
        "</mirror></mirrors></settings>"
    )


def _ctx_with_mirrors(mirrors, scoped=None, **kwargs):
    return server.ResolutionContext(
        "/__test__",
        scoped or {"dependency": [], "plugin": []},
        kwargs.pop("public_fallback", False),
        mirrors=mirrors,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# mirrorOf matching matrix
# ---------------------------------------------------------------------------
class MirrorOfMatchingTest(unittest.TestCase):
    def setUp(self):
        self.central = {
            "name": "Maven Central",
            "url": server.MAVEN_CENTRAL_URL,
        }
        self.google = {"name": "Google Maven", "url": server.GOOGLE_MAVEN_URL}
        self.custom = {"name": "corp", "url": CUSTOM_URL}
        self.local = {"name": "local", "url": "http://localhost:8081/repo"}

    def test_star_matches_everything(self):
        self.assertTrue(server._mirror_of_matches("*", self.central))
        self.assertTrue(server._mirror_of_matches("*", self.custom))
        self.assertTrue(server._mirror_of_matches("*", self.local))

    def test_external_star_skips_localhost(self):
        self.assertTrue(server._mirror_of_matches("external:*", self.central))
        self.assertTrue(server._mirror_of_matches("external:*", self.custom))
        self.assertFalse(server._mirror_of_matches("external:*", self.local))
        self.assertFalse(
            server._mirror_of_matches(
                "external:*", {"name": "f", "url": "file:///tmp/m2"}
            )
        )

    def test_explicit_id_list(self):
        self.assertTrue(server._mirror_of_matches("central", self.central))
        self.assertTrue(
            server._mirror_of_matches("central,google", self.google)
        )
        self.assertFalse(server._mirror_of_matches("central", self.custom))

    def test_exclusion_bang(self):
        self.assertFalse(server._mirror_of_matches("*,!central", self.central))
        self.assertTrue(server._mirror_of_matches("*,!central", self.custom))
        self.assertFalse(
            server._mirror_of_matches("external:*,!corp", self.custom)
        )
        self.assertTrue(
            server._mirror_of_matches("external:*,!corp", self.central)
        )

    def test_well_known_url_aliases(self):
        # Declared as mavenCentral() → friendly name, but mirrorOf=central
        # must still match via the well-known URL alias.
        entry = {"name": "Maven Central", "url": server.MAVEN_CENTRAL_URL}
        self.assertIn("central", server._repo_mirror_ids(entry))
        self.assertTrue(server._mirror_of_matches("central", entry))


class ParseSettingsMirrorsTest(unittest.TestCase):
    def test_parse_mirror_entries(self):
        xml = _settings_xml("*")
        mirrors = server._parse_settings_xml_mirrors(xml)
        self.assertEqual(len(mirrors), 1)
        self.assertEqual(mirrors[0]["id"], "nexus")
        self.assertEqual(mirrors[0]["url"], MIRROR_URL)
        self.assertEqual(mirrors[0]["mirrorOf"], "*")

    def test_commented_mirror_ignored(self):
        xml = (
            "<settings><mirrors>"
            "<!-- <mirror><id>x</id><url>https://x/</url>"
            "<mirrorOf>*</mirrorOf></mirror> -->"
            "<mirror><id>y</id><url>https://y/</url>"
            "<mirrorOf>central</mirrorOf></mirror>"
            "</mirrors></settings>"
        )
        mirrors = server._parse_settings_xml_mirrors(xml)
        self.assertEqual([m["id"] for m in mirrors], ["y"])

    def test_load_from_settings_path_override(self):
        xml = _settings_xml("external:*")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.xml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(xml)
            with unittest.mock.patch.dict(
                os.environ, {"MAVEN_MCP_SETTINGS": path}, clear=False
            ):
                mirrors = server._load_settings_xml_mirrors()
        self.assertEqual(mirrors[0]["mirrorOf"], "external:*")
        self.assertEqual(mirrors[0]["url"], MIRROR_URL)


class ApplyMirrorRewriteTest(unittest.TestCase):
    def test_star_rewrites_url_and_name(self):
        entry = {"name": "Maven Central", "url": server.MAVEN_CENTRAL_URL}
        mirrors = [{"id": "nexus", "url": MIRROR_URL, "mirrorOf": "*"}]
        out = server._apply_mirror_to_entry(entry, mirrors)
        self.assertEqual(out["url"], MIRROR_URL)
        self.assertEqual(out["name"], "nexus")
        self.assertTrue(out["mirrored"])

    def test_unmatched_unchanged(self):
        entry = {"name": "corp", "url": CUSTOM_URL}
        mirrors = [{"id": "nexus", "url": MIRROR_URL, "mirrorOf": "central"}]
        out = server._apply_mirror_to_entry(entry, mirrors)
        self.assertEqual(out["url"], CUSTOM_URL)
        self.assertEqual(out["name"], "corp")
        self.assertNotIn("mirrored", out)


# ---------------------------------------------------------------------------
# R2b: mirror credentials must resolve without a MAVEN_REPO_<ID>_HOST pin
# ---------------------------------------------------------------------------
# The GHSA-m2hv-xh72-cccw misbinding guard requires a host pin for name/id-
# keyed credentials, since `name` is normally untrusted build-file input. A
# mirror-applied entry's `name` is the settings.xml mirror's OWN <id> (see
# _apply_mirror_to_entry) — trusted, not build-file-controlled — so it must
# be exempt from the pin requirement. Before this fix, closed-mode mirror
# auth (#294) silently fell through to unauthenticated (401) once the #291
# guard shipped, because nothing pinned the mirror id to its own host.
class MirrorCredentialResolutionTest(unittest.TestCase):
    def test_mirror_derived_name_credential_resolves_without_host_pin(self):
        entry = {"name": "Maven Central", "url": server.MAVEN_CENTRAL_URL}
        mirrors = [{"id": "corp-mirror", "url": MIRROR_URL, "mirrorOf": "*"}]
        mirrored = server._apply_mirror_to_entry(entry, mirrors)
        self.assertTrue(mirrored["mirrored"])
        self.assertEqual(mirrored["name"], "corp-mirror")

        env = {
            "MAVEN_REPO_CORP_MIRROR_USER": "mirror-user",
            "MAVEN_REPO_CORP_MIRROR_PASSWORD": "mirror-pass",
        }
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("MAVEN_REPO_CORP_MIRROR_HOST", None)  # no pin set
            with unittest.mock.patch.object(
                server, "_load_settings_xml_servers", return_value={}
            ), unittest.mock.patch.object(
                server, "_load_gradle_properties", return_value={}
            ):
                creds = server.resolve_repo_credentials(mirrored)
        self.assertEqual(
            creds,
            {"type": "basic", "username": "mirror-user", "password": "mirror-pass"},
        )

    def test_unmirrored_entry_with_same_name_still_needs_host_pin(self):
        # Contrast case: an ORDINARY (non-mirrored) entry whose name happens
        # to equal "corp-mirror" is untrusted build-file input and MUST still
        # require the pin — the exception is keyed on `mirrored`, never on
        # the name string alone coinciding with a mirror id.
        entry = {"name": "corp-mirror", "url": "https://attacker.evil/repo"}
        env = {
            "MAVEN_REPO_CORP_MIRROR_USER": "mirror-user",
            "MAVEN_REPO_CORP_MIRROR_PASSWORD": "mirror-pass",
        }
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("MAVEN_REPO_CORP_MIRROR_HOST", None)
            with unittest.mock.patch.object(
                server, "_load_settings_xml_servers", return_value={}
            ), unittest.mock.patch.object(
                server, "_load_gradle_properties", return_value={}
            ):
                with self.assertLogs("maven_mcp", level="WARNING"):
                    creds = server.resolve_repo_credentials(entry)
        self.assertIsNone(creds)

    def test_settings_mirror_end_to_end_fetch_metadata_attaches_auth(self):
        # Full path: discover_repositories (empty declared repos) -> _repos_for
        # public fallback -> _finalize_repo_entries applies the mirror ->
        # fetch_metadata attaches Authorization from the mirror's OWN
        # settings.xml <servers> entry, with no _HOST pin configured anywhere.
        xml = _settings_xml("*", mirror_url=MIRROR_URL, mirror_id="corp-mirror")
        ctx = server.ResolutionContext(
            "/__x__", {"dependency": [], "plugin": []}, False,
            mirrors=server._parse_settings_xml_mirrors(xml),
        )
        env = {"MAVEN_REPO_CORP_MIRROR_TOKEN": "mirror-secret-tok"}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("MAVEN_REPO_CORP_MIRROR_HOST", None)
            with unittest.mock.patch.object(
                server, "_load_settings_xml_servers", return_value={}
            ), unittest.mock.patch.object(
                server, "_load_gradle_properties", return_value={}
            ), unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.0.0"]))]),
            ) as urlopen:
                result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["versions"], ["1.0.0"])
        req = urlopen.call_args.args[0]
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers["authorization"], "Bearer mirror-secret-tok")


# ---------------------------------------------------------------------------
# Offline / repository_base
# ---------------------------------------------------------------------------
class OfflineAndRepositoryBaseTest(unittest.TestCase):
    def test_offline_empty_scope_returns_no_repos(self):
        ctx = server.ResolutionContext(
            "/x", {"dependency": [], "plugin": []}, False, offline=True
        )
        self.assertEqual(server._repos_for("com.acme", "lib", ctx), [])

    def test_offline_drops_declared_public_shorthand(self):
        ctx = server.ResolutionContext(
            "/x",
            {
                "dependency": [
                    {"name": "Maven Central", "url": server.MAVEN_CENTRAL_URL}
                ],
                "plugin": [],
            },
            False,
            offline=True,
        )
        self.assertEqual(server._repos_for("com.acme", "lib", ctx), [])

    def test_repository_base_replaces_and_dedups_public(self):
        ctx = server.ResolutionContext(
            "/x",
            {"dependency": [], "plugin": []},
            False,
            repository_base=MIRROR_URL,
        )
        repos = server._repos_for("androidx.core", "core-ktx", ctx)
        # Google + Central both rewrite to the same base → one entry.
        self.assertEqual([r["url"] for r in repos], [MIRROR_URL])

    def test_offline_plus_repository_base_keeps_base(self):
        ctx = server.ResolutionContext(
            "/x",
            {"dependency": [], "plugin": []},
            False,
            offline=True,
            repository_base=MIRROR_URL,
        )
        repos = server._repos_for("com.acme", "lib", ctx)
        self.assertEqual([r["url"] for r in repos], [MIRROR_URL])

    def test_mirror_star_on_empty_scope_rewrites_public_fallback(self):
        ctx = _ctx_with_mirrors(
            [{"id": "nexus", "url": MIRROR_URL, "mirrorOf": "*"}]
        )
        repos = server._repos_for("com.acme", "lib", ctx)
        self.assertEqual([r["url"] for r in repos], [MIRROR_URL])
        self.assertEqual(repos[0]["name"], "nexus")

    def test_public_fallback_toggle_still_appends_when_not_offline(self):
        ctx = server.ResolutionContext(
            "/x",
            {
                "dependency": [{"name": "corp", "url": CUSTOM_URL}],
                "plugin": [],
            },
            True,  # public_fallback ON
        )
        urls = [r["url"] for r in server._repos_for("com.acme", "lib", ctx)]
        self.assertIn(CUSTOM_URL, urls)
        self.assertIn(server.MAVEN_CENTRAL_URL, urls)


# ---------------------------------------------------------------------------
# End-to-end: no public host contacted
# ---------------------------------------------------------------------------
class ClosedModeNoPublicContactTest(unittest.TestCase):
    def test_settings_mirror_star_fetch_metadata_hits_only_mirror(self):
        xml = _settings_xml("*")
        files = {
            "settings.gradle.kts": (
                "dependencyResolutionManagement { repositories { mavenCentral() } }"
            )
        }
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = os.path.join(tmp, "settings.xml")
            with open(settings_path, "w", encoding="utf-8") as fh:
                fh.write(xml)
            with temp_project(files) as root:
                with unittest.mock.patch.dict(
                    os.environ,
                    {"MAVEN_MCP_SETTINGS": settings_path},
                    clear=False,
                ):
                    # Ensure offline/base are not set from the developer env.
                    os.environ.pop("MAVEN_MCP_OFFLINE", None)
                    os.environ.pop("MAVEN_MCP_REPOSITORY_BASE", None)
                    ctx = server.build_resolution_context({"projectPath": root})
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _meta(["1.2.3"]))]),
            ) as m:
                result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["versions"], ["1.2.3"])
        urls = _urls(m)
        self.assertTrue(all(u.startswith(MIRROR_URL) for u in urls), urls)
        self.assertFalse(
            any(u.startswith(server.MAVEN_CENTRAL_URL) for u in urls)
        )

    def test_offline_fetch_metadata_raises_without_contacting_public(self):
        with temp_project({"README.md": "x"}) as root:
            with unittest.mock.patch.dict(
                os.environ, {"MAVEN_MCP_OFFLINE": "1"}, clear=False
            ):
                os.environ.pop("MAVEN_MCP_REPOSITORY_BASE", None)
                os.environ.pop("MAVEN_MCP_SETTINGS", None)
                # Point settings at a missing path so no real ~/.m2 mirrors leak in.
                os.environ["MAVEN_MCP_SETTINGS"] = os.path.join(
                    root, "no-such-settings.xml"
                )
                ctx = server.build_resolution_context({"projectPath": root})
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=AssertionError("no network")
        ) as m:
            with self.assertRaises(ValueError) as cm:
                server.fetch_metadata("com.acme", "lib", ctx)
        self.assertIn("offline/closed mode", str(cm.exception))
        self.assertEqual(m.call_count, 0)

    def test_repository_base_env_rewrites_public_fallback(self):
        with temp_project({"README.md": "x"}) as root:
            with unittest.mock.patch.dict(
                os.environ,
                {
                    "MAVEN_MCP_REPOSITORY_BASE": MIRROR_URL,
                    "MAVEN_MCP_SETTINGS": os.path.join(
                        root, "no-such-settings.xml"
                    ),
                },
                clear=False,
            ):
                os.environ.pop("MAVEN_MCP_OFFLINE", None)
                ctx = server.build_resolution_context({"projectPath": root})
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _meta(["9.9.9"]))]),
        ) as m:
            result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["versions"], ["9.9.9"])
        self.assertTrue(all(u.startswith(MIRROR_URL) for u in _urls(m)))


class GradleInitMirrorHeuristicTest(unittest.TestCase):
    def test_parse_single_non_public_url(self):
        script = (
            'repositories { mavenCentral()\n'
            f'  maven {{ url = uri("{MIRROR_URL}/") }}\n'
            "}"
        )
        urls = server._parse_gradle_init_mirror_urls(script)
        self.assertEqual(urls, [MIRROR_URL])

    def test_multi_url_not_promoted_to_catch_all(self):
        # Two distinct non-public URLs → too ambiguous; loader returns [].
        with tempfile.TemporaryDirectory() as tmp:
            gradle = os.path.join(tmp, ".gradle")
            os.makedirs(gradle)
            with open(
                os.path.join(gradle, "init.gradle.kts"), "w", encoding="utf-8"
            ) as fh:
                fh.write(
                    "repositories {\n"
                    f'  maven {{ url = uri("{MIRROR_URL}") }}\n'
                    f'  maven {{ url = uri("{CUSTOM_URL}") }}\n'
                    "  mavenCentral()\n"
                    "}\n"
                )
            real_expand = os.path.expanduser

            def _expand(p):
                return tmp if p == "~" else real_expand(p)

            with unittest.mock.patch.object(
                server.os.path, "expanduser", _expand
            ):
                # No settings.xml mirrors.
                with unittest.mock.patch.dict(
                    os.environ,
                    {"MAVEN_MCP_SETTINGS": os.path.join(tmp, "missing.xml")},
                    clear=False,
                ):
                    self.assertEqual(server._load_mirrors(), [])


if __name__ == "__main__":
    unittest.main()

"""Private Maven repository credential resolution and auth-header attachment (#291).

Covers env-var resolution, host matching, settings.xml / gradle.properties
fallbacks, Authorization header attachment on repo GETs, graceful
"auth required" failures, and secret redaction (secrets never appear in
tool-facing error strings or logs).
"""

import base64
import os
import tempfile
import unittest
import unittest.mock

from _helpers import server, mock_urlopen, http_error, temp_project, empty_ctx


def _headers_ci(req):
    return {name.lower(): value for name, value in req.header_items()}


def _meta(versions, last_updated="20240101000000"):
    vers = "".join(f"<version>{v}</version>" for v in versions)
    return (
        f"<metadata><versioning><versions>{vers}</versions>"
        f"<lastUpdated>{last_updated}</lastUpdated></versioning></metadata>"
    ).encode()


PRIVATE_URL = "https://nexus.example.com/repository/maven-releases/"
PRIVATE_HOST = "nexus.example.com"


class SanitizeCredKeyTest(unittest.TestCase):
    def test_alnum_uppercased(self):
        self.assertEqual(server._sanitize_cred_key("company-nexus"), "COMPANY_NEXUS")

    def test_host_dots_to_underscores(self):
        self.assertEqual(server._sanitize_cred_key("nexus.example.com"), "NEXUS_EXAMPLE_COM")

    def test_empty_and_symbols(self):
        self.assertEqual(server._sanitize_cred_key(""), "")
        self.assertEqual(server._sanitize_cred_key("!!!"), "")


class ResolveCredsFromEnvTest(unittest.TestCase):
    def test_bearer_token_alone(self):
        env = {"MAVEN_REPO_NEXUS_EXAMPLE_COM_TOKEN": "pat-secret"}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            # Clear sibling keys that might exist in the developer environment.
            for suffix in ("USER", "PASSWORD"):
                os.environ.pop(f"MAVEN_REPO_NEXUS_EXAMPLE_COM_{suffix}", None)
            creds = server._resolve_creds_from_env(PRIVATE_HOST)
        self.assertEqual(creds, {"type": "bearer", "token": "pat-secret"})

    def test_basic_user_password(self):
        env = {
            "MAVEN_REPO_CORP_NEXUS_USER": "alice",
            "MAVEN_REPO_CORP_NEXUS_PASSWORD": "s3cret",
        }
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("MAVEN_REPO_CORP_NEXUS_TOKEN", None)
            creds = server._resolve_creds_from_env("corp-nexus")
        self.assertEqual(
            creds, {"type": "basic", "username": "alice", "password": "s3cret"}
        )

    def test_basic_user_plus_token_as_password(self):
        # GitHub Packages / Artifactory PAT style: username + token, no password.
        env = {
            "MAVEN_REPO_GH_PACKAGES_USER": "alice",
            "MAVEN_REPO_GH_PACKAGES_TOKEN": "ghp_xxx",
        }
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("MAVEN_REPO_GH_PACKAGES_PASSWORD", None)
            creds = server._resolve_creds_from_env("gh-packages")
        self.assertEqual(
            creds, {"type": "basic", "username": "alice", "password": "ghp_xxx"}
        )

    def test_incomplete_user_only_returns_none(self):
        with unittest.mock.patch.dict(
            os.environ, {"MAVEN_REPO_HALF_USER": "alice"}, clear=False
        ):
            os.environ.pop("MAVEN_REPO_HALF_PASSWORD", None)
            os.environ.pop("MAVEN_REPO_HALF_TOKEN", None)
            self.assertIsNone(server._resolve_creds_from_env("half"))

    def test_no_match_returns_none(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            for k in list(os.environ):
                if k.startswith("MAVEN_REPO_MISSING_"):
                    os.environ.pop(k, None)
            self.assertIsNone(server._resolve_creds_from_env("missing"))


class SettingsXmlServersTest(unittest.TestCase):
    def test_parse_server_entries(self):
        xml = """
        <settings>
          <servers>
            <server>
              <id>corp-nexus</id>
              <username>bob</username>
              <password>p@ss</password>
            </server>
            <!-- <server><id>commented</id><username>x</username><password>y</password></server> -->
          </servers>
        </settings>
        """
        servers = server._parse_settings_xml_servers(xml)
        self.assertEqual(servers["corp-nexus"]["username"], "bob")
        self.assertEqual(servers["corp-nexus"]["password"], "p@ss")
        self.assertNotIn("commented", servers)

    def test_resolve_from_settings_file(self):
        xml = (
            "<settings><servers><server>"
            "<id>corp-nexus</id><username>bob</username><password>p@ss</password>"
            "</server></servers></settings>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            m2 = os.path.join(tmp, ".m2")
            os.makedirs(m2)
            with open(os.path.join(m2, "settings.xml"), "w", encoding="utf-8") as fh:
                fh.write(xml)
            real_expand = os.path.expanduser

            def _expand(p):
                return tmp if p == "~" else real_expand(p)

            with unittest.mock.patch.object(server.os.path, "expanduser", _expand):
                creds = server._resolve_creds_from_settings("corp-nexus")
        self.assertEqual(
            creds, {"type": "basic", "username": "bob", "password": "p@ss"}
        )


class GradlePropertiesCredsTest(unittest.TestCase):
    def test_parse_properties(self):
        text = "# comment\nnexusUsername=alice\nnexusPassword=s3cret\n"
        props = server._parse_gradle_properties(text)
        self.assertEqual(props["nexusUsername"], "alice")
        self.assertEqual(props["nexusPassword"], "s3cret")

    def test_resolve_username_password(self):
        text = "nexusUsername=alice\nnexusPassword=s3cret\n"
        with tempfile.TemporaryDirectory() as tmp:
            gradle = os.path.join(tmp, ".gradle")
            os.makedirs(gradle)
            with open(
                os.path.join(gradle, "gradle.properties"), "w", encoding="utf-8"
            ) as fh:
                fh.write(text)
            real_expand = os.path.expanduser

            def _expand(p):
                return tmp if p == "~" else real_expand(p)

            with unittest.mock.patch.object(server.os.path, "expanduser", _expand):
                creds = server._resolve_creds_from_gradle_properties("nexus")
        self.assertEqual(
            creds, {"type": "basic", "username": "alice", "password": "s3cret"}
        )


class ResolveRepoCredentialsTest(unittest.TestCase):
    def test_env_by_host_when_name_is_url(self):
        entry = {"name": PRIVATE_URL, "url": PRIVATE_URL}
        env = {"MAVEN_REPO_NEXUS_EXAMPLE_COM_TOKEN": "tok"}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            for suffix in ("USER", "PASSWORD"):
                os.environ.pop(f"MAVEN_REPO_NEXUS_EXAMPLE_COM_{suffix}", None)
            # settings/gradle fallbacks must not interfere
            with unittest.mock.patch.object(
                server, "_load_settings_xml_servers", return_value={}
            ), unittest.mock.patch.object(
                server, "_load_gradle_properties", return_value={}
            ):
                creds = server.resolve_repo_credentials(entry)
        self.assertEqual(creds, {"type": "bearer", "token": "tok"})

    def test_env_by_maven_id_preferred_over_host(self):
        entry = {"name": "corp-nexus", "url": PRIVATE_URL}
        env = {
            "MAVEN_REPO_CORP_NEXUS_USER": "id-user",
            "MAVEN_REPO_CORP_NEXUS_PASSWORD": "id-pass",
            "MAVEN_REPO_NEXUS_EXAMPLE_COM_TOKEN": "host-tok",
        }
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            with unittest.mock.patch.object(
                server, "_load_settings_xml_servers", return_value={}
            ), unittest.mock.patch.object(
                server, "_load_gradle_properties", return_value={}
            ):
                creds = server.resolve_repo_credentials(entry)
        self.assertEqual(
            creds, {"type": "basic", "username": "id-user", "password": "id-pass"}
        )

    def test_public_repo_no_creds(self):
        entry = {"name": "Maven Central", "url": server.MAVEN_CENTRAL_URL}
        with unittest.mock.patch.object(
            server, "_load_settings_xml_servers", return_value={}
        ), unittest.mock.patch.object(
            server, "_load_gradle_properties", return_value={}
        ):
            # Clear any accidental MAVEN_REPO_* for repo1.maven.org
            for k in list(os.environ):
                if k.startswith("MAVEN_REPO_REPO1_MAVEN_ORG"):
                    os.environ.pop(k, None)
            self.assertIsNone(server.resolve_repo_credentials(entry))


class AuthorizationHeaderTest(unittest.TestCase):
    def test_bearer(self):
        self.assertEqual(
            server._authorization_header({"type": "bearer", "token": "t"}),
            "Bearer t",
        )

    def test_basic_base64(self):
        header = server._authorization_header(
            {"type": "basic", "username": "u", "password": "p"}
        )
        expected = "Basic " + base64.b64encode(b"u:p").decode("ascii")
        self.assertEqual(header, expected)


class RepoRequestHeadersTest(unittest.TestCase):
    def test_attaches_bearer_for_matched_host(self):
        entry = {"name": PRIVATE_URL, "url": PRIVATE_URL}
        with unittest.mock.patch.object(
            server,
            "resolve_repo_credentials",
            return_value={"type": "bearer", "token": "secret-tok"},
        ):
            headers = server._repo_request_headers(entry)
        self.assertEqual(headers["Authorization"], "Bearer secret-tok")
        self.assertEqual(headers["User-Agent"], server.USER_AGENT)

    def test_no_authorization_without_creds(self):
        entry = {"name": "Maven Central", "url": server.MAVEN_CENTRAL_URL}
        with unittest.mock.patch.object(
            server, "resolve_repo_credentials", return_value=None
        ):
            headers = server._repo_request_headers(entry)
        self.assertNotIn("Authorization", headers)


class AuthHeaderAttachmentIntegrationTest(unittest.TestCase):
    """Repository GETs attach Authorization when credentials resolve."""

    def test_fetch_metadata_sends_basic_auth(self):
        ctx = server.ResolutionContext(
            "/__x__",
            {"dependency": [{"name": "corp-nexus", "url": PRIVATE_URL, "scope": "dependency"}],
             "plugin": []},
            False,
        )
        expected = "Basic " + base64.b64encode(b"alice:s3cret").decode("ascii")
        with unittest.mock.patch.object(
            server,
            "resolve_repo_credentials",
            return_value={"type": "basic", "username": "alice", "password": "s3cret"},
        ), unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _meta(["1.0.0"]))]),
        ) as urlopen:
            result = server.fetch_metadata("com.acme", "lib", ctx)
        self.assertEqual(result["versions"], ["1.0.0"])
        headers = _headers_ci(urlopen.call_args.args[0])
        self.assertEqual(headers["authorization"], expected)
        # Secret must not appear in resolvedFrom / tool-facing fields.
        self.assertNotIn("s3cret", str(result))
        self.assertNotIn("alice", str(result.get("resolvedFrom", {})))

    def test_fetch_metadata_auth_required_on_401(self):
        ctx = server.ResolutionContext(
            "/__x__",
            {"dependency": [{"name": "corp-nexus", "url": PRIVATE_URL, "scope": "dependency"}],
             "plugin": []},
            False,
        )
        with unittest.mock.patch.object(
            server, "resolve_repo_credentials", return_value=None
        ), unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error(PRIVATE_URL, 401)]),
        ):
            with self.assertRaises(ValueError) as cm:
                server.fetch_metadata("com.acme", "lib", ctx)
        msg = str(cm.exception)
        self.assertIn("auth required for corp-nexus", msg)
        self.assertIn("HTTP 401", msg)
        # No crash, no secret echo (there were none) — message is structured.
        self.assertNotIn("Authorization", msg)

    def test_fetch_metadata_auth_required_on_403_does_not_echo_token(self):
        ctx = server.ResolutionContext(
            "/__x__",
            {"dependency": [{"name": "corp-nexus", "url": PRIVATE_URL, "scope": "dependency"}],
             "plugin": []},
            False,
        )
        secret = "super-secret-token-value"
        with unittest.mock.patch.object(
            server,
            "resolve_repo_credentials",
            return_value={"type": "bearer", "token": secret},
        ), unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([http_error(PRIVATE_URL, 403)]),
        ):
            with self.assertRaises(ValueError) as cm:
                server.fetch_metadata("com.acme", "lib", ctx)
        msg = str(cm.exception)
        self.assertIn("auth required for corp-nexus", msg)
        self.assertNotIn(secret, msg)

    def test_public_repo_unchanged_without_creds(self):
        # empty_ctx → Maven Central only; no Authorization header.
        with unittest.mock.patch.object(
            server, "resolve_repo_credentials", return_value=None
        ), unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _meta(["9.0.0"]))]),
        ) as urlopen:
            result = server.fetch_metadata("org.example", "lib", empty_ctx())
        self.assertEqual(result["versions"], ["9.0.0"])
        headers = _headers_ci(urlopen.call_args.args[0])
        self.assertNotIn("authorization", headers)

    def test_verify_coordinates_sends_auth_and_resolves(self):
        files = {
            "settings.gradle.kts": (
                "dependencyResolutionManagement {\n"
                f'  repositories {{ maven {{ name = "corp-nexus"; url = uri("{PRIVATE_URL}") }} }}\n'
                "}\n"
            )
        }
        with temp_project(files) as root:
            with unittest.mock.patch.object(
                server,
                "resolve_repo_credentials",
                return_value={"type": "bearer", "token": "tok"},
            ), unittest.mock.patch(
                "urllib.request.urlopen",
                # Metadata probe + optional Layer-2 Solr (low_version_count may fire).
                side_effect=mock_urlopen([
                    (200, _meta(["1.2.3"])),
                    (200, b'{"response":{"docs":[]}}'),
                    (200, b'{"response":{"docs":[]}}'),
                ]),
            ) as urlopen:
                out = server.handle_verify_coordinates({
                    "dependencies": [{"groupId": "com.acme", "artifactId": "lib"}],
                    "projectPath": root,
                })
        item = out["results"][0]
        self.assertEqual(item["existenceStatus"], "exists")
        # First urlopen is the metadata probe; later gated Solr calls (typosquat
        # Layer 2) are unauthenticated Central searches — only assert the probe.
        probe_req = urlopen.call_args_list[0].args[0]
        headers = _headers_ci(probe_req)
        self.assertEqual(headers["authorization"], "Bearer tok")
        self.assertNotIn("tok", str(out))


class AuthCacheBypassTest(unittest.TestCase):
    def test_auth_headers_bypass_disk_cache(self):
        url = PRIVATE_URL + "com/acme/lib/maven-metadata.xml"
        headers = server._make_headers({"Authorization": "Bearer tok"})
        with unittest.mock.patch.object(
            server._file_cache, "get"
        ) as cache_get, unittest.mock.patch.object(
            server._file_cache, "set"
        ) as cache_set, unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b"<xml/>")]),
        ):
            status, body = server.http_get_cached(url, 3600, headers)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<xml/>")
        cache_get.assert_not_called()
        cache_set.assert_not_called()


class GradleNameParsingTest(unittest.TestCase):
    def test_maven_block_name_captured_for_cred_lookup(self):
        body = (
            'maven {\n'
            '  name = "corp-nexus"\n'
            f'  url = uri("{PRIVATE_URL}")\n'
            "}\n"
        )
        entries = server._parse_gradle_repos(body)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "corp-nexus")
        self.assertEqual(entries[0]["url"], PRIVATE_URL)


if __name__ == "__main__":
    unittest.main()

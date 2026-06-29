"""GitHub client + GitHub-only changelog path tests for the Python server.

Mirrors the TypeScript reference suites:
  - src/github/__tests__/github-client.test.ts   (gh_repo_exists / gh_fetch_*)
  - src/github/__tests__/discover-repo.test.ts    (discover_github_repo)
  - src/changelog/__tests__/github-provider.test.ts (the GitHub releases path)

Each test class cites the TS test it mirrors. Network is faked by patching
urllib.request.urlopen with the _helpers.mock_urlopen sequence builder; the
patched mock object records the urllib Request objects so URL + header
assertions read the exact bytes the server sent.

Divergence guardrail (#3): server.py's changelog path is GitHub-releases-ONLY.
There is no AGP/AndroidX provider and no provider-selection (the TS
changelog/resolver + agp/androidx providers do not exist in Python), and the
GitHub path does NOT fall back to a CHANGELOG.md file when no releases match
(the TS github-provider does). Those behaviours are intentionally NOT tested
here — only the github-releases path is exercised.
"""

import json
import re
import unittest
from unittest import mock

from _helpers import server, mock_urlopen, http_error


# POM fixtures mirror discover-repo.test.ts / github-provider.test.ts.
POM_WITH_SCM_KTOR = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<project><scm><url>https://github.com/ktorio/ktor</url></scm></project>"
)
POM_WITH_SCM_OKHTTP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<project><scm><url>https://github.com/square/okhttp</url></scm></project>"
)
POM_WITHOUT_SCM = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<project><groupId>com.example</groupId><artifactId>lib</artifactId></project>"
)


def _metadata_xml(versions):
    body = "".join(f"<version>{v}</version>" for v in versions)
    return f"<metadata><versioning><versions>{body}</versions></versioning></metadata>".encode()


def _captured_request(mock_obj, index=0):
    """Return the urllib Request object from the Nth recorded urlopen call."""
    return mock_obj.call_args_list[index].args[0]


# ---------------------------------------------------------------------------
# gh_repo_exists — mirrors github-client.test.ts "repoExists"
# ---------------------------------------------------------------------------
class GhRepoExistsTest(unittest.TestCase):
    def test_true_when_repo_exists(self):
        # repoExists "returns true when repo exists" + asserts URL.
        with mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([(200, b"{}")])
        ) as m:
            self.assertTrue(server.gh_repo_exists("owner", "repo"))
        req = _captured_request(m)
        self.assertEqual(req.full_url, "https://api.github.com/repos/owner/repo")
        self.assertEqual(req.get_header("Accept"), "application/vnd.github.v3+json")

    def test_false_when_repo_missing(self):
        # repoExists "returns false when repo does not exist" (404).
        err = http_error("https://api.github.com/repos/owner/repo", 404, "Not Found")
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen([err])):
            self.assertFalse(server.gh_repo_exists("owner", "repo"))

    def test_false_on_network_error(self):
        # repoExists "returns false on fetch error".
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([server.urllib.error.URLError("boom")]),
        ):
            self.assertFalse(server.gh_repo_exists("owner", "repo"))


# ---------------------------------------------------------------------------
# gh_fetch_repo — mirrors github-client.test.ts (repo JSON via _gh_get)
# ---------------------------------------------------------------------------
class GhFetchRepoTest(unittest.TestCase):
    def test_returns_repo_json(self):
        payload = {"full_name": "owner/repo", "stargazers_count": 42}
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, json.dumps(payload).encode())]),
        ) as m:
            result = server.gh_fetch_repo("owner", "repo")
        self.assertEqual(result, payload)
        self.assertEqual(
            _captured_request(m).full_url, "https://api.github.com/repos/owner/repo"
        )

    def test_returns_none_on_404(self):
        err = http_error("https://api.github.com/repos/owner/repo", 404)
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen([err])):
            self.assertIsNone(server.gh_fetch_repo("owner", "repo"))


# ---------------------------------------------------------------------------
# gh_fetch_releases — mirrors github-client.test.ts "fetchReleases"
# ---------------------------------------------------------------------------
class GhFetchReleasesTest(unittest.TestCase):
    def test_returns_releases_and_sends_headers(self):
        # fetchReleases "returns releases on success" + URL/header assertions.
        releases = [
            {"tag_name": "v1.0.0", "body": "First", "html_url": "u1"},
            {"tag_name": "v2.0.0", "body": "Second", "html_url": "u2"},
        ]
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, json.dumps(releases).encode())]),
        ) as m:
            result = server.gh_fetch_releases("owner", "repo")
        self.assertEqual(result, releases)
        req = _captured_request(m)
        self.assertEqual(
            req.full_url,
            "https://api.github.com/repos/owner/repo/releases?per_page=100",
        )
        self.assertEqual(req.get_header("Accept"), "application/vnd.github.v3+json")
        # User-Agent is stored capitalized as "User-agent" by urllib.request.Request.
        self.assertEqual(req.get_header("User-agent"), "maven-mcp/0.23.0")

    def test_returns_empty_list_on_404(self):
        # fetchReleases "returns empty array on non-ok response".
        err = http_error("https://api.github.com/x", 404)
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen([err])):
            self.assertEqual(server.gh_fetch_releases("owner", "repo"), [])

    def test_returns_empty_list_on_network_error(self):
        # fetchReleases "returns empty array on fetch error".
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([server.urllib.error.URLError("net")]),
        ):
            self.assertEqual(server.gh_fetch_releases("owner", "repo"), [])


# ---------------------------------------------------------------------------
# gh_fetch_user — _gh_get("/users/<login>")
# ---------------------------------------------------------------------------
class GhFetchUserTest(unittest.TestCase):
    def test_returns_user_json(self):
        payload = {"login": "square", "public_repos": 120}
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, json.dumps(payload).encode())]),
        ) as m:
            result = server.gh_fetch_user("square")
        self.assertEqual(result, payload)
        self.assertEqual(
            _captured_request(m).full_url, "https://api.github.com/users/square"
        )

    def test_returns_none_on_404(self):
        err = http_error("https://api.github.com/users/nobody", 404)
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen([err])):
            self.assertIsNone(server.gh_fetch_user("nobody"))


# ---------------------------------------------------------------------------
# gh_fetch_issue_stats — three sequential search calls (open, closed, median)
# ---------------------------------------------------------------------------
class GhFetchIssueStatsTest(unittest.TestCase):
    def test_aggregates_open_closed_ratio_and_median(self):
        open_resp = (200, json.dumps({"total_count": 5}).encode())
        closed_resp = (200, json.dumps({"total_count": 15}).encode())
        # Two closed issues: 2-day and 4-day durations -> even median = 3 days.
        median_resp = (
            200,
            json.dumps(
                {
                    "items": [
                        {
                            "created_at": "2024-01-01T00:00:00Z",
                            "closed_at": "2024-01-03T00:00:00Z",
                        },
                        {
                            "created_at": "2024-01-01T00:00:00Z",
                            "closed_at": "2024-01-05T00:00:00Z",
                        },
                    ]
                }
            ).encode(),
        )
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([open_resp, closed_resp, median_resp]),
        ) as m:
            stats = server.gh_fetch_issue_stats("owner", "repo")
        self.assertEqual(stats["open"], 5)
        self.assertEqual(stats["closed"], 15)
        self.assertEqual(stats["closeRatio"], 15 / 20)
        self.assertEqual(stats["medianDaysToClose"], 3)
        self.assertEqual(len(m.call_args_list), 3)
        self.assertIn("/search/issues", _captured_request(m).full_url)

    def test_returns_none_when_both_counts_unavailable(self):
        # Both search calls non-200 -> early return None before the median call.
        err = http_error("https://api.github.com/search/issues", 403, "rate limited")
        with mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([err, err])
        ) as m:
            self.assertIsNone(server.gh_fetch_issue_stats("owner", "repo"))
        # Only 2 calls: median_days_to_close is skipped when both counts are None.
        self.assertEqual(len(m.call_args_list), 2)


# ---------------------------------------------------------------------------
# GITHUB_TOKEN auth header — mirrors github-client.test.ts token tests
# ---------------------------------------------------------------------------
class GitHubAuthHeaderTest(unittest.TestCase):
    def test_authorization_header_sent_when_token_set(self):
        # "sends Authorization header when token is provided".
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "secret-token"}):
            with mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen([(200, b"{}")])
            ) as m:
                server.gh_fetch_repo("owner", "repo")
        self.assertEqual(
            _captured_request(m).get_header("Authorization"), "Bearer secret-token"
        )

    def test_no_authorization_header_without_token(self):
        # "does not send Authorization header when no token" (env cleared).
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch(
                "urllib.request.urlopen", side_effect=mock_urlopen([(200, b"{}")])
            ) as m:
                server.gh_fetch_repo("owner", "repo")
        self.assertIsNone(_captured_request(m).get_header("Authorization"))


# ---------------------------------------------------------------------------
# discover_github_repo — mirrors discover-repo.test.ts (POM SCM -> guess)
# ---------------------------------------------------------------------------
class DiscoverGithubRepoTest(unittest.TestCase):
    def test_returns_repo_from_pom_scm(self):
        # "returns GitHub repo from POM SCM". One urlopen (POM, Maven Central only).
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, POM_WITH_SCM_OKHTTP.encode())]),
        ) as m:
            result = server.discover_github_repo(
                "com.squareup.okhttp3", "okhttp", "4.12.0"
            )
        self.assertEqual(result, {"owner": "square", "repo": "okhttp"})
        self.assertEqual(len(m.call_args_list), 1)
        self.assertTrue(_captured_request(m).full_url.endswith("okhttp-4.12.0.pom"))

    def test_falls_back_to_guess_when_no_scm(self):
        # "falls back to guess when POM has no GitHub SCM" (io.github.* groupId).
        responses = [
            (200, POM_WITHOUT_SCM.encode()),  # POM has no github SCM
            (200, b"{}"),  # gh_repo_exists for the guessed repo -> 200
        ]
        with mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ) as m:
            result = server.discover_github_repo("io.github.javalin", "javalin", "5.0.0")
        self.assertEqual(result, {"owner": "javalin", "repo": "javalin"})
        self.assertEqual(len(m.call_args_list), 2)

    def test_returns_none_when_guessed_repo_missing(self):
        # "returns null when guess repo does not exist on GitHub".
        err = http_error("https://api.github.com/repos/someuser/nonexistent-lib", 404)
        responses = [(200, POM_WITHOUT_SCM.encode()), err]
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen(responses)):
            result = server.discover_github_repo(
                "io.github.someuser", "nonexistent-lib", "1.0.0"
            )
        self.assertIsNone(result)

    def test_returns_none_when_no_pom_and_not_guessable(self):
        # "returns null when no POM found and groupId is not guessable".
        err = http_error("https://repo1.maven.org/maven2/x.pom", 404)
        with mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen([err])
        ) as m:
            result = server.discover_github_repo(
                "org.apache.commons", "commons-lang3", "3.14.0"
            )
        self.assertIsNone(result)
        # POM fetch only (1 call); no guess possible -> no gh_repo_exists call.
        self.assertEqual(len(m.call_args_list), 1)


# ---------------------------------------------------------------------------
# _filter_version_range — from exclusive, to inclusive
# ---------------------------------------------------------------------------
class FilterVersionRangeTest(unittest.TestCase):
    def test_from_exclusive_to_inclusive(self):
        versions = ["1.0.0", "1.5.0", "2.0.0", "2.1.0"]
        result = server._filter_version_range(versions, "1.0.0", "2.0.0")
        # 1.0.0 excluded (from is exclusive); 2.0.0 included (to is inclusive);
        # 2.1.0 excluded (above to).
        self.assertEqual(result, ["1.5.0", "2.0.0"])

    def test_empty_when_nothing_in_range(self):
        versions = ["1.0.0"]
        self.assertEqual(server._filter_version_range(versions, "2.0.0", "3.0.0"), [])


# ---------------------------------------------------------------------------
# Tag normalization — re.sub(r"^[^0-9]*", "", tag)
# ---------------------------------------------------------------------------
class TagNormalizationTest(unittest.TestCase):
    def test_strips_leading_non_digits(self):
        # Mirrors tag-matcher.test.ts: leading prefix removed up to first digit.
        norm = lambda tag: re.sub(r"^[^0-9]*", "", tag)
        self.assertEqual(norm("v2.0.0"), "2.0.0")
        self.assertEqual(norm("release-1.5.0"), "1.5.0")
        self.assertEqual(norm("ktor-2.0.0"), "2.0.0")
        self.assertEqual(norm("1.0.0"), "1.0.0")


# ---------------------------------------------------------------------------
# _get_dependency_changes_impl — GitHub-releases-only changelog path
# mirrors changelog/__tests__/github-provider.test.ts (github path only)
# ---------------------------------------------------------------------------
class DependencyChangesImplTest(unittest.TestCase):
    def test_returns_changes_from_github_releases(self):
        # github-provider "returns entries from GitHub releases".
        releases = [
            {
                "tag_name": "v2.0.0",
                "body": "New features",
                "html_url": "https://github.com/ktorio/ktor/releases/tag/2.0.0",
            }
        ]
        responses = [
            (200, _metadata_xml(["1.0.0", "1.5.0", "2.0.0"])),  # fetch_metadata
            (200, POM_WITH_SCM_KTOR.encode()),  # discover_github_repo (POM SCM)
            (200, json.dumps(releases).encode()),  # gh_fetch_releases
        ]
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen(responses)):
            result = server._get_dependency_changes_impl(
                "io.ktor", "ktor-core", "1.0.0", "2.0.0"
            )
        self.assertNotIn("error", result)
        self.assertNotIn("repositoryNotFound", result)
        self.assertEqual(result["repositoryUrl"], "https://github.com/ktorio/ktor")
        by_version = {c["version"]: c for c in result["changes"]}
        # Range is (1.0.0, 2.0.0] -> 1.5.0 (no release) and 2.0.0 (matched).
        self.assertEqual(set(by_version), {"1.5.0", "2.0.0"})
        self.assertNotIn("body", by_version["1.5.0"])
        self.assertEqual(by_version["2.0.0"]["body"], "New features")
        self.assertEqual(
            by_version["2.0.0"]["releaseUrl"],
            "https://github.com/ktorio/ktor/releases/tag/2.0.0",
        )

    def test_tag_normalization_matches_prefixed_release(self):
        # A "ktor-1.5.0" tag is normalized to "1.5.0" and matched to the range.
        releases = [{"tag_name": "ktor-1.5.0", "body": "mid", "html_url": "u"}]
        responses = [
            (200, _metadata_xml(["1.0.0", "1.5.0"])),
            (200, POM_WITH_SCM_KTOR.encode()),
            (200, json.dumps(releases).encode()),
        ]
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen(responses)):
            result = server._get_dependency_changes_impl(
                "io.ktor", "ktor-core", "1.0.0", "1.5.0"
            )
        by_version = {c["version"]: c for c in result["changes"]}
        self.assertEqual(by_version["1.5.0"]["body"], "mid")

    def test_repository_not_found_branch(self):
        # discover_github_repo returns None (no SCM, groupId not guessable).
        responses = [
            (200, _metadata_xml(["1.0.0", "2.0.0"])),  # fetch_metadata
            (200, POM_WITHOUT_SCM.encode()),  # POM has no github SCM
        ]
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen(responses)):
            result = server._get_dependency_changes_impl(
                "com.example", "lib", "1.0.0", "2.0.0"
            )
        self.assertTrue(result["repositoryNotFound"])
        self.assertNotIn("repositoryUrl", result)

    def test_no_releases_branch(self):
        # Repo discovered but it has zero releases: every change is bare {version}.
        # Python divergence: unlike the TS github-provider, there is NO CHANGELOG.md
        # file fallback here — an empty releases list yields version-only entries.
        responses = [
            (200, _metadata_xml(["1.0.0", "2.0.0"])),
            (200, POM_WITH_SCM_KTOR.encode()),
            (200, b"[]"),  # gh_fetch_releases -> []
        ]
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen(responses)):
            result = server._get_dependency_changes_impl(
                "io.ktor", "ktor-core", "1.0.0", "2.0.0"
            )
        self.assertNotIn("error", result)
        self.assertEqual(result["repositoryUrl"], "https://github.com/ktorio/ktor")
        self.assertEqual(result["changes"], [{"version": "2.0.0"}])

    def test_empty_range_branch(self):
        # Filter yields nothing -> "No versions found" error, no network past metadata.
        responses = [(200, _metadata_xml(["1.0.0"]))]
        with mock.patch(
            "urllib.request.urlopen", side_effect=mock_urlopen(responses)
        ) as m:
            result = server._get_dependency_changes_impl(
                "io.ktor", "ktor-core", "2.0.0", "3.0.0"
            )
        self.assertEqual(result["error"], "No versions found between 2.0.0 and 3.0.0")
        self.assertEqual(len(m.call_args_list), 1)  # only the metadata fetch

    def test_metadata_unavailable_branch(self):
        # fetch_metadata raising (all repos 404) surfaces as an "error" field.
        err = http_error("https://repo1.maven.org/maven2/x/maven-metadata.xml", 404)
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen([err])):
            result = server._get_dependency_changes_impl(
                "io.ktor", "ktor-core", "1.0.0", "2.0.0"
            )
        self.assertIn("error", result)
        self.assertEqual(result["changes"], [])


if __name__ == "__main__":
    unittest.main()

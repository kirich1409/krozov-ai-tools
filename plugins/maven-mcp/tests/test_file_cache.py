"""Tests for FileCache primitive (T-1) and http_get_cached integration (T-2).

Import discipline: use ``import unittest.mock`` and fully-qualified refs
(``unittest.mock.patch``, ``unittest.mock.MagicMock``, etc.) throughout.
No ``from unittest import ...`` or ``from unittest.mock import ...`` — CodeQL
py/import-and-import-from blocks mixed-import patterns.
"""

import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
import unittest.mock
import urllib.error

from _helpers import server, mock_urlopen, empty_ctx, temp_cache_dir

# ---------------------------------------------------------------------------
# Shared test bodies for metadata / POM / search
# ---------------------------------------------------------------------------

_META_XML = (
    b'<?xml version="1.0"?>'
    b"<metadata>"
    b"<groupId>com.example</groupId>"
    b"<artifactId>artifact</artifactId>"
    b"<versioning>"
    b"<versions><version>1.0.0</version></versions>"
    b"<lastUpdated>20240101000000</lastUpdated>"
    b"</versioning>"
    b"</metadata>"
)

_POM_XML = b"<project><groupId>com.example</groupId><artifactId>artifact</artifactId><version>1.0.0</version></project>"

_SEARCH_JSON = json.dumps(
    {
        "response": {
            "docs": [
                {"g": "com.example", "a": "artifact", "latestVersion": "1.0.0", "versionCount": 5}
            ]
        }
    }
).encode()

_OSV_RESPONSE = json.dumps({"results": [{"vulns": []}]}).encode()


def _entry_path(tmpdir: str, url: str) -> str:
    """Return the expected cache file path for a given URL and XDG base dir."""
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return os.path.join(tmpdir, "maven-central-mcp", h + ".json")


# ---------------------------------------------------------------------------
# T-1: FileCache unit tests
# ---------------------------------------------------------------------------


class TestFileCache(unittest.TestCase):
    """Unit tests for the FileCache primitive (server.FileCache / server._file_cache)."""

    def setUp(self):
        self._ctx = temp_cache_dir()
        self.tmpdir = self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    # ---- basic hit/miss lifecycle -------------------------------------------

    def test_miss_set_hit_bytes_identical(self):
        url = "https://repo1.maven.org/maven2/com/example/1.0.0/example.pom"
        body = b"<project>hello</project>"
        self.assertIsNone(server._file_cache.get(url, 3600))
        server._file_cache.set(url, 200, body)
        result = server._file_cache.get(url, 3600)
        self.assertIsNotNone(result)
        self.assertEqual(result, (200, body))

    def test_empty_body_set_and_hit(self):
        """(200, b'') is a HIT — key/TTL decide the outcome, not body truthiness."""
        url = "https://repo1.maven.org/maven2/empty.xml"
        server._file_cache.set(url, 200, b"")
        result = server._file_cache.get(url, 3600)
        self.assertIsNotNone(result)
        self.assertEqual(result, (200, b""))

    # ---- TTL boundary (pin _now via monkeypatch) ----------------------------

    def test_ttl_boundary_hit_at_exact_ttl(self):
        """get at exactly t0+ttl must be a HIT (strict > not >=)."""
        url = "https://repo1.maven.org/maven2/ttl_hit.xml"
        t0 = 1_000_000.0
        ttl = 3600.0
        original_now = server._now
        server._now = lambda: t0
        try:
            server._file_cache.set(url, 200, b"data")
            server._now = lambda: t0 + ttl  # exactly at TTL
            result = server._file_cache.get(url, ttl)
            self.assertIsNotNone(result)
        finally:
            server._now = original_now

    def test_ttl_boundary_miss_one_second_past(self):
        """get at t0+ttl+1 must be a miss."""
        url = "https://repo1.maven.org/maven2/ttl_miss.xml"
        t0 = 1_000_000.0
        ttl = 3600.0
        original_now = server._now
        server._now = lambda: t0
        try:
            server._file_cache.set(url, 200, b"data")
            server._now = lambda: t0 + ttl + 1
            result = server._file_cache.get(url, ttl)
            self.assertIsNone(result)
        finally:
            server._now = original_now

    # ---- error / corruption cases ------------------------------------------

    def test_corrupt_entry_returns_none_no_raise(self):
        """A corrupt JSON cache file -> miss, never an exception."""
        url = "https://repo1.maven.org/maven2/corrupt.xml"
        cache_dir = os.path.join(self.tmpdir, "maven-central-mcp")
        os.makedirs(cache_dir, exist_ok=True)
        path = _entry_path(self.tmpdir, url)
        with open(path, "w") as fh:
            fh.write("{garbage")
        result = server._file_cache.get(url, 3600)
        self.assertIsNone(result)

    def test_non_200_set_writes_nothing(self):
        """set() with status != 200 must not write any file."""
        url = "https://repo1.maven.org/maven2/not_found.xml"
        server._file_cache.set(url, 404, b"Not Found")
        self.assertIsNone(server._file_cache.get(url, 3600))
        cache_dir = os.path.join(self.tmpdir, "maven-central-mcp")
        if os.path.exists(cache_dir):
            json_files = [f for f in os.listdir(cache_dir) if f.endswith(".json")]
            self.assertEqual(json_files, [])

    def test_url_mismatch_returns_miss(self):
        """A stored url != requested url (simulated hash collision) -> None."""
        url_a = "https://repo1.maven.org/maven2/a.xml"
        url_b = "https://repo1.maven.org/maven2/b.xml"
        # Prime the cache for url_a
        server._file_cache.set(url_a, 200, b"body_a")
        # Overwrite url_b's slot with url_a's entry (fake stored-url mismatch)
        path_a = _entry_path(self.tmpdir, url_a)
        path_b = _entry_path(self.tmpdir, url_b)
        with open(path_a, "rb") as fh:
            entry_data = json.loads(fh.read())
        # entry_data["url"] == url_a; put it at url_b's path → stored != requested
        with open(path_b, "w") as fh:
            json.dump(entry_data, fh)
        result = server._file_cache.get(url_b, 3600)
        self.assertIsNone(result)

    # ---- XDG / dir / permissions -------------------------------------------

    def test_xdg_cache_home_honored(self):
        """Cache files must live under XDG_CACHE_HOME/maven-central-mcp/."""
        url = "https://repo1.maven.org/maven2/xdg_test.xml"
        server._file_cache.set(url, 200, b"xdg_body")
        cache_dir = os.path.join(self.tmpdir, "maven-central-mcp")
        self.assertTrue(os.path.isdir(cache_dir), "maven-central-mcp subdir must be created")
        json_files = [f for f in os.listdir(cache_dir) if f.endswith(".json")]
        self.assertGreater(len(json_files), 0)

    def test_perms_under_pinned_umask(self):
        """Cache file must be 0o600 and dir must be 0o700 regardless of umask."""
        old_umask = os.umask(0o077)
        try:
            url = "https://repo1.maven.org/maven2/perms_test.xml"
            server._file_cache.set(url, 200, b"perm_body")
            cache_dir = os.path.join(self.tmpdir, "maven-central-mcp")
            dir_mode = stat.S_IMODE(os.stat(cache_dir).st_mode)
            self.assertEqual(dir_mode, 0o700, f"dir perms should be 0o700, got {oct(dir_mode)}")
            json_files = [f for f in os.listdir(cache_dir) if f.endswith(".json")]
            self.assertTrue(json_files, "at least one cache file must exist")
            for fname in json_files:
                fmode = stat.S_IMODE(os.stat(os.path.join(cache_dir, fname)).st_mode)
                self.assertEqual(fmode, 0o600, f"{fname} perms should be 0o600, got {oct(fmode)}")
        finally:
            os.umask(old_umask)

    def test_preexisting_loose_perm_dir_tightened(self):
        """A pre-existing 0o777 dir must be tightened to 0o700 on first cache use.

        This is the case that ACTUALLY exercises the explicit os.chmod call;
        the fresh-dir umask test passes even if the chmod is deleted.
        """
        cache_dir = os.path.join(self.tmpdir, "maven-central-mcp")
        os.makedirs(cache_dir, mode=0o777, exist_ok=True)
        os.chmod(cache_dir, 0o777)  # force loose perms before cache touches it

        url = "https://repo1.maven.org/maven2/loose_perm.xml"
        server._file_cache.set(url, 200, b"body")
        dir_mode = stat.S_IMODE(os.stat(cache_dir).st_mode)
        self.assertEqual(dir_mode, 0o700, f"dir should be tightened to 0o700, got {oct(dir_mode)}")

    # ---- set-swallow channel safety ----------------------------------------

    def test_set_swallow_does_not_write_stdout(self):
        """set() must swallow OSError without writing anything to stdout.

        StreamHandler binds sys.stderr at construction (import time), so
        redirect_stderr won't capture it — redirect the handler's stream
        directly via setStream for the duration of this test.
        """
        url = "https://repo1.maven.org/maven2/swallow.xml"
        stderr_buf = io.StringIO()
        stdout_buf = io.StringIO()
        original_stream = server._log_handler.stream
        server._log_handler.setStream(stderr_buf)
        try:
            with unittest.mock.patch("os.replace", side_effect=OSError("simulated disk full")):
                with unittest.mock.patch("sys.stdout", stdout_buf):
                    # Must NOT raise
                    server._file_cache.set(url, 200, b"body")
        finally:
            server._log_handler.setStream(original_stream)
        # JSON-RPC channel (stdout) must be untouched — load-bearing assertion
        self.assertEqual(stdout_buf.getvalue(), "")
        # Warning must land on stderr via the logger
        self.assertIn("FileCache set failed", stderr_buf.getvalue())

    # ---- disable flag -------------------------------------------------------

    def test_disable_truthy_values(self):
        """'1', 'true', 'yes', 'on' (case-insensitive) must disable the cache."""
        url = "https://repo1.maven.org/maven2/disable_truthy.xml"
        # Prime the cache while enabled
        server._file_cache.set(url, 200, b"cached")
        for value in ("1", "true", "True", "TRUE", "yes", "YES", "on", "ON"):
            with self.subTest(value=value):
                os.environ["MAVEN_MCP_CACHE_DISABLE"] = value
                try:
                    self.assertIsNone(server._file_cache.get(url, 3600),
                                      f"DISABLE={value!r} should cause a miss")
                finally:
                    os.environ.pop("MAVEN_MCP_CACHE_DISABLE", None)

    def test_disable_falsy_values_do_not_disable(self):
        """'0', 'false', '' must NOT disable the cache."""
        url = "https://repo1.maven.org/maven2/disable_falsy.xml"
        server._file_cache.set(url, 200, b"cached")
        for value in ("0", "false", ""):
            with self.subTest(value=value):
                os.environ["MAVEN_MCP_CACHE_DISABLE"] = value
                try:
                    result = server._file_cache.get(url, 3600)
                    self.assertIsNotNone(result, f"DISABLE={value!r} should NOT disable")
                finally:
                    os.environ.pop("MAVEN_MCP_CACHE_DISABLE", None)

    def test_disable_toggled_on_live_module(self):
        """MAVEN_MCP_CACHE_DISABLE set after import is honored per-call."""
        url = "https://repo1.maven.org/maven2/toggle.xml"
        server._file_cache.set(url, 200, b"initial")
        # Cache is active — should hit
        self.assertIsNotNone(server._file_cache.get(url, 3600))
        # Toggle disable on the live module
        os.environ["MAVEN_MCP_CACHE_DISABLE"] = "1"
        url2 = "https://repo1.maven.org/maven2/toggle2.xml"
        try:
            self.assertIsNone(server._file_cache.get(url, 3600),
                               "get must miss while DISABLE=1")
            server._file_cache.set(url2, 200, b"other")  # no-op while disabled
        finally:
            os.environ.pop("MAVEN_MCP_CACHE_DISABLE", None)
        # Nothing should have been written for url2 while disabled
        self.assertFalse(os.path.exists(_entry_path(self.tmpdir, url2)),
                         "set must be a no-op while MAVEN_MCP_CACHE_DISABLE=1")

    # ---- eviction -----------------------------------------------------------

    def test_eviction_invariants(self):
        """After inserting > CACHE_MAX_ENTRIES, count drops to ~90% and newest survives.

        Newest entry survival is verified by checking the cache FILE exists (not
        via get()) so the assertion is independent of the wall-clock TTL check.
        """
        n = server.CACHE_MAX_ENTRIES + 10
        t0 = 1_000_000.0  # synthetic fixed base time
        original_now = server._now
        try:
            for i in range(n):
                server._now = lambda _i=i: t0 + _i
                server._file_cache.set(f"https://example.com/e{i}", 200, b"x")
        finally:
            server._now = original_now

        cache_dir = os.path.join(self.tmpdir, "maven-central-mcp")
        entries = [f for f in os.listdir(cache_dir) if f.endswith(".json")]
        target = int(server.CACHE_MAX_ENTRIES * 0.9)
        # Count must be at or near the 90% target (slack for post-eviction inserts)
        self.assertLessEqual(len(entries), target + 11,
                             "eviction must bring count below CACHE_MAX_ENTRIES")
        # The newest entry's file must exist on disk (independent of TTL)
        newest_url = f"https://example.com/e{n - 1}"
        newest_path = _entry_path(self.tmpdir, newest_url)
        self.assertTrue(os.path.exists(newest_path),
                        "newest entry file must survive eviction")

    # ---- atomic write -------------------------------------------------------

    def test_atomic_write_no_tmp_residue(self):
        """After a successful set(), no *.tmp files should remain."""
        url = "https://repo1.maven.org/maven2/atomic.xml"
        server._file_cache.set(url, 200, b"atomic_body")
        cache_dir = os.path.join(self.tmpdir, "maven-central-mcp")
        tmp_files = [f for f in os.listdir(cache_dir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [], "no .tmp residue after successful set")

    def test_atomic_write_final_file_valid_json(self):
        """The written cache file must be parseable JSON with the correct structure."""
        url = "https://repo1.maven.org/maven2/json_check.xml"
        body = b"<data/>"
        server._file_cache.set(url, 200, body)
        path = _entry_path(self.tmpdir, url)
        with open(path) as fh:
            entry = json.load(fh)
        self.assertEqual(entry["v"], 1)
        self.assertEqual(entry["url"], url)
        self.assertEqual(entry["status"], 200)
        self.assertIn("body_b64", entry)
        self.assertIn("ts", entry)


# ---------------------------------------------------------------------------
# T-2: http_get_cached integration tests
# ---------------------------------------------------------------------------


class TestHttpGetCached(unittest.TestCase):
    """Integration tests for http_get_cached and the wired Maven call sites."""

    def setUp(self):
        self._ctx = temp_cache_dir()
        self.tmpdir = self._ctx.__enter__()
        # Patch _sleep so retry backoff does not slow tests
        self._sleep_patcher = unittest.mock.patch.object(server, "_sleep")
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()
        self._ctx.__exit__(None, None, None)

    def _cache_files(self):
        cache_dir = os.path.join(self.tmpdir, "maven-central-mcp")
        if not os.path.isdir(cache_dir):
            return []
        return [f for f in os.listdir(cache_dir) if f.endswith(".json")]

    # ---- T-2 (1): fetch_metadata cached after first call --------------------

    def test_fetch_metadata_cached_on_second_call(self):
        ctx = empty_ctx()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _META_XML)]),
        ) as m:
            server.fetch_metadata("com.example", "artifact", ctx)
            server.fetch_metadata("com.example", "artifact", ctx)
        self.assertEqual(m.call_count, 1, "second fetch_metadata must be served from cache")

    # ---- T-2 (2): fetch_pom cached after first call -------------------------

    def test_fetch_pom_cached_on_second_call(self):
        ctx = empty_ctx()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _POM_XML)]),
        ) as m:
            server.fetch_pom("com.example", "artifact", "1.0.0", ctx)
            server.fetch_pom("com.example", "artifact", "1.0.0", ctx)
        self.assertEqual(m.call_count, 1, "second fetch_pom must be served from cache")

    # ---- T-2 (2b): search_artifacts (via handle_search_artifacts) cached ----

    def test_handle_search_artifacts_cached(self):
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _SEARCH_JSON)]),
        ) as m:
            server.handle_search_artifacts({"query": "com.example", "limit": 10})
            server.handle_search_artifacts({"query": "com.example", "limit": 10})
        self.assertEqual(m.call_count, 1, "second search must be served from cache")

    # ---- T-2 (3): hit short-circuits ABOVE the retry layer ------------------

    def test_hit_short_circuits_above_http_get(self):
        """A cache hit must return without ever calling http_get (bypasses retry)."""
        ctx = empty_ctx()
        # First call: populate cache via real urlopen mock
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _META_XML)]),
        ):
            server.fetch_metadata("com.example", "artifact", ctx)
        # Second call: patch server.http_get itself — must never be called
        with unittest.mock.patch.object(server, "http_get") as mock_hg:
            server.fetch_metadata("com.example", "artifact", ctx)
            mock_hg.assert_not_called()

    # ---- T-2 (4): OSV excluded (POST never cached) --------------------------

    def test_osv_not_cached_positive_control(self):
        """query_osv_batch must hit the network on EVERY call (POST, never cached).

        Positive control: a fetch_metadata in the same fixture IS cached, proving
        the cache is live during this test.
        """
        ctx = empty_ctx()
        osv_dep = [{"groupId": "com.example", "artifactId": "artifact", "version": "1.0.0"}]
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([
                (200, _META_XML),      # fetch_metadata call 1 (miss -> network)
                (200, _OSV_RESPONSE),  # osv call 1
                (200, _OSV_RESPONSE),  # osv call 2
            ]),
        ) as m:
            server.fetch_metadata("com.example", "artifact", ctx)  # populates cache
            server.query_osv_batch(osv_dep)
            server.query_osv_batch(osv_dep)

        # fetch_metadata second call served from cache (urlopen NOT called again)
        server.fetch_metadata("com.example", "artifact", ctx)
        # Total: 1 (meta miss) + 2 (osv x2) = 3
        self.assertEqual(m.call_count, 3,
                         "OSV must hit network twice; meta only once (cached)")

    # ---- T-2 (5): GitHub excluded (stays raw http_get) ---------------------

    def test_github_not_cached_positive_control(self):
        """gh_repo_exists must hit the network on every call (not cached).

        Positive control: fetch_metadata in the same fixture IS cached.
        """
        ctx = empty_ctx()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([
                (200, _META_XML),   # fetch_metadata (miss)
                (200, b'{"id":1}'), # gh_repo_exists call 1
                (200, b'{"id":1}'), # gh_repo_exists call 2
            ]),
        ) as m:
            server.fetch_metadata("com.example", "artifact", ctx)
            server.gh_repo_exists("octocat", "hello-world")
            server.gh_repo_exists("octocat", "hello-world")

        # Total: 1 (meta miss) + 2 (gh x2) = 3
        self.assertEqual(m.call_count, 3,
                         "GitHub calls must hit network twice; meta only once (cached)")

    # ---- T-2 (6): _verify_one existence probe and suggestion search live ----

    def test_verify_one_existence_probe_and_suggestion_live(self):
        """_verify_one: both its per-repo existence probe AND its did-you-mean
        search must bypass the cache on every call (probe: raw http_get;
        search: search_maven_central use_cache=False).

        Positive control: fetch_metadata IS cached.
        """
        ctx = empty_ctx()
        # _verify_one with absent coord: probe returns 404, then suggestion search
        # Per call: 1 http_get (probe, 404) + 1 urlopen (search_maven_central live)
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([
                (200, _META_XML),       # fetch_metadata (miss -> network)
                (404, b""),             # _verify_one call 1: probe
                (200, _SEARCH_JSON),    # _verify_one call 1: suggestion search
                (404, b""),             # _verify_one call 2: probe
                (200, _SEARCH_JSON),    # _verify_one call 2: suggestion search
            ]),
        ) as m:
            server.fetch_metadata("com.example", "artifact", ctx)  # cached after this
            server._verify_one("com.ghost", "ghost-artifact", None, 3, ctx)
            server._verify_one("com.ghost", "ghost-artifact", None, 3, ctx)

        # meta: 1; _verify_one x2: 4 (2 probes + 2 searches) = 5 total
        self.assertEqual(m.call_count, 5,
                         "_verify_one must bypass cache for both probe and suggestion")

    # ---- T-2 (7): non-200 responses not cached ------------------------------

    def test_404_not_cached(self):
        """A 404 Maven metadata response must not be written to cache."""
        ctx = empty_ctx()
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([
                (404, b""),  # call 1
                (404, b""),  # call 2 — must hit network, not cache
            ]),
        ) as m:
            try:
                server.fetch_metadata("com.missing", "artifact", ctx)
            except ValueError:
                pass
            try:
                server.fetch_metadata("com.missing", "artifact", ctx)
            except ValueError:
                pass
        self.assertEqual(m.call_count, 2, "404 must not be cached")
        self.assertEqual(self._cache_files(), [],
                         "no cache file must be written for 404")

    def test_503_retried_and_not_cached(self):
        """A 503 response must be retried per HTTP_MAX_ATTEMPTS and never cached."""
        ctx = empty_ctx()
        attempts = server.HTTP_MAX_ATTEMPTS
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(503, b"")] * (attempts * 2)),
        ) as m:
            try:
                server.fetch_metadata("com.retried", "artifact", ctx)
            except Exception:
                pass
            try:
                server.fetch_metadata("com.retried", "artifact", ctx)
            except Exception:
                pass
        self.assertEqual(m.call_count, attempts * 2,
                         f"each 503 call should retry {attempts} times, never cached")
        self.assertEqual(self._cache_files(), [],
                         "no cache file must be written for 503")

    # ---- T-2 (8): transport error propagates, no cache file written ---------

    def test_transport_error_propagates_no_cache_file(self):
        """A transport error from http_get must propagate unchanged; no file written."""
        url = "https://repo1.maven.org/maven2/com/example/1.0.0/artifact-1.0.0.pom"
        exc = urllib.error.URLError("connection refused")
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([exc] * server.HTTP_MAX_ATTEMPTS),
        ):
            with self.assertRaises(urllib.error.URLError):
                server.http_get_cached(url, server.TTL_POM)
        self.assertEqual(self._cache_files(), [],
                         "no cache file on transport error")

    # ---- T-2 (9): MAVEN_MCP_CACHE_DISABLE disables wired call sites ---------

    def test_cache_disable_env_on_wired_path(self):
        """MAVEN_MCP_CACHE_DISABLE=1 must make fetch_metadata hit network every call."""
        ctx = empty_ctx()
        os.environ["MAVEN_MCP_CACHE_DISABLE"] = "1"
        try:
            with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=mock_urlopen([(200, _META_XML), (200, _META_XML)]),
            ) as m:
                server.fetch_metadata("com.example", "artifact", ctx)
                server.fetch_metadata("com.example", "artifact", ctx)
            self.assertEqual(m.call_count, 2,
                             "with DISABLE=1 both calls must hit network")
        finally:
            os.environ.pop("MAVEN_MCP_CACHE_DISABLE", None)

    # ---- T-2 (10): private/project-declared repo IS cached ------------------

    def test_private_repo_is_cached(self):
        """A fetch_metadata whose ctx resolves a custom host must be cached
        (proves call-site-discipline path works for non-public Maven repos).
        """
        ctx = server.ResolutionContext(
            "/__no_project__",
            {"dependency": [{"name": "private", "url": "https://maven.example.corp/repo"}],
             "plugin": []},
            False,
        )
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, _META_XML)]),
        ) as m:
            server.fetch_metadata("com.example", "artifact", ctx)
            server.fetch_metadata("com.example", "artifact", ctx)
        self.assertEqual(m.call_count, 1,
                         "private repo response must be cached after first call")

    # ---- T-2 (11): denylist bypass ------------------------------------------

    def test_denylist_bypass_github(self):
        """http_get_cached with an api.github.com URL must never write a cache file."""
        url = "https://api.github.com/repos/example/repo"
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b'{"id":1}'), (200, b'{"id":1}')]),
        ) as m:
            server.http_get_cached(url, 3600)
            server.http_get_cached(url, 3600)
        self.assertEqual(m.call_count, 2,
                         "api.github.com must bypass cache: 2 calls = 2 network hits")
        self.assertEqual(self._cache_files(), [],
                         "no cache file must be written for api.github.com")

    def test_denylist_bypass_osv(self):
        """http_get_cached with an api.osv.dev URL must never write a cache file.

        Note: real OSV uses POST (http_post_json), but the denylist applies to
        any GET at this host — belt-and-suspenders against future mis-wiring.
        """
        url = "https://api.osv.dev/v1/query"
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=mock_urlopen([(200, b'{}'), (200, b'{}')]),
        ) as m:
            server.http_get_cached(url, 3600)
            server.http_get_cached(url, 3600)
        self.assertEqual(m.call_count, 2,
                         "api.osv.dev must bypass cache: 2 calls = 2 network hits")
        self.assertEqual(self._cache_files(), [],
                         "no cache file must be written for api.osv.dev")


if __name__ == "__main__":
    unittest.main()

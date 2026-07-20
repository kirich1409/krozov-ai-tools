"""Shared test harness for the maven-mcp Python server.

Imports the shipped ``server`` module and provides HTTP / filesystem mocking
helpers. Stdlib only (zero third-party dependencies), matching the server's
zero-pip-dependency ethos.

Test modules should do ``from _helpers import server, mock_urlopen, ...`` so the
sys.path shim below is installed before ``server`` is first imported.
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest.mock
import urllib.error
from typing import Any, Callable, Dict, List, Optional, Union

# --- sys.path shim ----------------------------------------------------------
# Resolve plugin/server/ relative to THIS file, never the process cwd, so the
# suite imports the same `server` whether run from the repo root, /tmp, or
# anywhere else. server.py is import-safe (tail `if __name__ == "__main__"`).
_SERVER_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin", "server")
)
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

# Disable the on-disk cache for the whole test suite by default so mocked
# urlopen responses are not written to ~/.cache and do not serve stale data
# on subsequent runs.  Cache-specific tests re-enable per-test via temp_cache_dir().
os.environ.setdefault("MAVEN_MCP_CACHE_DISABLE", "1")
# Hermetic closed-mode defaults (#294): do not inherit the developer's
# ~/.m2/settings.xml mirrors or offline/base toggles into resolution tests.
# Tests that need mirrors set MAVEN_MCP_SETTINGS explicitly; offline/base
# tests use patch.dict.
os.environ.setdefault("MAVEN_MCP_SETTINGS", "/__maven_mcp_test_no_settings__")
os.environ.pop("MAVEN_MCP_OFFLINE", None)
os.environ.pop("MAVEN_MCP_REPOSITORY_BASE", None)
os.environ.pop("MAVEN_MCP_REPOSITORY_TYPE", None)
# Hermetic TLS/proxy defaults (#298): do not inherit developer proxy/CA/insecure.
os.environ.pop("MAVEN_MCP_CA_CERT", None)
os.environ.pop("MAVEN_MCP_INSECURE_TLS", None)
for _proxy_key in (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
):
    os.environ.pop(_proxy_key, None)

import server  # noqa: E402  (must follow the sys.path shim above)

# Public test API re-exported for ``from _helpers import ...``. Listing
# ``server`` makes the shimmed import above an intentional re-export rather
# than an unused import.
__all__ = [
    "server",
    "mock_urlopen",
    "http_error",
    "temp_project",
    "empty_ctx",
    "temp_cache_dir",
    "write_fake_gradlew",
    "write_smart_gradlew",
    "mock_gradle_resolve",
]


def empty_ctx(public_fallback: bool = False) -> "server.ResolutionContext":
    """A ResolutionContext with no project-declared repositories, so resolution
    falls back to the static public routing — the legacy behavior the pre-#310
    suite asserted. Hermetic (no filesystem read)."""
    return server.ResolutionContext(
        "/__no_project__", {"dependency": [], "plugin": []}, public_fallback
    )

# A single response spec: (status, body) tuple, or an Exception to raise.
ResponseSpec = Union["_MockResponse", BaseException, Any]


class _MockHeaders(dict):
    """Minimal headers mapping with case-insensitive ``.get`` for Content-Length."""

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        key_l = key.lower()
        for k, v in self.items():
            if str(k).lower() == key_l:
                return v
        return default


class _MockResponse:
    """Stand-in for the object returned by urllib.request.urlopen.

    server.py uses it as ``with urllib.request.urlopen(...) as resp:`` and reads
    ``resp.status`` / ``resp.read(n)`` / ``resp.headers`` — so this is both a
    context manager and exposes those members. ``read(n)`` honors a size cap
    like a real file-like body (#350).
    """

    def __init__(
        self,
        status: int,
        body: bytes,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.status = status
        self._body = body
        self._pos = 0
        self.headers = _MockHeaders(headers or {})

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            chunk = self._body[self._pos :]
            self._pos = len(self._body)
            return chunk
        chunk = self._body[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> "_MockResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


def mock_urlopen(responses: Union[ResponseSpec, List[ResponseSpec]]) -> Callable:
    """Build a ``side_effect`` callable for patching ``urllib.request.urlopen``.

    ``responses`` is a single response or a list of them consumed in order
    across consecutive urlopen calls. Each item is one of:
      - ``(status: int, body: bytes)`` -> returned as a context manager exposing
        ``.status`` and ``.read()``
      - ``(status: int, body: bytes, headers: dict)`` -> same, with headers
        (e.g. ``Content-Length`` for #350 size-cap tests)
      - an ``Exception`` instance (e.g. ``http_error(...)``) -> raised
      - a ``_MockResponse`` -> returned as-is

    Pass a ``list`` for a sequence; anything else is treated as a single
    response. Usage::

        with mock.patch("urllib.request.urlopen",
                        side_effect=mock_urlopen([(200, b"<xml/>")])):
            status, body = server.http_get(url)
    """
    queue = list(responses) if isinstance(responses, list) else [responses]
    iterator = iter(queue)

    def _side_effect(*_args: Any, **_kwargs: Any) -> _MockResponse:
        try:
            spec = next(iterator)
        except StopIteration:
            raise AssertionError(
                "mock_urlopen: more urlopen calls than configured responses"
            )
        if isinstance(spec, BaseException):
            raise spec
        if isinstance(spec, _MockResponse):
            return spec
        if len(spec) == 3:
            status, body, headers = spec
            return _MockResponse(status, body, headers)
        status, body = spec
        return _MockResponse(status, body)

    return _side_effect


def http_error(
    url: str,
    code: int,
    msg: str = "",
    hdrs: Any = None,
    body: bytes = b"",
) -> urllib.error.HTTPError:
    """Build a correctly-constructed 5-arg ``urllib.error.HTTPError``.

    server.py maps ``HTTPError -> (e.code, b"")``. Feed the result to
    ``mock_urlopen`` to make the patched urlopen raise it. Usage::

        err = http_error(url, 404, "Not Found")
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen([err])):
            status, body = server.http_get(url)  # -> (404, b"")
    """
    err = urllib.error.HTTPError(url, code, msg, hdrs or {}, io.BytesIO(body))
    # server.py maps HTTPError -> (e.code, b"") without ever reading the body, so
    # the wrapped BytesIO is never consumed. Close it now to avoid a
    # ResourceWarning when the unread stream is later garbage-collected.
    err.close()
    return err


@contextlib.contextmanager
def temp_project(files: Dict[str, str]):
    """Write ``{relative_path: content}`` into a fresh TemporaryDirectory and
    yield its path; the directory is removed on exit.

    Drives ``server.scan_project(path)`` against real build files. Usage::

        with temp_project({"pom.xml": "<project>...</project>"}) as root:
            result = server.scan_project(root)
    """
    with tempfile.TemporaryDirectory() as root:
        for rel, content in files.items():
            path = os.path.join(root, rel)
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        yield root


def write_fake_gradlew(root: str) -> str:
    """Create an executable stub ``gradlew`` in ``root`` for Gradle scan tests."""
    path = os.path.join(root, "gradlew")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    # Owner-only executable — avoids CodeQL py/overly-permissive-chmod on 0o755.
    os.chmod(path, 0o700)
    return path


def write_smart_gradlew(root: str) -> str:
    """Create a ``gradlew`` stub that echoes single-invocation init-script
    marker output (#401) for a two-module (root + ``:app``) project.

    Exercises the real subprocess → parse path in ``_gradle_resolve_dependencies``
    without a JVM or Gradle installation. The stub does not actually read the
    generated ``--init-script`` file (there is no JVM here to execute it) — it
    just recognises the ``--init-script`` flag and prints the same marker
    format the real init script would produce.
    """
    path = os.path.join(root, "gradlew")
    script = r"""#!/bin/sh
joined="$*"
if echo "$joined" | grep -q -- "--init-script"; then
  printf '%s\n' \
    "===MAVEN_MCP_MODULE=== :" \
    "===MAVEN_MCP_MODULE_END===" \
    "===MAVEN_MCP_MODULE=== :app" \
    "===MAVEN_MCP_CONFIG=== releaseRuntimeClasspath" \
    "io.ktor:ktor-client-core:3.1.2" \
    "===MAVEN_MCP_CONFIG_END===" \
    "===MAVEN_MCP_MODULE_END===" \
    "===MAVEN_MCP_BUILDENV===" \
    "com.android.tools.build:gradle:8.0.0" \
    "===MAVEN_MCP_BUILDENV_END==="
  exit 0
fi
exit 0
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(script)
    os.chmod(path, 0o700)
    return path


@contextlib.contextmanager
def mock_gradle_resolve(
    dependencies: Optional[List[Dict]] = None,
    *,
    errors: Optional[List[str]] = None,
    notes: Optional[List[str]] = None,
    production_count: Optional[int] = None,
):
    """Patch ``server._gradle_resolve_dependencies`` to return fixture output."""

    def _production_count(deps: List[Dict]) -> int:
        count = 0
        for dep in deps:
            for usage in dep.get("usages") or []:
                if server._is_production_runtime_configuration(
                    usage.get("configuration", "")
                ):
                    count += 1
                    break
        return count

    def _fake_resolve(_project_root: str) -> Dict:
        deps = list(dependencies if dependencies is not None else [])
        err = list(errors or [])
        if not deps and not err:
            # scan_project rejects an empty Gradle resolve; tests that only
            # exercise provenance/dead-repo hints need a placeholder GAV.
            deps = [{
                "groupId": "com.example",
                "artifactId": "fixture",
                "version": "1.0",
                "resolvedBy": "gradle",
                "usages": [{"module": None, "configuration": "releaseRuntimeClasspath"}],
            }]
        return {
            "dependencies": deps,
            "notes": list(notes or []),
            "errors": err,
            "productionCount": (
                production_count
                if production_count is not None
                else _production_count(deps)
            ),
        }

    with unittest.mock.patch.object(server, "_gradle_resolve_dependencies", _fake_resolve):
        yield


@contextlib.contextmanager
def temp_cache_dir():
    """Pin the file cache to a fresh temp dir and ensure MAVEN_MCP_CACHE_DISABLE is absent.

    Pins ``XDG_CACHE_HOME`` to a fresh ``TemporaryDirectory`` via
    ``unittest.mock.patch.dict`` (guaranteed env restore on exit).
    ``MAVEN_MCP_CACHE_DISABLE`` is popped before entering the patch so the
    cache is active inside the context; the ``finally`` block restores it even
    if the body raises, so both keys reset atomically.

    Usage::

        with temp_cache_dir() as tmpdir:
            server._file_cache.set(url, 200, b"body")
            # cache file written under tmpdir/maven-central-mcp/
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        prior_disable = os.environ.pop("MAVEN_MCP_CACHE_DISABLE", None)
        try:
            with unittest.mock.patch.dict("os.environ", {"XDG_CACHE_HOME": tmpdir}):
                yield tmpdir
        finally:
            if prior_disable is not None:
                os.environ["MAVEN_MCP_CACHE_DISABLE"] = prior_disable

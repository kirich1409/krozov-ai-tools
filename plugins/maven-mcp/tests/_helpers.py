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
import urllib.error
from typing import Any, Callable, Dict, List, Union

# --- sys.path shim ----------------------------------------------------------
# Resolve plugin/server/ relative to THIS file, never the process cwd, so the
# suite imports the same `server` whether run from the repo root, /tmp, or
# anywhere else. server.py is import-safe (tail `if __name__ == "__main__"`).
_SERVER_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin", "server")
)
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

import server  # noqa: E402  (must follow the sys.path shim above)

# Public test API re-exported for ``from _helpers import ...``. Listing
# ``server`` makes the shimmed import above an intentional re-export rather
# than an unused import.
__all__ = ["server", "mock_urlopen", "http_error", "temp_project"]

# A single response spec: (status, body) tuple, or an Exception to raise.
ResponseSpec = Union["_MockResponse", BaseException, Any]


class _MockResponse:
    """Stand-in for the object returned by urllib.request.urlopen.

    server.py uses it as ``with urllib.request.urlopen(...) as resp:`` and reads
    ``resp.status`` / ``resp.read()`` — so this is both a context manager and
    exposes those two members.
    """

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

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

"""Shared test harness for the youtube-transcript Python server.

T-1 scope only: the sys.path shim that lets test modules import the packages
under ``plugin/server/`` as top-level modules (``domain``, ``net``, ``providers``,
``formats``, ``protocol``, ``tools``), plus a hermetic env-var reset so the suite's
behavior does not depend on the developer's shell environment. Stdlib only (zero
third-party dependencies), matching the server's zero-pip-dependency ethos.

Later tasks (T-3) extend this file with ``FakeProvider``/``FakeSession``,
``mock_urlopen``, and other transport doubles once ``providers/base.py`` and
``net/client.py`` exist -- deliberately not added here.

Test modules should do ``import _helpers`` (or ``from _helpers import ...``) before
importing anything from the packages under ``plugin/server/``, so the sys.path shim
below is installed first.
"""

import os
import sys

# --- sys.path shim ----------------------------------------------------------
# Resolve plugin/server/ relative to THIS file, never the process cwd, so the
# suite imports the same packages whether run from the repo root, /tmp, or
# anywhere else (mirrors plugins/maven-mcp/tests/_helpers.py).
_SERVER_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin", "server")
)
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

# --- hermetic env-var reset --------------------------------------------------
# The live-canary gate (AC-13): default to off so an ambient
# YOUTUBE_TRANSCRIPT_LIVE_CANARY=1 in the developer's shell can't silently make an
# otherwise-mocked test suite reach out to the real network.
os.environ.pop("YOUTUBE_TRANSCRIPT_LIVE_CANARY", None)
# Hermetic proxy defaults: this server talks to the network via stdlib urllib
# (net/client.py, T-3+), so an inherited proxy env var must not change request
# routing under test, mirroring plugins/maven-mcp/tests/_helpers.py's identical
# reset for the same reason.
for _proxy_key in (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
):
    os.environ.pop(_proxy_key, None)

__all__: list = []

#!/usr/bin/env bash
# L3 smoke verification for a packed youtube-transcript MCPB bundle.
#
# Usage: scripts/smoke-mcpb.sh [--require-checksum] <bundle.mcpb>
#
# Runs eight assertions against the bundle produced by scripts/pack-mcpb.sh
# and exits 0 only if all of them pass. Each assertion fails with its own
# distinct, stable message so T-4b's tampered-bundle tests can grep for the
# exact assertion that caught a given defect.
#
# Requires a git checkout at the same commit as the bundle build (assertion 2
# reads the tracked file list via `git ls-files`).
#
# Scope: this verifies a bundle built from this same checkout. Assertion 7
# executes the bundle's server, so it is NOT a scanner for bundles from an
# untrusted source.
#
# Portability: this must run on stock macOS, which ships bash 3.2 (no
# `mapfile`/`readarray`) and no `timeout(1)`. Arrays are filled with
# `while IFS= read -r`, and the handshake's per-step deadline is implemented
# in the Python helper below (subprocess I/O with a real timeout) rather than
# with `timeout(1)` or a hand-rolled bash background-kill loop.
set -euo pipefail

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

REQUIRE_CHECKSUM=0
BUNDLE_ARG=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --require-checksum)
      REQUIRE_CHECKSUM=1
      shift
      ;;
    --)
      shift
      if [ "$#" -gt 0 ]; then
        BUNDLE_ARG="$1"
        shift
      fi
      ;;
    -*)
      fail "smoke-mcpb: unknown argument: $1"
      ;;
    *)
      # A silently dropped second path is the worst failure mode for a release
      # verifier: it would report success for a bundle it never looked at.
      if [ -n "$BUNDLE_ARG" ]; then
        fail "smoke-mcpb: unexpected extra argument: $1"
      fi
      BUNDLE_ARG="$1"
      shift
      ;;
  esac
done

if [ -z "$BUNDLE_ARG" ]; then
  fail "smoke-mcpb: usage: scripts/smoke-mcpb.sh [--require-checksum] <bundle.mcpb>"
fi

# Resolve the bundle path to absolute before any cd below changes cwd meaning.
case "$BUNDLE_ARG" in
  /*) BUNDLE="$BUNDLE_ARG" ;;
  *) BUNDLE="$PWD/$BUNDLE_ARG" ;;
esac

if [ ! -f "$BUNDLE" ]; then
  fail "smoke-mcpb: bundle not found: $BUNDLE"
fi

if REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
  :
else
  fail "smoke-mcpb: not inside a git checkout (required to verify assertion 2 against the tracked file list)"
fi
cd "$REPO_ROOT"

PLUGIN_JSON="plugins/youtube-transcript/plugin/.claude-plugin/plugin.json"
SERVER_DIR="plugins/youtube-transcript/plugin/server"

TMP=$(mktemp -d)
RUNDIR=$(mktemp -d)
cleanup() {
  rm -rf "$TMP" "$RUNDIR"
}
trap cleanup EXIT

# Path-traversal guard, deliberately BEFORE extraction. Assertion 1's
# `server/.*\.py` pattern does not exclude `..`, and Info-ZIP happens to strip
# `../` components on its own -- but that is a property of one unzip
# implementation, not a check. Refuse such an archive explicitly instead.
ENTRIES=$(unzip -Z1 "$BUNDLE")
if printf '%s\n' "$ENTRIES" | grep -q '\.\.'; then
  fail "assertion 1 failed: archive entry contains '..': $(printf '%s\n' "$ENTRIES" | grep '\.\.' | tr '\n' ' ')"
fi

unzip -q "$BUNDLE" -d "$TMP"

# --- Assertion 1: nothing foreign in the archive. ---------------------------
FOREIGN=$(printf '%s\n' "$ENTRIES" | grep -v '/$' | grep -vE '^(manifest\.json|LICENSE\.md|server/.*\.py)$' || true)
if [ -n "$FOREIGN" ]; then
  fail "assertion 1 failed: foreign archive entries present: $(printf '%s' "$FOREIGN" | tr '\n' ' ')"
fi

# --- Assertion 2: nothing missing -- archive .py set equals the tracked set,
# plus name anchors for the two files a naive '**/*.py' pathspec drops. -----
ARCHIVE_PY=$(printf '%s\n' "$ENTRIES" | grep -E '^server/.*\.py$' | LC_ALL=C sort || true)
GIT_PY=$(git ls-files -- "$SERVER_DIR" | grep '\.py$' | sed "s#^$SERVER_DIR/#server/#" | LC_ALL=C sort || true)

if [ "$ARCHIVE_PY" != "$GIT_PY" ]; then
  fail "assertion 2 failed: archive server .py set differs from the git index"
fi

if printf '%s\n' "$ARCHIVE_PY" | grep -Fxq "server/server.py"; then
  :
else
  fail "assertion 2 failed: archive missing anchor file server/server.py"
fi

if printf '%s\n' "$ARCHIVE_PY" | grep -Fxq "server/composition.py"; then
  :
else
  fail "assertion 2 failed: archive missing anchor file server/composition.py"
fi

# --- Assertion 3: manifest version equals plugin.json's. -------------------
MANIFEST_VERSION=$(jq -r '.version' "$TMP/manifest.json")
PLUGIN_VERSION=$(jq -r '.version' "$PLUGIN_JSON")
if [ "$MANIFEST_VERSION" != "$PLUGIN_VERSION" ]; then
  fail "assertion 3 failed: manifest version ($MANIFEST_VERSION) does not match plugin.json version ($PLUGIN_VERSION)"
fi

# --- Assertion 4: packed SERVER_VERSION agrees with the manifest. ----------
# Fixed-string, whole-line match: an ERE would let the '.' in "0.27.0" match
# any character. Deliberately not asserting on initialize's
# result.serverInfo.version -- protocol/dispatch.py hardcodes "1" there by
# design (see the plan brief); that field is the MCP wire protocol's own
# identity, decoupled from this plugin's release version.
if grep -qxF "SERVER_VERSION = \"$MANIFEST_VERSION\"" "$TMP/server/server.py"; then
  :
else
  fail "assertion 4 failed: packed server.py SERVER_VERSION does not equal manifest version $MANIFEST_VERSION"
fi

# --- Assertion 5: checksum verifies (transport integrity only). ------------
SHA_FILE="$BUNDLE.sha256"
if [ -f "$SHA_FILE" ]; then
  if command -v shasum >/dev/null 2>&1; then
    SHA_TOOL=(shasum -a 256)
  else
    SHA_TOOL=(sha256sum)
  fi
  if (cd "$(dirname "$BUNDLE")" && "${SHA_TOOL[@]}" -c "$(basename "$SHA_FILE")") >/dev/null 2>&1; then
    :
  else
    fail "assertion 5 failed: checksum verification failed for $(basename "$BUNDLE")"
  fi
else
  if [ "$REQUIRE_CHECKSUM" -eq 1 ]; then
    fail "assertion 5 failed: checksum file missing: $(basename "$SHA_FILE")"
  fi
fi

# --- Assertion 6: manifest contract -- deep equality on the whole `server`
# object (not field-by-field: v0.4 also allows mcp_config.env and
# mcp_config.platform_overrides, and a platform override replaces
# command/args for that platform -- a field-by-field check would pass a
# manifest that actually runs something else on the user's machine). --------
MANIFEST_SCHEMA_VERSION=$(jq -r '.manifest_version' "$TMP/manifest.json")
if [ "$MANIFEST_SCHEMA_VERSION" != "0.4" ]; then
  fail "assertion 6 failed: manifest_version is $MANIFEST_SCHEMA_VERSION, expected 0.4"
fi

if jq -e '.server == {"type":"python","entry_point":"server/server.py","mcp_config":{"command":"python3","args":["${__dirname}/server/server.py"]}}' "$TMP/manifest.json" >/dev/null; then
  :
else
  fail "assertion 6 failed: manifest .server object does not deep-equal the expected contract"
fi

if jq -e '.compatibility.platforms == ["darwin","linux"]' "$TMP/manifest.json" >/dev/null; then
  :
else
  fail "assertion 6 failed: compatibility.platforms does not equal [\"darwin\",\"linux\"]"
fi

# --- Assertion 7: handshake driven from the manifest's own command/args. ---
# Declarations only -- initialize, notifications/initialized, tools/list.
# No tools/call, no canary env var, no network egress (this runs on fork
# PRs). Deadlines are enforced inside the Python helper (subprocess pipe I/O
# with a real per-step timeout) rather than with timeout(1) (absent on stock
# macOS) or a bash FIFO background-kill loop.
#
# ORDERING INVARIANT -- DO NOT MOVE THIS BLOCK ABOVE ASSERTION 6. This step
# executes the command declared *inside the bundle under test*. The only reason
# that is safe is that assertion 6 has already pinned the whole `.server`
# object by deep equality, so `command`/`args` cannot be anything but
# python3 + the bundled entry point. Reordering turns this verifier into a
# runner of arbitrary commands from an archive. The explicit check below
# re-states the invariant locally instead of relying on line order alone (it
# also keeps "${ARGS[@]}" from tripping `set -u` on bash 3.2 when args is
# empty).
MANIFEST_COMMAND=$(jq -r '.server.mcp_config.command' "$TMP/manifest.json")
if [ "$MANIFEST_COMMAND" != "python3" ]; then
  fail "assertion 7 failed: manifest command is not python3 (assertion 6 must run first): $MANIFEST_COMMAND"
fi
ARGS=()
while IFS= read -r arg_line; do
  ARGS+=("$arg_line")
done < <(jq -r '.server.mcp_config.args[]' "$TMP/manifest.json")

if [ "${#ARGS[@]}" -eq 0 ]; then
  fail "assertion 7 failed: manifest declares no mcp_config.args (assertion 6 must run first)"
fi

for i in "${!ARGS[@]}"; do
  ARGS[i]="${ARGS[i]//\$\{__dirname\}/$TMP}"
done

HANDSHAKE_ERR="$RUNDIR/handshake.err"

if RUNTIME_TOOLS=$(cd "$RUNDIR" && python3 - "$MANIFEST_COMMAND" "${ARGS[@]}" 2>"$HANDSHAKE_ERR" <<'PYEOF'
import json
import queue
import subprocess
import sys
import threading

STEP_DEADLINE_SECONDS = 10.0
STDERR_TAIL_LINES = 200

proc = None
STDERR_BUF = []


def fail(message):
    # Best-effort: a failing assertion must not leave the spawned server
    # process (e.g. one hung in a sleep) running as an orphan after this
    # helper exits.
    if proc is not None and proc.poll() is None:
        proc.kill()
    print(message, file=sys.stderr)
    # Without this the real cause (ImportError, a missing module in the
    # bundle, an incompatible Python) collapses into a generic
    # "no response at step initialize" and is unrecoverable from CI logs.
    if STDERR_BUF:
        print("--- server stderr (last %d lines) ---" % STDERR_TAIL_LINES, file=sys.stderr)
        sys.stderr.write("".join(STDERR_BUF[-STDERR_TAIL_LINES:]))
    sys.exit(1)


cmd = sys.argv[1:]
try:
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
except OSError as exc:
    fail("assertion 7 failed: could not launch the server process: " + str(exc))


def _drain_stderr():
    # The pipe must be drained continuously, not read at the end: a server
    # writing more than the kernel pipe buffer (~64 KiB) before responding
    # blocks on write forever, which is indistinguishable from a hang.
    try:
        for line in proc.stderr:
            STDERR_BUF.append(line)
    except Exception:
        pass


threading.Thread(target=_drain_stderr, daemon=True).start()


def send(message):
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def recv_line(step):
    result = queue.Queue()

    def reader():
        try:
            result.put(proc.stdout.readline())
        except Exception:
            result.put("")

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        line = result.get(timeout=STEP_DEADLINE_SECONDS)
    except queue.Empty:
        fail("assertion 7 failed: handshake timed out at " + step)
    if not line:
        fail("assertion 7 failed: no response at step " + step)
    return line


send(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "smoke-mcpb", "version": "0"},
        },
    }
)
init_line = recv_line("initialize")
try:
    init_resp = json.loads(init_line)
except json.JSONDecodeError:
    fail("assertion 7 failed: initialize response is not valid JSON: " + init_line.strip())
if "error" in init_resp:
    fail("assertion 7 failed: initialize returned an error: " + json.dumps(init_resp["error"]))

send({"jsonrpc": "2.0", "method": "notifications/initialized"})

send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
list_line = recv_line("tools/list")
try:
    list_resp = json.loads(list_line)
except json.JSONDecodeError:
    fail("assertion 7 failed: tools/list response is not valid JSON: " + list_line.strip())
if "error" in list_resp:
    fail("assertion 7 failed: tools/list returned an error: " + json.dumps(list_resp["error"]))

tools = list_resp.get("result", {}).get("tools", [])
for tool in tools:
    print(tool["name"])

proc.terminate()
try:
    proc.wait(timeout=STEP_DEADLINE_SECONDS)
except Exception:
    proc.kill()
PYEOF
); then
  :
else
  ERR_MSG=$(cat "$HANDSHAKE_ERR" 2>/dev/null || true)
  if [ -n "$ERR_MSG" ]; then
    fail "$ERR_MSG"
  else
    fail "assertion 7 failed: handshake process exited with a non-zero status"
  fi
fi

# --- Assertion 8: manifest tools set equals the runtime tools/list set. ----
MANIFEST_TOOLS=$(jq -r '.tools[].name' "$TMP/manifest.json" | LC_ALL=C sort)
RUNTIME_TOOLS_SORTED=$(printf '%s\n' "$RUNTIME_TOOLS" | LC_ALL=C sort)
if [ "$MANIFEST_TOOLS" != "$RUNTIME_TOOLS_SORTED" ]; then
  fail "assertion 8 failed: manifest tools set differs from the runtime tools/list set"
fi

echo "smoke-mcpb: all 8 assertions passed"

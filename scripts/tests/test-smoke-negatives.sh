#!/usr/bin/env bash
# Negative-path proof for scripts/smoke-mcpb.sh: tamper a correctly-built
# bundle nine different ways and assert that each tamper is rejected by its
# own named assertion. A green run of smoke-mcpb.sh on a correct bundle does
# not prove the checks can fail -- a subtly inverted assertion looks
# identical on the happy path. This script is the counter-evidence.
#
# Does not modify scripts/smoke-mcpb.sh or scripts/pack-mcpb.sh: both are
# already closed and verified. This script only packs and tampered-packs
# bundles and feeds them through the unmodified smoke script.
#
# Portability: stock macOS bash 3.2 -- no associative arrays, no `mapfile`.
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

PACK="scripts/pack-mcpb.sh"
SMOKE="scripts/smoke-mcpb.sh"
MCPB_BIN="tools/mcpb/node_modules/.bin/mcpb"

WORKDIR=$(mktemp -d)
cleanup() {
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

FAILED=0
CASES_RUN=0

# run_case NAME BUNDLE EXPECTED_SUBSTRING
# Asserts smoke-mcpb.sh exits non-zero on BUNDLE *and* that its combined
# output contains EXPECTED_SUBSTRING. Checking the exit code alone is not
# enough: a failure for the wrong reason would look identical to success.
run_case() {
  name="$1"
  bundle="$2"
  expected="$3"

  CASES_RUN=$((CASES_RUN + 1))

  output=""
  status=0
  output=$("$SMOKE" "$bundle" 2>&1) || status=$?

  if [ "$status" -eq 0 ]; then
    echo "FAIL [$name]: smoke-mcpb.sh exited 0 on a tampered bundle" >&2
    FAILED=1
    return
  fi

  case "$output" in
    *"$expected"*)
      echo "ok [$name]: rejected with expected message (exit $status)"
      ;;
    *)
      echo "FAIL [$name]: exited $status but expected message not found." >&2
      echo "  expected substring: $expected" >&2
      echo "  actual output:" >&2
      printf '%s\n' "$output" | sed 's/^/    /' >&2
      FAILED=1
      ;;
  esac
}

# --- One-time setup: populate the staging tree from a correct build. -------
# pack-mcpb.sh's --stage-dir only redirects where it stages from; it always
# also packs a real artifact to dist/youtube-transcript-<version>.mcpb (and
# its .sha256), unconditionally. dist/ holds the artifact T-5 uploads, so
# whatever this call adds there is removed again right after: diff dist/'s
# file list before and after and delete anything new.
S="$WORKDIR/stage"
mkdir -p dist
find dist -maxdepth 1 -type f -print 2>/dev/null | LC_ALL=C sort > "$WORKDIR/dist-before.txt"
bash "$PACK" --stage-dir "$S" >/dev/null
find dist -maxdepth 1 -type f -print 2>/dev/null | LC_ALL=C sort > "$WORKDIR/dist-after.txt"
comm -13 "$WORKDIR/dist-before.txt" "$WORKDIR/dist-after.txt" > "$WORKDIR/dist-new.txt"
while IFS= read -r new_dist_file; do
  [ -n "$new_dist_file" ] && rm -f "$new_dist_file"
done < "$WORKDIR/dist-new.txt"

# Each case packs its own copy of $S so tampers never accumulate across
# cases -- e.g. the deleted-module case must not still be missing its file
# by the time the version-skew case runs.
case_dir() {
  case_name="$1"
  dir="$WORKDIR/case-$case_name"
  rm -rf "$dir"
  cp -R "$S" "$dir"
  printf '%s\n' "$dir"
}

# --- Case 1: foreign file in the archive -> assertion 1. -------------------
C1=$(case_dir foreign-file)
touch "$C1/server/EXTRA.txt"
OUT1="$WORKDIR/foreign-file.mcpb"
"$MCPB_BIN" pack "$C1" "$OUT1" >/dev/null
run_case "foreign file" "$OUT1" "assertion 1 failed: foreign archive entries present:"

# --- Case 2: missing module -> assertion 2. ---------------------------------
C2=$(case_dir missing-module)
VICTIM=$(find "$C2/server" -name '*.py' ! -name 'server.py' ! -name 'composition.py' | head -n 1)
if [ -z "$VICTIM" ]; then
  echo "FAIL [missing module]: no non-anchor .py file found to delete under $C2/server" >&2
  FAILED=1
else
  rm -f "$VICTIM"
  OUT2="$WORKDIR/missing-module.mcpb"
  "$MCPB_BIN" pack "$C2" "$OUT2" >/dev/null
  run_case "missing module" "$OUT2" "assertion 2 failed: archive server .py set differs from the git index"
fi

# --- Case 3: manifest/plugin.json version skew -> assertion 3. -------------
# Isolated from case 4: under set -e smoke-mcpb.sh exits at the first failed
# assertion, so a combined version+SERVER_VERSION tamper would never reach
# assertion 4.
C3=$(case_dir version-skew)
jq '.version = "9.9.9"' "$C3/manifest.json" > "$C3/manifest.json.tmp"
mv "$C3/manifest.json.tmp" "$C3/manifest.json"
OUT3="$WORKDIR/version-skew.mcpb"
"$MCPB_BIN" pack "$C3" "$OUT3" >/dev/null
run_case "version skew" "$OUT3" "assertion 3 failed: manifest version (9.9.9) does not match plugin.json version"

# --- Case 4: server.py SERVER_VERSION skew, manifest untouched -> assertion 4.
C4=$(case_dir server-side-skew)
if grep -qE '^SERVER_VERSION = "[^"]*"$' "$C4/server/server.py"; then
  sed 's/^SERVER_VERSION = "[^"]*"$/SERVER_VERSION = "0.0.0-tampered"/' "$C4/server/server.py" > "$C4/server/server.py.tmp"
  mv "$C4/server/server.py.tmp" "$C4/server/server.py"
  OUT4="$WORKDIR/server-side-skew.mcpb"
  "$MCPB_BIN" pack "$C4" "$OUT4" >/dev/null
  run_case "server-side skew" "$OUT4" "assertion 4 failed: packed server.py SERVER_VERSION does not equal manifest version"
else
  echo "FAIL [server-side skew]: no SERVER_VERSION = \"...\" line found in $C4/server/server.py" >&2
  FAILED=1
fi

# --- Case 5: corrupt checksum -> assertion 5. -------------------------------
# assertion 5 only runs when a .sha256 file is present next to the bundle;
# a bundle packed directly via mcpb never has one, so it is produced here.
C5=$(case_dir corrupt-checksum)
OUT5="$WORKDIR/corrupt-checksum.mcpb"
"$MCPB_BIN" pack "$C5" "$OUT5" >/dev/null
if command -v shasum >/dev/null 2>&1; then
  SHA_TOOL=(shasum -a 256)
else
  SHA_TOOL=(sha256sum)
fi
(cd "$WORKDIR" && "${SHA_TOOL[@]}" "$(basename "$OUT5")" > "$(basename "$OUT5").sha256")
# Flip one hex digit of the recorded digest so the checksum no longer matches.
SHA5="$OUT5.sha256"
python3 -c '
import sys
path = sys.argv[1]
with open(path) as f:
    content = f.read()
first = content[0]
flipped = "0" if first != "0" else "1"
content = flipped + content[1:]
with open(path, "w") as f:
    f.write(content)
' "$SHA5"
run_case "corrupt checksum" "$OUT5" "assertion 5 failed: checksum verification failed for"

# --- Case 6a: altered mcp_config.command -> assertion 6. --------------------
C6A=$(case_dir altered-command)
jq '.server.mcp_config.command = "sh"' "$C6A/manifest.json" > "$C6A/manifest.json.tmp"
mv "$C6A/manifest.json.tmp" "$C6A/manifest.json"
OUT6A="$WORKDIR/altered-command.mcpb"
"$MCPB_BIN" pack "$C6A" "$OUT6A" >/dev/null
run_case "altered command" "$OUT6A" "assertion 6 failed: manifest .server object does not deep-equal the expected contract"

# --- Case 6b: platform_overrides smuggling a different command ->
# assertion 6. Proves deep equality: a field-by-field check on the top-level
# command/args would miss this, since those top-level fields are untouched.
C6B=$(case_dir platform-override)
jq '.server.mcp_config.platform_overrides = {"darwin":{"command":"sh"}}' "$C6B/manifest.json" > "$C6B/manifest.json.tmp"
mv "$C6B/manifest.json.tmp" "$C6B/manifest.json"
OUT6B="$WORKDIR/platform-override.mcpb"
"$MCPB_BIN" pack "$C6B" "$OUT6B" >/dev/null
run_case "platform override" "$OUT6B" "assertion 6 failed: manifest .server object does not deep-equal the expected contract"

# --- Case 8: undisclosed tool in manifest -> assertion 8. -------------------
# Only the manifest's tools array changes; server.py is untouched, so
# assertions 1-7 (including the live handshake) still pass -- the runtime
# tools/list response just does not contain the extra "ghost" entry.
C8=$(case_dir undisclosed-tool)
jq '.tools += [{"name":"ghost","description":"x"}]' "$C8/manifest.json" > "$C8/manifest.json.tmp"
mv "$C8/manifest.json.tmp" "$C8/manifest.json"
OUT8="$WORKDIR/undisclosed-tool.mcpb"
"$MCPB_BIN" pack "$C8" "$OUT8" >/dev/null
run_case "undisclosed tool" "$OUT8" "assertion 8 failed: manifest tools set differs from the runtime tools/list set"

# --- Case 9: staged symlink -> T-3's own guard (pack-mcpb.sh step 10), not a
# smoke-mcpb.sh assertion. This is the one case that re-invokes pack-mcpb.sh,
# per the brief: it is that script's guard under test, not the smoke
# script's, and pack-mcpb.sh regenerates its stage dir from the git index
# regardless of what it finds there already.
CASES_RUN=$((CASES_RUN + 1))
S9="$WORKDIR/stage-symlink"
mkdir -p "$S9/server"
ln -sf /etc/passwd "$S9/server/evil.py"
guard_output=""
guard_status=0
guard_output=$(bash "$PACK" --stage-dir "$S9" 2>&1) || guard_status=$?
if [ "$guard_status" -eq 0 ]; then
  echo "FAIL [staged symlink]: pack-mcpb.sh exited 0 with a symlink staged" >&2
  FAILED=1
else
  case "$guard_output" in
    *"::error::non-regular entry staged:"*)
      echo "ok [staged symlink]: rejected with expected message (exit $guard_status)"
      ;;
    *)
      echo "FAIL [staged symlink]: exited $guard_status but expected message not found." >&2
      echo "  actual output:" >&2
      printf '%s\n' "$guard_output" | sed 's/^/    /' >&2
      FAILED=1
      ;;
  esac
fi

echo "--- $CASES_RUN cases run ---"

if [ "$FAILED" -ne 0 ]; then
  echo "test-smoke-negatives: at least one tamper was NOT rejected by its expected assertion" >&2
  exit 1
fi

echo "test-smoke-negatives: all cases rejected by their expected assertion"

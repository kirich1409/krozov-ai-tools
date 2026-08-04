#!/usr/bin/env bash
# Pack the youtube-transcript MCPB bundle from the tracked git index.
#
# Usage: scripts/pack-mcpb.sh [--expect-version <version>] [--stage-dir <path>]
#
# Produces dist/youtube-transcript-<version>.mcpb and its .sha256 checksum.
# Staging is done from `git ls-files -s`, not from a filename glob copy: the
# file list, the mode *and* the bytes all come from the index. Bytes are read
# with `git cat-file blob <oid>`, never with `cp` from the working tree --
# otherwise the mode gate would validate the index while the bundle received
# whatever the working tree happened to hold (uncommitted edits, or a symlink
# silently dereferenced into a regular file). See docs/plans for the full
# rationale.
#
# Consequence, warned about at build time: uncommitted working-tree edits do
# NOT reach the bundle. Stage the change first.
set -euo pipefail

PLUGIN_ROOT="plugins/youtube-transcript/plugin"
PLUGIN_JSON="$PLUGIN_ROOT/.claude-plugin/plugin.json"
SERVER_DIR="$PLUGIN_ROOT/server"
TEMPLATE="plugins/youtube-transcript/mcpb/manifest.template.json"
MCPB_BIN="tools/mcpb/node_modules/.bin/mcpb"
NORMALIZER="scripts/normalize-mcpb.py"

EXPECT_VERSION=""
EXPECT_VERSION_SET=0
STAGE_DIR_ARG=""
STAGE_DIR_SET=0

# "flag absent" and "flag present with an empty value" must stay
# distinguishable: Stage 2 passes --expect-version "${{ ... ref_name }}", and an
# unresolved expression expands to an empty string rather than to an error. With
# a bare ${2:-} the cross-check would silently switch itself off there. A
# missing value is also an explicit error, not a `shift 2` that returns 1 and
# lets set -e kill the script without printing anything.
while [ "$#" -gt 0 ]; do
  case "$1" in
    --expect-version)
      [ "$#" -ge 2 ] || { echo "::error::--expect-version requires a value" >&2; exit 1; }
      EXPECT_VERSION="$2"
      EXPECT_VERSION_SET=1
      shift 2
      ;;
    --stage-dir)
      [ "$#" -ge 2 ] || { echo "::error::--stage-dir requires a value" >&2; exit 1; }
      STAGE_DIR_ARG="$2"
      STAGE_DIR_SET=1
      shift 2
      ;;
    *)
      echo "::error::unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [ "$EXPECT_VERSION_SET" -eq 1 ] && [ -z "$EXPECT_VERSION" ]; then
  echo "::error::--expect-version was given an empty value" >&2
  exit 1
fi
if [ "$STAGE_DIR_SET" -eq 1 ] && [ -z "$STAGE_DIR_ARG" ]; then
  echo "::error::--stage-dir was given an empty value" >&2
  exit 1
fi

# 1. Anchor to the repo root. release.yml sets a job-level working-directory,
# so every path below must be resolved relative to the toplevel, not to cwd.
cd "$(git rev-parse --show-toplevel)"

# 1a. Toolchain preflight, before step 4 touches dist/ and with the command to
# run spelled out. Without it the script dies later with a bare
# "No such file or directory", having already removed the previous artifact.
if [ ! -x "$MCPB_BIN" ]; then
  echo "::error::mcpb CLI not found at $MCPB_BIN — run: (cd tools/mcpb && npm ci --ignore-scripts)" >&2
  exit 1
fi

if [ ! -f "$NORMALIZER" ]; then
  echo "::error::normalizer not found at $NORMALIZER" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "::error::python3 not found — required by $NORMALIZER (step 11a)" >&2
  exit 1
fi

if [ ! -f "$PLUGIN_JSON" ]; then
  echo "::error::plugin.json not found at $PLUGIN_JSON" >&2
  exit 1
fi

# 2. Read the version and require it to look like semver.
VERSION=$(jq -r '.version' "$PLUGIN_JSON")
if [ -z "$VERSION" ] || [ "$VERSION" = "null" ]; then
  echo "::error::plugin.json has no .version" >&2
  exit 1
fi
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
  echo "::error::plugin.json version is not semver: $VERSION" >&2
  exit 1
fi

# 3. Optional cross-check against the release tag.
if [ "$EXPECT_VERSION_SET" -eq 1 ] && [ "$EXPECT_VERSION" != "$VERSION" ]; then
  echo "::error::version mismatch: expected $EXPECT_VERSION, plugin.json has $VERSION" >&2
  exit 1
fi

# 4. Ensure dist/ exists. The previous artifact is NOT removed here: everything
# from the mode gates through `mcpb pack` can still fail, and a failed build
# must not destroy the last good bundle. Packing goes to a temp path and the
# swap into dist/ happens in step 11, after every gate has passed.
mkdir -p dist

# 5. Staging directory. --stage-dir is used as-is and left in place on exit
# (this is the supported hook T-4b uses to tamper with staged content before
# calling `mcpb pack` directly). Without it, use a throwaway dir cleaned up
# on EXIT.
STAGE_TMP=""
OUT_TMP=""
cleanup() {
  [ -z "$STAGE_TMP" ] || rm -rf "$STAGE_TMP"
  [ -z "$OUT_TMP" ] || rm -rf "$OUT_TMP"
  return 0
}
trap cleanup EXIT

if [ "$STAGE_DIR_SET" -eq 1 ]; then
  STAGE="$STAGE_DIR_ARG"
  # Both `git cat-file > path` and `jq > path` write *through* an existing
  # symlink instead of replacing it, so the step-10 containment check detects
  # the situation only after the write has already landed outside the stage
  # tree. Run the same check up front, before anything is written, so a
  # pre-populated stage directory cannot be used to redirect writes.
  if [ -L "$STAGE" ]; then
    echo "::error::non-regular entry staged: $STAGE" >&2
    exit 1
  fi
  if [ -e "$STAGE" ]; then
    PRE_BAD=$(find "$STAGE" -mindepth 1 \( -type l -o \( ! -type f -a ! -type d \) \) -print)
    [ -z "$PRE_BAD" ] || { echo "::error::non-regular entry staged: $PRE_BAD" >&2; exit 1; }
  fi
else
  STAGE=$(mktemp -d)
  STAGE_TMP="$STAGE"
fi
mkdir -p "$STAGE/server"

# 6 & 7. Stage the server tree from the git index, not from a filename glob.
# `git ls-files -s -z` is NUL-delimited so a path containing whitespace
# cannot be mis-split by the very script that is the containment boundary.
# Pathspec glob magic ('**/*.py') silently drops top-level files under
# SERVER_DIR — plain `-- SERVER_DIR` filtered in the loop is the form that
# does not lose entries.
#
# Bytes come from the blob whose mode was just checked (`git cat-file blob
# <oid>`), not from the working tree: `git ls-files -s` reports the index, so
# reading the file with `cp` would let the gate validate one thing and the
# bundle receive another.
BAD_MODE=""
NON_PY=""
STAGED_PATHS=()
while IFS= read -r -d '' entry; do
  # entry: "<mode> <oid> <stage>\t<path>"
  mode="${entry%% *}"
  entry_rest="${entry#* }"
  oid="${entry_rest%% *}"
  path="${entry#*$'\t'}"
  case "$path" in
    *.py)
      case "$mode" in
        100644|100755)
          rel="${path#"$SERVER_DIR"/}"
          mkdir -p "$STAGE/server/$(dirname "$rel")"
          git cat-file blob "$oid" > "$STAGE/server/$rel"
          STAGED_PATHS[${#STAGED_PATHS[@]}]="$path"
          ;;
        *)
          BAD_MODE="$BAD_MODE $path($mode)"
          ;;
      esac
      ;;
    *)
      NON_PY="$NON_PY $path"
      ;;
  esac
done < <(git ls-files -s -z -- "$SERVER_DIR")

if [ -n "$BAD_MODE" ]; then
  echo "::error::tracked .py file with non-regular mode under $SERVER_DIR:$BAD_MODE" >&2
  exit 1
fi
if [ -n "$NON_PY" ]; then
  echo "::error::non-.py file tracked under $SERVER_DIR would be silently dropped:$NON_PY" >&2
  exit 1
fi

# 8. LICENSE.md goes through the same mode gate as the server tree, not a
# bare cp: a symlinked LICENSE.md would otherwise place foreign bytes in the
# bundle as a regular file.
license_entry=$(git ls-files -s -- LICENSE.md)
license_mode="${license_entry%% *}"
license_rest="${license_entry#* }"
license_oid="${license_rest%% *}"
if [ "$license_mode" != "100644" ]; then
  echo "::error::LICENSE.md has unexpected git mode: ${license_mode:-<untracked>}" >&2
  exit 1
fi
git cat-file blob "$license_oid" > "$STAGE/LICENSE.md"
STAGED_PATHS[${#STAGED_PATHS[@]}]="LICENSE.md"

# 8a. The bundle now carries index content, so working-tree edits that were
# never staged are invisible to it. That must not happen silently: name the
# files whose working-tree copy differs from what was bundled.
DIRTY=$(git diff --name-only -- "${STAGED_PATHS[@]}")
if [ -n "$DIRTY" ]; then
  {
    echo "::warning::working tree differs from the git index for bundled files;"
    echo "the indexed (committed/staged) version was packed, not your edits:"
    printf '%s\n' "$DIRTY" | sed 's/^/  /'
  } >&2
fi

# 9. Inject the version into the manifest. The template intentionally has no
# .version key so the repo does not gain a fourth place version is stored.
if [ -L "$TEMPLATE" ]; then
  echo "::error::manifest template must not be a symlink: $TEMPLATE" >&2
  exit 1
fi
jq --arg v "$VERSION" '. + {version: $v}' "$TEMPLATE" > "$STAGE/manifest.json"
"$MCPB_BIN" validate "$STAGE/manifest.json"

# 10. Final containment check on the staged tree. `\( ! -type f \)` alone
# would match every directory (never empty); `! find ... | grep -q .` would
# not abort under set -e. Capture the result and branch explicitly instead.
BAD=$(find "$STAGE" -mindepth 1 \( -type l -o \( ! -type f -a ! -type d \) \) -print)
[ -z "$BAD" ] || { echo "::error::non-regular entry staged: $BAD" >&2; exit 1; }

# 11. Pack. Always the pinned local CLI, never npx. Output goes to a temp
# directory first so a failure anywhere above (mode gates, `mcpb validate`,
# the containment check, `mcpb pack` itself) leaves the previously built
# artifact in dist/ untouched.
OUT_TMP=$(mktemp -d)
BUNDLE_NAME="youtube-transcript-$VERSION.mcpb"
"$MCPB_BIN" pack "$STAGE" "$OUT_TMP/$BUNDLE_NAME"

# 11a. Normalize the archive into a byte-deterministic form BEFORE the checksum
# is taken, so the published .sha256 describes the shipped bytes. `mcpb pack`
# embeds file mtimes and does not honour SOURCE_DATE_EPOCH (measured -- see
# docs/PLUGIN-STANDARDS.md §12), so identical sources otherwise yield different
# digests. Still inside OUT_TMP: the swap into dist/ below stays the only
# externally visible write, and a normalizer failure leaves the previous
# artifact intact.
#
# Any future `mcpb sign` step MUST run AFTER this line: an MCPB signature is a
# PKCS#7 block appended past the zip EOCD (see @anthropic-ai/mcpb
# dist/node/sign.js), and rebuilding the archive here would discard it. The
# normalizer refuses such an archive rather than silently unsigning it, so the
# wrong order fails the build instead of shipping.
python3 "$NORMALIZER" "$OUT_TMP/$BUNDLE_NAME" "$OUT_TMP/$BUNDLE_NAME.norm"
mv "$OUT_TMP/$BUNDLE_NAME.norm" "$OUT_TMP/$BUNDLE_NAME"

# 12. Checksum with cwd set to the file's directory so it holds a bare
# basename. smoke-mcpb.sh repeats the same tool-selection logic independently:
# pack and smoke run as separate `run:` blocks in separate processes, so
# exporting the choice here would not reach it anyway.
(
  cd "$OUT_TMP"
  if command -v shasum >/dev/null 2>&1; then
    SHA_TOOL=(shasum -a 256)
  else
    SHA_TOOL=(sha256sum)
  fi
  "${SHA_TOOL[@]}" "$BUNDLE_NAME" > "$BUNDLE_NAME.sha256"
)

# 12a. Swap into dist/ only now that both files exist. Only this plugin's
# outputs are removed: dist/ is gitignored, absent on a fresh clone, and may
# be shared with other tooling.
rm -f dist/youtube-transcript-*.mcpb dist/youtube-transcript-*.mcpb.sha256
mv "$OUT_TMP/$BUNDLE_NAME" "$OUT_TMP/$BUNDLE_NAME.sha256" dist/

# 13. Emit the produced paths.
MCPB_PATH="dist/youtube-transcript-$VERSION.mcpb"
MCPB_SHA256_PATH="dist/youtube-transcript-$VERSION.mcpb.sha256"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  {
    printf 'mcpb_path=%s\n' "$MCPB_PATH"
    printf 'mcpb_sha256_path=%s\n' "$MCPB_SHA256_PATH"
  } >> "$GITHUB_OUTPUT"
else
  printf '%s\n' "$MCPB_PATH"
  printf '%s\n' "$MCPB_SHA256_PATH"
fi

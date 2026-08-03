#!/usr/bin/env bash
# Pack the youtube-transcript MCPB bundle from the tracked git index.
#
# Usage: scripts/pack-mcpb.sh [--expect-version <version>] [--stage-dir <path>]
#
# Produces dist/youtube-transcript-<version>.mcpb and its .sha256 checksum.
# Staging is done from `git ls-files`, not from a filename glob copy: `cp`
# dereferences symlinks, so a tracked symlink would silently become a regular
# file with foreign content inside the bundle. See docs/plans for the full
# rationale.
set -euo pipefail

PLUGIN_ROOT="plugins/youtube-transcript/plugin"
PLUGIN_JSON="$PLUGIN_ROOT/.claude-plugin/plugin.json"
SERVER_DIR="$PLUGIN_ROOT/server"
TEMPLATE="plugins/youtube-transcript/mcpb/manifest.template.json"
MCPB_BIN="tools/mcpb/node_modules/.bin/mcpb"

EXPECT_VERSION=""
STAGE_DIR_ARG=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --expect-version)
      EXPECT_VERSION="${2:-}"
      shift 2
      ;;
    --stage-dir)
      STAGE_DIR_ARG="${2:-}"
      shift 2
      ;;
    *)
      echo "::error::unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# 1. Anchor to the repo root. release.yml sets a job-level working-directory,
# so every path below must be resolved relative to the toplevel, not to cwd.
cd "$(git rev-parse --show-toplevel)"

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
if [ -n "$EXPECT_VERSION" ] && [ "$EXPECT_VERSION" != "$VERSION" ]; then
  echo "::error::version mismatch: expected $EXPECT_VERSION, plugin.json has $VERSION" >&2
  exit 1
fi

# 4. Reset only this plugin's bundle output. dist/ is gitignored and absent
# on a fresh clone; never wipe the whole directory since other tooling may
# use it too.
mkdir -p dist
rm -f dist/youtube-transcript-*.mcpb dist/youtube-transcript-*.mcpb.sha256

# 5. Staging directory. --stage-dir is used as-is and left in place on exit
# (this is the supported hook T-4b uses to tamper with staged content before
# calling `mcpb pack` directly). Without it, use a throwaway dir cleaned up
# on EXIT.
if [ -n "$STAGE_DIR_ARG" ]; then
  STAGE="$STAGE_DIR_ARG"
else
  STAGE=$(mktemp -d)
  trap 'rm -rf "$STAGE"' EXIT
fi
mkdir -p "$STAGE/server"

# 6 & 7. Stage the server tree from the git index, not from a filename glob.
# `git ls-files -s -z` is NUL-delimited so a path containing whitespace
# cannot be mis-split by the very script that is the containment boundary.
# Pathspec glob magic ('**/*.py') silently drops top-level files under
# SERVER_DIR — plain `-- SERVER_DIR` filtered in the loop is the form that
# does not lose entries.
BAD_MODE=""
NON_PY=""
while IFS= read -r -d '' entry; do
  mode="${entry%% *}"
  path="${entry#*$'\t'}"
  case "$path" in
    *.py)
      case "$mode" in
        100644|100755)
          rel="${path#"$SERVER_DIR"/}"
          mkdir -p "$STAGE/server/$(dirname "$rel")"
          cp -P -- "$path" "$STAGE/server/$rel"
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
if [ "$license_mode" != "100644" ]; then
  echo "::error::LICENSE.md has unexpected git mode: ${license_mode:-<untracked>}" >&2
  exit 1
fi
cp -P -- LICENSE.md "$STAGE/LICENSE.md"

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

# 11. Pack. Always the pinned local CLI, never npx.
"$MCPB_BIN" pack "$STAGE" "dist/youtube-transcript-$VERSION.mcpb"

# 12. Checksum with cwd set to dist/ so the file holds a bare basename.
# smoke-mcpb.sh repeats the same tool-selection logic independently: pack and
# smoke run as separate `run:` blocks in separate processes, so exporting the
# choice here would not reach it anyway.
(
  cd dist
  if command -v shasum >/dev/null 2>&1; then
    SHA_TOOL=(shasum -a 256)
  else
    SHA_TOOL=(sha256sum)
  fi
  "${SHA_TOOL[@]}" "youtube-transcript-$VERSION.mcpb" > "youtube-transcript-$VERSION.mcpb.sha256"
)

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

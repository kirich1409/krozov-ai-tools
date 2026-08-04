#!/usr/bin/env bash
# Proof that scripts/pack-mcpb.sh is byte-reproducible: build the bundle twice
# from the same checkout and require the two artifacts to be identical.
#
# Usage: bash scripts/tests/test-mcpb-reproducible.sh
#
# Why a separate script and not a ninth smoke-mcpb.sh assertion: smoke-mcpb.sh
# verifies *one bundle handed to it* and is also run against bundles it did not
# build (release.yml re-checks downloaded bytes). Reproducibility is a property
# of the build, provable only by running it twice -- which a per-bundle verifier
# must not do. scripts/tests/ is where this repository already keeps the
# "prove the gate can actually fail" scripts.
#
# Cost: two full pack runs (~1 s each locally, plus mcpb CLI startup). The
# archive is ~78 kB and the tree ~27 files, so this is negligible next to the
# npm install the job already pays for.
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

PACK="scripts/pack-mcpb.sh"

WORKDIR=$(mktemp -d)
cleanup() {
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

# `env -u GITHUB_OUTPUT` so the produced paths land on stdout instead of in the
# Actions output file: this keeps the bundle path coming from pack-mcpb.sh
# itself rather than being recomputed here from plugin.json, which would let the
# two drift apart silently. The mcpb CLI also writes to stdout, so the paths are
# the last two lines, not the whole output.
build() {
  out_var="$1"
  log="$WORKDIR/$out_var.log"
  env -u GITHUB_OUTPUT bash "$PACK" > "$log"
  path=$(tail -n 2 "$log" | head -n 1)
  if [ ! -f "$path" ]; then
    echo "test-mcpb-reproducible: pack did not report a bundle path (got: $path)" >&2
    sed 's/^/    /' "$log" >&2
    exit 1
  fi
  cp "$path" "$WORKDIR/$out_var.mcpb"
  cp "$path.sha256" "$WORKDIR/$out_var.sha256"
}

build first

# Not a readiness wait, and not removable: this is what makes the test able to
# fail. The defect it guards against is mtime leakage, and a zip's DOS date
# field has 2-second granularity -- two back-to-back builds (~1 s apart) can
# land in the same 2-second bucket and agree *even with mtimes embedded*.
# Verified: with the epoch normalization deliberately reverted, the two builds
# still matched until this delay was introduced. 3 s > 2 s guarantees a
# different bucket.
sleep 3

build second

SHA_FIRST=$(cut -d' ' -f1 < "$WORKDIR/first.sha256")
SHA_SECOND=$(cut -d' ' -f1 < "$WORKDIR/second.sha256")

echo "build 1: $SHA_FIRST"
echo "build 2: $SHA_SECOND"

# Both checks, not just the digest comparison: the digests come from the same
# tool run twice, so a checksum step that silently stopped describing the
# shipped file would still agree with itself. `cmp` compares the artifacts.
if [ "$SHA_FIRST" != "$SHA_SECOND" ]; then
  echo "test-mcpb-reproducible: two builds of the same checkout produced different SHA-256 digests" >&2
  exit 1
fi

if cmp -s "$WORKDIR/first.mcpb" "$WORKDIR/second.mcpb"; then
  :
else
  echo "test-mcpb-reproducible: two builds of the same checkout produced different bytes" >&2
  exit 1
fi

echo "test-mcpb-reproducible: two builds are byte-identical"

#!/usr/bin/env python3
"""Rewrite a packed .mcpb (a zip) into a byte-deterministic form.

Usage:
    python3 scripts/normalize-mcpb.py <in.mcpb> <out.mcpb>

Why this exists: `mcpb pack` embeds each file's mtime in the archive, so two
builds of an identical source tree produce different bytes and therefore
different SHA-256 digests. `SOURCE_DATE_EPOCH` -- the de facto standard knob
for reproducible builds -- is ignored by the CLI (measured, see
docs/PLUGIN-STANDARDS.md §12), so the normalization is done here instead of
being asked of the packer.

What is normalized:
    - entry order: byte-wise sorted by name (the packer's order is incidental);
    - timestamps: every entry gets the ZIP epoch 1980-01-01 00:00:00, the
      oldest value the DOS date field can represent;
    - permissions: forced to 0644. This is NOT always what `mcpb pack` emits:
      it copies the staging tree's mode, so an executable file would arrive as
      0755 and its exec bit is dropped here. That is deliberate -- every
      bundled file is data read by an interpreter (the entrypoint runs as
      `python3 server/server.py`), so no entry needs to be executable. A future
      bundle that does need an executable entry must change this function
      rather than work around it;
    - compression: STORE for every entry. Deliberately not DEFLATE: deflate
      output is a property of the runtime's zlib build, so a compressed archive
      is only reproducible for someone whose zlib matches the release runner's.
      Storing costs size (~194 kB instead of ~77 kB) and buys a digest that any
      Python on any platform reproduces;
    - creating system: 3 (Unix), so the field does not depend on the host OS.

Content is copied verbatim; this changes archive metadata only.

Refusals (each is a loud failure, never a silent rewrite):
    - an entry whose file-type bits are neither unset nor regular. Measured
      caveat, so it is not mistaken for the symlink boundary: `mcpb pack`
      DEREFERENCES symlinks -- a symlink to /etc/passwd is packed as a regular
      entry holding that file's bytes -- and always writes bare permission bits
      with the type bits at zero, so this check cannot fire on any archive this
      pipeline produces. It is a belt-and-braces guard against a future packer
      that preserves symlinks. The actual containment boundary is `find -type l`
      in pack-mcpb.sh (steps 5 and 10) and it must not be relaxed on the
      strength of this check;
    - a directory entry. `mcpb pack` writes none (measured: an empty staging
      directory simply does not appear in the archive), and emitting one here
      correctly requires S_IFDIR plus the MS-DOS directory flag -- untestable
      code that would ship wrong. If a future CLI starts writing them, this
      fails in CI rather than producing a malformed record;
    - an unsafe or non-round-trippable entry name (NUL, backslash, absolute,
      or `..`), because zipfile's own ZipInfo constructor rewrites such names
      (it truncates at the first NUL), which could collapse two distinct input
      entries into one output entry;
    - bytes appended past the End Of Central Directory record. An MCPB
      signature is a PKCS#7 block concatenated after the EOCD, not a zip entry;
      rebuilding the archive from its entries would drop it without a word.

Stdlib only, matching the rest of this repository's tooling.
"""

import stat
import sys
import zipfile

# Oldest timestamp representable in a zip's DOS date field. Anything earlier
# raises ValueError in zipfile.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

EOCD_SIGNATURE = b"PK\x05\x06"
EOCD_SIZE = 22
MAX_ZIP_COMMENT = 0xFFFF


def assert_no_trailing_data(path: str) -> None:
    """Fail if anything follows the End Of Central Directory record.

    zipfile ignores such bytes and ZipFile(dst, "w") rebuilds the archive from
    the central directory alone, so an MCPB signature block (appended past the
    EOCD by @anthropic-ai/mcpb dist/node/sign.js) would vanish silently.
    """
    with open(path, "rb") as fh:
        blob = fh.read()
    size = len(blob)
    floor = max(0, size - EOCD_SIZE - MAX_ZIP_COMMENT)
    pos = blob.rfind(EOCD_SIGNATURE, floor)
    while pos != -1:
        if pos + EOCD_SIZE <= size:
            comment_len = int.from_bytes(blob[pos + 20:pos + 22], "little")
            if pos + EOCD_SIZE + comment_len == size:
                return
        pos = blob.rfind(EOCD_SIGNATURE, floor, pos)
    raise SystemExit(
        "normalize-mcpb: archive has data appended past the EOCD record "
        "(a signed .mcpb carries its PKCS#7 block there and rebuilding the "
        "zip would discard it): " + path
    )


def check_entry(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if ("\x00" in name or "\\" in name or name.startswith("/")
            or name == ".." or name.startswith("../") or "/../" in name):
        raise SystemExit(
            "normalize-mcpb: refusing unsafe archive entry name: %r" % name
        )
    if info.is_dir():
        raise SystemExit(
            "normalize-mcpb: refusing directory archive entry: %s "
            "(this pipeline's packer emits none)" % name
        )
    # create_system 3 == Unix; only then does the high half of external_attr
    # carry a st_mode worth judging.
    if info.create_system != 3:
        raise SystemExit(
            "normalize-mcpb: refusing entry from an unknown creating system: "
            "%s (create_system %d)" % (name, info.create_system)
        )
    type_bits = (info.external_attr >> 16) & 0o170000
    # `mcpb pack` writes a bare permission mask (0644) with the file type bits
    # left at zero, so "unset" must be accepted -- treating it as non-regular
    # would reject every bundle this repo builds.
    if type_bits not in (0, stat.S_IFREG):
        raise SystemExit(
            "normalize-mcpb: refusing non-regular archive entry: "
            "%s (mode %o)" % (name, info.external_attr >> 16)
        )


def normalize(src_path: str, dst_path: str) -> None:
    assert_no_trailing_data(src_path)

    with zipfile.ZipFile(src_path) as src:
        entries = src.infolist()

        names = [info.filename for info in entries]
        if len(names) != len(set(names)):
            raise SystemExit(
                "normalize-mcpb: archive has duplicate entry names: " + src_path
            )

        for info in entries:
            check_entry(info)

        entries.sort(key=lambda info: info.filename.encode("utf-8"))
        expected = [info.filename for info in entries]

        with zipfile.ZipFile(dst_path, "w") as dst:
            for info in entries:
                out = zipfile.ZipInfo(info.filename, date_time=ZIP_EPOCH)
                out.create_system = 3
                out.external_attr = 0o644 << 16
                out.compress_type = zipfile.ZIP_STORED
                dst.writestr(out, src.read(info.filename))

            # ZipInfo's constructor is allowed to rewrite the name it is given;
            # assert the copy stayed exact rather than trusting that the checks
            # above enumerated every rewrite it can perform.
            if dst.namelist() != expected:
                raise SystemExit(
                    "normalize-mcpb: entry names changed while rewriting "
                    + src_path
                )


def main(argv):
    if len(argv) != 3:
        raise SystemExit(
            "usage: normalize-mcpb.py <in.mcpb> <out.mcpb>"
        )
    normalize(argv[1], argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

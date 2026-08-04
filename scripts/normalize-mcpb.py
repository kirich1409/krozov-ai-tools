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
    - permissions: 0644 for files, 0755 for directory entries -- the same
      values `mcpb pack` already emits, restated so a future CLI change cannot
      leak the umask of the build machine into the artifact;
    - compression: DEFLATE at a pinned level for files, STORE for directory
      entries.
    - creating system: 3 (Unix), so the field does not depend on the host OS.

Content is copied verbatim; this changes archive metadata only. Refuses any
entry that is neither a regular file nor a directory (a symlink entry would
otherwise be silently rewritten into a regular file, defeating the containment
gates in pack-mcpb.sh).

Stdlib only, matching the rest of this repository's tooling.
"""

import stat
import sys
import zipfile

# Oldest timestamp representable in a zip's DOS date field. Anything earlier
# raises ValueError in zipfile.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

# Pinned rather than left at zlib's default: the default level is a property of
# the runtime, so leaving it implicit would make the output depend on which
# Python built it. Byte-identical output across *different* machines still also
# requires the same zlib implementation -- see docs/PLUGIN-STANDARDS.md §12.
COMPRESS_LEVEL = 9


def normalize(src_path: str, dst_path: str) -> None:
    with zipfile.ZipFile(src_path) as src:
        entries = src.infolist()

        names = [info.filename for info in entries]
        if len(names) != len(set(names)):
            raise SystemExit(
                "normalize-mcpb: archive has duplicate entry names: " + src_path
            )

        for info in entries:
            # create_system 3 == Unix; only then does the high half of
            # external_attr carry a st_mode worth judging.
            if info.create_system != 3:
                continue
            type_bits = (info.external_attr >> 16) & 0o170000
            # `mcpb pack` writes a bare permission mask (0644) with the file
            # type bits left at zero, so "unset" must be accepted -- treating
            # it as non-regular would reject every bundle this repo builds.
            if type_bits not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise SystemExit(
                    "normalize-mcpb: refusing non-regular archive entry: "
                    "%s (mode %o)" % (info.filename, info.external_attr >> 16)
                )

        entries.sort(key=lambda info: info.filename.encode("utf-8"))

        with zipfile.ZipFile(dst_path, "w") as dst:
            for info in entries:
                is_dir = info.is_dir()
                out = zipfile.ZipInfo(info.filename, date_time=ZIP_EPOCH)
                out.create_system = 3
                out.external_attr = (0o755 if is_dir else 0o644) << 16
                if is_dir:
                    out.external_attr |= 0x10  # MS-DOS directory flag
                    out.compress_type = zipfile.ZIP_STORED
                    dst.writestr(out, b"")
                else:
                    out.compress_type = zipfile.ZIP_DEFLATED
                    dst.writestr(out, src.read(info.filename),
                                 compresslevel=COMPRESS_LEVEL)


def main(argv):
    if len(argv) != 3:
        raise SystemExit(
            "usage: normalize-mcpb.py <in.mcpb> <out.mcpb>"
        )
    normalize(argv[1], argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

# krozov-ai-tools

[![CI](https://github.com/kirich1409/krozov-ai-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/kirich1409/krozov-ai-tools/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/@krozov/maven-central-mcp)](https://www.npmjs.com/package/@krozov/maven-central-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)

Claude Code plugin marketplace by Kirill Rozov.

## Installation

Add the marketplace to Claude Code:

```
/plugin marketplace add kirich1409/krozov-ai-tools
```

Install a plugin:

```
/plugin install maven-mcp@krozov-ai-tools
```

## Plugins

### maven-mcp

Maven dependency intelligence for JVM projects. Auto-registers an MCP server that provides tools for version lookup, dependency auditing, vulnerability checking, and changelog tracking across Maven Central, Google Maven, and custom repositories. The server also runs standalone (stdio or HTTP) and can be connected to any MCP-compatible agent — see [Use with any MCP client](plugins/maven-mcp/README.md#use-with-any-mcp-client).

**Features:**
- Version intelligence — stability-aware selection, upgrade type classification
- Project scanning — Gradle, Maven, version catalogs
- Repository auto-discovery from build files
- Vulnerability checking via [OSV.dev](https://osv.dev/)
- Changelog tracking — GitHub releases, AndroidX, AGP, Firebase release notes
- Artifact search across Maven Central

**Skills:** `/check-deps`, `/latest-version`, `/dependency-changes`

See [`plugins/maven-mcp/`](plugins/maven-mcp/) for full documentation.

### youtube-transcript

Fetches existing YouTube subtitles (manual or auto-generated) via the InnerTube API. Auto-registers an MCP server that returns transcript text — no speech-to-text, no video/audio download, only captions YouTube already publishes.

See [`plugins/youtube-transcript/`](plugins/youtube-transcript/) for full documentation.

#### Install as a desktop extension (`.mcpb`)

Besides the marketplace install above, `youtube-transcript` is published as an `.mcpb` bundle you can install into the Claude desktop app with a double click. Requires Python 3.9+ on macOS or Linux (`compatibility` in the bundle manifest declares `darwin`, `linux`).

**1. Download.** Releases of this repository interleave two independent version lines, so the newest release may belong to `maven-mcp`. Pick a release from the plugin's own tag namespace — [releases tagged `youtube-transcript--v*`](https://github.com/kirich1409/krozov-ai-tools/releases?q=youtube-transcript) — not from `/releases/latest`. Each release that carries a bundle attaches two files: `youtube-transcript-<version>.mcpb` and `youtube-transcript-<version>.mcpb.sha256`.

**2. Verify authenticity — build provenance.** Installing an `.mcpb` makes the Claude desktop app run the bundled Python server on your machine, with your own privileges and no sandbox — an unverified bundle is arbitrary code execution, not just a file. **Verification is blocking: if any of the commands below fails, do not install the bundle.** Report it as a security issue instead.

```
gh attestation verify youtube-transcript-<version>.mcpb \
  --repo kirich1409/krozov-ai-tools \
  --signer-workflow kirich1409/krozov-ai-tools/.github/workflows/release.yml \
  --source-ref refs/tags/youtube-transcript--v<version> \
  --deny-self-hosted-runners
```

The fully-qualified `--signer-workflow` is load-bearing: `--repo` alone accepts an attestation minted by *any* workflow in the repository.

What this proves: these exact bytes were produced by that workflow file in that repository, at that tag, on a GitHub-hosted runner. What it does **not** prove: `--signer-workflow` pins the workflow's *path*, not the source commit — add `--source-digest <commit sha>` to pin that too. Provenance also says nothing about whether anyone reviewed the release; it says where the bytes came from.

**3. Checksum — corruption detection only.**

```
shasum -a 256 -c youtube-transcript-<version>.mcpb.sha256
```

This catches a truncated or corrupted download. It is **not** an authenticity control: both files are published together by the same job, so anyone able to replace the bundle on the release can replace the checksum with it. Authenticity is step 2's job, not this one.

The bundle *is* byte-reproducible: `scripts/pack-mcpb.sh` normalizes the archive's metadata before checksumming it (`mcpb pack` itself embeds file mtimes and ignores `SOURCE_DATE_EPOCH`) and stores entries uncompressed, so the digest does not depend on your Python version, platform, or zlib build. The one precondition is the `mcpb` CLI version, and the repository pins it — `npm ci` in `tools/mcpb` installs exactly the version the release used.

Rebuild the released tag and compare:

```
git clone https://github.com/kirich1409/krozov-ai-tools
cd krozov-ai-tools
git checkout youtube-transcript--v<version>
(cd tools/mcpb && npm ci --ignore-scripts)
bash scripts/pack-mcpb.sh
shasum -a 256 dist/youtube-transcript-<version>.mcpb
```

The digest must equal the one in the published `.mcpb.sha256`. Requires `node`, `npm`, `jq`, `git`, and `python3`. That is still a rebuild-and-compare check, not an authenticity control; authenticity is step 2's job. Scope and known limits — `docs/PLUGIN-STANDARDS.md` §12.

**4. Install.** Double-click the verified `.mcpb`; the Claude desktop app installs it as an extension.

## License

MIT

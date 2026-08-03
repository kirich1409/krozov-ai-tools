---
type: plan
slug: youtube-transcript-mcpb-bundle
date: 2026-08-03
status: approved
spec: none
stage: 1 of 2
research: swarm-report/research/research-youtube-transcript-desktop-install.md (untracked — see Verification & Sources)
risk_areas: [supply-chain, ci, packaging]
review_verdict: conditional
review_cycles: 6
review_panel: [devops-expert, security-expert]
---

# Plan: MCPB bundle for youtube-transcript — Stage 1 (build + CI)

## Context & Decision

The `youtube-transcript` MCP server reaches users through one channel today: the Claude Code plugin marketplace. Desktop-app users must hand-edit `claude_desktop_config.json` (`README.md:30-53`). The decision — made by the user, researched, and verified by spike — is to add an MCPB bundle (`.mcpb`) as a second distribution artifact.

### Why this plan covers only half of that

Review converged on one structural problem: **the release path cannot be verified before a tag is pushed.** Restructuring `release.yml` was the only change whose acceptance reduced to "read the YAML and be convinced", and the next real tag also releases `maven-mcp` — a mistake there breaks a pipeline that works today. Three revisions running, that section was fixed incompletely.

- **Stage 1 (this plan):** manifest template, pinned toolchain, build script, verification scripts, CI job, documentation. Everything asserted by a machine on every pull request. `release.yml` untouched; no bundle reaches users.
- **Stage 2 (separate plan, after Stage 1 merges):** release wiring, gated on a `workflow_dispatch` dry-run. Scope preserved in *Stage 2 handoff*.

### Spike facts (reproduced verbatim — do not re-derive)

The research report is untracked (`.gitignore:23`) and does not travel with this branch:

- CLI `@anthropic-ai/mcpb` **2.1.2** accepts `server.type: "python"` with a bare `command: "python3"`. `validate` → `pack` → `unpack` → live handshake all passed. Verified during review: the package has **no `engines` field**, so Node choice is unconstrained by it.
- Manifest schema **`0.4`** is current. The package's own `mcpb-manifest-latest.schema.json` is stale at `0.3`, and **`mcpb validate` accepts both** while rejecting a manifest with no `manifest_version` — so `validate` is a shape check, not a version pin.
- Claude Desktop resolves the **user's full shell PATH**: `Using MCP server command: /opt/homebrew/bin/python3`, 32-entry PATH.
- Observed handshake: `initialize` → `notifications/initialized` → `tools/list` → result, then clean close. Server starts on demand.
- Unsigned bundles install and run.
- **macOS only.** Nothing was observed about how the app treats `compatibility` fields.

The server is self-contained — `server.py` resolves imports from `sys.path[0]`, locked by `tests/test_composition.py:122-141`. **No server code changes are permitted.**

## Technical Approach

**The artifact.** An `.mcpb` is a zip: `manifest.json` at the root plus the server tree. The CLI reads only that literal filename, so the repo keeps a template under a different name and the build script materialises `manifest.json` in a staging directory.

**Version handling.** No hard-coded version in the manifest: the build script injects `plugin.json`'s. No fourth version location, and `scripts/validate.sh` is **not modified**.

**The skew this does not close, and how it is closed.** The manifest version comes from `plugin.json`; `server.py` carries `SERVER_VERSION`, and `validate.sh` compares them only under `--check-tag` — never on a PR. The smoke script greps the **packed** `server/server.py` for `SERVER_VERSION = "<manifest version>"`.

Do **not** instead assert on `initialize`'s `result.serverInfo.version`. `protocol/dispatch.py:45-53` hardcodes `{"name": "youtube-transcript", "version": "1"}` and documents the decoupling as deliberate. Verified live: the handshake returns `"1"`.

**Containment — enumerated from the index, and every guard verified to actually fire.** Staging enumerates tracked files via `git ls-files -s -z`, accepts only regular-file modes (`100644`/`100755`), and copies with `cp -P` so nothing is dereferenced on the way in. `LICENSE.md` goes through the *same* mode check rather than a bare `cp` — it is the one file not under the server tree, and an unchecked `cp` of a symlinked licence would place foreign bytes in the bundle as a regular file, invisible to every later check.

Two guards that earlier revisions got wrong, both re-verified by running them:

- `find "$S" -mindepth 1 \( -type l -o ! -type f \)` matches **every directory** (`! -type f` is true for them), so on a correct tree it emits the six package dirs and the check can never be satisfied.
- `! find … | grep -q .` does not abort under `set -euo pipefail`: bash exempts `!`-inverted commands from `set -e`. Proven with a symlink planted in staging — the script printed its end-of-script marker and exited 0.

So the assertion is written as an explicit capture-and-test (`BAD=$(find …); [ -z "$BAD" ] || exit 1`) over `-type l` and non-regular-non-directory entries, and it gets its own negative test.

Verification asserts the invariant rather than a committed listing: every archive entry matches `^(manifest\.json|LICENSE\.md|server/.*\.py)$`, and the `.py` set equals the tracked set. **The pathspec was verified empirically:** `git ls-files 'plugins/youtube-transcript/plugin/server/**/*.py'` returns **23** of **25**, silently dropping `server.py` and `composition.py`, because a pathspec without `:(glob)` requires `**/` to consume a segment. The correct form is `git ls-files -- <dir>` filtered to `.py`. A count guard alone is not enough — if pack and smoke share the same bad pathspec both sides shrink together and stay equal — so the check additionally anchors on those two filenames by name, which is what a shared under-match would drop.

**What the manifest declares must be asserted, not just its shape.** `server.mcp_config` decides what executes on the user's machine at install time. `mcpb validate` checks schema shape only, and a handshake driven from a hardcoded path proves nothing about the declared command. So the smoke script asserts against the **packed** manifest that `entry_point`, `command` and `args` are exactly what this plan specifies, and drives its handshake from those declared values with `${__dirname}` substituted. The same reasoning that makes `tools` set-equality necessary applies with more force here.

**Toolchain.** Not `npx --yes`: pinning `@anthropic-ai/mcpb@2.1.2` pins only the top level (9 caret-ranged direct dependencies, ~56 packages), and `npx --yes` runs lifecycle scripts. Instead a committed `tools/mcpb/package.json` + `package-lock.json`, installed with `npm ci --ignore-scripts` via `working-directory`, invoked as `tools/mcpb/node_modules/.bin/mcpb`. `.gitignore:17` ignores all lockfiles, so a negation is required (verified: `git check-ignore` exits 0 on that path today). The directory is `tools/mcpb/`, not the repo root, so the repo gains no root `package.json` readable as publishable (`CLAUDE.md:9`).

**Build-time only**: the npm tree never enters the bundle (index-enumerated staging), and the plugin's runtime stays stdlib-only — which is what keeps this consistent with the plugin's `No pip dependencies` non-negotiable, whose purpose is avoiding third-party supply-chain risk in the *shipped* tool.

**Audit gate — calibrated against measured reality, not a remembered id.** A committed lockfile freezes advisories. Measured on the pinned tree: five advisories, none with a fix available. A blanket `--audit-level=critical` would be green against all of them and against every future high, so the gate runs at `high` with an explicit allowlist of accepted GHSA ids.

Three mechanics that must be specified rather than assumed, all established by running the command:

- `--audit-level` affects only the **exit code**, not the JSON — the report lists every severity regardless, so the gate must filter by severity itself.
- Ids live per-advisory at `.vulnerabilities[].via[] | select(type=="object") | .url`; propagated records carry `via: ["<package>"]` with no id at all, so a naive "every advisory must have an allowlisted id" rule cannot be implemented.
- `npm audit --audit-level=high` exits non-zero when anything at that level exists, so under `set -e` the step dies before any allowlist logic runs.

The allowlist is **seeded from a real run**, not from a value written into this plan: an earlier revision hardcoded an id that turned out to be the wrong advisory (a `low`) while the actual `high` was absent, which would have made the gate red on its first CI run behind a green task check. T-2 generates it and records each id's severity and reachability argument.

**Node.** `ubuntu-latest` ships Node, so `actions/setup-node` is about pinning the major, not availability. `node-version: "22"`: maintenance LTS through 2027-04-30 and the version the spike used. Active LTS is 24; the CLI declares no `engines`, so nothing constrains the choice, and 22 is picked for spike parity.

**Checksum.** Generated with cwd set to the bundle's directory so the file holds a **bare basename** — the form an end user needs in a flat download directory. CI verifies it in the smoke script. Note what it is: both files come out of the same job and travel together, so this detects transport corruption, not authenticity. In Stage 2 authenticity belongs to provenance attestation, and the README must say so rather than presenting a co-located checksum as proof of origin.

**Shared shell logic.** `scripts/pack-mcpb.sh`, `scripts/smoke-mcpb.sh`, `scripts/tests/test-smoke-negatives.sh`. Both of the first two resolve the repo root themselves (`git rev-parse --show-toplevel`) — `release.yml:11-13` sets `defaults.run.working-directory: plugins/maven-mcp` and carries two comments about paths double-resolving from that trap. `smoke-mcpb.sh` reads the git index, so any job running it needs a checkout at the same commit; it is not runnable against a bare downloaded artifact.

## Affected Modules & Files

| Path | Change | Note |
|---|---|---|
| `plugins/youtube-transcript/mcpb/manifest.template.json` | new | `manifest_version: "0.4"`, no `version` |
| `tools/mcpb/package.json`, `tools/mcpb/package-lock.json` | new | Pinned CLI tree |
| `tools/mcpb/audit-allowlist.txt` | new | Accepted GHSA ids, generated from a real run |
| `.gitignore` | edit | Negate line 17 for `tools/mcpb/package-lock.json` |
| `.github/dependabot.yml` | new | npm ecosystem, `/tools/mcpb` (verified absent today) |
| `scripts/pack-mcpb.sh` | new | Index-enumerated staging, version injection, pack, `.sha256` |
| `scripts/smoke-mcpb.sh` | new | Containment, manifest contract, version agreement, handshake, tool-set equality |
| `scripts/tests/test-smoke-negatives.sh` | new | Proves each fail-closed check actually fails |
| `.github/workflows/ci.yml` | edit | New job `youtube-transcript-mcpb` |
| `docs/PLUGIN-STANDARDS.md` | edit | Section 12 |
| `plugins/youtube-transcript/CLAUDE.md`, `plugins/youtube-transcript/AGENTS.md` | edit | One identical line each |
| `.github/workflows/release.yml` | **unchanged** | Stage 2 |
| `CLAUDE.md`, `AGENTS.md`, `plugins/youtube-transcript/README.md` | **unchanged** | Stage 2 |
| `scripts/validate.sh` | **unchanged** | Out of scope by design |
| `plugins/youtube-transcript/plugin/server/**` | **unchanged** | Touching it is a plan violation |

## Decisions Made

| Decision | Rationale |
|---|---|
| Split into two stages | The release path is the only part not machine-verifiable on a PR, and it shares a pipeline with `maven-mcp`'s working release |
| Version injected at build time | No fourth version location; skew impossible rather than checked |
| Skew closed by static grep of the packed `server.py` | `dispatch.py` hardcodes `"version": "1"` by design |
| Staging enumerates `git ls-files -s -z`, filters on mode, copies with `cp -P`; `LICENSE.md` goes through the same check | `cp` dereferences symlinks; a tracked symlink — including a symlinked `LICENSE.md` — would ship foreign content as a regular file, invisible to every name-based check |
| Guards written as capture-and-test, not `! cmd \| grep -q` | Verified: `!`-inverted commands are exempt from `set -e`, and `! -type f` matches directories. The earlier form was a double no-op |
| Containment anchored on `server.py`/`composition.py` by name, not only by count | A pathspec shared between pack and smoke shrinks both sides equally; a count comparison stays green |
| `mcp_config` and `entry_point` asserted against the packed manifest | This field decides what runs on the user's machine; `mcpb validate` checks shape only |
| Manifest `tools` set must equal the runtime set | `tools` is install-time **disclosure, not enforcement** — nothing in MCPB constrains what the server exposes |
| Audit gate at `high` with an allowlist generated from a real run | `critical` is green by construction; a hand-written id proved to be the wrong advisory |
| Dependabot on `/tools/mcpb` | Version-update notifications. Not a gate — the allowlist is |
| `.sha256` holds a bare basename, and CI verifies it | The end-user command must work in a flat directory; a format decided in prose and exercised nowhere is how earlier defects arose |
| `manifest_version: "0.4"` asserted by `jq` on the packed manifest | Verified: the CLI accepts `0.3` too |
| `platforms` and `runtimes.python` are declarations of intent, not verified enforcement | The spike observed nothing about how the app treats them. A user with only Python 3.8 will likely see the server start and fail on syntax rather than a clean refusal — a known Stage 1 limitation |
| `node-version: "22"` | Maintenance LTS through 2027-04-30 and spike parity; the CLI declares no `engines` |
| Handshake asserts declarations only — no `tools/call`, no canary env var | Keeps the PR job network-free |
| `LICENSE.md` staged into the bundle | First channel distributing this code standalone |
| `maven-mcp` untouched | Plugin isolation is a repo-level principle |

## Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Supply-chain compromise via the CLI tree | major | Committed lockfile, `--ignore-scripts`, execution in a job holding only `contents: read` (`ci.yml:11-12`) with no secrets; GHSA-allowlist audit gate; Dependabot for updates |
| Foreign content enters the bundle | major | Index-enumerated staging with mode filtering and `cp -P`, `LICENSE.md` under the same check, plus a capture-and-test assertion over the staged tree and a regex invariant over every archive entry |
| The manifest declares something other than what was reviewed | major | Deep equality on the whole `server` object against the packed manifest — not field-by-field, because the v0.4 schema also allows `mcp_config.env` and `platform_overrides`, and a per-platform override replaces `command`/`args` for that platform. The handshake is driven from the declared values, and a negative test tampers an override specifically |
| Manifest version and packed `SERVER_VERSION` diverge | major | Static grep in the smoke script, every PR |
| Manifest `tools` drifts from what the server exposes | major | Set-equality between manifest and `tools/list` |
| A fail-closed assertion silently stops failing | major | `scripts/tests/test-smoke-negatives.sh` covers assertions 1, 2, 3, 4, 5 and 7 plus the staging symlink guard, each proven red on tampered input in CI. Assertion 6's timeout path is not negatively tested — simulating a hung server is disproportionate here, and it is stated rather than implied |
| Bundle builds but does not run | major | Smoke starts the packed server from an unrelated cwd and completes a real handshake, with per-exchange timeouts so a hang fails loudly |
| `scripts/` is linted nowhere in this repo | minor | Ungated `shellcheck` over both script directories — new coverage; verified green on the existing `validate.sh` |
| A non-`.py` runtime asset is added under `plugin/server/` | minor | Staging keeps only `.py`, so such a file would be silently dropped. The smoke script fails if the tracked set under that path contains a non-`.py` file, turning a silent omission into a loud one |
| New CI job is not a required check | minor | Branch protection is outside CI's reach; T-5 names the check and the interim consequence |
| Registry outage during `npm audit` | minor | `cache: npm` covers `npm ci` tarballs but **not** `npm audit`, which always contacts the advisory endpoint. The gate fails **closed** on a degraded report — `set -euo pipefail` inside the `run:` block plus a `has("vulnerabilities")` shape assertion, both required because Actions defaults to `bash -e` without `pipefail`; verified that without them an outage passes silently. A re-run is the remedy |
| A new advisory lands while no watched path changes | minor | The gate is path-gated and the lockfile is frozen, so the case where it would newly fire is the case where it does not run. Depends on repository-level Dependabot security alerts, which `dependabot.yml` cannot express — named in §12, not silently assumed |
| Bundle bytes are not reproducible | minor | `mcpb pack` embeds mtimes, so rebuilding identical inputs yields a different SHA-256. Recorded in §12; whether to pursue determinism is a Stage 2 question |

## Verification & Sources

**Source of truth for "done":** this plan. No spec exists — the change is build infrastructure. The research report is untracked, so its load-bearing facts are reproduced above.

**Baseline collected before implementation:** yes, observed rather than expected. A hand-built bundle from this exact server tree was installed into Claude Desktop and produced the recorded handshake and interpreter resolution. Additionally established by running commands during review: the live `serverInfo.version`; the CLI accepting both schema versions and rejecting a missing one; the `git ls-files` pathspec under-match (23 of 25); `find … ! -type f` matching directories; `!`-inverted commands escaping `set -e`; `cp` dereferencing a symlinked source; `npm audit --json` ignoring `--audit-level` and omitting ids on propagated records; the CLI having no `engines` field; and a real `mcpb pack` emitting 27 entries with no directory records.

**Testing strategy by pyramid level:**

- **L0:** `bash scripts/pack-mcpb.sh` exits 0 and emits bundle + `.sha256`; `mcpb validate` passes on the staged manifest.
- **L1a:** **ungated** `shellcheck scripts/*.sh scripts/tests/*.sh` — new coverage: `ci.yml:88-90` shellchecks only `plugins/maven-mcp/plugin/hooks/*.sh` behind a `maven_mcp` gate, and neither `validate.sh` nor `PLUGIN-STANDARDS.md:139` reaches `scripts/`. Plus the GHSA-allowlist audit gate. `bash scripts/validate.sh` stays green.
- **L1b:** `code-reviewer`, `devops-expert`, `security-expert` during `/acceptance`.
- **L2:** `scripts/tests/test-smoke-negatives.sh` — tampers with a staged tree and asserts each fail-closed check goes red with its own message.
- **L3:** `scripts/smoke-mcpb.sh` — containment regex, tracked-set equality with filename anchors, manifest contract (`entry_point`/`command`/`args`), manifest version, packed `SERVER_VERSION`, checksum, handshake driven from the declared command, tool-set equality. Declarations only; no network.
- **L4:** not applicable to Stage 1 — no release path is modified.
- **L5 (manual, required):** open the PR run's Artifacts, download the archive — `upload-artifact` always delivers a **zip container**, so a plain double-click will not work — unzip, run `shasum -a 256 -c` (**transport integrity only, not authenticity**), drag the `.mcpb` into Claude Desktop, confirm both tools appear and answer.

## Stage 2 handoff (not built here)

Stage 2 gets its own plan and review. Recorded so nothing is re-derived.

**Step→job mapping is a hard requirement.** `release.yml` has exactly eight steps; every one must be placed explicitly:

| Existing step | Target job |
|---|---|
| `actions/checkout` (`:21-23`) | every job needing a tree (`gate`, `pack`, `publish`) |
| Verify tag reachable from `main` (`:25-34`) | `gate` |
| `validate.sh --check-tag` (`:36-38`) | `gate` |
| `Setup Python 3.9` (`:43-46`) | `gate` |
| `Run Python tests` (`:51-53`) | `gate` |
| `Run Python tests (youtube-transcript)` (`:61-63`) | `gate` |
| `Create GitHub Release` (`:65-69`) | `publish` |
| Per-plugin tags (`:71-110`) | `publish` |

**Ordering rule:** no job may build, checksum, attest, or publish before the ancestry check *and* `--check-tag` have both passed in `gate`. The ancestry check refuses to release an unreviewed branch commit; downstream of `pack`/`attest` it would mean signing bytes from an arbitrary commit.

**Permissions.** Declare `permissions: {}` at workflow level and grant explicitly per job. This is the construct that fails closed: with **no** workflow-level block, a job omitting `permissions:` inherits the repository default, which may be read-write — the opposite of what an earlier draft of this handoff claimed.

| Job | Permissions |
|---|---|
| `gate`, `pack` | `contents: read`; no `id-token`, no secrets |
| `attest` | `contents: read` **plus** `id-token: write`, `attestations: write` — job-level permissions replace rather than extend, so omitting `contents: read` breaks `actions/checkout`; check whether `download-artifact@v4` also needs `actions: read` |
| `publish` | `contents: write`; no npm, no `id-token` |

Remaining requirements:

- `workflow_dispatch` with a dry-run input running `gate` + `pack` and skipping `publish`; a successful dispatch run is a required acceptance item — this is what makes the restructure falsifiable before a tag exists.
- `pack` must call `bash scripts/pack-mcpb.sh --expect-version "${GITHUB_REF_NAME#v}"` — the flag exists in Stage 1 solely for this — then `bash scripts/smoke-mcpb.sh --require-checksum "$MCPB_PATH"` before `attest`. Containment lives entirely in the smoke script; `pack-mcpb.sh` asserts none of it. `--require-checksum` is mandatory here: without it a missing `.sha256` skips verification silently, which is fail-open against a `download-artifact` result. Smoke reads the git index, so that job needs a checkout at the same commit.
- Artifact hand-off: explicit `name:` on both `upload-artifact` and `download-artifact`; do not rely on least-common-ancestor path stripping.
- Publish `pack`'s checksum as a **job output**, so `publish` verifies against a value that did not travel with the bytes it checks.
- Asset publication: `softprops/action-gh-release` with explicit `files:` listing the `.mcpb` and its `.sha256`.
- Consider ordering `attest` after `publish` to avoid an orphan attestation if publishing fails.
- `timeout-minutes` on every job; drop `defaults.run.working-directory` from `publish` if no remaining step needs it.
- Verify (do not assume) whether `softprops/action-gh-release` at the pinned SHA updates an existing release or fails, before documenting a recovery procedure that depends on the answer.
- Evaluate bundle reproducibility (`SOURCE_DATE_EPOCH` or post-pack normalisation) before deciding the checksum's role.
- Documentation last: `CLAUDE.md` + `AGENTS.md` Publishing sections (**both copies**), the `per plugin` wording on the version non-negotiable (user-approved), release recovery in §12, the §10 checklist item for a green bundle job, and `README.md`'s install section. The README must present provenance as the authenticity control and `shasum -c` as corruption detection only, with this exact command:

```
gh attestation verify youtube-transcript-<version>.mcpb \
  --repo kirich1409/krozov-ai-tools \
  --signer-workflow kirich1409/krozov-ai-tools/.github/workflows/release.yml
```

`--signer-workflow` fully qualified is load-bearing: `--repo` alone accepts an attestation minted by any workflow in the repository.

## Out of Scope

- Everything in *Stage 2 handoff*.
- Code signing and certificate acquisition.
- Submission to the Anthropic Extensions/Connectors directory.
- An MCPB bundle for `maven-mcp`.
- Windows support — excluded deliberately.
- Closing the repo-wide `scripts/` blind spot in `validate.sh` and `PLUGIN-STANDARDS.md:139`'s exec-bit check.
- Any change to `plugins/youtube-transcript/plugin/server/**`.

## Open Questions

None blocking. Three forks were resolved by the user during planning: build-time version injection over a fourth version location; adding `per plugin` to the version non-negotiable (Stage 2); and splitting release wiring into a second stage.

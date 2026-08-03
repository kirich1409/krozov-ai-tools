# Tasks — Stage 2, release wiring

Plan: `docs/plans/youtube-transcript-mcpb-stage2/plan.md`.
Branch `feature/mcpb-release-wiring`, worktree `.worktrees/mcpb-release-wiring`.

**Never** write a guard or an acceptance check as `! cmd` / `! cmd | grep -q .` — verified in Stage 1:
bash exempts `!`-inverted commands from `set -e`, so the guard silently cannot fail.

**Never** assume a GitHub Actions `run:` block has `pipefail` — the default is `bash -e` without it.
Every non-trivial block declares its own `set -euo pipefail`.

Do not touch `plugins/*/plugin/server/**`. Do not bump any version.

---

## T-1 — `validate.sh` accepts a per-plugin tag

**files:** `scripts/validate.sh` (edit)

**what:** `--check-tag` currently takes a bare version and validates whichever plugins sit at it
(`check_tag_versions`). Accept the per-plugin form as well: `--check-tag youtube-transcript--v0.1.0`
validates that named plugin's three version locations against `0.1.0`.

Errors, each with a distinct message: tag does not parse as `<plugin>--v<semver>`; plugin absent from
`marketplace.json`; named plugin's version differs from the tag's.

The bare-version form keeps its current behaviour unchanged — humans and docs use it.

**acceptance:** THE SYSTEM SHALL validate exactly the named plugin when given a per-plugin tag, AND
SHALL fail with a distinct message for each of the three error classes, AND SHALL leave bare-version
behaviour unchanged.

**check:**
```
bash scripts/validate.sh --check-tag youtube-transcript--v0.1.0   # passes
bash scripts/validate.sh --check-tag youtube-transcript--v9.9.9   # fails: version mismatch
bash scripts/validate.sh --check-tag nosuch--v1.0.0               # fails: unknown plugin
bash scripts/validate.sh --check-tag not-a-tag                    # fails: unparseable
bash scripts/validate.sh --check-tag 0.27.0                       # unchanged: maven-mcp only
bash scripts/validate.sh                                          # green
shellcheck scripts/validate.sh
```

---

## T-2 — restructure `release.yml` into four jobs

**files:** `.github/workflows/release.yml` (rewrite)

**what:** The plan's *Design* section is the specification: trigger, four jobs, permissions matrix,
step→job mapping, ordering rule. Every one of the eight existing steps must land where the mapping
table says, or be deleted only where the table says `deleted`.

Required explicitly:

- `permissions: {}` at workflow level; each job declares its own. `attest` restates `contents: read`
  — job-level permissions replace rather than extend.
- `gate` parses `github.ref_name` into `plugin`/`version` job outputs; unparseable tag or unknown
  plugin is a hard error.
- Ancestry check and `--check-tag` skipped on `workflow_dispatch`, everything else runs.
- `pack`/`attest` gated on `plugins/<plugin>/mcpb/manifest.template.json` existing — data-driven,
  never a hardcoded plugin name.
- `attest` before `publish` (D2). Neither runs on a dry run.
- `pack` exposes the checksum as a job output; `publish` verifies against it.
- `defaults.run.working-directory` dropped (D5); `timeout-minutes` on every job.
- The per-plugin tag creation step is deleted (D1).
- `actions/attest-build-provenance` and `download-artifact` pinned like the existing
  `softprops/action-gh-release` pin.

**acceptance:** GIVEN a tag `<plugin>--v<version>` on a commit reachable from `main`, WHEN the
workflow runs, THEN it SHALL gate, pack (when that plugin has a bundle), attest and publish in that
order; AND GIVEN a `workflow_dispatch` dry run, it SHALL gate and pack and SHALL NOT attest or
publish; AND GIVEN a tag naming an unknown plugin, it SHALL fail in `gate`.

**check:** `actionlint .github/workflows/release.yml`; YAML parses; every step from the mapping table
is present at its target job, verified by name.

---

## T-3 — dry run on the real repository

**files:** none (verification task)

**what:** Push the branch, then trigger the workflow via `workflow_dispatch` with `dry_run: true` for
`youtube-transcript`, and again for `maven-mcp` (which has no bundle — `pack` must skip, not fail).

This is the acceptance item the whole stage exists for. It is not optional and cannot be replaced by
reading the YAML.

**acceptance:** THE SYSTEM SHALL complete a dispatch dry run green for both plugins, with `pack`
running for `youtube-transcript` and skipped for `maven-mcp`, and with `attest` and `publish` skipped
in both.

**check:** run URLs and per-job conclusions recorded verbatim in the report. Establish while here —
by observation, not assumption — whether `download-artifact@v4` needs `actions: read`.

---

## T-4 — README install section

**files:** `README.md` (edit), `plugins/youtube-transcript/README.md` if one exists

**what:** How to install the bundle: download the `.mcpb` from the release, verify, install by
double-click. Present `gh attestation verify` (fully qualified `--signer-workflow`, exact command in
the plan) as the authenticity control, and `shasum -a 256 -c` as corruption detection only. Do not
present a co-located checksum as proof of origin.

`README.md` at repo root is exempt from the English rule (`CLAUDE.md`); match the file's existing
language.

**acceptance:** THE SYSTEM SHALL document download, verification and installation, AND SHALL
distinguish authenticity from corruption detection rather than conflating them.

---

## T-5 — publishing documentation

**files:** `CLAUDE.md` (edit), `AGENTS.md` (edit), `docs/PLUGIN-STANDARDS.md` (edit)

**what:** The release procedure changed shape: releases are triggered by `<plugin>--v<version>`,
never by a unified `v*` tag.

- `CLAUDE.md` and `AGENTS.md` Publishing sections — **both copies**, kept identical where they were
  identical before.
- `docs/PLUGIN-STANDARDS.md` §12 grows the release half it promised in Stage 1, plus a recovery
  procedure for a partially failed release. Write recovery only from established behaviour of
  `softprops/action-gh-release` on an existing release — establish it in T-3 or state plainly that it
  is unknown.
- §10 pre-release checklist gains the item Stage 1 deliberately withheld: the bundle job green for
  the release commit, and a green dispatch dry run before the first tag under a changed workflow.

`docs/**` and root-level docs are exempt from the English rule; match each file's existing language.

**acceptance:** THE SYSTEM SHALL describe the per-plugin release procedure identically in both
instruction files, AND SHALL document recovery only from established behaviour.

**check:** `diff` the Publishing sections of `CLAUDE.md` and `AGENTS.md`; `bash scripts/validate.sh`.

---

## T-6 — reproducibility question, answered rather than assumed

**files:** `docs/PLUGIN-STANDARDS.md` (edit)

**what:** `mcpb pack` embeds mtimes, so two builds of identical inputs differ by SHA-256. Establish
by running whether `SOURCE_DATE_EPOCH` or post-pack normalisation makes the bundle reproducible.

Record the answer either way. If it does not, say so and state what the checksum is therefore for —
do not leave a reader to infer that a published checksum implies a rebuildable artifact.

**acceptance:** THE SYSTEM SHALL record a measured answer, with the command that produced it.

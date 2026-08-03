# Tasks — Stage 2, release wiring (revision 2)

Plan: `docs/plans/youtube-transcript-mcpb-stage2/plan.md`.
Branch `feature/mcpb-release-wiring`, worktree `.worktrees/mcpb-release-wiring`.

Revision 2 incorporates 40 findings from parallel devops and security reviews of revision 1, both of
which returned BLOCK. Ordering below is load-bearing: T-0 must land on `main` before T-3 can run.

**Never** write a guard as `! cmd` / `! cmd | grep -q .` — bash exempts `!`-inverted commands from
`set -e`, so the guard silently cannot fail.

**Never** assume a `run:` block has `pipefail` — the default is `bash -e` without it.

**Never** interpolate `${{ }}` into script text for any value derived from a ref. Actions substitutes
into the script *text* before bash sees it, so quoting cannot save it. Pass through `env:`.

Do not touch `plugins/*/plugin/server/**`. Do not bump any version.

---

## T-0 — preparatory: dispatch trigger on `main`

**files:** `.github/workflows/release.yml` (edit, minimal), own PR, merged before T-3

**what:** `workflow_dispatch` is only dispatchable when declared on the default branch. Add it — with
the `plugin` choice input and **no** `dry_run` input — plus the guard that makes it inert: every
existing step gains `if: github.event_name == 'push'`, or the job does. A dispatch on today's
workflow must do nothing observable.

No other behaviour change. This exists solely to make T-3 possible.

**acceptance:** GIVEN today's `release.yml` on `main` plus this change, WHEN dispatched, THEN it
SHALL complete without creating a release, a tag, or an attestation.

**check:** dispatch it on `main` after merge; record the run URL and per-step conclusions.

---

## T-1 — `validate.sh` accepts a per-plugin tag

**files:** `scripts/validate.sh` (edit)

**what:** `--check-tag` currently takes a bare version and validates whichever plugins sit at it.
Accept `--check-tag youtube-transcript--v0.1.0` as well, validating that named plugin's three version
locations against `0.1.0`.

Parsing follows D7: anchored `^([a-z0-9-]+)--v([0-9]+\.[0-9]+\.[0-9]+)$`, never a prefix strip.
Distinct error messages for: unparseable tag; plugin absent from `marketplace.json`; version mismatch
on the named plugin. Bare-version behaviour unchanged.

**acceptance:** THE SYSTEM SHALL validate exactly the named plugin for a per-plugin tag, AND SHALL
fail with a distinct message per error class, AND SHALL leave bare-version behaviour unchanged.

**check:**
```
bash scripts/validate.sh --check-tag youtube-transcript--v0.1.0   # passes
bash scripts/validate.sh --check-tag youtube-transcript--v9.9.9   # fails: version mismatch
bash scripts/validate.sh --check-tag nosuch--v1.0.0               # fails: unknown plugin
bash scripts/validate.sh --check-tag 'evil--v1.0.0;id'            # fails: unparseable
bash scripts/validate.sh --check-tag 0.27.0                       # unchanged
bash scripts/validate.sh                                          # green
shellcheck scripts/validate.sh
```

---

## T-2 — restructure `release.yml`

**files:** `.github/workflows/release.yml` (rewrite)

**what:** The plan's *Design* section is the specification. Every decision D1–D11 applies. Points that
are non-obvious and were each a review finding:

- **D2's `publish` condition is adopted whole**, both halves. A condition that only restores the
  skipped-plugin path ships unattested assets; one that only guards failure deletes the bundle-less
  plugin's release.
- `gate` resolves plugin/version per D6 — parse only on `push`, `choice` input plus
  `marketplace.json` lookup on dispatch.
- D7's anchored parse and `env:` passing throughout.
- `pack` carries the toolchain and supply-chain steps from `ci.yml`'s `youtube-transcript-mcpb` job:
  `setup-node`, `npm ci --ignore-scripts`, the npm audit gate, `setup-python`. These are controls, not
  scaffolding.
- `publish` verifies the checksum against `needs.pack.outputs.sha256` **before** the release step and
  attaches both files via `files:`.
- `attest` per D9 — verify before signing, or run inside `pack`.
- `concurrency` group; `timeout-minutes` on every job; `persist-credentials: false` where no push
  happens; `defaults.run.working-directory` dropped.
- Pin `actions/attest-*` and `download-artifact` the way `softprops/action-gh-release` is pinned.

**acceptance:** GIVEN a tag `<plugin>--v<version>` on a commit reachable from `main`, THEN the
workflow SHALL gate, pack and attest when that plugin has a bundle, and publish in all cases; AND
GIVEN a dispatch, it SHALL gate and pack and SHALL NOT attest or publish; AND GIVEN a tag naming an
unknown plugin, it SHALL fail in `gate`; AND GIVEN a tag name containing shell metacharacters, no
part of it SHALL reach a shell unquoted.

**check:** `actionlint` — noting that it provably does **not** catch D7's class, so additionally
assert by grep that no `${{ github.ref_name }}` or `${{ needs.*.outputs.* }}` appears inside any
`run:` body; every mapping-table step present at its target job, verified by name.

---

## T-3 — dry run on the real repository

**files:** none (verification)

**what:** Requires T-0 merged. Dispatch this branch's workflow for `youtube-transcript` (bundle
present — `pack` must run) and for `maven-mcp` (no bundle — `pack` must skip, not fail). Neither may
attest or publish.

This is the acceptance item the stage exists for and cannot be replaced by reading YAML.

**acceptance:** THE SYSTEM SHALL complete a dispatch green for both plugins, with `pack` run for one
and skipped for the other, and `attest`/`publish` skipped in both.

**check:** run URLs and per-job conclusions verbatim. Establish while here: whether
`download-artifact@v4` needs `actions: read`, and whether the attest action requires
`artifact-metadata: write`.

**Stated limitation, to be repeated in the report:** the dry run exercises `gate` and `pack` only.
`attest` and `publish` — the jobs holding the dangerous permissions — first execute on a real tag, by
construction (D4). The first tag after this lands is a supervised release.

---

## T-4 — guard the retired tag form

**files:** `.github/workflows/legacy-tag-guard.yml` (new)

**what:** The documented procedure was `git tag v0.9.0 && git push origin v0.9.0`. After D1 that push
triggers nothing — no run, no error — while the tag appears on GitHub and looks like a release
happened. Every prior release used this form and it is in `docs/` and history, so future sessions will
reach for it.

A minimal workflow on `push: tags: ["v*"]` that fails immediately with a message naming the new
procedure. `permissions: {}`.

**acceptance:** GIVEN a `v*` tag push, THEN a run SHALL fail visibly and its message SHALL name the
per-plugin tag form.

---

## T-5 — protect the tag namespace (D1a)

**files:** none in-repo — a repository ruleset

**what:** Verified during review: the repository has exactly one ruleset, `target: branch`. Tags in
the distribution namespace can be created, force-updated and deleted by anyone with write access, and
under D1 that tag is what consumers' `dependencies` ranges resolve to.

Create a tag ruleset over `*--v*` forbidding deletion and non-fast-forward updates.

**acceptance:** THE SYSTEM SHALL reject deletion and force-update of a `*--v*` tag.

**check:** read the ruleset back from the API; attempt a force-update of a throwaway tag matching the
pattern and record the rejection.

---

## T-6 — README install section

**files:** `README.md` (edit)

**what:** Download the `.mcpb` from the plugin's release, verify, install by double-click. Present
provenance verification as the authenticity control with the fully-qualified `--signer-workflow`
command from the plan, and `shasum -a 256 -c` as corruption detection only. State what verification
does **not** prove — it pins the workflow path, not its ref.

Link the plugin's tag namespace, not `/releases/latest`: with independent versions the newest release
may belong to the other plugin (D11).

Root `README.md` is exempt from the English rule; match the file's language.

**acceptance:** THE SYSTEM SHALL document download, verification and installation, AND SHALL
distinguish authenticity from corruption detection rather than conflating them.

---

## T-7 — publishing documentation

**files:** `CLAUDE.md`, `AGENTS.md`, `docs/PLUGIN-STANDARDS.md` (edit)

**what:** Releases are triggered by `<plugin>--v<version>`, never by a unified `v*` tag. Update the
Publishing sections in **both** instruction files, identically where they were identical. §12 gains
the release half promised in Stage 1 plus a recovery procedure written only from established
behaviour of `softprops/action-gh-release` on an existing release — establish it in T-3 or state
plainly that it is unknown. §10 gains the checklist item withheld in Stage 1: bundle job green for the
release commit, and a green dispatch dry run before the first tag under a changed workflow.

Record the ancestry check honestly: it guards against maintainer accident, not against a party with
push access, because the workflow that runs is the one at the tagged commit.

**check:** `diff` the Publishing sections of both files; `bash scripts/validate.sh`.

---

## T-8 — reproducibility, measured

**files:** `docs/PLUGIN-STANDARDS.md` (edit)

**what:** `mcpb pack` embeds mtimes. Establish by running whether `SOURCE_DATE_EPOCH` or post-pack
normalisation yields byte-identical rebuilds. Record the answer either way, with the command; if it
does not, state what the checksum is therefore for.

**acceptance:** THE SYSTEM SHALL record a measured answer with its command.

---
type: plan
slug: youtube-transcript-mcpb-stage2
status: approved
stage: 2 of 2
predecessor: docs/plans/youtube-transcript-mcpb-bundle/plan.md
---

# Stage 2 — release wiring for the MCPB bundle

Stage 1 built and verified the bundle; it reaches nobody. This stage delivers it to users, proves
where it came from, and moves the release trigger to per-plugin tags.

## Why this stage was deferred, and what changed

Stage 1 stopped short of `release.yml` because that path cannot be exercised before a tag is
pushed. Three review cycles each found a fresh critical defect in a blind restructure. On
2026-08-03 the point was made empirically: the `v0.1.0` release run failed at its last step —
`git fetch --tags` was rejected with `would clobber existing tag`, because `actions/checkout`
leaves a *lightweight* local tag while the pushed tag was *annotated*. Validation, both test
suites and the GitHub Release all succeeded; only `youtube-transcript--v0.1.0` was lost, and it
was created by hand. Fixed in `9ea164a` with `--force`.

That failure is the argument for this stage's central acceptance item: **a green
`workflow_dispatch` dry-run is required before any tag is pushed.**

## Decisions

**D1 — the release trigger becomes the per-plugin tag.** `youtube-transcript--v0.2.0`,
`maven-mcp--v0.28.0`. Chosen by the user on 2026-08-03.

Consequence, and the reason it is worth the churn: the step that creates per-plugin tags from a
unified one **disappears entirely**, and with it the whole class of failure observed today. The
tag a human pushes *is* the tag Claude Code resolves `dependencies` ranges through. No derived
tags, no recursion question about workflow-created tags, no fetch of remote tag state.

The unified `v*` trigger is removed rather than kept alongside: two live paths through release
infrastructure is exactly the ambiguity this stage exists to remove. Historical `v*` tags stay as
history.

**D2 — attestation is minted before publication, not after.** The handoff left this open. Publishing
first leaves a window in which users can download an asset whose provenance cannot yet be checked;
attesting first risks an orphan attestation over bytes nobody received. An unusable attestation is
harmless, an unverifiable download is not.

**D3 — `pack` and `attest` are conditional on the released plugin actually having a bundle.**
`maven-mcp` has none. The condition is data-driven — the presence of
`plugins/<plugin>/mcpb/manifest.template.json` — never a hardcoded plugin name, so adding a bundle
to another plugin needs no workflow edit.

**D4 — the release gate keeps running *every* plugin's test suite.** Inherited from `release.yml:55-57`
and deliberately preserved: a tag ships one commit of the whole repo, so a break in any plugin is a
break in what the release publishes.

**D5 — `defaults.run.working-directory: plugins/maven-mcp` is dropped.** It already required two
explanatory comment blocks about paths double-resolving (`release.yml:48-50`, `:58-61`). With the
workflow no longer maven-mcp-shaped, it is a trap with no remaining beneficiary.

**D6 — `make_latest: true` is kept, with an explicit release `name:`.** With independent versions
"latest" now flips between plugins, which is factually correct but reads oddly; naming the release
`<plugin> <version>` removes the ambiguity where a reader actually looks.

## Design

### Trigger

```yaml
on:
  push:
    tags: ["*--v*"]
  workflow_dispatch:
    inputs:
      plugin:   { type: choice, options: [youtube-transcript, maven-mcp] }
      dry_run:  { type: boolean, default: true }
```

`gate` parses `github.ref_name` into `plugin` and `version` and exposes both as job outputs. A tag
that does not parse, or names a plugin absent from `marketplace.json`, is a hard error — it would
otherwise release nothing while reporting success.

On `workflow_dispatch` there is no tag: the ancestry check and the tag↔version equality check are
skipped, everything else runs. That is the dry run, and it is what makes this workflow falsifiable.

### Jobs

| Job | Runs | Permissions |
|---|---|---|
| `gate` | always | `contents: read` |
| `pack` | plugin has a bundle | `contents: read` |
| `attest` | after `pack`, not on dry run | `contents: read`, `id-token: write`, `attestations: write` |
| `publish` | after `attest`, not on dry run | `contents: write` |

Workflow level declares `permissions: {}`. This is the construct that fails closed: with no
workflow-level block a job omitting `permissions:` inherits the repository default, which may be
read-write. Job-level permissions **replace** rather than extend, so `attest` must restate
`contents: read` or `actions/checkout` breaks. Whether `download-artifact@v4` additionally needs
`actions: read` must be established by running it, not assumed.

**Ordering rule:** nothing builds, checksums, attests or publishes before the ancestry check *and*
`--check-tag` have both passed in `gate`. The ancestry check refuses to release an unreviewed branch
commit; downstream of `pack` it would mean attesting bytes from an arbitrary commit.

### Step→job mapping

Every one of the eight existing steps is placed explicitly. Nothing may be dropped silently — the
last review cycle of Stage 1 caught exactly that, two vanished `Run Python tests` steps.

| Existing step | Target |
|---|---|
| `actions/checkout` (`:21-23`) | `gate`, `pack` (both need a tree) |
| Verify tag reachable from `main` (`:25-34`) | `gate`, skipped on dispatch |
| `validate.sh --check-tag` (`:36-38`) | `gate`, skipped on dispatch |
| `Setup Python 3.9` (`:43-46`) | `gate` |
| `Run Python tests` (`:51-53`) | `gate` |
| `Run Python tests (youtube-transcript)` (`:62-64`) | `gate` |
| `Create GitHub Release` (`:66-70`) | `publish` |
| Publish per-plugin tags (`:72-110`) | **deleted** — D1 makes it unnecessary |

### `validate.sh --check-tag`

Currently takes a bare version and validates whichever plugins sit at it. With a per-plugin tag the
released plugin is *named*, so the check must assert that plugin specifically — otherwise a tag
naming one plugin could pass on another's version coincidence.

Extend it to accept the per-plugin form (`--check-tag youtube-transcript--v0.1.0`) alongside the
existing bare-version form, which stays for humans and docs. Unknown plugin name, unparseable tag,
or a version mismatch on the named plugin are each errors.

### Bundle hand-off between jobs

- Explicit `name:` on both `upload-artifact` and `download-artifact`; never rely on
  least-common-ancestor path stripping.
- `pack` publishes its checksum as a **job output**, so `publish` verifies against a value that did
  not travel with the bytes it checks.
- `pack` calls `bash scripts/pack-mcpb.sh --expect-version "<version from tag>"` — the flag exists
  in Stage 1 solely for this — then `bash scripts/smoke-mcpb.sh --require-checksum "$MCPB_PATH"`.
  `--require-checksum` is mandatory: without it a missing `.sha256` skips assertion 5 silently,
  which is fail-open against a `download-artifact` result.
- `smoke-mcpb.sh` reads the git index, so any job running it needs a checkout at the same commit. It
  is not runnable against a bare downloaded artifact.

### Authenticity

The `.sha256` detects transport corruption only: both files come out of the same job and travel
together, so anyone able to write to releases replaces both. Authenticity comes from
`actions/attest-build-provenance`, verified by the user with:

```
gh attestation verify youtube-transcript-<version>.mcpb \
  --repo kirich1409/krozov-ai-tools \
  --signer-workflow kirich1409/krozov-ai-tools/.github/workflows/release.yml
```

`--signer-workflow` fully qualified is load-bearing: `--repo` alone accepts an attestation minted by
any workflow in the repository. The README must present provenance as the authenticity control and
`shasum -c` as corruption detection, not as proof of origin.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| The restructure cannot be verified by a tag push without publishing something | high | The dispatch dry run is a required acceptance item, run before merge |
| `softprops/action-gh-release` behaviour on an existing release is unknown | medium | Establish by running it; document recovery only after the answer is known, never from assumption |
| Bundle bytes are not reproducible (`mcpb pack` embeds mtimes) | minor | Evaluate `SOURCE_DATE_EPOCH` or post-pack normalisation before deciding the checksum's role; do not claim reproducibility |
| Switching the trigger breaks the release habit for `maven-mcp` | medium | Both `CLAUDE.md` and `AGENTS.md` Publishing sections updated in the same change; user chose this explicitly |
| Attestation permissions are easy to get subtly wrong | medium | Job-level permissions restate `contents: read`; `actions: read` need established by running |

## Out of scope

Code signing and certificate acquisition; submission to the Anthropic extensions directory; an MCPB
bundle for `maven-mcp`; Windows support; any change under `plugins/*/plugin/server/**`.

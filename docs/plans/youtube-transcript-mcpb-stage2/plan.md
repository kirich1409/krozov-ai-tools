---
type: plan
slug: youtube-transcript-mcpb-stage2
status: approved
stage: 2 of 2
revision: 2
predecessor: docs/plans/youtube-transcript-mcpb-bundle/plan.md
review_panel: [devops-expert, security-expert]
review_verdict: BLOCK on revision 1 — 40 findings, 6 blocking; all incorporated here
---

# Stage 2 — release wiring for the MCPB bundle

Stage 1 built and verified the bundle; it reaches nobody. This stage delivers it to users, proves
where it came from, and moves the release trigger to per-plugin tags.

## Why this stage was deferred, and what changed

Stage 1 stopped short of `release.yml` because that path cannot be exercised before a tag is pushed.
On 2026-08-03 the point was made empirically: the `v0.1.0` release run failed at its last step —
`git fetch --tags` rejected with `would clobber existing tag`, because `actions/checkout` leaves a
*lightweight* local tag while the pushed tag was *annotated*. Validation, both test suites and the
GitHub Release succeeded; only `youtube-transcript--v0.1.0` was lost, and it was created by hand.
Fixed in `9ea164a`.

Revision 1 of this plan was reviewed by devops and security panels in parallel and returned **BLOCK
from both** — 40 findings, 6 blocking. The findings are incorporated below. Two are worth stating up
front because they shaped the design rather than patching it:

- **The panels' blockers interact.** The obvious repair for "publication is skipped entirely for a
  bundle-less plugin" is `if: always()` / `!cancelled()` — which is precisely the fail-open form that
  publishes after a *failed* attestation. A one-sided fix for either makes the other worse. D2 below
  states the condition that closes both, and it must be adopted whole.
- **The stated verification could not have caught the worst defect.** Revision 1 named `actionlint`
  as T-2's check. Measured during review: `actionlint` does **not** flag `github.ref_name`
  interpolated into `run:`, while flagging `github.event.issue.title` in the identical position. And
  `git check-ref-format` accepts tag names containing command substitution, `;`, `&&`, `|` and
  quotes. A plan that parses the tag name into shell therefore needs D8's controls, not a linter.

## Decisions

**D1 — the release trigger is the per-plugin tag.** `youtube-transcript--v0.2.0`,
`maven-mcp--v0.28.0`. Chosen by the user. The step that derived per-plugin tags from a unified one
disappears, and with it the failure class observed on 2026-08-03. The unified `v*` trigger is
removed rather than kept alongside; historical `v*` tags remain as history.

**D1a — the per-plugin tag namespace must be protected by a repository ruleset.** Verified against
the live repository: exactly one ruleset exists, `target: branch` over `~DEFAULT_BRANCH`. **No tag
ruleset exists**, so tags in the distribution namespace can be created, force-updated and deleted by
anyone with write access. Under D1 that tag *is* the release trigger and *is* what Claude Code
resolves `dependencies` ranges through, so moving it silently substitutes what consumers receive for
an already-published version, with no version change and nothing visible on the release page.

Required: a tag ruleset over `*--v*` forbidding deletion and non-fast-forward updates. This is a
repository setting, not a workflow change — it is a task in this plan, and the release procedure is
not complete without it.

Related limit, stated because revision 1 implied otherwise: **the workflow that gates a tag push is
the workflow at the tagged commit.** A tag placed on a commit whose `release.yml` lacks the ancestry
check runs that file. The ancestry check guards against maintainer accident, not against a party with
push access. It is not a security boundary and must not be described as one.

**D2 — `publish` runs for every released plugin, and its condition is explicit.** Both panels found
this underspecified from opposite ends. The condition must be, verbatim in shape:

```yaml
if: >-
  ${{ !cancelled()
      && github.event_name == 'push'
      && needs.gate.result == 'success'
      && needs.pack.result != 'failure'
      && needs.attest.result != 'failure' }}
```

`!cancelled()` is what stops a *skipped* `pack`/`attest` from skipping `publish` — that is the
bundle-less plugin's release, which revision 1 deleted by omission. The two `!= 'failure'` clauses
are what stop a *failed* `attest` from publishing an unattested asset. Neither half may be adopted
alone. Asset attachment is separately conditional on `needs.gate.outputs.has_bundle`.

**D3 — attestation is minted before publication.** Publishing first leaves a window in which users
download an asset whose provenance cannot yet be checked; attesting first risks an attestation over
bytes nobody received. An unusable attestation is harmless; an unverifiable download is not.

**D4 — `workflow_dispatch` is *always* a dry run.** Revision 1 exposed a `dry_run` boolean; setting
it false would have attested and published from an arbitrary unreviewed branch with `id-token: write`
and `contents: write`, bypassing the ancestry check whose entire purpose is refusing exactly that.
The input is removed. `attest` and `publish` gate on `github.event_name == 'push'`. There is no
stated use case for publishing by hand, so nothing is lost and the escape hatch cannot be forged.

This also makes D5 safe by construction.

**D5 — the dispatch trigger lands on `main` first, as its own preparatory change.** GitHub offers
`workflow_dispatch` only for a workflow whose **default-branch** copy declares it; dispatching a
feature branch otherwise fails. Sequence: (a) a small PR adds the always-dry-run dispatch trigger to
`release.yml` on `main` with no other behaviour change; (b) the restructure branch is then
dispatchable and its dry run is a genuine pre-merge gate. Under D4 step (a) cannot publish anything.

**D6 — plugin and version never come from parsing a ref outside a tag push.** On `push`, `gate`
parses `github.ref_name` under D8's controls. On `workflow_dispatch`, `plugin` is the enumerated
`choice` input and `version` is read from `marketplace.json` for that plugin, with an empty result a
hard error. Revision 1 parsed `github.ref_name` unconditionally, which on dispatch is the *branch*
name — every dry run would have been red, and the two obvious repairs pull opposite ways: a strict
parse fails every dispatch, a lax one feeds branch names into the shell.

**D7 — the tag parse is an anchored allowlist and its results reach the shell only through `env:`.**
`^([a-z0-9-]+)--v([0-9]+\.[0-9]+\.[0-9]+)$`, anchored, with the plugin name additionally required to
exist in `marketplace.json`. Never a prefix/suffix strip. Values are passed as `env:` variables and
referenced as `"$VAR"`; never interpolated as `${{ }}` into script text, because Actions substitutes
into the script *text* before bash sees it, so author-side quoting cannot help. `actionlint` is
structurally incapable of catching a violation here, so T-2's check asserts the shape of the workflow
directly.

**D8 — `pack` and `attest` are conditional on the released plugin having a bundle**, expressed as the
presence of `plugins/<plugin>/mcpb/manifest.template.json`. Revision 1 claimed this made the workflow
generic; both panels found the claim false one layer down — `scripts/pack-mcpb.sh` hardcodes the
plugin's paths. The claim is withdrawn: the *workflow* needs no edit for a second bundled plugin, the
*scripts* do. Say so rather than implying otherwise.

**D9 — `attest` does not sign bytes it has not verified.** Revision 1 had `attest` download the
artifact and sign it. Either it verifies the checksum against `pack`'s job output before signing, or
— preferred — `attest` runs inside `pack` where the bytes were produced, removing the transfer from
the trust path entirely.

**D10 — `defaults.run.working-directory: plugins/maven-mcp` is dropped.** It already required two
comment blocks about paths double-resolving. With the workflow no longer maven-mcp-shaped it is a
trap with no beneficiary.

**D11 — `make_latest` is not left at `true` unexamined.** With independent versions, "latest" flips
between plugins, and a README pointing at "the latest release" would hand a `maven-mcp` release to
someone looking for the bundle. The release gets an explicit `name: <plugin> <version>` and the
README links the plugin's tag namespace, not `/releases/latest`.

## Design

### Trigger

```yaml
on:
  push:
    tags: ["*--v*"]
  workflow_dispatch:
    inputs:
      plugin: { type: choice, options: [youtube-transcript, maven-mcp] }
```

No `dry_run` input (D4). Dispatch never attests and never publishes.

A `concurrency` group keyed on the resolved `<plugin>--<version>` with `cancel-in-progress: false`,
so two pushes cannot race to publish the same release.

### Jobs

| Job | Condition | Permissions |
|---|---|---|
| `gate` | always | `contents: read` |
| `pack` | `needs.gate.outputs.has_bundle == 'true'` | `contents: read` |
| `attest` | as `pack`, plus `github.event_name == 'push'` | `contents: read`, `id-token: write`, `attestations: write`, and `artifact-metadata: write` if the action requires it — establish by running, do not assume |
| `publish` | D2's condition verbatim | `contents: write` |

Workflow level declares `permissions: {}`. Job-level permissions **replace** rather than extend, so
`attest` must restate `contents: read` or `actions/checkout` breaks. Whether `download-artifact@v4`
needs `actions: read` is established by running it.

Every job carries `timeout-minutes` and `persist-credentials: false` on checkout where no push is
performed — `pack` runs third-party npm code and has no reason to hold a credential.

### Step→job mapping

All eight existing steps, plus the toolchain steps revision 1 omitted. Nothing may vanish silently —
Stage 1's last review cycle caught exactly that.

| Step | Target |
|---|---|
| `actions/checkout` (`:21-23`) | `gate`, `pack` |
| Verify tag reachable from `main` (`:25-34`) | `gate`, push events only |
| `validate.sh --check-tag` (`:36-38`) | `gate`, push events only |
| **plain `validate.sh`** (no tag) | `gate`, **all** events — dispatch must not skip validation wholesale, only the tag-specific check |
| `Setup Python 3.9` (`:43-46`) | `gate` |
| `Run Python tests` (`:51-53`) | `gate` |
| `Run Python tests (youtube-transcript)` (`:62-64`) | `gate` |
| `Create GitHub Release` (`:66-70`) | `publish`, **with `files:`** |
| Publish per-plugin tags (`:72-110`) | deleted (D1) |
| **`actions/setup-node`, `npm ci --ignore-scripts`, the npm audit gate** — from `ci.yml`'s `youtube-transcript-mcpb` job | `pack`; these are the supply-chain controls, and omitting them from the mapping is how they get lost |
| **`actions/setup-python`** | `pack` — the smoke test launches the bundle's server; pin it rather than inheriting the runner default |

### `publish`

Downloads `pack`'s artifact by explicit `name:`, verifies its SHA-256 against `needs.pack.outputs.sha256`
**before** the release step, then passes both files to `softprops/action-gh-release` via `files:`
(`<name>.mcpb`, `<name>.mcpb.sha256`) with explicit `tag_name` and `name: <plugin> <version>`. Assets
are attached only when `has_bundle`.

Revision 1 never said the release attaches anything: a faithful implementation would have produced a
release with generated notes and no bundle — the one thing this stage exists to deliver.

`generate_release_notes: true` has no sane baseline once two tag namespaces interleave; establish what
it produces on the first release and replace it with an explicit body if the result is wrong.

### `validate.sh --check-tag`

With a per-plugin tag the released plugin is *named*, so validation must assert that plugin
specifically — otherwise a tag naming one plugin passes on another's version coincidence. The
bare-version form stays for humans and docs.

### Authenticity

The `.sha256` detects transport corruption only: both files leave the same job together, so anyone
able to write to releases replaces both. Authenticity comes from build provenance, verified with:

```
gh attestation verify youtube-transcript-<version>.mcpb \
  --repo kirich1409/krozov-ai-tools \
  --signer-workflow kirich1409/krozov-ai-tools/.github/workflows/release.yml
```

`--signer-workflow` fully qualified is load-bearing: `--repo` alone accepts an attestation minted by
any workflow in the repository. It pins the workflow's *path*, not its ref — `gh attestation verify`
also offers `--source-ref`/`--source-digest`, and the README must state what the check does and does
not prove rather than presenting it as a blanket guarantee.

`actions/attest-build-provenance` is now a wrapper over `actions/attest`; check current upstream
guidance before pinning.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| The privileged half (`attest`, `publish`) is never exercised by a dry run and first executes on a real tag | high | Accepted and stated, not hidden: D4 makes it structurally impossible to dry-run them. The first tag after this lands is treated as a supervised release |
| A one-sided fix to D2's condition reintroduces one of the two blockers | high | D2 is adopted whole, and both directions get an explicit acceptance case |
| Tag namespace is unprotected | high | D1a — a ruleset task in this plan, not an afterthought |
| `softprops/action-gh-release` behaviour on an existing release is unknown | medium | Establish by running; document recovery only after the answer is known |
| Bundle bytes are not reproducible (`mcpb pack` embeds mtimes) | minor | Measure whether `SOURCE_DATE_EPOCH` helps; record the answer either way and never imply reproducibility |
| The old `git tag v0.9.0 && git push` becomes a silent no-op | medium | A guard workflow on `v*` that fails loudly with the new procedure |

## Out of scope

Code signing and certificate acquisition; submission to the Anthropic extensions directory; an MCPB
bundle for `maven-mcp`; Windows support; any change under `plugins/*/plugin/server/**`.

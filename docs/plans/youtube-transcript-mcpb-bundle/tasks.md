# Tasks: MCPB bundle — Stage 1 (build + CI)

Read `plan.md` first. Its *Spike facts* section is the authoritative copy of the research, which is untracked (`.gitignore:23`).

Repo-wide constraints for every task:

- Never modify `plugins/youtube-transcript/plugin/server/**`.
- Never modify `scripts/validate.sh` or `.github/workflows/release.yml` — the latter is Stage 2.
- Shipped prose and the bundle manifest are English (`CLAUDE.md:12`); `docs/**` is exempt and stays Russian.
- Do not touch `maven-mcp`.
- Shell: `set -euo pipefail` everywhere — **including inside every workflow `run:` block**, because GitHub Actions defaults to `bash -e` with no `pipefail`, so a failing `jq` in `jq … | sort > out` is masked by `sort`'s exit 0 (`ci.yml:274` already sets it in a sibling job).
- **Never** write a guard or an acceptance check as `! cmd` / `! cmd | grep -q .` — verified: bash exempts `!`-inverted commands from `set -e`, so such a check passes even when the thing it tests is broken. Write an explicit failing branch instead:
  ```
  if cmd_that_must_fail; then echo "FAIL: <what was not detected>"; exit 1; fi
  ```
  This applies to the `check` blocks below as much as to the scripts — an earlier revision of this file stated the rule and then violated it three times.

---

## T-1: Bundle manifest template

**files:** `plugins/youtube-transcript/mcpb/manifest.template.json` (new)

**interface:** produces JSON with every MCPB v0.4 field except `version`.

**what:** Identity fields copy `plugins/youtube-transcript/plugin/.claude-plugin/plugin.json` verbatim (`name`, `description`, `author.name`, `homepage`, `license`, `keywords`); `repository` is an object in MCPB (`{"type": "git", "url": …}`) while `plugin.json:9` holds a string — convert it. No `category` (marketplace-only).

Required beyond identity:

```json
"manifest_version": "0.4",
"server": {
  "type": "python",
  "entry_point": "server/server.py",
  "mcp_config": {
    "command": "python3",
    "args": ["${__dirname}/server/server.py"]
  }
},
"compatibility": {
  "platforms": ["darwin", "linux"],
  "runtimes": { "python": ">=3.9" }
}
```

`platforms` excludes `win32` deliberately (spike was macOS-only; `python3` on Windows typically hits the Store alias stub).

Populate `tools` with `list_transcript_tracks` and `get_transcript` plus one-line descriptions.

Note where these fields are *enforced*: T-4 asserts all of them against the **packed** manifest on every PR, because that is the artifact users receive. This task's own check is a fast local sanity pass, not the gate — `mcpb validate` checks schema shape only and accepts `0.3` as readily as `0.4`.

**acceptance:** THE SYSTEM SHALL declare `manifest_version: "0.4"`, omit `version`, declare exactly `["darwin","linux"]`, list both tool names, and declare `entry_point`/`command`/`args` exactly as above.
**check:**
```
M=plugins/youtube-transcript/mcpb/manifest.template.json
jq -e '.manifest_version == "0.4"' $M
jq -e 'has("version") | not' $M
jq -e '.compatibility.platforms == ["darwin","linux"]' $M
jq -e '[.tools[].name] | sort == ["get_transcript","list_transcript_tracks"]' $M
jq -e '.server.entry_point == "server/server.py"' $M
jq -e '.server.mcp_config.command == "python3"' $M
jq -e '.server.mcp_config.args == ["${__dirname}/server/server.py"]' $M
```

---

## T-2: Pinned toolchain, audit gate seed, update channel

**files:** `tools/mcpb/package.json`, `tools/mcpb/package-lock.json`, `tools/mcpb/audit-allowlist.txt`, `.github/dependabot.yml` (all new), `.gitignore` (edit)

**interface:** produces a lockfile-pinned `@anthropic-ai/mcpb@2.1.2`, installable with `npm ci --ignore-scripts` under `working-directory: tools/mcpb`, executable at `tools/mcpb/node_modules/.bin/mcpb`.

**what:** `package.json`: one dependency, `@anthropic-ai/mcpb` at exactly `2.1.2` (no caret), `"private": true`, no `scripts` block. Generate the lockfile with `npm install --package-lock-only --ignore-scripts`. (Verified: the package declares no `engines`, so Node 22 is unconstrained — no conditional to resolve.)

`.gitignore:17` ignores `package-lock.json` globally — add `!tools/mcpb/package-lock.json` **after** that line; verify with `git check-ignore`, not by reading the file (verified: it currently exits 0 on that path, so the negation is genuinely required).

`.github/dependabot.yml`: `package-ecosystem: npm`, `directory: /tools/mcpb`, weekly. Verified absent today — create it.

**`audit-allowlist.txt` is generated, not transcribed.** Run the extraction the gate itself uses and seed the file from its output:

```
(cd tools/mcpb && npm audit --json > /tmp/audit.json || true)
jq -r '[.vulnerabilities[].via[]? | select(type=="object")
        | select(.severity=="high" or .severity=="critical")
        | .url | split("/")[-1]] | unique[]' /tmp/audit.json
```

Write each returned id on its own line with its severity and a reachability argument. Do **not** copy an id out of `plan.md` or from memory: an earlier revision hardcoded one that turned out to be a `low` advisory while the actual `high` was missing, which would have made the gate red on its first CI run behind a green task check. Known at planning time: the `high` on `tmp` is a path-traversal advisory, and the symlink-`dir` advisory frequently cited alongside it is a `low` — but confirm both from the command above rather than trusting this sentence.

Three mechanics the gate implementation (T-5) depends on, all verified: `--audit-level` changes only the exit code, not the JSON, so severity filtering happens in `jq`; propagated records carry `via: ["<package>"]` with no id, which is why the filter selects only object-typed entries; and `npm audit` exits non-zero when anything at the threshold exists, so the invocation needs `|| true` before the report is evaluated.

**acceptance:** GIVEN a clean checkout, WHEN `npm ci --ignore-scripts` runs in `tools/mcpb`, THEN it SHALL exit 0 and yield a working `mcpb 2.1.2`; the lockfile SHALL be tracked; the allowlist SHALL contain exactly the ids the extraction above returns, each with a severity and rationale; AND Dependabot SHALL be configured for that directory.
**check:**
```
set -euo pipefail
if git check-ignore -q tools/mcpb/package-lock.json; then echo "FAIL: lockfile still ignored"; exit 1; fi
jq -e '.dependencies["@anthropic-ai/mcpb"] == "2.1.2" and .private == true' tools/mcpb/package.json
grep -q '/tools/mcpb' .github/dependabot.yml
(cd tools/mcpb && npm ci --ignore-scripts && ./node_modules/.bin/mcpb --version | grep -q '2\.1\.2')
# allowlist matches the extraction exactly — regenerate the report here rather than
# reusing a /tmp file from an earlier step, and extract before sorting (sorting whole
# lines first would order by the rationale prose, not by id)
(cd tools/mcpb && npm audit --json > /tmp/audit-check.json || true)
jq -e 'has("vulnerabilities")' /tmp/audit-check.json > /dev/null
diff <(grep -o 'GHSA-[a-z0-9-]*' tools/mcpb/audit-allowlist.txt | sort -u) \
     <(jq -r '[.vulnerabilities[].via[]? | select(type=="object") | select(.severity=="high" or .severity=="critical") | .url | split("/")[-1]] | unique[]' /tmp/audit-check.json | sort -u)
```

---

## T-3: Pack script

**files:** `scripts/pack-mcpb.sh` (new)
**after:** T-1, T-2

**interface:**
- consumes: template (T-1), `plugin.json` (`.version`), the tracked server tree, repo-root `LICENSE.md`, CLI (T-2).
- accepts: optional `--expect-version <v>` and `--stage-dir <path>`.
- produces: `dist/youtube-transcript-<version>.mcpb` + `.mcpb.sha256`. Writes `mcpb_path`/`mcpb_sha256_path` to `$GITHUB_OUTPUT` when set; prints both paths otherwise.

**what:** Bash, `set -euo pipefail`, executable.

1. `cd "$(git rev-parse --show-toplevel)"`; fail with a named error if `plugins/youtube-transcript/plugin/.claude-plugin/plugin.json` is absent. Do not assume cwd — `release.yml:11-13` sets a job-level `working-directory` and carries two comments (`:48-50`, `:55-60`) about paths double-resolving from this trap.
2. Read `VERSION` via `jq -r '.version'`; fail if empty or not semver.
3. `--expect-version <v>`: when given and different from `VERSION`, fail naming both.
4. `mkdir -p dist`, then `rm -f dist/youtube-transcript-*.mcpb dist/youtube-transcript-*.mcpb.sha256`. `dist/` is gitignored (`.gitignore:2`) and absent on a fresh clone. Never remove all of `dist/`.
5. Staging: `--stage-dir <path>` when given (used as-is, not cleaned up — this is what makes T-4b's tampering possible through the supported interface), otherwise `mktemp -d` with a cleanup trap on EXIT.
6. **Stage from the git index.** `git ls-files -s -z -- plugins/youtube-transcript/plugin/server` read with `while IFS= read -r -d ''` (NUL-delimited, so a path with whitespace cannot be mis-split by the script that *is* the containment boundary). Keep entries whose mode is `100644` or `100755` and whose path ends in `.py`; copy each with **`cp -P`** preserving its path relative to `plugin/server/` into `<staging>/server/`. Fail with a named error if any tracked `.py` under that path has another mode — `cp` dereferences symlinks, so a tracked `*.py` symlink (mode `120000`) would copy foreign content in as a regular file and satisfy every name-based check downstream.
7. Fail if the tracked set under `plugin/server/` contains any non-`.py` file. Staging keeps only `.py`, so such a file would be silently dropped from a bundle that still passes every check; making it loud is the point.
8. `LICENSE.md` goes through the **same** gate, not a bare `cp`: assert `git ls-files -s -- LICENSE.md` reports mode `100644`, then `cp -P "$ROOT/LICENSE.md" "$STAGE/LICENSE.md"`. It is the one staged file outside the server tree, and an unchecked copy of a symlinked licence places foreign bytes in the bundle as a regular file — invisible to step 10.
9. Assert `manifest.template.json` is not a symlink (`[ ! -L … ]`) before reading it, then write `<staging>/manifest.json` = template with version injected: `jq --arg v "$VERSION" '. + {version: $v}'`. Run `mcpb validate <staging>/manifest.json`.
10. Assert nothing irregular was staged, as a **capture-and-test**:
    ```
    BAD=$(find "$STAGE" -mindepth 1 \( -type l -o \( ! -type f -a ! -type d \) \) -print)
    [ -z "$BAD" ] || { echo "::error::non-regular entry staged: $BAD" >&2; exit 1; }
    ```
    Both details are load-bearing and were verified by running them: `\( ! -type f \)` alone matches every directory (7 hits on a clean tree, so the check could never pass), and `! find … | grep -q .` does not abort under `set -e` (a script with a planted symlink ran to completion and exited 0).
11. `mcpb pack <staging> dist/youtube-transcript-$VERSION.mcpb` using `tools/mcpb/node_modules/.bin/mcpb`. Never `npx`.
12. Emit the checksum **with cwd set to `dist/`** so the file holds a bare basename. Select the tool into a bash **array** — `SHA_TOOL=(shasum -a 256)` or `SHA_TOOL=(sha256sum)` — since a quoted scalar breaks on the two-word form. `smoke-mcpb.sh` repeats the same selection logic independently: pack and smoke are separate `run:` blocks in separate processes, so an `export` does not cross between them. (The two formats are interchangeable — each verifies the other's files.)
13. Export both paths per `interface`.

**acceptance:** GIVEN a clean checkout with no `dist/`, WHEN the script runs from any directory inside the repo, THEN it SHALL exit 0, create `dist/`, produce bundle and checksum, embed exactly `plugin.json`'s version, include `LICENSE.md`, write a checksum containing no `/`, and stage no symlink; AND `--expect-version` SHALL exit 0 on a match and non-zero on a mismatch naming both values.
**check:**
```
set -euo pipefail
rm -rf dist
(cd plugins/maven-mcp && bash ../../scripts/pack-mcpb.sh)      # wrong-cwd resilience + dist creation
V=$(jq -r .version plugins/youtube-transcript/plugin/.claude-plugin/plugin.json)
unzip -p "dist/youtube-transcript-$V.mcpb" manifest.json | jq -e --arg v "$V" '.version == $v'
unzip -Z1 "dist/youtube-transcript-$V.mcpb" | grep -qx 'LICENSE.md'
if grep -q '/' "dist/youtube-transcript-$V.mcpb.sha256"; then echo "FAIL: checksum holds a path, not a basename"; exit 1; fi
(cd dist && shasum -a 256 -c "youtube-transcript-$V.mcpb.sha256")
bash scripts/pack-mcpb.sh --expect-version "$V"                # positive direction must pass
if bash scripts/pack-mcpb.sh --expect-version 9.9.9; then echo "FAIL: version mismatch not detected"; exit 1; fi
shellcheck scripts/pack-mcpb.sh
```

Both `--expect-version` directions are checked deliberately: an inverted comparison passes a negative-only test and ships a gate that is green exactly when it should be red. Note the branch form — `! bash scripts/pack-mcpb.sh …` would itself be exempt from `set -e` and pass against a script that ignores the flag entirely (verified).

---

## T-4: Smoke script

**files:** `scripts/smoke-mcpb.sh` (new)
**after:** T-3

**interface:**
- consumes: a `.mcpb` path as `$1` (**required** — no default).
- requires: a git checkout at the same commit (assertion 2 reads the index).
- produces: exit 0 on all assertions passing; non-zero with a distinct named message otherwise.

**what:** The L3 evidence, in a script so it is shellcheckable, runnable locally, and reusable by Stage 2.

Unpack once with `unzip -q "$1" -d "$TMP"` and assert:

1. **Nothing foreign:** every archive entry matches `^(manifest\.json|LICENSE\.md|server/.*\.py)$`. Capture-and-test over `unzip -Z1 "$1" | grep -v '/$' | grep -vE '<pattern>'` — never `! … | grep -q .`.
2. **Nothing missing:** the `server/**.py` archive entries equal the tracked set. **Use this pathspec:**
   ```
   git ls-files -- plugins/youtube-transcript/plugin/server | grep '\.py$'
   ```
   Do **not** use `git ls-files '…/server/**/*.py'` — verified: it returns 23 of 25, dropping `server.py` and `composition.py`. Compare with `LC_ALL=C sort` on both sides. Additionally anchor by name: fail unless the archive contains `server/server.py` **and** `server/composition.py`. A count-only guard is insufficient — if pack and smoke share the same bad pathspec both sides shrink to 23 and compare equal; the anchors are exactly the two files such a pathspec drops.
3. **Manifest version equals `plugin.json`'s.**
4. **Packed `SERVER_VERSION` agrees with the manifest:** `grep -qxF "SERVER_VERSION = \"$MANIFEST_VERSION\"" "$TMP/server/server.py"`. Fixed-string, whole-line — an ERE would let the `.` in `0.27.0` match any character. **Do not** assert on `initialize`'s `result.serverInfo.version` — `protocol/dispatch.py:45-53` hardcodes `"version": "1"` deliberately.
5. **Checksum verifies:** when `<bundle>.sha256` exists, `(cd "$(dirname "$1")" && "${SHA_TOOL[@]}" -c "$(basename "$1").sha256")`, selecting the tool with the same logic as T-3. Transport integrity only — not authenticity. Accept a `--require-checksum` flag (default off) that turns a missing `.sha256` into a failure: the conditional form is right for T-4b's tampered bundles, but Stage 2 runs this against a `download-artifact` result where a silently absent checksum would be fail-open. The Stage 2 handoff records that `pack` must pass the flag.
6. **Manifest contract — deep equality on the whole `server` object**, not field-by-field:
   ```
   jq -e '.server == {"type":"python","entry_point":"server/server.py",
                      "mcp_config":{"command":"python3","args":["${__dirname}/server/server.py"]}}' <packed manifest>
   ```
   plus `manifest_version == "0.4"` and `compatibility.platforms == ["darwin","linux"]`. Equality rather than per-field checks is deliberate: the v0.4 schema (read from the CLI package's own `schemas/mcpb-manifest-v0.4.schema.json`) also allows `mcp_config.env` and `mcp_config.platform_overrides`, and an override keyed by platform replaces `command`/`args` for that platform. A field-by-field check passes a manifest carrying `platform_overrides.darwin.command: "sh"` — which is what would actually run on the user's machine. Deep equality closes `env`, `platform_overrides`, `server.type` and any field added later, at once.
7. **Handshake, driven from the manifest:** build the command from the packed manifest's `command`/`args` with `${__dirname}` substituted to `$TMP`, run it from an unrelated cwd, and send `initialize`, `notifications/initialized`, `tools/list` over stdio. Driving it from the declared values rather than a hardcoded path is what makes assertion 6 meaningful. Wrap each exchange in a deadline, failing with `handshake timed out at <step>`.
   Portability, since the plan calls this script locally runnable on macOS: stock macOS ships bash 3.2 (no `mapfile`/`readarray` — read `args` with `while IFS= read -r`) and has **no** `timeout(1)`. Use `timeout`/`gtimeout` when present, otherwise a background-read-plus-`kill` pattern; if neither is available, proceed without a deadline and print a named warning rather than failing.
8. **Manifest `tools` set equals the runtime set:** `diff` of `jq -r '.tools[].name'` from the packed manifest against the `tools/list` names, both sorted.

**Hard constraint:** declarations only. No `tools/call`, no `YOUTUBE_TRANSCRIPT_LIVE_CANARY`, no network egress — this runs on fork PRs.

**acceptance:** GIVEN a bundle from T-3, WHEN `bash scripts/smoke-mcpb.sh <bundle>` runs, THEN all eight assertions SHALL pass.
**check:** exits 0 on a real build; `shellcheck scripts/smoke-mcpb.sh`. Proof that the assertions can fail is T-4b — not a human's judgment here.

---

## T-4b: Negative tests

**files:** `scripts/tests/test-smoke-negatives.sh` (new)
**after:** T-4

**what:** Executable proof that the fail-closed checks go red. Without it they are verified on the happy path only, and a subtly inverted check ships green — the failure mode that produced two blockers in earlier revisions of this plan.

**How tampering works, stated explicitly** — `pack-mcpb.sh` regenerates what it stages (step 6 re-copies every tracked `.py` from the index; step 9 rewrites `manifest.json` from the template), so re-running it would undo most tampers:

- Populate the staging tree **once** with `bash scripts/pack-mcpb.sh --stage-dir "$S"`.
- For every *mutative or subtractive* case below, tamper `$S` and then pack directly: `tools/mcpb/node_modules/.bin/mcpb pack "$S" "$OUT"`. Do **not** re-invoke `pack-mcpb.sh`.
- Only the staged-symlink case re-invokes `pack-mcpb.sh --stage-dir "$S"`, because it is T-3's own guard under test rather than the smoke script's (`mkdir -p "$S/server"` first if starting from an empty dir).

Assert each is rejected **with its own message** (grep the message, so a failure for the wrong reason does not count):

| Case | Tamper | Must fail |
|---|---|---|
| foreign file | `touch "$S/server/EXTRA.txt"` | assertion 1 |
| missing module | delete one staged `.py` | assertion 2 |
| version skew | `jq '.version = "9.9.9"'` on the staged manifest | assertion 3 |
| server-side skew | edit only `"$S/server/server.py"`'s `SERVER_VERSION` line | assertion 4, isolated from 3 |
| corrupt checksum | flip a byte in the `.sha256` | assertion 5 |
| altered command | `jq '.server.mcp_config.command = "sh"'` | assertion 6 |
| platform override | `jq '.server.mcp_config.platform_overrides = {"darwin":{"command":"sh"}}'` | assertion 6 — proves deep equality, which a field-by-field check would miss |
| undisclosed tool | `jq '.tools += [{"name":"ghost","description":"x"}]'` | assertion 8 |
| staged symlink | `ln -sf /etc/passwd "$S/server/evil.py"`, then `pack-mcpb.sh --stage-dir "$S"` | T-3 step 10 |

The version-skew and server-side-skew cases are separate deliberately: under `set -e` the script exits at assertion 3, so a combined case would never exercise assertion 4 — the mitigation for a risk this plan rates major.

Assertion 7's timeout path is not covered: simulating a hung server is disproportionate here. `plan.md`'s risk row says so explicitly rather than implying full coverage.

Bash, `set -euo pipefail`, executable, shellcheck-clean.

**acceptance:** THE SYSTEM SHALL exit 0 only when every case above is rejected by its own named assertion.
**check:** `bash scripts/tests/test-smoke-negatives.sh` exits 0; `shellcheck scripts/tests/test-smoke-negatives.sh`.

---

## T-5: CI job

**files:** `.github/workflows/ci.yml` (edit)
**after:** T-4b

**what:** Add job `youtube-transcript-mcpb`, following the four sibling `youtube-transcript-*` jobs (`ci.yml:255-449`): always runs (so it can be a required check), a `Detect changes` step sets a `GITHUB_OUTPUT` flag from `git diff --name-only "$BASE_SHA...$HEAD_SHA"`, heavy steps gated on it.

Required explicitly:

- `fetch-depth: 0` on checkout — needed by the three-dot diff, which fails at depth 1. (Not needed by `git ls-files`, which reads the index — do not restate that as a reason.)
- `timeout-minutes: 10`, matching `:257, 309, 356, 404`.
- Watched paths: `plugins/youtube-transcript/**`, `scripts/pack-mcpb.sh`, `scripts/smoke-mcpb.sh`, `scripts/tests/test-smoke-negatives.sh`, `tools/mcpb/**`, `.github/workflows/ci.yml`, `LICENSE.md`.
- `if: steps.changes.outputs.<flag> == 'true'` on **each** of: setup-node, setup-python, `npm ci`, audit gate, pack, smoke, negatives, upload. Only shellcheck stays ungated. Naming them individually matters: `smoke-mcpb.sh` takes a required argument, and an ungated smoke step after a skipped pack step would receive an empty string.

Steps: `actions/setup-node@v4` (no `setup-node` exists in this workflow today, so there is no in-repo precedent to copy; `@v4` matches the tag-pinning convention used for `actions/checkout@v4` and `actions/setup-python@v5`) with `node-version: "22"` and `cache: npm`, `cache-dependency-path: tools/mcpb/package-lock.json`; `actions/setup-python` at `3.9`; `npm ci --ignore-scripts` (`working-directory: tools/mcpb`); the **audit gate**; `bash scripts/pack-mcpb.sh` with `id: pack`; `bash scripts/smoke-mcpb.sh "${{ steps.pack.outputs.mcpb_path }}"`; `bash scripts/tests/test-smoke-negatives.sh`; `actions/upload-artifact@v4` with `name: mcpb-bundle`, the bundle and its `.sha256`, `retention-days: 14`, `if-no-files-found: error` (the default `warn` uploads nothing silently); ungated `shellcheck scripts/*.sh scripts/tests/*.sh`.

**Audit gate**, written out because four of its mechanics are counter-intuitive and each was verified by running it:

```yaml
- name: Audit pinned toolchain
  working-directory: tools/mcpb          # allowlist path is relative to this
  run: |
    set -euo pipefail
    npm audit --json > audit.json || true   # exits non-zero whenever findings exist
    jq -e 'has("vulnerabilities")' audit.json > /dev/null \
      || { echo "::error::npm audit produced no usable report"; exit 1; }
    jq -r '[.vulnerabilities[].via[]? | select(type=="object")
            | select(.severity=="high" or .severity=="critical")
            | .url | split("/")[-1]] | unique[]' audit.json | sort -u > found.txt
    grep -o 'GHSA-[a-z0-9-]*' audit-allowlist.txt | sort -u > allowed.txt
    UNEXPECTED=$(comm -23 found.txt allowed.txt)
    [ -z "$UNEXPECTED" ] || { echo "::error::unallowlisted advisories: $UNEXPECTED"; exit 1; }
```

The first two lines are what stop the gate failing open, and both were demonstrated: without `set -euo pipefail` a `run:` block is `bash -e` with **no** `pipefail`, so on a registry outage `jq` dies with `Cannot iterate over null`, the pipeline takes `sort`'s exit 0, `found.txt` is empty and the step reports success. The shape assertion covers the same class for empty, non-JSON and schema-changed reports.

`--audit-level` is deliberately absent: it changes only the exit code, not the JSON, so severity filtering happens in `jq`. Propagated records carry `via: ["<package>"]` with no id, which is why only object-typed entries are selected. A blanket `--audit-level=critical` would be green against today's known high and every future one.

**Known limitation, stated rather than papered over:** this gate is path-gated like the rest of the job, and the lockfile is frozen — so the case where it would newly fire (a freshly published advisory against unchanged dependencies) is exactly the case where no watched path changed. Between-PR discovery therefore depends on repository-level Dependabot **security alerts** being enabled, which `dependabot.yml` cannot express and this plan does not configure. Note it in T-6's §12 text.

The artifact `name:` is not cosmetic — Stage 2's `download-artifact` consumes it by name.

Keep workflow-level `permissions: contents: read` (`ci.yml:11-12`).

**Not automated here:** promoting `youtube-transcript-mcpb` to a required status check is a branch-ruleset change the maintainer makes (`ci.yml:93-97` records the same for existing jobs). Until then a broken bundle build does not block merge.

**acceptance:** GIVEN a PR touching any watched path, WHEN CI runs, THEN the job SHALL build, smoke-test, run the negative tests, pass the audit gate, upload `mcpb-bundle`, and shellcheck both script directories; AND GIVEN a PR touching none, it SHALL report success with every gated step skipped.
**check:** the job passes on this plan's own PR (which touches `scripts/`); its log shows both tool names from the handshake and every tampered bundle rejected; the run's artifact list contains `mcpb-bundle`. Additionally prove the audit gate can fire: temporarily empty `audit-allowlist.txt` locally, run the gate's script body, and confirm it exits non-zero.

---

## T-6: Documentation

**files:** `docs/PLUGIN-STANDARDS.md` (edit), `plugins/youtube-transcript/CLAUDE.md` (edit), `plugins/youtube-transcript/AGENTS.md` (edit)
**after:** T-5

**what:** `docs/**` is exempt from the English rule — match `PLUGIN-STANDARDS.md`'s existing Russian. The two plugin files are English.

`docs/PLUGIN-STANDARDS.md` — add **section 12** after section 11 (ends at line 158), scoped to Stage 1:

- what the bundle is; template at `plugins/youtube-transcript/mcpb/manifest.template.json`; version injected at build time and therefore **not** a fourth version location; built by `scripts/pack-mcpb.sh`, verified by `scripts/smoke-mcpb.sh`, and the verifier itself checked by `scripts/tests/test-smoke-negatives.sh`;
- that the npm toolchain is **build-time only** — it never enters the bundle (staging enumerates the git index and accepts only regular-file modes) and the plugin's runtime stays stdlib-only, so the plugin's `No pip dependencies` non-negotiable is unaffected;
- the audit gate: filtering happens in `jq` because `--audit-level` only changes the exit code; the `run:` block needs its own `set -euo pipefail` plus a report-shape assertion, since Actions defaults to `bash -e` without `pipefail` and the gate would otherwise pass silently on a registry outage; exceptions live in `tools/mcpb/audit-allowlist.txt` as reviewable diffs; regenerate the allowlist from a real run when bumping the CLI, never by hand;
- that the gate is path-gated while the lockfile is frozen, so a newly published advisory against unchanged dependencies will not trigger it — between-PR discovery relies on repository-level **Dependabot security alerts** being enabled, which `dependabot.yml` cannot express; `dependabot.yml` itself supplies version updates and is a notification channel, not a gate;
- that `mcpb pack` embeds mtimes, so two builds of identical inputs differ by SHA-256 — the bundle is not reproducible, and any future scheme comparing a CI build against a released one must account for that;
- a line stating release wiring is Stage 2 and this section will grow when it lands, so its absence is not read as an oversight.

No `§10` checklist item in Stage 1: a "bundle job green for the release commit" line would gate a release path that does not exist yet. It is recorded in the Stage 2 handoff.

`plugins/youtube-transcript/CLAUDE.md` **and** `plugins/youtube-transcript/AGENTS.md` — one identical line each, under the architecture section: the MCPB bundle ships exactly the tracked `.py` files under `plugin/server/` plus `LICENSE.md` and a generated `manifest.json`; adding a **Python module** needs no bundle-side change, but adding a **tool** requires updating `tools` in the manifest template, and adding a **non-`.py` runtime asset** requires changing the staging allowlist — the build fails loudly on the last case rather than shipping a bundle missing it. Both files are read by agents and must carry this note identically; the rest of their divergence is deliberate condensation (`AGENTS.md` cross-references `CLAUDE.md` for lint/canary commands), so do not "re-sync" anything else.

**acceptance:** THE SYSTEM SHALL document the artifact, the build-time-only boundary, the audit gate mechanics, the non-reproducibility caveat and the Stage 2 pointer in §12; AND SHALL add the module/tool/asset note to both plugin files identically.
**check:**
```
grep -n '## 12' docs/PLUGIN-STANDARDS.md
grep -Fq 'audit-allowlist.txt' docs/PLUGIN-STANDARDS.md
grep -Fq 'manifest.template.json' plugins/youtube-transcript/CLAUDE.md
grep -Fq 'manifest.template.json' plugins/youtube-transcript/AGENTS.md
diff <(grep -A3 'manifest.template.json' plugins/youtube-transcript/CLAUDE.md) \
     <(grep -A3 'manifest.template.json' plugins/youtube-transcript/AGENTS.md)
```

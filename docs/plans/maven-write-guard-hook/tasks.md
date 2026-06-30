# Tasks: maven-mcp PreToolUse write-time guard hook (#283)

> Plan: ./plan.md · One PR (branch `feat/maven-write-guard-hook`, off main@fe0d189). Baseline = 334
> tests. bash+jq hook (mirror `post-edit-deps.sh` style); no new MCP tool; no new Python deps. All
> shipped content English. Fail-open is the dominant invariant.

## T-1 — `pre-edit-deps.sh` + register in hooks.json
- after: none
- files: `plugins/maven-mcp/plugin/hooks/pre-edit-deps.sh` (new, git mode 100755), `plugins/maven-mcp/plugin/hooks/hooks.json`
- acceptance: THE SYSTEM SHALL add a `command` PreToolUse hook — explicit shebang
  `#!/usr/bin/env bash` (match `post-edit-deps.sh`; portable), **bash-3.2-safe** (macOS default
  `/bin/bash`: NO `declare -A`, `${var,,}`, `mapfile`; guard array expansions `"${a[@]:-}"`), all
  shipped strings English — that:
  - **Fail-open is structural, not `set -e`:** after `set -euo pipefail`, `trap 'exit 0' EXIT`
    immediately. The script can reach ONLY `exit 0` (allow = exit 0 no stdout; deny/ask = exit 0 +
    JSON); it must NEVER `exit 2` (the only PreToolUse block-by-exit-code). Wrap EVERY external call so
    failure → allow (`x=$(cmd) || x=""`, `g=$(grep … || true)`), INCLUDING the envelope `jq` that
    parses stdin (a malformed-stdin or empty/non-JSON python stdout must not propagate a non-zero/2).
    Assemble the decision in a variable and `printf` it ONCE at the very end after all fallible work.
  - reads stdin once; allow-exit if `jq` absent, `tool_name` ∉ {`Edit`,`Write`,`MultiEdit`}, or
    `basename(.tool_input.file_path)` ∉ {`build.gradle`,`build.gradle.kts`,`settings.gradle`,
    `settings.gradle.kts`,`pom.xml`,`libs.versions.toml`};
  - extracts candidate `groupId:artifactId[:version]` from NEW content only — `.tool_input.new_string`
    (Edit) / `.tool_input.content` (Write) / concatenated `.tool_input.edits[].new_string` (MultiEdit).
    **Recall-limited best-effort** (a miss = no guard, never a wrong block): Gradle string-notation
    `"g:a:v"`/`'g:a:v'`; TOML `[libraries]` `module="g:a"` (single line); Maven `<dependency>`/`<plugin>`
    only when the fragment has the full `<groupId>`+`<artifactId>` pair. A `version.ref` or any
    **non-literal version containing `$`** → drop the version (GA-only); resolve `version.ref` WITHOUT
    an associative array. Enforce coordinate charset `[A-Za-z0-9._-]`. De-dup; cap `MAX_COORDS=8`; zero
    coords → allow-exit (no python spawn);
  - verifies in ONE python invocation: build each request with `jq -c -n --arg` (NEVER interpolate
    file content); OMIT the `version` key for GA-only coords; pass `projectPath` only when `.cwd`
    non-empty. Send `verify_coordinates` (`id:1`, all coords) and — ONLY if ≥1 versioned coord —
    `get_dependency_vulnerabilities` (`id:2`); pipe into `<T> 8 python3 "${CLAUDE_PLUGIN_ROOT}/server/
    server.py"` where `<T>` = `timeout` → `gtimeout` → (none → allow-exit, don't risk a hung edit).
    **Scrub `GITHUB_TOKEN`** from the spawned env (`env -u GITHUB_TOKEN …` or unset). Unwrap by
    MATCHING JSON-RPC `.id` (not line order) → `.result.content[0].text|fromjson`; `.error`/missing
    `.result`/null `.text` → that tool contributed nothing (allow-side);
  - DECIDES (deny wins over ask if both): existence actionable = `existenceStatus=="absent"` AND
    (`likelyHallucination==true` OR non-empty `suggestions`) → `permissionDecision:"deny"`. Bare
    `absent` (no flag, no suggestion) → NO action (allow) — add an inline comment forbidding
    "tightening" to deny-on-bare-absent (would false-block private/androidx coords; Central-scoped by
    design). Vuln actionable = versioned coord with `CRITICAL`/`HIGH` severity → `permissionDecision:
    "ask"` (NOT deny; do not gate harder when `fixedVersion` absent). MEDIUM/LOW → no action.
  - REASON built with `jq -n --arg` from KNOWN fields only (`g:a[:v]`, `severity`, `fixedVersion`,
    suggestion `g:a`+`versionCount`) — NEVER raw network text; the embedded suggestion coordinate is
    charset-filtered `[A-Za-z0-9._-]` + length-capped before embedding; suggestions phrased as
    candidates to verify, not "replace with X"; for `Write`, name the exact offending coordinate(s). Emit the full
    envelope `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny|ask",
    "permissionDecisionReason":"…"}}`.
  - FAILS OPEN (allow, ≤1 non-fatal stderr line that never echoes env/token/file-content): missing
    `jq`/`python3`/timeout-cmd; non-zero/124 exit; empty OR garbage stdout; `.error`/missing-`.result`;
    malformed-stdin; any coord `existenceStatus=="unknown"`.
  - Register in `hooks.json`: add a `PreToolUse` array `{matcher:"Edit|Write|MultiEdit", hooks:[{type:
    "command", command:"${CLAUDE_PLUGIN_ROOT}/hooks/pre-edit-deps.sh", timeout:12}]}` alongside the
    existing PostToolUse (inner `timeout 8` < hooks.json `12` so the script wins the race). `chmod +x`.
- check: `bash -n pre-edit-deps.sh` clean; `shellcheck pre-edit-deps.sh` clean; committed git mode
  100755; `jq` validates the emitted decision JSON; `jq . hooks.json` parses and has BOTH PreToolUse +
  PostToolUse. Behavior proven by T-2.

## T-2 — `test_pre_edit_hook.py` (subprocess + recording stub server, no network)
- after: T-1
- files: `plugins/maven-mcp/tests/test_pre_edit_hook.py` (+ a stub-server written into a per-test tempdir)
- acceptance: THE SYSTEM SHALL run `pre-edit-deps.sh` as a subprocess (`subprocess.run`, stdin =
  crafted hook JSON) with `CLAUDE_PLUGIN_ROOT` → a **fixture dir whose `server/server.py` is a STUB**
  that: LOOPS over stdin to EOF (handles 1 OR 2 requests — the GA-only path sends only the verify
  line); RECORDS the `arguments` it received to a marker file (so EXTRACTION is proven and so every
  allow-case has a positive "stub-invoked" control vs a vacuous pass); emits `id`-correlated canned
  `{"jsonrpc":"2.0","id":N,"result":{"content":[{"type":"text","text":"<json>"}]}}`. Stub wiring is
  byte-identical across deny and allow cases (only the canned payload differs). Import style:
  `import unittest.mock` + fully-qualified refs (CodeQL py/import-and-import-from); no unused imports;
  every `except` carries an explanatory comment (CodeQL py/empty-except). `skipUnless` the whole module
  (clear message) when `jq` absent; `skipUnless` the timeout-expiry case when neither `timeout` nor
  `gtimeout` present. Stub must be Python-3.9-syntax-safe (CI matrix runs 3.9 + 3.13).
- check: cases (assert exit code + parsed stdout JSON + stub marker):
  - **extraction** (stub records args, test asserts the exact `dependencies`): Gradle Groovy
    `implementation 'g:a:1.0'`; Kotlin DSL `implementation("g:a:1.0")`; `pom.xml` `<dependency>`; TOML
    `lib = "g:a:1.0"`; TOML module+`version.ref` → GA-only (no version) AND **excluded from the
    `get_dependency_vulnerabilities` args**; Gradle `"g:a:$ver"`/`${…}` → GA-only (no literal `$var`
    version sent); MultiEdit `edits[].new_string` concatenated.
  - **Write `content` path** (distinct from Edit `new_string` — a broken `.content` jq path fails
    open SILENTLY, defeating half of #283): a `Write` whole-file `content` with one absent/hallucinated
    coord among several valid ones → stub received the coord via the content path AND the deny reason
    NAMES the exact offending coordinate (discharges the ARCH-3 "name exact coord" requirement).
  - **absent+hallucination/suggestion → deny**: assert FULL envelope (`hookSpecificOutput.hookEventName
    =="PreToolUse"`, `permissionDecision=="deny"`) + suggested coord present in reason (non-imperative).
  - **bare `absent` (likelyHallucination:false, empty suggestions) → ALLOW** (over-deny boundary;
    stub-invoked marker present).
  - **CRITICAL/HIGH CVE → ask** (NOT deny), fix in reason when present; CVE with no fixedVersion → still
    `ask` (not deny). **MEDIUM/LOW only → allow** (marker present).
  - **unknown → allow** (marker present). **clean (`exists`, no vuln) → allow** (marker present).
  - **fail-open** (each: exit 0, no decision JSON): stub exits non-zero; stub emits **empty** stdout;
    stub emits **garbage** stdout; stub emits a valid **JSON-RPC error** envelope (no `.result`); stub
    hangs > timeout (124); `python3` removed from PATH; `jq` removed from PATH; **malformed/non-JSON
    stdin**.
  - **non-build file** (`README.md`) → allow, stub NEVER invoked (assert marker ABSENT).
  - **GITHUB_TOKEN scrub**: set `GITHUB_TOKEN` in the subprocess env; stub records its received env →
    assert the spawned python did NOT see `GITHUB_TOKEN` (security contract).
  - **charset reject**: a coordinate token with an invalid char (e.g. a quote/space/`;`) is dropped at
    extraction (not sent to the stub / not in the request args).
  - **MAX_COORDS cap + de-dup**: content with >8 distinct coords → ≤8 sent; duplicates collapsed.
  - **multiple problems** (one absent + one CVE) → single decision aggregating both (deny wins).
  - **contract-drift guard**: feed the hook's EXACT emitted JSON-RPC line(s) into the REAL
    `server.dispatch`/handlers (with `urllib.request.urlopen` mocked, as the suite does) and assert a
    well-formed `.result.content[0].text` comes back — catches the hook speaking a stale arg contract.

## T-3 — docs + shellcheck CI gate + L5 smoke
- after: T-2
- files: `plugins/maven-mcp/README.md`, `plugins/maven-mcp/CLAUDE.md`, `.github/workflows/ci.yml`, `docs/plans/maven-write-guard-hook/progress.md`
- acceptance: THE SYSTEM SHALL (all SHIPPED content → ENGLISH; plugins/ is NOT covered by the top-level
  docs carve-out):
  - document the PreToolUse guard in README.md — what it does; triggers on the build-file allow-list;
    requires `jq`+`python3` (+`timeout`/`gtimeout`); **fail-open** when offline/rate-limited/missing-tool
    (incl. the macOS-without-coreutils no-`timeout` no-op); GITHUB_TOKEN/`MAVEN_MCP_PUBLIC_FALLBACK`
    relevance;
  - document in plugin CLAUDE.md: the hook; the structural fail-open contract; `deny` (absent/halluc)
    vs `ask` (CRITICAL/HIGH CVE); that it consumes verify_coordinates + get_dependency_vulnerabilities;
    that `unknown` never gates; and the **Maven-Central-scoped existence limitation** (do not tighten to
    deny-on-bare-`absent`);
  - add a `shellcheck plugins/maven-mcp/plugin/hooks/*.sh` step to `.github/workflows/ci.yml` (preinstalled
    on `ubuntu-latest`); it must pass for both the new hook and the existing `post-edit-deps.sh`;
  - L5 manual smoke (transcript in progress.md): hallucinated coord → deny + candidate suggestion; real
    coord → allow; stub `unknown` → allow.
- check: `bash scripts/validate.sh` rc=0; `shellcheck` step green; full suite green (334 + new);
  `python3 -m compileall` clean; L5 transcript recorded; PR open with `python-tests (3.9)/(3.13)` +
  `validate-marketplace` (+ shellcheck) green and no CodeQL threads.

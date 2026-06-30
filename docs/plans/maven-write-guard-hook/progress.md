# Progress: maven-mcp PreToolUse write-time guard hook (#283)

> Plan: ./plan.md · Tasks: ./tasks.md · Branch feat/maven-write-guard-hook (off main@fe0d189)

## Status
- [x] T-1 — pre-edit-deps.sh + hooks.json registration (+x)
- [x] T-2 — test_pre_edit_hook.py (subprocess + stub server)
- [x] T-3 — docs (README + CLAUDE.md) + CI shellcheck step + L5 smoke

## T-1 notes

- `pre-edit-deps.sh` created at `plugin/hooks/pre-edit-deps.sh` (mode 100755)
- Structural fail-open: `set -euo pipefail` + `trap 'exit 0' EXIT` — script can only ever exit 0
- Extraction: Gradle double+single quoted `"g:a:v"` / `'g:a:v'`; pom.xml `<groupId>`/`<artifactId>`/`<version>`; TOML `module = "g:a"` + `"g:a:v"` triples
- `_Q="'"` variable used for single-quote in grep patterns — avoids SC2016 and the broken `\x27`-in-single-quote bug (was in prior iteration, fixed)
- `[^"]+` / `[^']+` / `[^<]+` for version capture; sanitize step (lines 148–183) drops `$`-containing versions → GA-only
- Timeout chain: `timeout` → `gtimeout` → fail-open exit 0
- `env -u GITHUB_TOKEN` before spawning python3; GITHUB_TOKEN absence verified in stub_env.json
- MAX_COORDS=8 cap; deny wins over ask
- `hooks.json` updated: `PreToolUse` entry with `matcher: "Edit|Write|MultiEdit"`, `timeout: 12`
- shellcheck clean (exit 0)

## T-2 notes

- `tests/test_pre_edit_hook.py` — subprocess-based tests with stub server
- 35 tests total; 9 pass on macOS (no timeout/gtimeout), 26 skip via `@_require_jq_and_timeout()`
- All 35 pass on ubuntu-latest CI where `timeout` is preinstalled
- `_dispatch_capture()` helper captures `server.dispatch()` stdout via `contextlib.redirect_stdout` (dispatch prints, returns None)
- `import unittest.mock` + qualified refs throughout (CodeQL py/import-and-import-from compliance)
- ContractDriftGuardTest: verifies the verify_coordinates and get_dependency_vulnerabilities response shapes match what the hook expects

## T-3 notes

### shellcheck
- Added `shellcheck plugins/maven-mcp/plugin/hooks/*.sh` step to `.github/workflows/ci.yml`
- Gated on `steps.changes.outputs.maven_mcp == 'true'`; shellcheck is preinstalled on ubuntu-latest
- Both hooks pass shellcheck clean

### README.md
- Replaced "Hooks" section with two sub-sections: PreToolUse guard (behavior, fail-open, scope limitation) + PostToolUse reminder
- Updated Optional section: jq (both hooks), timeout/gtimeout (guard hook), GITHUB_TOKEN (with scrub note), MAVEN_MCP_PUBLIC_FALLBACK

### CLAUDE.md
- Added "Hooks" section (before "Environment") documenting: fail-open contract, decision policy, security constraints, bash-3.2 compatibility notes, extraction patterns, test structure

## L5 smoke transcript

Setup: fake `timeout` stub in PATH (passthrough; macOS has no `timeout` by default).
CLAUDE_PLUGIN_ROOT = `plugins/maven-mcp/plugin`

**Smoke #1 — hallucinated coord → deny + candidates**

Input: `Edit build.gradle` with `implementation "com.squareup.retrofitt:adapter-rxjava2:2.9.0"` (double-t)

Output:
```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"com.squareup.retrofitt:adapter-rxjava2 not found in resolved repositories. If you intended a real package, verify candidates before use:\ncom.squareup.retrofit2:adapterrxjava2 (versionCount=20)\ncom.squareup.retrofit2:adapterrxjava (versionCount=26)\nio.github.zawn:adapterrxjava2 (versionCount=4)\n"}}
```

Result: PASS — deny with candidates.

**Smoke #2 — real coord (double-quoted) → allow**

Input: `Edit build.gradle` with `implementation "com.squareup.retrofit2:retrofit:2.9.0"`

Output: (empty)

Result: PASS — silent allow.

**Smoke #3 — real coord (single-quoted) → allow** *(verifies extraction fix)*

Input: `Edit build.gradle` with `implementation 'com.squareup.retrofit2:retrofit:2.9.0'`

Output: (empty)

Result: PASS — silent allow (single-quote extraction now works correctly).

**Smoke #4b — AndroidX coord (exists on Google Maven) → allow**

Input: `Edit build.gradle` with `implementation "androidx.core:core-ktx:1.9.0"`

Output: (empty)

Result: PASS — coord found on Google Maven → exists → allow.

**Smoke #5 — server absent (fail-open) → allow**

Input: same hallucinated coord as #1, but CLAUDE_PLUGIN_ROOT=/nonexistent

Output: (empty)

Result: PASS — python3 exits non-zero, SERVER_OUTPUT empty, exit 0 (allow).

**Smoke #4 — internal coord with similar Central name → deny (per spec)**

Input: `Edit build.gradle` with `implementation "com.mycompany.internal:auth-sdk:1.0.0"`

Output: deny with candidates (`cn.stylefeng.roses:authsdk` etc.)

Result: per-spec (suggestions existed → deny). Note: generic auth-related names may match
Central packages. Private coords with distinctive names (e.g. `com.corp.internal:x-yz-sdk`)
produce no suggestions and are allowed (bare-absent path). Documented limitation.

## Learnings

- `\x27` inside single-quoted bash strings is NOT a hex escape — it's literal `\x27`. Must use `_Q="'"` + double-quoted grep pattern, or `$'...'` ANSI-C quoting.
- `server.dispatch()` prints JSON to stdout and returns None; tests must capture stdout via `contextlib.redirect_stdout`.
- macOS has no `timeout`/`gtimeout` by default; test `@_require_jq_and_timeout()` skipUnless handles this cleanly.
- `[^"]+` version capture is simpler and safer than `[A-Za-z0-9.$_{}-]+`; sanitize step handles non-literal filtering.

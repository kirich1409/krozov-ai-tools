---
type: plan
slug: maven-write-guard-hook
date: 2026-06-30
status: approved
spec: none
risk_areas:
  - "hook hard-blocking edits on network/lookup failure (must fail-open)"
  - "false-positive deny on a real coordinate (offline 'unknown' misread as absent)"
  - "latency added to every build-file edit"
  - "coordinate extraction misparsing build-file syntaxes"
  - "shell→python invocation surface (quoting, untrusted file content)"
review_verdict: PASS
---

# Plan: maven-mcp PreToolUse write-time guard hook (#283)

## Context & Decision

maven-mcp's only hook today is **PostToolUse** (`post-edit-deps.sh`): after a build file is edited it
prints an advisory `{"systemMessage": "...run /check-deps"}`. Epic #281's thesis (Sonatype: *safety
comes from real-time software intelligence, not a bigger model*) is that the valuable moment is
**before** the coordinate lands. #283 adds a **PreToolUse** guard that intercepts `Edit|Write` on
build files, verifies the coordinates being added, and — when one definitively does not exist or a
pinned version carries a CRITICAL/HIGH CVE — returns a `deny` + reason so the agent self-corrects in
the same turn. It must be **advisory and safe-by-default**: any uncertainty or failure (offline,
rate-limited, parse miss, tool error) **fails open** (the edit proceeds).

This consumes the already-shipped `verify_coordinates` (#282) and `get_dependency_vulnerabilities`
tools; it adds **no new MCP tool**.

## Technical Approach

A new `command`-type PreToolUse hook script `pre-edit-deps.sh` (bash + jq, mirroring
`post-edit-deps.sh`), registered in `hooks/hooks.json`. Flow:

1. **Fast gate (no cost on unrelated edits).** Read stdin JSON once. If `tool_name` ∉
   {`Edit`,`Write`,`MultiEdit`} → `exit 0`. `basename(tool_input.file_path)` must be in the
   build-file allow-list (same as `post-edit-deps.sh`: `build.gradle[.kts]`, `settings.gradle[.kts]`,
   `pom.xml`, `libs.versions.toml`) → else `exit 0`. If `jq` is absent → `exit 0` (no-op, like the
   existing hook).
2. **Extract candidate coordinates from the NEW content only** — `tool_input.new_string` (Edit),
   `tool_input.content` (Write), or the concatenation of `tool_input.edits[].new_string`
   (MultiEdit). This is a **recall-limited best-effort heuristic**, NOT a robust parser: a missed
   coordinate just means the guard does not fire on it (fail-open, never a wrong block), so the bar
   is "cheap superset filter feeding a fail-open verifier," not "match the server's Python parsers."
   PreToolUse fires *before* the edit, so the script only sees the new *fragment* (which for an Edit
   may be a partial block) — extraction therefore favors **fragment-safe single-token forms**:
   - **Gradle** (`build.gradle[.kts]`): string-notation `"group:artifact:version"` /
     `'group:artifact:version'` (self-contained token; fragment-safe).
   - **TOML** (`libs.versions.toml`): `[libraries]` `module = "g:a"` (single line; fragment-safe).
     `version.ref` and inline `version` are best-effort; a `version.ref` (or any non-literal version)
     resolves to **GA-only** (no concrete version) rather than reaching for an associative-array
     lookup (see bash-3.2 constraint below).
   - **Maven** (`pom.xml`): a `<dependency>`/`<plugin>` block parsed only when the fragment/content
     contains the full `<groupId>`+`<artifactId>` pair; a fragment changing only `<version>` yields
     no GA → not extracted (acceptable: fail-open, the PostToolUse audit nudge still covers it).
   - **Version sanitation:** if an extracted version contains `$` (Gradle `"g:a:$ver"` /
     `"g:a:${libs.x}"`, Maven `${x}`) or is otherwise not a literal version token, **drop the
     version → treat the coordinate as GA-only** (existence check, no CVE query). Enforce a coordinate
     charset of `[A-Za-z0-9._-]` (defense-in-depth; reject anything else).
   - De-duplicate; **cap at `MAX_COORDS = 8`** (interactive gate — keep the synchronous I/O small;
     ARCH/devops perf concern). If zero coordinates parsed → `exit 0` (no python spawn).
   - **bash-3.2 constraint** (macOS default `/bin/bash` is 3.2): NO `declare -A`, `${var,,}`,
     `mapfile`/`readarray`; guard every array expansion as `"${arr[@]:-}"`. All constructs must run
     on bash 3.2.
3. **Verify (one bounded python invocation).** Build each JSON-RPC request with `jq -c -n --arg`
   (NEVER string-interpolate file content); **omit** the `version` key for GA-only coords (do not
   send `null`/`""`); pass `projectPath` only when stdin `.cwd` is non-empty. Send
   `verify_coordinates` with `id:1` (all coords) and — **only when ≥1 versioned coord exists** —
   `get_dependency_vulnerabilities` with `id:2` (`handle_get_dependency_vulnerabilities` does a hard
   `args["dependencies"]`, so never send it an empty/absent list). Pipe the 1-or-2 request lines into
   `<timeout-cmd> 8 python3 "${CLAUDE_PLUGIN_ROOT}/server/server.py"` (line-oriented stdio loop;
   `tools/call` needs no `initialize`; reads to EOF). Resolve `<timeout-cmd>` as
   `timeout` → `gtimeout` → none (darwin lacks `timeout`; without either, fail-open and skip rather
   than risk a hung edit). **Scrub `GITHUB_TOKEN`** from the spawned env (neither tool uses it —
   least privilege). Unwrap each response by **matching JSON-RPC `id`** (not line order) →
   `.result.content[0].text | fromjson`; a response carrying `.error`, missing `.result`, or null
   `.text` → treat as fail-open (that tool contributed nothing).
4. **Decide** (assemble the decision in a variable; print once at the very end — see fail-open).
   - **Actionable — existence:** `existenceStatus == "absent"` **AND** (`likelyHallucination == true`
     OR non-empty `suggestions`). Never act on `exists` or `unknown`. **Bare `absent` (no
     hallucination flag, no suggestion) must ALLOW** — a private/internal/androidx coordinate that
     404s across all probed repos is `absent` without a Central suggestion; denying it would
     false-block a legitimate private dependency. Consequence (documented limitation): the existence
     guard is effectively **Maven-Central-scoped** — it does not catch a confidently-absent
     non-Central coordinate. This is the *safe* direction (a miss is fail-open; denying on bare
     `absent` would be a wrong block). An inline comment + CLAUDE.md must record this so a future
     change does not "tighten" it.
   - **Actionable — vulnerability:** a versioned coordinate with a `CRITICAL`/`HIGH` vulnerability.
   - **Decision verbs differ by arm:** existence/hallucination → `permissionDecision: "deny"`
     (a 404-everywhere coordinate would not resolve at build time anyway; near-perfect precision,
     agent self-corrects from the reason). CVE → `permissionDecision: "ask"` (a real, resolvable,
     possibly-deliberately-pinned version; a hard deny with no `fixedVersion` would dead-end the
     user). Aggregate all findings into one decision (deny wins over ask if both present).
   - **Reason JSON** built with `jq -n --arg` from KNOWN structured fields only — `groupId:artifactId
     [:version]`, `severity`, `fixedVersion`, and for suggestions `groupId:artifactId` + `versionCount`
     — **never** pass through arbitrary network-returned text. Phrase suggestions as **candidates to
     verify, not an instruction to substitute** ("`g:a` not found in resolved repositories; if you
     intended a real package, verify candidates before use: …") — `verify_coordinates` does not flag
     typosquats-of-existing (#322), so an imperative "replace with X" could steer the agent to an
     attacker-seeded near-name. The embedded **suggestion** coordinate (the one network-derived
     string reaching the agent) is itself charset-filtered `[A-Za-z0-9._-]` and length-capped before
     embedding (last sliver of untrusted-text-into-agent). For `Write` (whole-file content), the
     reason **names the exact offending coordinate(s)** so the agent distinguishes a pre-existing bad
     coord from the line it just edited.
   - Otherwise → `exit 0` with **no stdout JSON** (normal permission flow = allow).
5. **Fail-open is guaranteed structurally, not by `set -e`.** Only exit code **2** blocks a
   PreToolUse tool call; `jq`/`grep` can exit 2 on usage/parse errors and `pipefail` propagates them,
   so a stray failure under `set -euo pipefail` is a **fail-CLOSED** hazard (esp. the *envelope*
   `jq` parsing stdin, and `jq` parsing empty/non-JSON python stdout). Therefore:
   `trap 'exit 0' EXIT` immediately after `set -euo pipefail` (both allow and deny are exit-0, so the
   trap is a clean fail-open net); wrap **every** external call so its failure routes to allow
   (`out=$(… ) || out=""`, `coords=$(grep … || true)`); the script must be able to reach **only**
   `exit 0` — never `exit 2`. Triggers that all map to allow: missing `jq`/`python3`/timeout-cmd;
   non-zero/`timeout`(124) exit; **empty** stdout; **garbage** stdout; `.error`/missing-`.result`;
   malformed/non-JSON **stdin**; any coordinate `existenceStatus == "unknown"` (degraded, *not*
   clean — never gates, never swallowed-as-problem). The one stderr diagnostic line must never echo
   env, the token, or raw file content (redaction rule).

### Why a `command` hook (not `mcp_tool`)

Claude Code also offers a `type: "mcp_tool"` hook that calls a connected server tool directly with
`${tool_input.*}` placeholders. It does **not** fit here: `verify_coordinates` needs
`{dependencies:[{groupId,artifactId,version}]}`, but `tool_input` carries raw file text
(`new_string`/`content`). The coordinate **extraction/transformation** step has no home in an
`mcp_tool` placeholder mapping, so a `command` hook that parses then calls the server is required.

### Why the JSON-RPC pipe (not `python3 -c` direct import)

Piping a `tools/call` line into `python3 server.py` reuses the **exact** interpreter+path the plugin
already registers for the MCP server (`plugin.json` → `python3 ${CLAUDE_PLUGIN_ROOT}/server/server.py`)
and depends only on the **public tool contract**, not internal handler names — robust to server
refactors. Cost: output is double-encoded (`jq` twice). The `python3 -c "import server; ..."`
alternative yields raw `{"results":...}` but couples the hook to internal function names and inline
quoting; rejected for fragility.

### Why parse coordinates in bash (not a server-side parse-from-text tool)

The server already owns robust multi-syntax parsers (`_parse_gradle_deps`, `_parse_maven_deps`,
`_parse_toml_catalog`). A clean alternative is a new server tool `extract_coordinates(fileType, text)`
reusing them — but it is **rejected** for two reasons: (1) #283 explicitly scopes to "no new MCP
tool"; (2) those parsers are **whole-file** parsers and PreToolUse only sees a *fragment*, so they
would need fragment-tolerance work anyway. Because extraction is a recall-limited best-effort filter
feeding a **fail-open** verifier (a miss = no guard, never a wrong block), a thin bash heuristic is an
acceptable, deliberately-documented trade-off rather than a second robust parser. **Accepted
limitation:** the bash heuristic and the Python parsers may diverge; the bash side only needs to be a
superset *filter*, and its misses are safe.

| Path | Change | Note |
|---|---|---|
| `plugins/maven-mcp/plugin/hooks/hooks.json` | modify | add a `PreToolUse` array (matcher `Edit|Write|MultiEdit`, `${CLAUDE_PLUGIN_ROOT}/hooks/pre-edit-deps.sh`, `timeout`) alongside the existing PostToolUse |
| `plugins/maven-mcp/plugin/hooks/pre-edit-deps.sh` | add (git mode 100755) | the guard; bash-3.2-safe + jq; structurally fail-open; SHIPPED content → English |
| `plugins/maven-mcp/tests/test_pre_edit_hook.py` | add | Python `unittest` running the hook as a subprocess against a **stub server** (no network); skips if `jq`/`timeout` absent |
| `.github/workflows/ci.yml` | modify | add a `shellcheck plugins/maven-mcp/plugin/hooks/*.sh` step (shellcheck is preinstalled on `ubuntu-latest`) |
| `plugins/maven-mcp/README.md` | modify | PreToolUse-guard subsection + GITHUB_TOKEN/offline/macOS-no-`timeout` degradation note (SHIPPED → English) |
| `plugins/maven-mcp/CLAUDE.md` | modify | document the hook, the fail-open contract, and the Central-scope existence limitation (SHIPPED → English) |

## Decisions Made

1. **`command` hook + JSON-RPC pipe into `python3 server.py`** — robust, public-contract-only.
   `mcp_tool`, `-c` import, and a server-side parse-from-text tool all rejected (see rationale above).
2. **Fail-open is guaranteed structurally** — `trap 'exit 0' EXIT`, every external call wrapped to
   route failure → allow, the script can only ever `exit 0` (never the block-triggering exit 2). Deny
   only on a confident finding; every uncertainty/error/`unknown`/empty/garbage/malformed-stdin
   allows. (SEC-1/DEVOPS-1/TEST-1 convergent critical.)
3. **Decision verb by arm: `deny` for absent/hallucination, `ask` for CRITICAL/HIGH CVE.** Absent is
   near-perfect precision (404-everywhere wouldn't build); CVE is a real, possibly-deliberate version
   where a hard deny — especially with no `fixedVersion` — would dead-end the user. (SEC-4.)
4. **Existence guard stays conservative: `absent AND (likelyHallucination OR suggestions)`.** Bare
   `absent` ALLOWS (a private/internal/androidx coord 404s everywhere → `absent` with no Central
   suggestion; denying it would false-block a real private dep). Documented consequence: the existence
   guard is **Maven-Central-scoped**. This is the *safe direction* (a miss is fail-open; deny-on-bare-
   absent is a wrong block). Inline comment + CLAUDE.md must forbid "tightening" it. (SEC-5 over ARCH-2.)
5. **Only CRITICAL/HIGH CVEs gate** (→ `ask`); MEDIUM/LOW not surfaced. Full audit stays the
   PostToolUse `/check-deps` nudge (kept — complementary, not folded).
6. **Untrusted-content discipline:** both the inbound JSON-RPC request and the outbound
   `permissionDecisionReason` are built with `jq -c -n --arg` from known structured fields only —
   never string-interpolated, never passing arbitrary network text; coordinate charset
   `[A-Za-z0-9._-]`. Suggestions are phrased as candidates-to-verify, not substitute-instructions
   (anti-slopsquat, #322). `GITHUB_TOKEN` scrubbed from the spawned env. (SEC-2/SEC-3/SEC-7.)
7. **bash-3.2-safe + bounded:** no bash-4 constructs (macOS default shell is 3.2); `MAX_COORDS = 8`;
   inner `timeout 8` < `hooks.json` `"timeout": 12` so the script wins the race and fails open;
   `timeout`→`gtimeout`→none fallback; `shellcheck` CI gate. (DEVOPS-2/3/4/5, ARCH-6.)
8. **New content only**, recall-limited best-effort extraction. For `Write` (whole-file content) the
   guard checks every coordinate present and the deny reason **names the exact offending one**; a
   non-literal/`${…}` version is treated GA-only. (ARCH-1/ARCH-3/ARCH-4.)

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **Accidental hard-block** (`set -e`/`pipefail` → exit 2; jq parse error on stdin or empty python stdout) | `trap 'exit 0' EXIT`; every external call wrapped `… || true`; script can only `exit 0`; tests for empty-stdout, garbage-stdout, malformed-stdin, JSON-RPC-error → all allow |
| Hard-blocking edits when offline/rate-limited | fail-open on `unknown`/error/timeout(124)/missing-tool; deny only on confident finding |
| False-positive deny on a real (esp. private/androidx) coordinate | never deny on `unknown`/`exists`/bare-`absent`; existence deny requires `likelyHallucination`/suggestion (Central-scoped, conservative) |
| Latency on every build-file edit | fast gate exits before any python spawn; `MAX_COORDS=8`; inner `timeout 8`; no spawn when zero coords; single python invocation for both tools |
| Misparsing / fragment / `${ver}` | best-effort heuristic, fail-open on miss; `${…}`/non-literal version → GA-only; charset-restricted |
| Untrusted file content → shell/python/agent | requests AND reason built with `jq -n --arg` (never interpolated, never raw network text into the reason); coordinate charset `[A-Za-z0-9._-]`; `GITHUB_TOKEN` scrubbed from spawned env; stderr never echoes env/content/token |
| Suggestion steers agent to attacker-seeded near-name (#322) | reason phrases suggestions as candidates-to-verify (non-imperative) + `versionCount`; never "replace with X" |
| `timeout`/`gtimeout`/`python3`/`jq` absent (macOS) | detected → fail-open; guard silently no-ops (documented); `gtimeout` probed as fallback |
| Guard silently never fires (wrong decision envelope) | tests assert full `hookSpecificOutput.hookEventName=="PreToolUse"` envelope, not just `permissionDecision` |

## Verification & Sources

- **Source of truth for "done":** this plan + issue #283's acceptance criteria (hallucinated coord →
  surfaced, not silently allowed; known-CVE version → CVE+fix surfaced; network failure → fail-open;
  only build files trigger). No separate spec. The CC PreToolUse contract
  (`hookSpecificOutput.permissionDecision` `deny|allow|ask`, exit-0+JSON; exit-2+stderr alternative;
  `tool_input` shapes for Edit/Write/MultiEdit) is the integration contract, verified against
  code.claude.com/docs/en/hooks.md (2026-06-30).
- **Testing strategy (pyramid):**
  - **L0 Build:** `python3 -m compileall plugins/maven-mcp/plugin/server/server.py` (unchanged);
    `bash -n pre-edit-deps.sh` syntax check; hook committed with git mode 100755 (validate.sh L6).
  - **L1 Static:** `bash scripts/validate.sh` rc=0; CodeQL clean (tests: `import unittest.mock`+
    qualified, no unused import, commented `except`); **`shellcheck` as a CI gate** on
    `plugins/maven-mcp/plugin/hooks/*.sh` (preinstalled on ubuntu-latest; also lint `post-edit-deps.sh`).
  - **L2 Unit/integration:** `test_pre_edit_hook.py` runs `pre-edit-deps.sh` as a subprocess with
    crafted stdin and `CLAUDE_PLUGIN_ROOT` → a **fixture dir whose `server/server.py` is a stub** that
    LOOPS over stdin to EOF (handles 1-or-2 requests), RECORDS the args it received (so extraction is
    actually proven, not just the response consumed), and emits canned `id`-correlated JSON-RPC. Every
    **allow**-case drops/asserts a "stub-invoked" marker (positive control vs vacuous pass), with stub
    wiring byte-identical to a paired deny-case. Full case list in `tasks.md` — including the fail-open
    paths (empty-stdout, garbage-stdout, malformed-stdin, JSON-RPC-error-envelope, python/jq/timeout
    absent, `unknown`), the over-deny boundary (bare `absent`→allow), GA-only/`${ver}`→excluded-from-
    vuln-args, full deny-envelope assertion, and a test that feeds the hook's **exact emitted JSON-RPC**
    into the **real** `dispatch`/handlers (urlopen mocked) to catch hook↔server contract drift.
  - **L5 manual smoke:** run the hook by hand with a hallucinated coord (`org.apache.commons:commons-lang:9.9.9`)
    → `deny` JSON with a candidate suggestion; a real coord → allow; stub `unknown` → allow.
- This is additive (a new hook); no before-state behavior to preserve. The new tests + the existing
  334-test suite are the regression guard.

## Out of Scope

- New MCP tools or changes to `verify_coordinates`/`get_dependency_vulnerabilities` internals.
- Compatibility-aware messages (H2 #285) — richer reasons later.
- A true added-vs-removed coordinate diff (new-content scan is sufficient for hallucination/CVE).
- Caching the guard's lookups across edits / a batch-level deadline (the #328 concern); the per-call
  `timeout` + `MAX_COORDS` cap is the bound here.
- Private-repo auth (H3 #290), plugin-marker→GAV (H3).

## Open Questions

_None blocking._ The cycle-1 review resolved the prior open items: **deny-vs-ask** → split by arm
(`deny` for absent/hallucination, `ask` for CVE — SEC-4); **deny-on-bare-`absent`** → rejected, keep
the conservative Central-scoped condition (SEC-5 over ARCH-2, safe-direction). Both are recorded in
Decisions with rationale, so architecture's cycle-2 re-review sees the deliberate trade-off rather
than a silent pick.

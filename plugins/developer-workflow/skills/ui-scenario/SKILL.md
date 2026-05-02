---
name: ui-scenario
description: >-
  Author, run, or update re-runnable UI scenarios — markdown scripts executed
  on a live app or browser through the `mobile` / `playwright` MCP servers.
  Operator behind the `ui-scenario` test type declared in `generate-test-plan`
  and `docs/TESTING-STRATEGY.md`.

  Three modes: **write** (transcribe a journey into a persistent scenario file),
  **run** (execute an existing scenario, produce a pass/fail report), **update**
  (heal a scenario failing because the UI changed, with confirmation per change).

  Use when: "write a UI scenario", "run scenario X", "execute the checkout
  scenario", "the checkout scenario is failing — update it", "add a re-runnable
  UI test for the login flow", "regression UI scenario".
  Do NOT use for: Compose UI tests / XCUITest / ViewInspector code (engineer
  agents during `implement` / `write-tests`), one-shot manual QA against a spec
  (use `acceptance`), undirected exploratory QA (use `bug-hunt`), or visual
  snapshot tests (use the project's screenshot framework via `write-tests`).
disable-model-invocation: true
---

# UI Scenario

Re-runnable UI tests that execute against a real running app or browser through `mobile` (Android / iOS) and `playwright` (web) MCP servers. The output is a markdown file that lives in the project (`tests/ui-scenarios/<scenario-name>.md`) and can be re-run on any branch — by `acceptance`, by the user, or in future by a CI runner — without rewriting it for each release.

This skill is **QA-execution**: it is allowed to reference `mobile` / `playwright` MCP tool names directly and to fail fast with an install/enable message when those servers are not available. Graceful degradation without real device automation is impossible. See `developer-workflow/CLAUDE.md` Conventions for the QA-execution exception.

## Three modes

The caller picks the mode in the invocation prompt; defaults to `run` when an existing scenario name is referenced.

| Mode | Trigger | Outcome |
|---|---|---|
| **write** | "write a scenario for X", "transcribe this journey", or no scenario file exists yet | Engineer describes the journey; this skill produces a `tests/ui-scenarios/<name>.md` file matching the format in [`references/scenario-format.md`](references/scenario-format.md) |
| **run** | Scenario file exists; caller asks to execute | Skill reads the scenario, executes step-by-step against a connected device / browser via the matching MCP, produces `swarm-report/<slug>-ui-scenario-<name>.md` with pass / fail and evidence |
| **update** | Existing scenario fails because the UI changed (rename, restructure, copy change) | Skill diffs the failing step against the current UI tree, proposes minimal changes (selector replacement, step reorder, assertion update) per change. Each change is confirmed with the user before being persisted |

## Phase 1: Identify mode and locate scenario

1. **Mode** — read the caller's prompt:
   - "write" / "create" / "transcribe" / "add scenario" → `write`
   - "run" / "execute" / "play" / "verify" / no verb but a scenario name is given → `run`
   - "update" / "heal" / "fix selectors" / "the scenario is broken because the UI changed" → `update`
2. **Locate** the scenario file:
   - Convention: `tests/ui-scenarios/<scenario-name>.md`. Slug-style file names (kebab-case, descriptive — `checkout-happy-path.md`, not `tc-1.md`).
   - `write` mode — choose a name from the journey description; ask the user once if a file with that name already exists.
   - `run` / `update` modes — fail fast if the file does not exist (with the path that was looked up).
3. **Detect the platform target** from the scenario's `Platforms:` line and the running environment:
   - `android` / `ios` → use the `mobile` MCP server.
   - `web` → use the `playwright` MCP server.
   - If the caller's environment does not have the matching MCP enabled, stop with an install/enable message.

## Phase 2 (write mode): Transcribe the journey

The engineer describes the journey in natural language. The skill produces the markdown file.

1. Read the description; resolve any ambiguous step (which screen, which button, which assertion) by **one** clarifying question per ambiguity, batched at the end.
2. Choose selectors using the priority list in [`references/scenario-format.md`](references/scenario-format.md#selector-priority):
   1. `id` / `accessibility-id` / `resource-id` (preferred — stable across UI restructuring).
   2. `text` (acceptable — fragile to copy / localisation changes).
   3. `xpath` / complex queries (discouraged — only when the first two are not available).
3. Write the file at `tests/ui-scenarios/<name>.md` following the format spec.
4. **Do NOT execute the scenario in `write` mode.** The author validates the scenario by invoking `run` mode after the file is saved.

The `write` mode does not assume an app is running. It produces a file; running it is the caller's next step.

## Phase 3 (run mode): Execute and report

For each step in the scenario:

1. Resolve the selector to a current UI element via `mobile` / `playwright` (use the cheapest read first — `ui` tree before `screen` capture).
2. Apply the action (`tap`, `fill`, `swipe`, `wait`, …) mapped to the matching MCP tool.
3. Evaluate every assertion attached to the step.
4. On the first assertion failure or element-not-found, stop and produce a failure report with:
   - The failing step and its assertions.
   - The actual UI state at the moment of failure (text excerpt of the relevant tree subset; one screenshot only if the tree is insufficient — keeps token cost down).
   - A short explanation: why the assertion failed (literal mismatch, element absent, timeout, navigation drift).

Successful steps are recorded as `[PASS] <step text>` in the report; the body of the running report uses checkboxes so completed steps survive context compaction.

Save the report to `swarm-report/<slug>-ui-scenario-<name>.md`. The verdict is one of:

- **PASS** — every step's assertions satisfied, no timeouts.
- **FAIL** — at least one assertion mismatch or element-not-found. Report names the first failing step and its evidence.
- **PARTIAL** — only emitted when the caller passes `--continue-on-fail`; lists every failing step.

## Phase 4 (update mode): Heal a failing scenario

Update mode is destructive (it edits the persistent scenario file). Always confirm changes with the user before persisting.

1. Run the scenario with `run` mode internally to identify the first failing step.
2. Diff the failing selector against the current UI tree:
   - Rename detected (same role, different `id` / `text`) → propose the new selector.
   - Element moved into a different parent → propose updated step or suggest reorder.
   - Element removed entirely → ask the user whether the scenario step is still valid (delete the step, replace with an alternative path, or mark the scenario as a known regression).
3. Surface the proposed change to the user as `<old> → <new>` with the reason. Apply only after confirmation.
4. Re-run the scenario after every confirmed change to find the next failing step. Loop until PASS or the user opts out.

Update mode is not for migrating a scenario across a major UI redesign — that is a `write` from scratch.

## Integration with `acceptance`

`acceptance` Branch 2 (test-plan-driven verification) checks for a persistent scenario before falling back to one-shot manual-tester execution:

1. For each `ui-scenario`-typed Test Case in the test plan, look up `tests/ui-scenarios/<scenario-from-tc>.md`.
2. If the file exists, invoke `ui-scenario` `run` mode and consume its receipt as the verification evidence for that TC.
3. If the file does not exist, fall back to the one-shot `manual-tester` flow already documented in `acceptance/SKILL.md`.

The acceptance skill records `test_plan_source: ui-scenario` (with the scenario file path) when the persistent scenario was used.

## Output artifacts

| Mode | Artifact | Path |
|---|---|---|
| write | Persistent scenario file | `tests/ui-scenarios/<name>.md` |
| run | Run report | `swarm-report/<slug>-ui-scenario-<name>.md` |
| update | Modified persistent scenario file + run report | same paths as above |

## Escalation

Stop and report when:

- The required MCP server (`mobile` for `android`/`ios`, `playwright` for `web`) is not available in the environment — give the install / enable message and do not try alternatives.
- No connected device / running app for the requested platform — ask the user to start the simulator / emulator / browser and try again.
- More than three consecutive `update`-mode confirmations are needed in one run (signals UI redesign rather than scenario drift) — recommend a full `write` rewrite.
- An `update`-mode change would alter the meaning of the scenario (e.g. removing a critical assertion) — refuse to apply silently; raise to user.

## Selector priority and other rules

See [`references/scenario-format.md`](references/scenario-format.md) for the full grammar (preconditions / steps / assertions / cleanup), the MCP-tool-to-action mapping, the Platforms field, and a worked example.

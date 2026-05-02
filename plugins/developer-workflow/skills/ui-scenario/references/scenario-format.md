# UI Scenario Format

Canonical structure for `tests/ui-scenarios/<name>.md`. Every scenario is a markdown file with three sections — **header**, **steps**, **cleanup** — plus an optional **fixtures** block. The format is human-readable AND machine-parseable: the running agent reads each step verbatim and maps actions to MCP tool calls.

## File layout

```markdown
# UI Scenario: <human title>

Platforms: android, ios, web        # one or more, comma-separated
Device profile: default              # optional — see "Device profiles" below
Tags: smoke, checkout, regression    # optional — used by acceptance/CI to filter
Timeout: 60s                          # optional — overall scenario timeout

## Preconditions

- App installed and launched (or browser open at the start URL)
- User logged in as test_user
- Cart contains exactly 1 item: SKU-001

## Fixtures

- test_user: email = qa+test@example.com, password = $TEST_USER_PASSWORD
- card_number: 4242 4242 4242 4242

## Steps

1. tap element: id="checkout_button"
   assert: screen visible "Payment"

2. fill field: id="card_number" value="$fixtures.card_number"
   fill field: id="cvv" value="123"

3. tap element: text="Pay"
   wait for: 5s
   assert: screen visible "Order confirmed"
   assert: text visible "Order #"

## Cleanup

- Reset cart via test API
- Log out
```

## Header rules

| Field | Required | Notes |
|---|---|---|
| Title (`# UI Scenario: ...`) | yes | Human-readable; not used by the runner |
| `Platforms:` | yes | One or more of `android`, `ios`, `web`. Determines which MCP server (`mobile` / `playwright`) executes the scenario |
| `Device profile:` | no | Defaults to `default`. Project-specific profiles can declare locale, screen size, network throttle |
| `Tags:` | no | Free-form list, comma-separated. `acceptance` and CI runners filter on these |
| `Timeout:` | no | Overall wall-clock cap. Defaults to 120s for `mobile`, 60s for `playwright`. Per-step waits do NOT count against this — only total wall time |

## Selector priority

The runner picks the most stable form first. Authors must follow the same order:

1. **`id="..."`** / **`accessibility-id="..."`** / **`resource-id="..."`** — preferred. Survives copy changes, restructuring, localisation. Use whenever the project provides one.
2. **`text="..."`** — acceptable when no stable id exists. Fragile to copy edits and i18n.
3. **`xpath="..."`** / complex queries — discouraged. Only when (1) and (2) cannot identify the element. Document why in a comment on the step.

A scenario that uses `xpath` for more than one step in ten is a sign the screen needs `accessibilityIdentifier` / `testTag` / `data-testid` attributes — open a follow-up issue rather than papering over with brittle selectors.

## Step grammar

Each step is a numbered list item containing:

- One or more **actions** — verbs that drive the UI: `tap`, `fill`, `swipe`, `scroll to`, `long-press`, `wait for`, `back`, `navigate`, `key press`, …
- Zero or more **assertions** — `assert:` lines that must hold before the next step runs.

Each line is `<verb>: <selector-or-target>` followed by optional named arguments (`value="..."`, `direction="up"`, etc.).

### Common actions

| Verb | Selector / target | Notes |
|---|---|---|
| `tap element` | id / text / xpath | Default tap on the centre of the matched element |
| `long-press element` | id / text / xpath | `duration="<seconds>"` optional |
| `fill field` | id / text | `value="..."` required. Use `$fixtures.<name>` to inject from the Fixtures section |
| `swipe` | id / text / `screen` | `direction="up|down|left|right"`, `distance="..."` optional |
| `scroll to` | id / text | Scroll until the element is visible; honours direction inference |
| `wait for` | id / text / `<seconds>` | Wait until element is visible OR the literal duration. `<seconds>` form is `wait for: 5s` |
| `key press` | platform key code (`back`, `enter`, `escape`, `tab`) | Web maps to keyboard, mobile to system back / IME |
| `navigate` | URL (web only) | Sets the browser to a specific URL — equivalent to clicking a link |

### Common assertions

| Assert | Form | Meaning |
|---|---|---|
| `screen visible "..."` | text or screen identifier | The current screen / route matches the value (text contains, route equals) |
| `text visible "..."` | substring match anywhere on the visible UI | Use sparingly — prefer matching against a specific element |
| `element visible: <selector>` | id / text / xpath | The element is present and visible |
| `element absent: <selector>` | id / text / xpath | The element is NOT present (timeout-aware) |
| `field has value: <selector> value="..."` | id / text | Input field's current value equals the literal |
| `count: <selector> = N` | id / text | Element count satisfies the relation (`=`, `>=`, `<=`, `between A..B`) |

## Fixtures

The `## Fixtures` section is optional. Variables declared there can be referenced in step values via `$fixtures.<name>`. Secrets must come from environment variables, written as `$TEST_USER_PASSWORD` (the runner reads from the process environment, never from the file).

## Pass / fail semantics

- **PASS** — every step ran without failure and every assertion attached to those steps was satisfied.
- **FAIL** — first assertion mismatch, element-not-found timeout, or unexpected platform error. The runner stops at the first failure unless `--continue-on-fail` is passed by the caller.
- **PARTIAL** — only with `--continue-on-fail`. Reports every failed step, but does not stand in for PASS.

The run report at `swarm-report/<slug>-ui-scenario-<name>.md` keeps the verdict as the last fenced block:

```
verdict: FAIL
passed_steps: [1]
failed_step: 2
failure_reason: element not found — id="card_number"
evidence: <relative path to UI tree dump or screenshot>
```

## Worked example — checkout happy path

```markdown
# UI Scenario: Checkout happy path

Platforms: android, ios
Tags: smoke, checkout
Timeout: 60s

## Preconditions

- App installed and launched
- User logged in as test_user
- Cart contains exactly 1 item: SKU-001

## Fixtures

- card_number: 4242 4242 4242 4242

## Steps

1. tap element: id="cart_button"
   assert: screen visible "Cart"

2. tap element: id="checkout_button"
   assert: screen visible "Payment"

3. fill field: id="card_number" value="$fixtures.card_number"
   fill field: id="card_expiry" value="12/30"
   fill field: id="card_cvv" value="123"

4. tap element: id="pay_button"
   wait for: id="confirmation_screen"
   assert: screen visible "Order confirmed"
   assert: element visible: id="order_number"

## Cleanup

- Tap "Done" to return to the catalogue
- Reset cart via test API endpoint POST /test/reset-cart
```

## Anti-patterns

- **Long sequence of taps without assertions.** Every 3–4 actions should have at least one assertion that anchors the runner to a known state.
- **`xpath` everywhere.** Add `accessibilityIdentifier` / `testTag` / `data-testid` attributes to the production code and use those instead.
- **Hard-coded waits.** Prefer `wait for: <selector>` over `wait for: 10s`. The literal-duration form is the escape hatch, not the default.
- **Implicit fixtures in plain text.** If a value depends on environment, declare it in `## Fixtures` (or as `$ENV_VAR`) — never inline a secret in `value="..."`.
- **Branching logic in steps.** Scenarios are linear; conditional flows are separate scenarios that share fixtures.

## Conformance with the testing strategy

This format is the canonical implementation of the `ui-scenario` test type listed in [`docs/TESTING-STRATEGY.md`](../../../docs/TESTING-STRATEGY.md#test-types) and in the `generate-test-plan` Type field. A test case typed `ui-scenario` in `<slug>-test-plan.md` references a file under `tests/ui-scenarios/`; `acceptance` honours that mapping (see `ui-scenario/SKILL.md` § Integration with `acceptance`).

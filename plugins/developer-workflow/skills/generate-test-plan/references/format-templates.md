Referenced from: `plugins/developer-workflow/skills/generate-test-plan/SKILL.md` (§Test Plan Format).

# Test Plan Format Templates

Every generated test plan must follow this exact structure:

```markdown
---
type: test-plan
slug: <feature-slug>
generated: YYYY-MM-DD
---

# Test Plan: [Feature Name]

| Field | Value |
|-------|-------|
| **Source** | [spec link / Figma link / code path — whatever was provided] |
| **Generated** | [YYYY-MM-DD] |
| **Scope** | [one-line summary of what is covered] |
| **Status** | Draft / Ready for Review / Approved |

The `type: test-plan` frontmatter lets `multiexpert-review` and `acceptance` identify the
artifact deterministically (Signal #1 of the classifier). `slug` matches the receipt and
any decomposition artifact for the same feature.

---

## Findings

Discrepancies, ambiguities, or assumptions discovered during analysis.
Each finding has a short title and explanation.

- **[Finding title]** — [explanation]

> Omit this section entirely if there are no findings.

---

## Risk Areas

| Area | Risk Level | Reason |
|------|-----------|--------|
| [area name] | High / Medium / Low | [why this area is risky] |

---

## Test Cases

### [Group Name]

Group related test cases by feature area, screen, or workflow
(e.g., Authentication, Cart Checkout, Error Handling).

#### TC-[N]: [Short descriptive title]

| Field | Value |
|-------|-------|
| **Type** | unit / integration / ui-instrumentation / ui-scenario / screenshot / e2e |
| **Type rationale** | One short line — why this type catches the AC failure with the smallest scope |
| **Priority** | P0 Critical / P1 High / P2 Medium / P3 Low |
| **Tier** | Smoke / Feature / Regression |
| **Preconditions** | What must be true before starting |
| **Steps** | 1. First step  2. Second step  3. Third step |
| **Expected Result** | Observable outcome that means the test passed |
| **Source** | Spec §section / Figma frame name / `path/to/file.kt:42` / [inferred from code] |

---

## Edge Cases & Negative Scenarios

Same TC format as above. Grouped separately for visibility.
Includes: boundary values, invalid inputs, error states, permission denials,
network failures, empty/null data, concurrent operations.

---

## Coverage Matrix

| Requirement / Screen / Flow | Test Cases | Risk |
|-----------------------------|-----------|------|
| [requirement or screen name] | TC-1, TC-3 | High |
| [another requirement] | TC-2 | Low |

---

## Suggested Automation Candidates

Test cases that are good candidates for automated testing.

| Test Case | Rationale |
|-----------|-----------|
| TC-[N] | [why this is a good automation candidate] |

> Omit this section if no test cases are suitable for automation.

---

## Non-functional / Instrumentation

> **Mandatory** when the spec / task is `user-facing` or `prod-bound`, or the
> feature touches an observability hot-path (network calls, payments,
> background jobs, auth, data migrations). Internal / dev-only / pure refactor
> tasks may set the section to `N/A: <reason>` (one line) — never delete the
> heading.

### Log events
- Event: `<namespace>.<action>` — when fired, key fields (NO PII)

### Metrics
- Counter: `<name>` — increments on ..., labels ...
- Histogram: `<name>` — observes ..., bucket strategy ...
- Gauge: `<name>` — tracks ...

### Traces
- Span: `<operation>` — entry point, child spans, key attributes
- Parent context: where the trace-id originates

### Alerts
- Alert: `<name>` — condition, severity, route (oncall / Slack / email)
- Runbook: `runbooks/<slug>.md` (if the project follows that convention)

### Dashboards
- Existing to update: URL / id
- New needed: yes / no, owner

> Naming, namespacing, and stack (OTel, Prometheus, StatsD, vendor-specific) are
> read from the project's `CLAUDE.md`. The skill does not prescribe a stack —
> it records what the project already uses, or asks one question if the
> project has none.
```

## Phase Segmentation

When the feature reaches this skill via `decompose-feature` with phases (e.g. T-1..T-3 in
Phase 1, T-4..T-6 in Phase 2), the permanent file splits the `## Test Cases` section by
phase so each phase can ship and be re-verified independently. One permanent document per
feature remains the rule — phases are sections inside it, not separate files.

Apply segmentation when the decomposition artifact contains two or more phases **and** test
cases can be grouped by which phase introduces the behavior they cover. Otherwise keep a
single flat `## Test Cases` section.

Example for a feature with two phases:

```markdown
## Test Cases

### Phase 1 (T-1..T-3) — Core login flow

#### TC-1: Successful login with valid credentials
| Field | Value |
|-------|-------|
| **Type** | ui-instrumentation |
| **Type rationale** | Single screen; assertions on visible state after a user action. Smaller scope (`unit`) cannot cover the screen-level state transition. |
| **Priority** | P0 Critical |
| **Tier** | Smoke |
| **Preconditions** | User account exists, email is verified |
| **Steps** | 1. Open login screen  2. Enter email  3. Enter password  4. Tap Login |
| **Expected Result** | Home screen is shown, session token stored |
| **Source** | Spec §2.1 |

#### TC-2: Invalid password shows inline error
...

#### TC-3: Rate-limit after 5 failed attempts
...

### Phase 2 (T-4..T-6) — Password reset flow

#### TC-4: Request reset email from login screen
| Field | Value |
|-------|-------|
| **Type** | ui-scenario |
| **Type rationale** | Multi-screen journey (login → forgot → confirmation); cheaper to maintain as a re-runnable scripted scenario than a full e2e suite. |
| **Priority** | P0 Critical |
| **Tier** | Feature |
| **Preconditions** | User account exists |
| **Steps** | 1. Tap "Forgot password?"  2. Enter email  3. Submit |
| **Expected Result** | Confirmation screen shown, reset email dispatched |
| **Source** | Spec §3.2 |

#### TC-5: Reset link expires after 15 minutes
...

#### TC-6: Reset flow rejects reused link
...
```

When segmentation is applied, the receipt's `phase_coverage` field lists the phase labels
present (e.g. `[Phase 1, Phase 2]`), and the TC ranges covered by each phase appear in the
receipt's Phase Coverage section.

## Lightweight template (non-UI features)

When the non-UI detector triggers (see Input Discovery), use this reduced TC format in place
of the standard one. The entire behavior of each TC is captured in Given/When/Then — no
numbered Steps, no separate Expected Result field, since both collapse into the Then clause
for non-interactive surfaces.

```markdown
#### TC-[N]: [Short title]
| **Type** | unit / integration |
| **Type rationale** | Why this scope catches the AC failure with the smallest cost |
| **Priority** | P0/P1/P2/P3 |
| **Tier** | Smoke/Feature/Regression |
| **Preconditions** | [state] |
| **Scenario (Given/When/Then)** | Given X, When Y, Then Z |
| **Source** | [Spec §section / inferred from code] |
```

Non-UI features are typically `unit` or `integration`. UI types (`ui-instrumentation`, `ui-scenario`, `screenshot`, `e2e`) do not appear in the lightweight template — if a UI type is needed, switch back to the full TC template.

Example:

```markdown
#### TC-3: Token refresh succeeds before expiry
| **Type** | integration |
| **Type rationale** | Real `TokenManager` + test HTTP server to assert end-to-end refresh + scope preservation; pure-unit scope cannot reach the network call |
| **Priority** | P0 Critical |
| **Tier** | Feature |
| **Preconditions** | Valid refresh token stored, access token within 60s of expiry |
| **Scenario (Given/When/Then)** | Given an access token with <60s TTL, When the client calls `refresh()`, Then a new access token is returned with the original refresh-token scope preserved |
| **Source** | `src/auth/TokenManager.kt:142` |
```

All other sections of the Test Plan Format (front-matter table, Findings, Risk Areas,
Coverage Matrix, Suggested Automation Candidates, Phase Segmentation when applicable) are
used unchanged — only the TC blocks switch to this reduced form.

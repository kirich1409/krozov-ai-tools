---
name: bug-hunt
description: >-
  This skill should be used when the user asks to "find bugs", "check if anything is broken",
  "poke around the app", "explore the app", "do a sanity check", "QA the app", "stress test",
  "find UX issues", "check for crashes", "do pre-release QA", or "check app quality" — without
  providing a specification or formal test plan. Also use when the user mentions a running app
  (emulator, simulator, device, localhost URL, staging URL) and wants undirected quality assessment,
  when the feature is built but has no spec yet, when checking if a refactor broke anything, when
  the user reports vague bugs and wants exploration, or for a quick accessibility sweep. Launches
  the manual-tester agent with device/browser MCP tools for real interaction.
  Do NOT trigger when: the user provides a spec/mockup/PRD and wants verification against it (use
  acceptance), the user only wants test cases written without execution (use generate-test-plan),
  or the user asks about automated unit/integration tests (out of scope).
---

# Bug Hunt

Explore a running application to discover bugs, UX issues, and edge cases — guided by testing
heuristics rather than a specification. This is fundamentally different from `acceptance`:
there is no spec to verify against, no pass/fail verdict, and no predefined test plan. The goal
is to find problems the team hasn't anticipated.

The skill launches the `manual-tester` agent in exploratory mode: instead of following a test
plan and comparing results against a spec, the agent navigates the app freely, applies heuristics
at each screen, probes edge cases, and reports everything it finds.

---

## Step 1: Establish Target

Determine what is being tested and how to connect.

### 1.1 Target type

Ask or infer from context:
- **Mobile / desktop app** — need a device/simulator/emulator and an app identifier
- **Web app** — need a URL

If the user says "the app is already running" or provides a device/URL, use it directly.
Otherwise, follow the standard app-launch sequence:

1. Build the app with the project's default tooling (Gradle, Xcode, `npm run dev`, etc.)
2. Install on the target device / simulator, or start the dev server for web
3. Verify the process is reachable (device is visible to the automation MCP, URL responds)
4. If any step fails, surface the error to the user and stop — do not explore a half-launched app

This mirrors `acceptance`'s launch logic so the two skills behave identically; kept inline
to avoid silent coupling to that skill's step numbering.

### 1.1.1 Session identifier

Generate a short session ID used for `BUG-[SESSION_ID]-[n]` / `OBSERVATION-[SESSION_ID]-[n]`
and for the persistent artifact path:

```
<SESSION_ID> = <YYYY-MM-DD>-<short-target-slug>
```

Example: `2026-04-20-payments-flow`, `2026-04-20-full-app`. The artifact path (see Step 3) is
`./swarm-report/bug-hunt-<SESSION_ID>.md`.

### 1.2 Focus area (optional)

The user may name a specific area to concentrate on: "payments flow", "settings screen",
"onboarding", "the new search feature". If provided, exploration starts there and goes deep
before branching out. If not provided, start from the app's entry point and explore
systematically screen by screen.

Do not ask for a focus area if the user didn't mention one — just start broad.

### 1.3 Scope

Exploration is bounded by screen count to keep sessions productive:

| Scope | Screens | When to use |
|-------|---------|-------------|
| **Quick** | ~5 | Fast sanity check, single flow |
| **Standard** | ~15 | Default — good coverage of core flows |
| **Deep** | 30+ | Pre-release sweep, complex app |

Use **Standard** by default. Only ask for scope preference if the user's intent is ambiguous.
If they say "quick check" or "just the settings screen", use Quick. If they say "full QA" or
"before we release", use Deep.

---

## Step 2: Launch Manual Tester in Exploratory Mode

Spawn the `manual-tester` agent with an exploratory prompt. The prompt structure differs from
`acceptance` — instead of a spec and test plan, it provides heuristics and exploration rules.

**MCP prerequisite (QA-execution exception, see `developer-workflow/CLAUDE.md`):** bug-hunt
requires real device/browser automation via the `mobile` MCP (mobile targets) or `playwright`
MCP (web targets). If the required MCP server is not installed or enabled, **stop with a
clear install/enable message** — do not attempt to continue without automation. Graceful
degradation is impossible when real interaction is required.

```
You are performing exploratory testing — there is no specification to verify against.
Your goal is to discover bugs, UX problems, crashes, and edge cases by navigating the app
and applying testing heuristics at every screen you visit.

## Target
[Device/URL/connection details from Step 1]

## Focus Area
[User-provided focus area, or: "None — start from the entry point and explore systematically"]

## Scope
Explore up to [N] unique screens or flows. Maintain a running list of visited screens.
Stop when you reach the boundary or have covered all reachable screens.

## Exploration Heuristics

At each screen, apply these checks:

**Visibility of system status** — Does the app show loading indicators, progress bars,
success confirmations, error messages? Try triggering a slow operation and watch.

**Error handling** — Enter invalid input in every field you find. Try submitting empty forms.
What happens with no network? Does the app show helpful error messages or fail silently?

**Navigation consistency** — Does the back button work as expected? Are there dead ends?
Can you reach the same screen from multiple paths and get consistent results?

**State preservation** — Rotate the device (mobile) or resize the browser window (web).
Background and foreground the app. Is state preserved across these transitions?

**Input edge cases** — For each input field you encounter, try ONE of these:
- A string longer than 200 characters
- Special characters: emoji (😀), RTL text (مرحبا), HTML tags (<b>test</b>)
- Empty submission (leave required fields blank)
Do not try all three on every field — pick the one most likely to cause trouble.

**Empty states** — Navigate to screens that display lists or data. What happens when
there is no data? Is there a meaningful empty state, or does the screen look broken?

**Performance** — Note any visible lag, janky animations, slow transitions, or unresponsive
UI. You don't need to measure precisely — just flag what feels wrong.

**Visual consistency** — Compare the current screen to others you've seen. Are fonts, spacing,
colors, and alignment consistent? Flag anything that looks out of place.

**Accessibility basics** — Are there buttons without labels? Touch targets that look too small
(below ~44×44 dp on mobile)? Text that's hard to read against its background?

## Reporting

Report issues in two categories:

**Bugs** — Use the standard BUG format (BUG-[SESSION_ID]-[n]) for anything that is clearly
wrong: crashes, broken functionality, visual defects, data loss, incorrect behavior.

**Observations** — Use a new OBSERVATION format for things that aren't clearly bugs but are
noteworthy: confusing UX, inconsistent patterns, surprisingly slow transitions, missing
feedback, questionable design choices. These are "a reasonable user might struggle here"
findings.

OBSERVATION-[SESSION_ID]-[n]: [Title]
Screen: [where you saw it]
Details: [what you noticed and why it matters to users]
Heuristic: [which heuristic flagged this — e.g., "error handling", "visual consistency"]

**Coverage log** — After each screen, add it to your running coverage list with a one-line
note of what heuristics you applied and what (if anything) you found.

Do NOT produce a pass/fail verdict or a ship/no-ship recommendation.
There is no spec to verify against — you are discovering, not judging.
```

Let the agent run its full cycle. Do not interfere unless it asks a question or hits a P0
blocker (P0 escalation rule still applies — a crash or data loss warrants immediate attention
even in exploratory mode).

---

## Step 3: Collect and Present Exploration Report

When the manual-tester agent completes, process its output into a structured report and
persist it to `./swarm-report/bug-hunt-<SESSION_ID>.md` (the path registered in Step 1.1.1).
This file is what `Re-exploration After Fixes` re-reads to verify previously reported bugs
— the report is not scroll-ephemeral.

### Report Format

```
## Bug Hunting Report

**Session ID:** [SESSION_ID from Step 1.1.1]
**Date:** [date]
**App:** [name, version, or URL]
**Device / Browser:** [device name + OS version, or browser + viewport]
**Focus Area:** [area, or "General — full app exploration"]
**Scope:** [Quick / Standard / Deep] — [N] screens visited

---

### Coverage Map

| # | Screen / Flow | Heuristics Applied | Issues |
|---|---------------|-------------------|--------|
| 1 | [screen name] | [which checks were done] | BUG-..., OBS-... or "—" |
| 2 | ... | ... | ... |

---

### Bugs ([n] total)

P0 Blockers: [n] | P1 Major: [n] | P2 Minor: [n] | P3 Cosmetic: [n]

[Full BUG entries in standard manual-tester format, ordered P0-first]

---

### Observations ([n] total)

[Full OBSERVATION entries, grouped by heuristic category]

---

### Summary

[2-3 sentence overall quality assessment based on what was found]
```

---

## Step 4: Recommend Next Steps

Based on findings, guide the user toward the right next action:

**P0 blockers found** — Critical issues need fixing before further testing. After fixes,
re-run bug-hunt on the affected area, or use `acceptance` with a spec for targeted
verification.

**P1/P2 bugs found, no blockers** — The app is functional but has issues. Consider creating
a test plan for the affected areas using `generate-test-plan`, then verifying fixes with
`acceptance`.

**Only P3 bugs or observations** — No critical issues. The app is in reasonable shape for the
areas explored. If pre-release confidence is needed, consider a spec-based verification pass
with `acceptance`.

**Nothing found** — The explored scope looks clean. Consider increasing scope to Deep, focusing
on a specific area the team is concerned about, or moving on to spec-based verification.

---

## Re-exploration After Fixes

When the user fixes reported bugs and wants to check again:

1. Load the prior report from `./swarm-report/bug-hunt-<SESSION_ID>.md` and extract the list
   of previously reported bugs (by BUG-ID)
2. Re-launch with the same focus area (or the area where bugs were found)
3. The agent re-verifies each previously reported bug and marks it `Fixed` / `Still present` /
   `Cannot reproduce` in the new report
4. The agent continues exploring adjacent areas for regressions
5. Write the updated report to a new `bug-hunt-<SESSION_ID>-run<N>.md` alongside the original
   so both are preserved for audit

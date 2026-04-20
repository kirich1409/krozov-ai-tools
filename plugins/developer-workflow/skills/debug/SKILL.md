---
name: debug
description: >-
  Systematic root cause investigation — stops at diagnosis, does NOT fix.
  Invoke when user says "debug", "find root cause", "why is X broken", "investigate bug",
  "что сломалось", "почему не работает", "найди причину", "дебаг", "отладь",
  "test fails", "build breaks", "crash", "unexpected behavior", "regression",
  or when a previous fix attempt didn't work.

  Produces a debug report with symptom, reproduction steps, root cause evidence, and
  recommended fix direction — ready to hand off to the implement stage.

  Do NOT use for: feature implementation, code review, performance optimization (unless it's a
  performance bug), writing new tests from scratch (use write-tests), general research (use research).
disable-model-invocation: true
---

# Systematic Debugging

## Core Principle

**UNDERSTAND BEFORE FIXING.**

Random fixes waste time and create new bugs. Symptom fixes mask underlying issues.
This skill stops at root cause — the fix is a separate stage.

## When to Use

- Test failures
- Bugs (production or development)
- Unexpected behavior
- Build failures
- Crashes
- Integration issues
- Regressions
- **Especially when:** under time pressure, "just one quick fix" seems obvious, previous fix
  didn't work, you've tried multiple fixes already

## Three Phases

Complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

1. **Read error messages completely**
   - Don't skip past errors or warnings
   - Read stack traces top to bottom — note line numbers, file paths, error codes
   - They often contain the exact answer

2. **Reproduce consistently**
   - Can you trigger it reliably? What are the exact steps?
   - If not reproducible → gather more data, don't guess

3. **Check recent changes**
   - `git diff`, recent commits, new dependencies, config changes
   - What changed that could cause this?

4. **Gather evidence at component boundaries**
   When the system has multiple components (API → service → database, CI → build → signing):
   - Log what data enters and exits each component
   - Verify environment/config propagation across layers
   - Run once to collect evidence showing WHERE it breaks
   - Then investigate that specific component

5. **Trace data flow backward**
   From the symptom, work backward through layers:
   - Wrong output? → Find where the wrong value was produced
   - Wrong value in DB? → Find the INSERT/UPDATE query
   - Wrong API response? → Find which handler produced it
   - Ask: "If the result is X, what must have happened before?"

**Delegate investigation to the `debugging-expert` agent** — it specializes in read-only root
cause analysis.

### Phase 2: Binary Search Narrowing

**LLMs naturally enumerate all possibilities instead of bisecting. This phase enforces
disciplined narrowing.**

At each step, halve the search space:
- Comment out half the code path → does the bug persist?
- `git bisect` between known-good and known-bad commits
- Disable half the components/middleware
- Add a checkpoint in the middle of the pipeline

**Rules:**
- Each iteration MUST eliminate ~50% of the remaining search space
- If you find yourself listing 5+ hypotheses without testing → STOP, switch to binary search
- Document what was eliminated at each step

### Phase 3: Hypothesis and Confirmation

1. **Form ONE specific hypothesis**
   - "I think X is the root cause because Y"
   - Be specific — not "something in the network layer", but "the retry interceptor swallows
     401 responses"

2. **Design the SMALLEST possible test**
   - One variable at a time
   - Don't test multiple hypotheses simultaneously

3. **Evaluate result**
   - Confirmed → **STOP. Do NOT fix.** Document root cause and produce the artifact. Even if the fix is one obvious line, the fix belongs to the `implement` stage — ending here is the contract of this skill.
   - Refuted → form NEW hypothesis informed by what was learned, return to Phase 2
   - After 3+ failed hypotheses → STOP, likely an architectural issue, escalate to user

## Debugger Integration

If a debugger (DAP, IDE integration, MCP debug tools) is available:
- Use breakpoints, step-through execution, and variable inspection
- This is the fastest path to root cause in Phase 1

If no debugger is available:
- Use structured logging at component boundaries
- Use test isolation and binary search (Phase 2)
- Use `git bisect` for regression hunting

## Red Flags — STOP and Return to Phase 1

If you catch yourself thinking:
- "Just try changing X and see if it works"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- Proposing solutions before tracing data flow
- Listing 5+ hypotheses without binary search narrowing

**ALL of these mean: STOP. Return to Phase 1.**

## Escalation

Escalate to user when:
- Investigation reveals scope is larger than expected
- Root cause is in a dependency or external system beyond your control
- Multiple valid fix approaches exist with non-obvious trade-offs
- The bug requires access, credentials, or environment you don't have
- Cannot reproduce after exhausting available information

## Report

Save findings to `swarm-report/<slug>-debug.md`:

```
## Symptom
What was observed — error message, failing test, unexpected behavior

## Reproduction Steps
Exact steps to trigger the bug consistently

## Investigation Path
What was checked, what was eliminated (binary search log)

## Root Cause
What actually causes it — with evidence (file:line, stack trace, data flow)

## Recommended Fix Direction
What needs to change and where — NOT the implementation, just the direction

## Status
Diagnosed / Escalated / Not Reproducible
```

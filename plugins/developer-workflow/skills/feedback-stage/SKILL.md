---
name: feedback-stage
description: >-
  Feedback processing stage — monitors feedback sources, reads and classifies each item,
  and returns a routing verdict to the orchestrator. Source-agnostic: handles CI/CD output,
  code review comments, bot reports, UAT results, or any other form of feedback.
  Analogous to decompose-feature, but for feedback: reads input, understands it in context
  of the full diff, breaks it into actionable items, tells the orchestrator where each goes.
  Does NOT fix code, run tests, or execute merges — strictly reads and routes.
  Trigger on: "check the PR", "process feedback", "what did reviewers say", "CI failed",
  "handle review comments", or when orchestrator transitions to FeedbackStage.
  Do NOT use for: initial implementation (use implement), QA verification (use acceptance),
  executing a merge (orchestrator's responsibility based on verdict).
disable-model-invocation: true
---

# Feedback Stage

Reads feedback from any source, understands it in the context of all changes made,
classifies each item, and returns a routing verdict to the orchestrator.

**Does NOT fix issues, write code, or execute merges.** Those are handled by the stages
it routes to (implement, acceptance, research) and by the orchestrator itself.

**Core principle:** a comment about one file often signals a systemic issue across all changes.
Always read the full git diff alongside the feedback — understand the pattern, not just the
specific location.

---

## Inputs

This skill accepts feedback in any format. The orchestrator provides:

| Input | Required | Description |
|-------|----------|-------------|
| PR reference | Yes (if PR exists) | PR URL or number to monitor |
| Git diff | Yes | Full diff of all changes (`git diff main...HEAD`) |
| Artifacts | Yes | Paths to `research.md`, `test-plan.md`, `implement.md`, `acceptance.md` |
| Feedback (direct) | Optional | Pre-collected feedback text, file, or report |

If feedback is not yet available — enter monitoring mode (see Step 1).

---

## Step 1: Collect Feedback

### 1.1 Identify available feedback sources

Check what's available:

| Source | How to check | Latency |
|--------|-------------|---------|
| CI/CD | PR checks status via GitHub MCP | Fast (minutes) |
| Automated bots | PR comments from bots (security, lint, etc.) | Fast (minutes) |
| Human reviewers | PR review comments | Slow (hours to days) |
| UAT / stakeholder | User-provided report or comment | Variable |
| Direct input | User pastes feedback text in the conversation | Immediate |

### 1.2 Wait strategy

**Fast feedback (CI, bots):** actively monitor. Poll every 2-3 minutes for up to 30 minutes.
If CI is still running after 30 minutes — report status to user and continue waiting passively.

**Slow feedback (human review):** do NOT block the session. Report:

```
PR is open and waiting for human review.
CI: [green / red / running]
Bots: [passed / issues found / pending]

Resuming when review arrives. Come back and say "process the review" when ready.
```

Stop the session. Resume when the user provides the feedback or says to check again.

**Direct input:** if the user provides feedback text directly — skip monitoring, go to Step 2.

### 1.3 Read all available feedback

Collect everything into a single picture before classifying:
- CI/CD logs (failures, warnings)
- All review comments (inline and general)
- Bot reports
- Any other provided materials

---

## Step 2: Understand in Context

Before classifying, anchor to the full picture:

1. Read `swarm-report/<slug>-implement.md` — what was built and why
2. Read `swarm-report/<slug>-test-plan.md` — what the acceptance contract was
3. Read `swarm-report/<slug>-acceptance.md` — what QA already verified
4. Read the full git diff — understand the entire change surface

**Generalization rule:** a comment on one file may reveal a systemic issue.
For each feedback item, ask: "Does this pattern appear elsewhere in our changes?"
If yes — include all affected locations in the classified item, not just the commented one.

Example:
> Reviewer comments on `UserRepository.kt`: "This method is too long, extract it."
> → Check the full diff: same pattern in `OrderRepository.kt` and `ProductRepository.kt`
> → Classified item covers all three files, not just the one mentioned.

---

## Step 3: Classify Feedback

For each feedback item, determine:

### 3.1 Issue type

| Type | Description | Route to |
|------|-------------|---------|
| **CI failure** | Build error, test failure, lint violation | Implement |
| **Code quality** | Style, naming, complexity, duplication | Implement |
| **Logic error** | Wrong behavior, edge case missed | Implement |
| **Design / architecture** | Wrong abstraction, bad dependency direction, API shape | Research or PlanReview |
| **Approach** | Fundamentally wrong solution direction | Research |
| **Functional** | Feature doesn't work as specified, regression | Acceptance |
| **Security** | Vulnerability, unsafe pattern | Implement (+ security-expert if needed) |
| **Performance** | Inefficient pattern identified | Implement |
| **Scope / product** | Feature scope question, product decision needed | Escalate to user |

### 3.2 Affected scope

List all files/locations affected by this item (including generalizations from Step 2).

### 3.3 Priority

| Priority | Meaning |
|----------|---------|
| **P0** | Blocks merge — must fix before proceeding |
| **P1** | Should fix before merge |
| **P2** | Nice to fix, won't block |
| **P3** | Minor, can defer |

---

## Step 4: Produce Routing Plan

Group classified items by destination stage:

```
## Routing Plan

### → Implement
- [P0] CI: test `UserRepositoryTest.testFetchUser` fails — NPE on null userId
- [P1] Code quality: method `processOrder()` too long (lines 45–120) — same pattern in
  OrderService, PaymentService, ShippingService (generalized from reviewer comment on OrderService)

### → Research
- [P1] Architecture: reviewer questions use of Repository pattern for this use case —
  suggests investigating CQRS as alternative

### → Acceptance
- [P0] Functional: reviewer reports login flow broken on Android 12 — not covered in QA

### → Escalate to user
- [P2] Scope: reviewer asks "should this also handle guest checkout?" — product decision
```

Save to `swarm-report/<slug>-feedback.md`.

---

## Step 5: Delegate

### 5.1 If any P0/P1 items exist

Route to the highest-priority destination stage first. Pass:
- The routing plan artifact (`<slug>-feedback.md`)
- The specific items for that stage
- Full context artifacts (implement.md, test-plan.md, acceptance.md)

Priority order when multiple stages needed: Implement → Acceptance → Research.

After the routed stage completes — re-run this feedback-stage to re-check remaining items.

### 5.2 If only P2/P3 items

Summarize for the user. They decide: fix now or proceed.

### 5.3 If all feedback resolved — no actionable changes required

Report verdict to the orchestrator: **CLEAR — no changes required**.

Include in the verdict:
- Which sources were checked
- Which items were P2/P3 only (not blocking)
- Current PR state: CI status, review decision, unresolved threads

The orchestrator decides what happens next (e.g. proceed to merge).

---

## Output Artifact

Save to `swarm-report/<slug>-feedback.md`:

```
# Feedback Stage: <slug>

**Date:** <date>
**PR:** <URL or number>
**Sources checked:** CI / bots / human review / UAT / direct input

## Feedback Summary
- Total items: [n]
- P0: [n] | P1: [n] | P2: [n] | P3: [n]

## Routing Plan
[grouped by destination stage, as in Step 4]

## Generalizations Applied
[items where a specific comment was expanded to cover more of the diff]

## Verdict
ROUTING / RESOLVED / WAITING
```

---

## Resuming After a Routed Stage

When the orchestrator returns control after Implement/Acceptance/Research:

1. Re-read `swarm-report/<slug>-feedback.md` — which items were pending
2. Re-read the updated PR state
3. Check if previously routed items are now resolved
4. Process remaining items or confirm all clear

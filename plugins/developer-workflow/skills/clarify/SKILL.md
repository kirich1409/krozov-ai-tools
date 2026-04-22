---
name: clarify
description: Lightweight Q&A pit-stop that locks requirements before decomposition — elicits acceptance criteria, non-functional constraints, and out-of-scope boundaries from research findings via 2-round interview with pre-filled defaults. Runs inside feature-flow between Research and Decompose; can also be invoked standalone when requirements need clarification before planning.
---

# Clarify

Lightweight requirements lock between Research and Decompose. Clarify reads the research
artifact, identifies gaps and ambiguities, and resolves them through a concise Q&A session
(max 2 rounds, 5-7 questions each). The output is a structured artifact of locked requirements
that Decompose, PlanReview, and TestPlan treat as binding constraints.

**Key difference from write-spec:** write-spec is a standalone heavy-spec path that produces
a formal specification document through multiple interview rounds. Clarify is an inline pit-stop
— it never replaces write-spec and does not produce a full spec. Its sole purpose is to prevent
ambiguous requirements from reaching decomposition.

**When invoked inside feature-flow:** automatically triggered after Research completes and
before Decompose begins. The orchestrator passes the research slug and task description.

**When invoked standalone:** the user provides a slug or direct artifact path. Behavior is
identical — the output artifact lands at the same path for full downstream compatibility.

---

## Inputs

**Required:**
- `swarm-report/<slug>-research.md` — the research artifact produced by the research skill

**Optional:**
- `swarm-report/<slug>-design-options.md` — architectural alternatives artifact, if produced by design-options

**Context:**
- Task description from the caller (feature goal, constraints, success criteria stated so far)

---

## Skip Conditions

Skip Clarify entirely when any of the following is true:

- **Trivial task** — same threshold as Research skip: single-file change, obviously scoped change,
  no external APIs involved, no unfamiliar libraries, no architectural decisions required
- **Explicit opt-out** — user passed `--no-clarify`, or their message contained "no questions",
  "don't ask", or equivalent
- **Requirements already locked** — the research artifact contains a "Requirements" section
  with acceptance criteria already answered in full

When skipping: announce the skip reason in one line. Do NOT write an artifact. Proceed
immediately to the next stage.

---

## Phase 1: Extract Questions

### 1.1 Read inputs

Read `swarm-report/<slug>-research.md`. If `swarm-report/<slug>-design-options.md` exists,
read it as well.

### 1.2 Identify unclear items

Extract items that are unclear or have multiple valid interpretations across these categories:

| Category | Examples |
|---|---|
| Acceptance criteria boundaries | What counts as "done"? What is the measurable success condition? |
| Non-functional constraints | Performance targets, security requirements, platform/OS compatibility |
| Edge cases with product impact | Error handling behaviour, limits, empty states, concurrent access |
| Out-of-scope decisions | What should NOT be built to keep scope bounded |
| Priority conflicts | When two requirements conflict — which wins? |

### 1.3 Classify each item

For every extracted item, assign one of three dispositions:

- **Already answered in research** → do not ask; record the answer directly as a locked requirement
- **Has an obvious default** → propose the default; list as "accept-or-override" in the Q&A
- **Genuine gap** → ask explicitly; no default proposed (or default is clearly arbitrary)

### 1.4 Prioritize and trim

Sort items by impact × uncertainty: high-impact, high-uncertainty items first.

Keep the question list to **5-7 items maximum** for round 1. If more items exist:
- Lower-priority items go to round 2 only if the user keeps engaging after round 1
- Items that cannot fit in 2 rounds become non-blocking open questions in the artifact

### 1.5 Save state

Save the extracted and classified items to `swarm-report/clarify-<slug>-state.md` before
presenting any questions. This protects against context compaction — if the session is
interrupted, resume from this file rather than re-reading all inputs.

---

## Phase 2: Q&A Rounds

### 2.1 Question format

Present each question using this format:

```
Q{N}: {Topic — one line}

Recommendation: {One-sentence default answer or assumption}
Alternatives:
  A. {Option A — label + consequence}
  B. {Option B — label + consequence}
  [C. Custom]

Impact if deferred: {One sentence — what breaks or becomes ambiguous if left unresolved}
```

Present all questions in a single message. Wait for the user's response before proceeding.

### 2.2 Accepting defaults

If the user says "accept all defaults", "принимаю всё", or any equivalent phrasing:
- Record every proposed default as a confirmed assumption in the artifact
- Do not re-ask any of the defaulted items
- Proceed directly to Phase 3

### 2.3 Round structure

**Round 1:** present all prepared items (max 7). Record answers and any follow-up gaps they open.

**Round 2 (optional):** only if round 1 answers opened new genuine gaps — for example, the user
chose an alternative that implies a constraint not previously known. Announce explicitly:
"Round 2 of 2:" before presenting questions. Max 3 new questions.

**Hard cap:** after 2 rounds, record any remaining items as non-blocking open questions.
Do NOT ask a third round under any circumstances.

### 2.4 Backward edge to Research

If user answers reveal a significant knowledge gap that cannot be resolved from existing
research (for example: "we don't know how the payment API handles retries"), announce:

> **Backward: Clarify → Research**
> Reason: [what gap was exposed]
> Re-invoking research on the specific gap.

Then invoke the research skill on the specific gap, read the new artifact, and continue
Clarify from where it left off with the new information.

**Cap:** 1 backward transition per Clarify invocation. If the targeted re-research still
leaves the gap unresolved — record it as an open question and continue. Do not loop back
to Research a second time.

---

## Phase 3: Save Artifact

### 3.1 Write the artifact

Save `swarm-report/<slug>-clarify.md` using the template below. Fill every section — do not
leave placeholder text. If a section has no items, write "None." rather than omitting the
section.

```markdown
---
slug: <slug>
date: YYYY-MM-DD
status: done | partial
research_path: swarm-report/<slug>-research.md
backward_to_research: 0 | 1
---

## Locked Requirements

Acceptance criteria confirmed during clarification. Each criterion must be verifiable.

- AC-1: ...
- AC-2: ...

## Non-Functional Constraints

- Performance: ...
- Security: ...
- Compatibility: ...
- [category]: ...

## Confirmed Assumptions

Items where the user accepted the proposed default, or where an obvious default was applied
without asking.

- [auto-confirmed] <assumption text>
- [user-confirmed] <assumption text>

## Out of Scope

Explicitly excluded to keep the feature bounded.

- ...

## Open Questions (non-blocking)

Items deferred due to the round cap or insufficient information. These do not block
implementation but should be revisited during or after the first implementation wave.

- ...
```

**status field:** use `done` when all high-impact items were resolved. Use `partial` when
high-impact items remain as open questions due to the round cap or a failed backward edge.

### 3.2 Clean up state file

Update `swarm-report/clarify-<slug>-state.md` status to `done`, then delete the file.
It is operational only and must not persist after the artifact is saved.

### 3.3 Post chat summary

Post a summary in the chat (20 lines maximum):

1. One sentence: "Clarify complete. N requirements locked, M assumptions recorded."
2. Up to 5 bullets covering:
   - Key ACs added (e.g. "AC-1: success = response <2 s under 100 concurrent users")
   - Non-trivial non-functional constraints locked
   - Surprising out-of-scope decisions (if any)
   - Assumptions that could affect architecture choices
3. If non-blocking open questions remain: list them in 3 bullets or fewer.
4. One line: "Next step: Decompose." (or the appropriate downstream stage).

Do NOT paste the full artifact content into chat.

---

## Standalone Invocation

When invoked outside feature-flow, the user must supply one of:
- **Slug** — Clarify resolves `swarm-report/<slug>-research.md` automatically
- **Direct artifact path** — path to a research artifact that may use a non-standard location

If neither is provided, ask for one before proceeding. Once the artifact is located, all
phases run identically to the inline invocation. The output path is always
`swarm-report/<slug>-clarify.md` for downstream compatibility.

---

## Integration Notes

**Decompose, PlanReview, TestPlan:** feature-flow passes `swarm-report/<slug>-clarify.md`
as an additional input to all three stages. They must treat locked requirements as binding
constraints — a plan that contradicts an AC is a defect, not an open question.

**multiexpert-review on PlanReview:** receives the clarify artifact alongside the plan.
Ambiguity in the plan that is contradicted by a locked AC is a FAIL finding — "unclear
requirements" is no longer an acceptable excuse when a clarify artifact exists.

**write-spec:** unaffected. write-spec remains the standalone heavy-spec path for features
that require a formal specification document. Clarify and write-spec serve different purposes
and can coexist in the same flow if the user explicitly invokes both.

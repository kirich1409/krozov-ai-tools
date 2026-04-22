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

- **Obviously scoped change** — single-file change, no architectural decisions, no external APIs
  or unfamiliar libraries involved
- **Explicit opt-out** — user passed `--no-clarify`, or their message contained "no questions",
  "don't ask", or equivalent
- **Requirements already locked** — the research artifact contains a "Requirements" section
  with acceptance criteria already answered in full

When skipping: announce the skip reason in one line. Do NOT write an artifact. Return
control to the caller; in feature-flow, the caller then proceeds immediately to the next
stage.

If the skip reason is **Requirements already locked**, downstream stages (Decompose,
PlanReview, TestPlan) must treat the research artifact's `Requirements` section as the
binding source of locked requirements — equivalent to a Clarify artifact for this run.

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

Keep the list as short as possible — aim for the minimum set that unblocks decomposition.
If many questions surface, that is usually a sign Research was too shallow, not that all
questions must be asked. Ruthlessly cut low-impact items; record them as non-blocking open
questions in the artifact without asking.

Separate remaining items into two buckets:
- **Round 1** — high-impact items that must be resolved before decomposition
- **Round 2 candidates** — lower-priority items and any new gaps opened by round 1 answers

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

Recommendation: {One-sentence default answer or assumption} | none
Alternatives:
  A. {Option A — label + consequence}
  B. {Option B — label + consequence}
  [C. Custom]

Impact if deferred: {One sentence — what breaks or becomes ambiguous if left unresolved}
```

For items classified as "genuine gap" in Phase 1.3 (no obvious default), use
`Recommendation: none` and omit the Alternatives block if no clear options exist.

Present all questions in a single message. Wait for the user's response before proceeding.

### 2.2 Accepting defaults

If the user says "accept all defaults", "принимаю всё", or any equivalent phrasing:
- Record every proposed default from round 1 as a confirmed assumption in the artifact
- For round 2 candidates: auto-confirm those that have an obvious default; record the rest
  as non-blocking open questions
- Do not ask any further questions
- Proceed directly to Phase 3

### 2.3 Round structure

**Round 1:** present high-impact items from the round 1 bucket. Record answers and note any
new gaps they open (add those to the round 2 candidates bucket).

**Round 2 (optional):** run only if the round 2 candidates bucket is non-empty after round 1.
Candidates come from two sources: lower-priority items carried over from Phase 1.4, and new
gaps opened by round 1 answers. Announce explicitly: "Round 2 of 2:" before presenting.
Keep it short — fewer questions, not more.

**Hard cap:** after 2 rounds, record any remaining items as non-blocking open questions.
Do NOT ask a third round under any circumstances.

### 2.4 Backward edge to Research

If user answers reveal a significant knowledge gap that cannot be resolved from existing
research (for example: "we don't know how the payment API handles retries"), announce:

> **Backward: Clarify → Research**
> Reason: [what gap was exposed]
> Requested research scope: [the specific gap to investigate]

Then stop Clarify and return control to the orchestrator (feature-flow). The orchestrator
is responsible for performing the `Clarify → Research` transition, enforcing the
backward-edge cap, and resuming Clarify with the updated research artifact.

**Cap:** 1 backward transition per Clarify invocation, enforced by the orchestrator. If
the targeted re-research still leaves the gap unresolved, feature-flow resumes Clarify
once with the best available artifact — Clarify must then record the item as an open
question and continue. Do not request or perform a second transition to Research.

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

Delete `swarm-report/clarify-<slug>-state.md`. It is operational only and must not persist
after the artifact is saved.

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
- **Direct artifact path** — path to a research artifact that may use a non-standard
  location; if the filename matches `<slug>-research.md`, derive `<slug>` from that
  filename; otherwise the caller must also provide `slug: <slug>` explicitly

If neither is provided, ask for one before proceeding. If a direct artifact path is
provided and `<slug>` cannot be derived from a `<slug>-research.md` filename and no
explicit `slug:` is supplied, stop and ask the user for the slug before proceeding.
Once the artifact is located and `<slug>` is known, all phases run identically to the
inline invocation. The output path is always `swarm-report/<slug>-clarify.md` for
downstream compatibility.

---

## Integration Notes

**Decompose, PlanReview, TestPlan:** feature-flow passes `swarm-report/<slug>-clarify.md`
as an additional input to all three stages. They must treat locked requirements as binding
constraints — a plan that contradicts an AC is a defect, not an open question. When the
artifact has `status: partial`, downstream stages should surface the open questions to the
user before committing to a decomposition or plan — partial clarification is better than
none, but the gaps are real.

**multiexpert-review on PlanReview:** receives the clarify artifact alongside the plan.
Ambiguity in the plan that is contradicted by a locked AC is a FAIL finding — "unclear
requirements" is no longer an acceptable excuse when a clarify artifact exists.

**write-spec:** unaffected. write-spec remains the standalone heavy-spec path for features
that require a formal specification document. Clarify and write-spec serve different purposes
and can coexist in the same flow if the user explicitly invokes both.

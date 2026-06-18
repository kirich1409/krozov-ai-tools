# Plan templates

Copy each block verbatim into the matching file under `docs/plans/<slug>/` and fill every
placeholder. Three files, split by lifetime: `plan.md` and `tasks.md` are the stable design;
`progress.md` is the volatile execution ledger (Cline-style split — execution churn must never
rewrite the design).

---

## `docs/plans/<slug>/plan.md`

```markdown
---
type: plan
slug: <kebab-case>
date: <YYYY-MM-DD>
status: draft           # draft → approved (set by Phase 4 on PASS/CONDITIONAL); stays draft on escalate (review_verdict carries escalate, not this field)
spec: docs/specs/<YYYY-MM-DD>-<slug>.md    # real path if a spec exists (date is the spec's own date, format matches write-spec output); if no spec exists, write: none — do NOT invent a path
risk_areas: []          # subset of [auth, payment, pii, data-migration, perf-critical] — advisory only; reviewer selection is driven by the plan's prose (Technical Approach / Risks), so risks must also be described there for the matching expert (e.g. security-expert) to be triggered
review_verdict: pending # pending → pass | conditional | escalate (set by Phase 3)
review_blockers: []     # filled by the review loop when blockers remain
---

# Plan: <title>

## Context & Decision
<2–4 sentences: what is being built and why it is already decided. Link the spec / research /
request that decided it. This plan is the HOW, not the WHAT — do not re-argue scope here.>

## Technical Approach
<The concrete design. Architecture, data flow, key types/interfaces, the integration points in the
existing codebase (cite file:line from investigation). Enough that an implementing agent does not
need to re-research.>

## Affected Modules & Files
| Path | Change | Note |
|---|---|---|
| `<path>` | New / Modified / Renamed / Deleted | <what changes and why> |

## Decisions Made
| Decision | Rationale | Alternatives rejected |
|---|---|---|
| <what we chose> | <because…> | <X because…> |

## Risks & Mitigations
| Risk | Severity | Mitigation |
|---|---|---|
| <risk> | critical / major / minor | <how the plan handles it> |

## Out of Scope
- <explicitly NOT done by this plan, with owner / deferral target if relevant>

## Open Questions
- [blocking] <question that must be answered before / during implementation>
- [non-blocking] <question that can be resolved while implementing>
```

---

## `docs/plans/<slug>/tasks.md`

Ordered, dependency-aware checklist. Each task is small enough to implement AND verify in one
focused pass, and carries an acceptance condition that is checkable without human judgement — this
is what makes autonomous execution safe.

```markdown
# Tasks: <title>

> Plan: ./plan.md · Spec AC referenced inline as AC-N

## T-1 — <short title>
- after: none
- files: `<path>`, `<path>`
- acceptance: GIVEN <precondition> WHEN <action> THEN <observable result>   (or: THE SYSTEM SHALL <…>)
- check: <test name / grep / build target that proves acceptance>   (satisfies AC-1)

## T-2 — <short title>
- after: T-1
- files: `<path>`
- acceptance: <Given/When/Then or SHALL statement>
- check: <how it is verified>   (satisfies AC-2, AC-3)
```

Acceptance phrasing: prefer Given/When/Then for behaviour, "THE SYSTEM SHALL …" (EARS) for
invariants/constraints. Always pair acceptance with a concrete `check` — a test name, a grep, a
build/lint target — never "looks right".

---

## `docs/plans/<slug>/progress.md`

Initialize with one unchecked box per task and an empty learnings log. The implementer updates this
as work proceeds; it carries state across sessions and fresh-context runs (so a stop/resume or an
autonomous loop never loses its place).

```markdown
# Progress: <title>

> Plan: ./plan.md · Tasks: ./tasks.md

## Status
- [ ] T-1 — <short title>
- [ ] T-2 — <short title>

## Learnings
<!-- Append one line per completed task: surprises, gotchas, decisions taken during implementation.
     This is the memory that survives context resets. -->
```

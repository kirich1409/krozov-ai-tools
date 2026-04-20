Referenced from: `plugins/developer-workflow/skills/write-spec/SKILL.md` (§Phase 3 Write Spec Draft).

# Spec Draft Template

```markdown
---
type: spec
slug: {slug}
date: {YYYY-MM-DD}
status: draft
# Optional fields — leave blank when not applicable. Consumed by `acceptance`
# (choreography) and by `generate-test-plan` (platform-aware coverage).
platform: []                     # Canonical values from ORCHESTRATION.md §Project type detection: [android], [ios], [web], [desktop], [backend-jvm], [backend-node], [cli], [library], [generic]. May be multi-value for cross-platform features.
surfaces: []                     # e.g. [ui], [api], [cli], [background-job]. Drives which acceptance checks run.
risk_areas: []                   # e.g. [auth], [payment], [pii], [data-migration], [perf-critical]. Each entry triggers a conditional expert in acceptance.
non_functional:                  # Optional block. Each present entry triggers an expert check.
  sla:                           # e.g. p99 < 150ms. Triggers performance-expert.
  a11y:                          # e.g. wcag-aa. Triggers ux-expert a11y mode.
acceptance_criteria_ids: []      # e.g. [AC-1, AC-2, AC-3]. Each AC in the list MUST appear as a bullet in §Acceptance Criteria.
design:                          # Optional.
  figma:                         # e.g. https://www.figma.com/file/XXX. Triggers ux-expert design-review.
  design_system:                 # Optional reference to a design system doc.
---

# Spec: {Feature Name}

Date: {YYYY-MM-DD}
Status: draft
Slug: {slug}

---

## Context and Motivation

{2-4 sentences: what this feature does, who benefits, why now.
Write the "why" that will still make sense in 6 months.}

## Acceptance Criteria

The feature is complete when ALL of the following are true. Each criterion is assigned a
stable `AC-N` id. The frontmatter `acceptance_criteria_ids` list is **optional** for
back-compat, but when it is provided, it MUST include every `AC-N` id listed here and nothing
else; that is what `acceptance` uses to drive AC-coverage checks via `business-analyst`.
Leaving `acceptance_criteria_ids` empty disables the business-analyst conditional.

- [ ] **AC-1** — {Concrete, observable behavior — not internal state}
- [ ] **AC-2** — {Another criterion}
- [ ] **AC-3** — {Error / edge case criterion}
- [ ] **AC-4** — {Performance criterion with specific numbers, if relevant}
- [ ] **AC-5** — {Compatibility criterion, if relevant}

**Authoritative definition of done.** The implementing agent validates against this
list before marking any task complete.

## Prerequisites

Steps that must be completed BEFORE implementation begins. Each item is either
already done, or is an explicit task for the implementing agent or a human.

| Prerequisite | Status | Owner | Notes |
|--------------|--------|-------|-------|
| {e.g., Create FCM project in Firebase console} | ⬜ Todo / ✅ Done | Human / Agent | {how to do it} |
| {e.g., Add notification entitlement to app} | ⬜ Todo | Agent | {file to modify} |

*(Remove this section if there are no prerequisites outside of code changes.)*

## Affected Modules and Files

| Module / File | Change type | Notes |
|---------------|-------------|-------|
| {path or module name} | New / Modified / Deleted | {what changes and why} |

Key integration points:
- {Interface or class that new code must implement or call}
- {Existing service or repository that will be extended}

## Technical Approach

{High-level description of HOW the feature will be implemented — not code, but enough
to guide architecture:
- Which pattern to follow (existing or new)
- Data flow: source → transformation → destination
- Key new abstractions (classes, interfaces, modules)
- Error handling strategy
- State management approach (if UI-relevant)}

## Technical Constraints

Rules the implementing agent must follow without deviation:

- {Must use X library — already in project}
- {Must NOT add new dependencies without approval}
- {Must follow Y pattern used elsewhere}
- {Must support API level Z+}
- {Must be KMP-compatible / Android-only}
- {No blocking operations on the main thread}

## Decisions Made

Choices locked in during spec. The implementing agent does NOT revisit these.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| {What was decided} | {The choice} | {Why this over alternatives} |

## Out of Scope

Will NOT be implemented as part of this spec:

- {Behavior or feature explicitly excluded}
- {Edge case deferred to a future spec}
- {Migration or compatibility concern left out}

## Open Questions

Unresolved questions the implementing agent must handle or escalate:

- [ ] {Question} — *blocking / non-blocking*
  - Options: {A}, {B}
  - Recommendation: {preferred}

If none: write "None — spec is complete." and remove this section.

## Future Phases

*(Only when feature was split into phases)*

**Phase 2 — {name}:** {brief description, why deferred}
**Phase 3 — {name}:** {brief description}

Specced separately after Phase 1 is implemented and validated in production.
```

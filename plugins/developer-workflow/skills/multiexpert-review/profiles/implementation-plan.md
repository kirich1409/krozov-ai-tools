---
name: implementation-plan
description: Default profile for implementation plans (Plan Mode output, plan.md files, conversation-described plans). Verdict alphabet PASS/CONDITIONAL/FAIL. Agents selected by tech-match from plan content.

detect:
  frontmatter_type: [implementation-plan, plan]
  path_globs: []
  structural_signatures: []

reviewer_roster:
  primary: []
  optional_if: []

allow_single_reviewer: true

verdicts: [PASS, CONDITIONAL, FAIL]

source_routing:
  plan_mode: EnterPlanMode
  file: edit-in-place
  conversation: inline-revise
---

## Rubric

Generic implementation-plan assessment. Each reviewer applies their expertise:

- Scope of changes clearly described
- Architectural fit — modules, layers, dependency direction
- Technical approach sufficient for implementation without further questions
- Risks named and addressed
- Trade-offs surfaced where multiple valid approaches exist
- Dependencies (code, libraries, services) identified
- Testing approach outlined (if implementation includes test code)

No fixed severity mapping — reviewers judge severity from their expertise.

## Prompt augmentation

(none — reviewers use the generic engine prompt)

## Agent pre-selection heuristic

`reviewer_roster.primary` is intentionally empty. The engine falls back to **tech-match selection**: scan plan content for technology keywords, map to agent expertise, recommend 2–3 agents whose specialties the plan actually touches. Rules:

- **Technology match** — plan must specifically mention technologies, frameworks, or layers the agent specializes in. Generic "architecture" or "security" relevance is NOT enough (e.g., `security-expert` only when plan touches auth, encryption, tokens, or user data; `architecture-expert` only when new modules, dependency direction changes, or public API modifications are involved).
- **Problem-specific value** — would this agent catch issues that others on the panel wouldn't?
- **Gap coverage** — does this agent cover a blind spot that other recommended agents miss?

Prefer 2–3 agents, but quality over quantity — if only 1 is genuinely relevant, recommend 1 (permitted by `allow_single_reviewer: true`). `general-purpose` is a fallback only when no specialist covers a real gap.

## Source routing notes

- **Plan Mode** — on FAIL/CONDITIONAL fix, engine calls `EnterPlanMode` with the issues list.
- **File** — engine edits the plan file directly, adding `## Issues to Resolve` or restructuring inline.
- **Conversation** — engine presents blockers and works through them with the user inline.

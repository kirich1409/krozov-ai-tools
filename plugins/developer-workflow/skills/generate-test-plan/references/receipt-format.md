Referenced from: `plugins/developer-workflow/skills/generate-test-plan/SKILL.md` (§Receipt).

# Test Plan Receipt Format

When this skill is invoked from the `feature-flow` orchestrator, a `slug` argument is passed
explicitly. In that case, in addition to the permanent document, produce a **receipt**
at `swarm-report/<slug>-test-plan.md` that the orchestrator and downstream stages
(`multiexpert-review`, `acceptance`) can consume for receipt-based gating.

The permanent file remains the source of truth. The receipt is metadata + pointer.

Receipt format:

```markdown
---
name: test-plan-receipt
description: Test plan artifact for <slug>
slug: <slug>
type: test-plan-receipt
status: Draft
permanent_path: docs/testplans/<slug>-test-plan.md
source_spec: <path to spec if any, or "inline spec">
review_verdict: pending
review_warnings: []            # populated by multiexpert-review on WARN — list of short strings
review_blockers: []            # populated by multiexpert-review on FAIL — list of short strings
phase_coverage: [Phase 1, Phase 2, ...]
platform: []                   # optional; inherited from the source spec's `platform:` field when present.
                               # Drives platform-aware TC generation and downstream acceptance checks (e.g.,
                               # skip mobile-only TCs on a backend-only target). Leave empty when the spec
                               # did not set it; acceptance falls back to its project-type heuristic.
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Test Plan Receipt: <slug>

**Status:** <status>
**Permanent artifact:** [`docs/testplans/<slug>-test-plan.md`](../docs/testplans/<slug>-test-plan.md)
**Source spec:** <path or description>
**Review verdict:** <verdict>
```

## Field conventions

- `status`: `Draft` right after generation; `Ready` after multiexpert-review returns PASS/WARN;
  `Approved` when the user explicitly signs off; `Mounted` when a user-authored permanent
  file is adopted without regeneration (see `feature-flow/SKILL.md` §1.5 Pre-check).
- `review_verdict`: `pending` at creation; updated by `multiexpert-review` to
  `PASS | WARN | FAIL`; `skipped` on mount (no review occurs).
- `review_warnings` / `review_blockers`: arrays of short strings populated by `multiexpert-review`.
  `review_warnings` is written on WARN verdicts (items d or e of the checklist violated —
  non-blocking); `review_blockers` is written on FAIL (items a, b, or c violated —
  blocks transition to Implement). Both remain empty arrays on PASS / pending / skipped.
  Frontmatter is the single source of truth for review findings — the receipt body does
  not re-list them, keeping downstream YAML parsers authoritative.
- `phase_coverage`: list of phase labels present in the permanent file. Empty list if the
  feature has no phase segmentation.
- `created` / `updated`: ISO dates (`YYYY-MM-DD`). `updated` must change whenever either the
  permanent file or any receipt field is modified.
- Relative path in the markdown link assumes the conventional `swarm-report/` ↔ `docs/`
  sibling layout at the repo root.

## Backward compatibility — standalone invocation without slug

When a user invokes this skill directly (e.g. "create a test plan for X") without the
orchestrator passing a `slug`, the receipt is **not** produced. The permanent file is
still saved under the canonical slug-based filename:

- Permanent file generated at `docs/testplans/<slug>-test-plan.md`, where `<slug>` is
  either provided inline or derived from the feature name per the Slug resolution rules
  in SKILL.md. If the plan may later be consumed by another workflow that mounts an existing
  plan (e.g. `bugfix-flow` → `acceptance` Branch 2), use the eventual orchestrator slug
  at creation time so the file is deterministically mountable without renaming.
- No `swarm-report/<slug>-test-plan.md` receipt is written.
- No `phase_coverage` or receipt metadata tracked elsewhere.

Standalone callers continue to work: the slug-based filename is the single canonical
artifact. Pre-existing `docs/testplans/*-test-plan.md` files authored before this
convention are not auto-migrated — they remain readable by humans, but mount logic
matches only on the exact `<slug>-test-plan.md` path.

---
name: spec
description: Profile for feature specifications (docs/specs/<date>-<slug>.md). Panel of business-analyst + architecture-expert. Rubric checks falsifiable AC, scope boundaries, explicit decisions, prerequisite realism.

detect:
  frontmatter_type: [spec]
  path_globs:
    - "docs/specs/**"
  structural_signatures: []

reviewer_roster:
  primary: [business-analyst, architecture-expert]
  optional_if:
    - when: "auth|token|encryption|PII|credential"
      agent: security-expert
    - when: "SLA|latency|throughput|budget|performance"
      agent: performance-expert
    - when: "a11y|accessibility|user-facing|UI|UX"
      agent: ux-expert

allow_single_reviewer: false

verdicts: [PASS, CONDITIONAL, FAIL]

severity_mapping:
  - items: [acceptance_criteria, prerequisites]
    severity: critical
  - items: [out_of_scope, decisions_made, affected_modules]
    severity: major
  - items: [open_questions_tagged, technical_approach_detail]
    severity: minor

source_routing:
  plan_mode: N/A
  file: edit-in-place
  conversation: inline-revise
---

## Rubric

Reviewers evaluate the spec against these criteria. Each bullet carries the **item ID** (matches `severity_mapping.items`) in parentheses — use the ID verbatim in every Issue title stem so synthesizer aggregation and receipts stay greppable.

### Critical — spec is not implementable without these

- **(acceptance_criteria) Acceptance Criteria are falsifiable** — every AC is a grep-check, diff-check, YAML-parse, fixture-run, or structural-equivalence assertion. «Feels right» or «should be fast» is not acceptable. An implementing agent must know unambiguously when each AC passes.
- **(prerequisites) Prerequisites realistic and complete** — every prerequisite has status (Done / Todo), owner (Human / Agent), and concrete exit criterion (how do we verify it's satisfied). No hand-waved «everything is ready».

### Major — spec is implementable but risky without these

- **(out_of_scope) Out of Scope is explicit** — there is an «Out of Scope» section that enumerates what will NOT be done. Sweeping things under the rug or leaving out-of-scope implied = violation.
- **(decisions_made) Decisions Made have rationale** — each locked decision has a «Rationale» column/line. «We chose X» without «because Y» = violation.
- **(affected_modules) Affected modules/files complete** — table listing every file touched with change type (New / Modified / Renamed / Deleted) and notes. Missing files → implementing agent re-plans mid-implementation.

### Minor — spec is implementable but less clear

- **(open_questions_tagged) Open questions tagged blocking vs non-blocking** — each OQ has explicit tag. Unmarked OQs leave ambiguity.
- **(technical_approach_detail) Technical approach detail** — enough design detail that the implementing agent doesn't need further research. High-level «use pattern X» without concrete locations/contracts = minor issue.

## Prompt augmentation

Reviewers: evaluate the spec against the rubric above AND apply your general expertise (architecture-expert checks dependency direction / module boundaries; business-analyst checks scope / requirements consistency / user value).

**Issue title stem format (mandatory):** `(<item_id>) <violated | partial | satisfied>: <one-line summary>`. Example: `(acceptance_criteria) violated: AC-R4 grep check unsatisfiable given AC-R6 whitelist`. This lets the engine map your issue to `severity_mapping` deterministically — unprefixed Issues fall back to reviewer-assigned severity, losing the profile's intended weighting.

## Verdict policy

Matches engine default for `[PASS, CONDITIONAL, FAIL]`:

- **PASS** — no critical issues, no important improvements, or only minor suggestions
- **CONDITIONAL** — no critical issues but major items from the rubric are violated (strongly recommended to fix before implement)
- **FAIL** — any critical rubric item violated OR any blocker from reviewer expertise

## No receipt

Spec profile does not write a receipt. Verdict is a conversation-level output consumed by `write-spec` Phase 4 loop (and, in the future, by `decompose-feature` if it runs spec review before decomposition).

## Rationale (why this profile exists)

Before this profile, `write-spec` Phase 4.3 invoked the review engine on a spec artifact, and the detector silently classified it as an implementation-plan. The implementation-plan rubric is generic tech-review; it doesn't specifically check whether AC are falsifiable, whether Out of Scope is explicit, whether decisions have rationale, etc. Specs ended up reviewed by a rubric that didn't match their structure. This profile closes that drift.

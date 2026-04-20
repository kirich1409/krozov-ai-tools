Referenced from: `plugins/developer-workflow/skills/acceptance/SKILL.md` (§Step 4: Aggregate and Write Receipt).

# Acceptance — Aggregation, Receipt Format, and Routing

Read frontmatter of each `swarm-report/<slug>-acceptance-<check>.md` first (verdict +
severity + confidence + domain_relevance + blocked_on). Read the body only if
`verdict != PASS`. Do not inline artifact bodies — link them.

**Missing per-check artifact.** Step 2.5 writes a stub for skipped `code-reviewer`; Step 3.3
writes an artifact even on build-smoke failure. If a planned per-check artifact is
nonetheless missing at aggregation time, treat the check as `verdict: FAIL` with
`blocked_on: per-check artifact missing` — do not silently drop it. `blocked_on` is the
canonical field for surfacing unresolved conditions per the per-check schema; no separate
`error:` field exists.

## Aggregation — PoLL rules

Acceptance uses the same aggregation protocol as `multiexpert-review` (see
`multiexpert-review/SKILL.md` §"Step 4 — Synthesize verdict"). Input shape is per-check
(not per-reviewer), reduction logic identical:

| Signal | Action |
|---|---|
| **`critical` severity** from any sub-check with `confidence: high` | → Blocker. Aggregated Status = `FAILED`. |
| **Same issue** (same file:line or same AC id) raised by 2+ sub-checks independently | → Escalate to `critical` regardless of individual severity. Multiple specialists seeing the same problem = real problem. |
| **`major` severity** from a sub-check with `domain_relevance: high` | → Important. Aggregated Status = `PARTIAL` if not already escalated. |
| **Contradicting verdicts** (one `PASS`, another `FAIL` on the same item) | → "Uncertainty — requires decision". Aggregated Status = `PARTIAL`, contradiction listed in the receipt. |
| **`minor` severity** or **`low` confidence** from a single check | → Note, not blocker. Does not affect aggregated Status. |
| **`low` domain_relevance** check flagging an issue | → Note, weight lower. |

**Bug severities (P0–P3) remain the primary routing axis** for
`feature-flow`/`bugfix-flow`. Any P0/P1 bug reported by any sub-check maps directly to
`FAILED` regardless of the PoLL above; PoLL layers additional rules on top for cases not
covered by bug severity alone (e.g. AC coverage FAIL without an associated P0 bug).

## Aggregated Status — final table

| Input | Aggregated Status |
|---|---|
| All checks `PASS` or `SKIPPED`, no P0–P3 bugs, no PoLL blocker | `VERIFIED` |
| Any P0 / P1 bug **or** PoLL blocker (critical high-confidence, or 2+-agent escalation) | `FAILED` |
| P2 / P3 bugs only, **or** PoLL important, **or** contradicting verdicts, **or** any `WARN` not otherwise classified | `PARTIAL` |
| `manual-tester` returned `WARN` with `blocked_on` | `PARTIAL` with `blocked_on` surfaced in Summary |

## Receipt format

Save to `swarm-report/<slug>-acceptance.md`. Legacy fields preserved; new sections appended.

```markdown
# Acceptance: <slug>

**Status:** VERIFIED / FAILED / PARTIAL
**Date:** <date>
**Type:** Feature / Bug fix
**Project type:** <project_type>
**Project type override:** <spec | user | none>
**Ecosystem:** <ecosystem>
**Spec source:** [what was used]
**Test plan:** [resolved permanent path / generated on-the-fly / none]
**test_plan_source:** receipt | mounted | on-the-fly | absent
**Context artifacts:** [paths to research.md, debug.md, implement.md, quality.md used as input]

## Idempotency Hashes
- `diff_hash`: <sha256 of `git diff <base>...HEAD`>
- `spec_hash`: <sha256 of the spec file bytes, or `null` if no file spec>
- `test_plan_hash`: <sha256 of the permanent test plan, or `null`>

These three hashes drive the Re-verification Loop decision table; downstream orchestrators
don't need to read them.

## Check Plan
- list of checks that ran, one per line, with their trigger
- e.g. `business-analyst` (AC coverage) — triggered by spec.acceptance_criteria_ids
- e.g. `ux-expert` — not triggered (no design.figma)

## Check Results

| Check | Agent / Tool | Verdict | Severity | Confidence | Artifact |
|---|---|---|---|---|---|
| Manual QA | manual-tester | … | … | … | swarm-report/<slug>-acceptance-manual.md |
| Code review | code-reviewer | … | … | … | swarm-report/<slug>-acceptance-code.md |
| AC coverage | business-analyst | … | … | … | swarm-report/<slug>-acceptance-ac-coverage.md |
| Design | ux-expert | … | … | … | swarm-report/<slug>-acceptance-design.md |
| A11y | ux-expert | … | … | … | swarm-report/<slug>-acceptance-a11y.md |
| Security | security-expert | … | … | … | swarm-report/<slug>-acceptance-security.md |
| Performance | performance-expert | … | … | … | swarm-report/<slug>-acceptance-performance.md |
| Architecture | architecture-expert | … | … | … | swarm-report/<slug>-acceptance-architecture.md |
| Build config | build-engineer | … | … | … | swarm-report/<slug>-acceptance-build-config.md |
| DevOps | devops-expert | … | … | … | swarm-report/<slug>-acceptance-devops.md |
| Build smoke | bash | … | … | … | swarm-report/<slug>-acceptance-build.md |

## Convergence signals
Issues raised by 2+ sub-checks independently. Strongest signal of real problems.
List one line each with the file:line or AC id and the list of checks that flagged it.

## Summary
[1–3 sentences. If PARTIAL with blocked_on — state the blocker first. If any convergence
signal — mention it in the first sentence.]

## Test Results
- Total: [n] | Passed: [n] | Failed: [n] | Blocked: [n]

## Bugs Found
[List by severity — P0 first, then P1, P2, P3. Link each to the per-check artifact that
reported it.]

## Bug Reproduction Check (bug fix only)
- Reproduction steps from debug.md: [executed / not applicable]
- Bug reproduces after fix: [yes / no]

## Recommendation
[Ship / Do not ship / Ship with known issues — and why]
```

## Routing (consumed by orchestrators)

- **VERIFIED** → `create-pr` (or mark existing PR ready for review).
- **FAILED** with P0/P1 and obvious cause → `implement` with the bug list as input. Max 3
  round-trips.
- **FAILED** with P0/P1 and unclear cause → `debug` first, then `implement`.
- **FAILED** with P0/P1 requiring regression coverage → `test-plan` append `## Regression TC`,
  then `implement`.
- **PARTIAL** with P2/P3 only or WARN — orchestrator asks the user: fix now or ship with
  known issues (continue to `create-pr`, include in PR description).
- **PARTIAL** with `blocked_on` — surface the blocker; do not continue until resolved.

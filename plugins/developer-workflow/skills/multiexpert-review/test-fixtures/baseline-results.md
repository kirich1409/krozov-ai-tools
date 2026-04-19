# Smoke-test baseline — captured 2026-04-19

Captured manually via direct agent invocation on the fixtures in this directory. Asserted **structural** properties only; content of individual issues is PoLL-stochastic and not part of the baseline.

## Fixture: `plan.md` (implementation-plan profile)

**Profile detection:** `implementation-plan` via frontmatter `type: plan`
**Reviewer invoked:** `architecture-expert` (tech-match on cache layer / modules)
**Verdict alphabet used:** `PASS / CONDITIONAL / FAIL` (per profile `verdicts`)
**Severity labels in output:** `critical | major | minor` (engine-standard)
**Structural properties verified:**
- Output follows engine template (Summary / Domain Relevance / Issues)
- Issues include all required fields (severity, confidence, issue, suggestion)
- No engine error prefix (normal review path)
- No receipt written (profile has no `receipt:` section)

**Sample observed findings:** 6 issues total (2 major, 3 minor, 1 major). Touched: cache invalidation coverage, multi-instance consistency contract, write ordering, domain/infra boundary, fallback contract specificity, latency-budget decomposition. All architecture-domain findings — consistent with invoked agent specialty.

## Fixture: `test-plan.md` (test-plan profile)

**Profile detection:** `test-plan` via frontmatter `type: test-plan` (frontmatter path takes precedence over structural signatures)
**Reviewer invoked:** `business-analyst` (per profile `reviewer_roster.primary`)
**Optional_if trigger activated:** `performance-expert` flagged as recommended (artifact mentions `latency`, `p99`, matching `SLA|latency|throughput|budget` regex) — the reviewer noted this in their output but the actual panel was kept to business-analyst for this lightweight smoke-test
**Verdict alphabet used:** `PASS / WARN / FAIL` (per profile `verdicts`)
**Severity mapping applied:**
- (a), (b), (c) items → `critical`
- (d), (e) items → `major`
**Structural properties verified:**
- 5-item checklist evaluated explicitly (each item marked satisfied / violated)
- Final verdict derived from profile verdict policy: `FAIL` because (b) and (c) violated (critical)
- Output follows engine template
- Receipt path resolved to `swarm-report/smoke-test-test-plan-fixture-test-plan.md` (not written in smoke-test since no live pipeline)

**Sample observed findings:** 6 issues total — items (b), (c) flagged critical; items (a), (d), (e) flagged with matching severities; verdict FAIL per profile policy. Reviewer also raised open questions about test infrastructure and PII handling — domain-appropriate.

## Fixture: `spec.md` (spec profile)

**Profile detection:** `spec` via frontmatter `type: spec`
**Reviewer invoked:** `business-analyst` (first of `reviewer_roster.primary: [business-analyst, architecture-expert]`)
**Verdict alphabet used:** `PASS / CONDITIONAL / FAIL` (per profile `verdicts`)
**Severity mapping applied:**
- items `acceptance_criteria`, `prerequisites` → `critical`
- items `out_of_scope`, `decisions_made`, `affected_modules` → `major`
- items `open_questions_tagged`, `technical_approach_detail` → `minor`
**Structural properties verified:**
- Issues titled with rubric-item keys (`acceptance_criteria violated`, `prerequisites violated`, etc.) per profile prompt augmentation contract
- Severities assigned per `severity_mapping` of the profile
- Final verdict FAIL — both critical items violated
- No receipt written (profile has no `receipt:` section)

**Sample observed findings:** 7 issues — all rubric items evaluated, two critical (AC + prerequisites), three major (out_of_scope, decisions, modules), two minor (OQ, technical_approach). This is the **expected** output for a deliberately-skeletal spec fixture. Verdict FAIL is correct per profile policy.

## Fixture: `unknown-artifact.md` (no profile)

**Profile detection:** none — all four detection stages fall through:
1. No hint prefix in invocation args
2. No YAML frontmatter at all → stage 2 falls through
3. No path-glob in the inventory matches `test-fixtures/unknown-artifact.md`
4. Structural signatures: test-plan signatures don't match (no `## Test Cases`, no TC-ID pattern); spec has no structural_signatures; implementation-plan has no structural_signatures
5. → fallback: engine prompts user with `AskUserQuestion` listing `PROFILE_INVENTORY`

**Structural property verified:** engine does **not** silently default to implementation-plan. Operator must explicitly pick a profile.

This path was not fully executed (would require interactive user prompt); behavior documented per `SKILL.md` Step 1 Detection precedence and spec AC-D3.

## Summary table

| Fixture | Profile detected | Detection source | Verdict alphabet | Verdict | Structural check |
|---------|------------------|------------------|------------------|---------|------------------|
| `plan.md` | implementation-plan | frontmatter | PASS/CONDITIONAL/FAIL | CONDITIONAL (implied by 3 major issues) | ✓ |
| `test-plan.md` | test-plan | frontmatter | PASS/WARN/FAIL | FAIL | ✓ |
| `spec.md` | spec | frontmatter | PASS/CONDITIONAL/FAIL | FAIL | ✓ |
| `unknown-artifact.md` | (none — ask user) | fallback stage 5 | N/A | N/A | ✓ (documented) |

## What this baseline is NOT

- Not a pre/post comparison — the pre-refactor baseline was not captured before commit `8608cbe`. For future regression testing, use this baseline as the post-reference and capture pre-baseline before the next structural change.
- Not a multi-run modal average — PoLL stochasticity means content of individual findings will differ next run. Only the structural properties listed above should be stable across runs.
- Not a full acceptance of AC-E2/E3 from `docs/specs/2026-04-19-multiexpert-review.md` — that spec required 3 runs per fixture; this is a single-run capture as a lightweight smoke-test. Full compliance would require a test harness not built here.

## Re-running

For future refactors of `multiexpert-review`, re-run each fixture after the change and compare **structural** properties (profile detected, reviewer roster, verdict alphabet, verdict label, engine error prefix presence) against this baseline. Any divergence is a behavioral regression signal.

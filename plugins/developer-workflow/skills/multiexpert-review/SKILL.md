---
name: multiexpert-review
description: >-
  This skill should be used when the user wants a plan, spec, or test-plan reviewed by a
  panel of independent expert agents (PoLL — Panel of LLM Evaluators — protocol) before
  committing. Triggers: "review the plan", "review the spec", "review the test-plan",
  "multi-expert review", "panel review", "проверь план", "оцени план", "проверь спецификацию",
  "проверь тест-план". Do NOT use for code review (use code-reviewer) or for generating
  alternative designs (use design-options).
---

# Multi-Expert Review

Engine for multi-agent independent review of a documentation artifact (plan, spec, test-plan, etc.) followed by consensus synthesis. Artifact-specific semantics live in **profiles** at `profiles/<name>.md`. The engine here is artifact-agnostic — it discovers and routes, but never encodes one artifact type's rubric in its own body.

## Why This Exists

A single reviewer has blind spots. Different experts catch different problems — an architect spots coupling issues, a security engineer finds auth gaps, a performance expert flags N+1 queries. Independent parallel review prevents groupthink: each agent forms their own opinion before seeing anyone else's, which surfaces more diverse issues than sequential discussion.

The core value is not that individual reviews are better — it's that **multiple independent perspectives surface issues that any single reviewer would miss**, and the structured synthesis makes disagreements and consensus explicit rather than hidden.

## Protocol: PoLL (Panel of LLM Evaluators)

The review follows the Panel of LLM Evaluators protocol:

1. **Independent parallel review** — each agent reviews the artifact from their expertise, unaware of other reviewers
2. **Structured output** — every agent returns issues with severity and confidence scores
3. **Confidence-weighted synthesis** — the orchestrator aggregates results, weighting by domain relevance
4. **Explicit uncertainty** — disagreements between agents surface as "requires decision", not silently resolved

## Engine invariants (not overridable by profiles)

Profiles MUST NOT declare these — they are engine constants:

- **Review output structure** — Summary / Domain Relevance / Issues with severity+confidence+issue+suggestion (fixed in Step 3 prompt)
- **Aggregation rules** — convergence → escalate, contradictions → surface, confidence-weighting (fixed in Step 4)
- **State machine transitions** — fixed in this file
- **Revise-loop cap** — max 3 cycles (engine constant)
- **Review prompt template skeleton** — profiles add via `## Prompt augmentation`, never replace

See `profiles/README.md` for the negative-list of forbidden frontmatter fields and the `FORBIDDEN_PROFILE_FIELD` error behavior.

## Workflow

```
┌─ Read artifact, detect profile, load it
│       ↓
│  Discover agents, pre-select per profile.reviewer_roster
│       ↓
│  Spawn selected agents in parallel (independent review)
│       ↓
│  Collect all reviews
│       ↓
│  Synthesize verdict (engine aggregation, profile-supplied verdict alphabet)
│       ↓
│  Present verdict + update receipt (if profile has one)
│       ↓
│  ┌─ PASS → Done (proceed to implementation)
│  ├─ CONDITIONAL / WARN → see profile verdict policy
│  └─ FAIL → Fix artifact at source → Re-review ─┐
│                                                │
└────────────────────────────────────────────────┘
                              (max 3 review cycles)
```

### Allowed transitions

```
Read+Detect  → Select Agents
Select       → Parallel Review
Review       → Synthesize
Synthesize   → Verdict
Verdict:PASS → Done
Verdict:COND → Fix Artifact   (profiles whose alphabet includes CONDITIONAL)
Verdict:WARN → Done           (profiles whose alphabet includes WARN)
Verdict:FAIL → Fix Artifact
Fix Artifact → Re-review (back to Parallel Review with same agents + locked profile)
Re-review    → Synthesize → Verdict (same cycle)
```

**Forbidden:** skipping Read+Detect → Review, or re-running detection in cycle ≥2 (profile is locked at cycle 1).

**Cycle cap:** 3 total (initial + 2 re-reviews). Still FAIL after cycle 3 → escalate to user.

## Persistence (compaction resilience)

Save state to `./swarm-report/multiexpert-review-<slug>-state.md` (or `multiexpert-review-<YYYYMMDD-HHMM>-state.md` if no slug known).

**Slug source** (in priority order):
1. Explicit caller args (`slug:` field)
2. Artifact frontmatter `slug:` field
3. Artifact filename without extension
4. Timestamp fallback

**Legacy read:** if the slug-qualified file doesn't exist, try `./swarm-report/plan-review-state.md` (legacy from pre-rename era). If found, copy content into the new slug-qualified name and continue on the new file. Do not delete the legacy file — user decides.

**Always write:** new slug-qualified name.

State file structure:

```markdown
# Multi-Expert Review State
Source: {plan_mode | file:<path> | conversation}
Profile: {implementation-plan | test-plan | spec | ...}   # locked at cycle 1
Profile source: {caller_hint | frontmatter | path | signature | user_prompt}
Cycle: {1 | 2 | 3} of 3
Status: {detecting | reviewing | synthesizing | fixing | done}

## Artifact Summary
{goal, technologies, scope — extracted in Step 1}

## Selected Agents
- {agent1} (recommended)
- {agent2} (recommended)

## Reviews Completed
- [x] {agent1} — {severity counts: N critical, M major, K minor}
- [ ] {agent2} — pending

## Verdict History
### Cycle 1: {PASS | CONDITIONAL | FAIL | WARN}
- Blockers: {list}
- Improvements: {list}

### Cycle 2: ...
```

Update after each significant step. Re-read before each action — skip completed steps.

## Step 1 — Read artifact and detect profile

Locate the artifact. Check sources in order:

1. **Active Plan Mode output** — artifact is in conversation context
2. **File reference** — user points to a `.md` file; read it
3. **Conversation context** — user described it inline; extract
4. **Ask** — if none of the above

Track the source (Plan Mode / file / conversation) — Step 5 needs this.

### Detect profile

Follow the precedence chain defined in `profiles/README.md` §Detection precedence (canonical source). Engine enforces error semantics from that section — `UNKNOWN_PROFILE_HINT` on unknown caller hint, never silent fallback to a default profile.

Cycle-locking, profile validation (negative-list), and inventory-mismatch checks — see `profiles/README.md`. Engine applies these on every invocation before Step 2.

## Step 2 — Discover and select agents

### Discovery

Find real agents via `Glob("**/agents/*.md")` + built-in subagents from system prompt. Read each agent's frontmatter to confirm. Never invent phantom agents.

**Short-name collision tie-break:** if the same agent short-name resolves to multiple files (e.g., two plugins define `security-expert`), prefer first match in this order: (1) same-plugin as the caller skill, (2) sibling `developer-workflow-*` plugin, (3) any other source. If still ambiguous, fail loud with the dedicated category: `[multiexpert-review ERROR] AMBIGUOUS_REVIEWER: short-name <name> resolves to <paths>`. Distinct from `NO_REVIEWERS_AVAILABLE` (which covers the "agents missing entirely" path) so consumers can branch on intent. In practice the `developer-workflow-*` family guarantees unique short-names — this guard only triggers on non-family plugin conflicts.

### Selection per profile

Use `profile.reviewer_roster`:

- **`primary`** — mandatory roster. For each agent: if installed, include; if missing, skip.
- **`optional_if`** — for each entry: if `when` regex matches artifact content AND agent is installed, include.
- **Empty primary + empty optional_if match** — fall back to **tech-match selection** (implementation-plan profile relies on this): scan artifact for technology keywords, score agents by technology match / problem-specific value / gap coverage, recommend 2–3.

### Single-reviewer guard

If exactly 1 agent ended up selected:
- If `profile.allow_single_reviewer: true` — proceed. Final verdict carries a `## Review Mode: single-perspective` marker in the output text (not in any receipt — receipt schemas are profile-declared and do not include `review_mode`).
- If `profile.allow_single_reviewer: false` — fail loud `[multiexpert-review ERROR] NO_REVIEWERS_AVAILABLE: profile <name> requires panel, only <agent> available`.

If 0 agents — same `NO_REVIEWERS_AVAILABLE` error regardless of flag.

### User confirmation

Use `AskUserQuestion` with `multiSelect: true`, recommended agents first with one-sentence reason. User may override.

**Explicit user override:** if the user's prompt named specific agents (e.g., "review with kotlin-engineer"), skip discovery confirmation and use those.

## Step 3 — Parallel independent review

Spawn each selected agent in a **single message** (parallel) via the `Agent` tool.

### Review prompt (engine skeleton)

```
You are reviewing a {artifact_type} as a {agent_role} expert.

## The Artifact
{full_artifact_text}

{PROFILE_PROMPT_AUGMENTATION}

## Your Task
Review this artifact from the perspective of your expertise. Be specific and actionable.

## Required Output Format

You MUST structure your response exactly as follows:

### Summary
2-3 sentence overall assessment from your perspective.

### Domain Relevance
State one of: high | medium | low — how much does this artifact touch your area of expertise.

### Issues
For each issue, use this exact structure:

**Issue N: {short title}**
- **severity**: critical | major | minor
- **confidence**: high | medium | low
- **issue**: what the problem is (1-2 sentences)
- **suggestion**: what to do instead (1-2 sentences)

Severity guide:
- critical = blocks implementation or will cause serious failures
- major = significantly affects quality, performance, or maintainability
- minor = nice to have, low risk if skipped

Confidence guide:
- high = this is squarely in your domain and you're certain
- medium = relevant to your domain but you could be wrong
- low = outside your core expertise but worth flagging

Respond in the same language the artifact is written in.
```

`{PROFILE_PROMPT_AUGMENTATION}` is substituted from the profile's `## Prompt augmentation` section (empty for profiles that don't define one).

### Invariant rules

- **Never share one agent's review with another** — independence is the whole point
- **All agents get the same artifact text** — no summaries or interpretations
- **Prompt skeleton is engine-fixed** — profiles only add via augmentation section, never replace

## Step 4 — Synthesize verdict

Read all reviews. The engine aggregation rules (non-overridable):

| Signal | Action |
|--------|--------|
| Critical severity with high confidence | Blocker |
| Same issue from 2+ agents independently | Escalate to critical regardless of individual severity |
| Major severity with high domain_relevance | Important improvement |
| Contradicting opinions between agents | Surface as "Uncertainty — requires decision"; do NOT silently pick one |
| Minor severity OR low confidence (single agent) | Suggestion |
| Low domain_relevance agent flagging an issue | Note but weight lower |

Profile contributes:

- **`verdicts`** — alphabet (e.g., `[PASS, CONDITIONAL, FAIL]` or `[PASS, WARN, FAIL]`)
- **`severity_mapping`** — for checklist-based profiles (e.g., test-plan items a-e)

### Verdict format

```
## Multi-Expert Review Verdict: {PASS | CONDITIONAL | WARN | FAIL}

### Blockers (must fix)
- {issue} — raised by {agent(s)}, severity: critical
  Suggestion: {what to do}

### Important Improvements (strongly recommended)
- {issue} — raised by {agent(s)}, confidence: {level}

### Suggestions (nice to have)
- {issue}

### Uncertainties (requires your decision)
- {topic} — {Agent A} says X, {Agent B} says Y

### Consensus
{what all agents agreed on}

## Review Mode: single-perspective       # only when single-reviewer path was taken
```

**Single-agent case:** skip cross-referencing (no convergence / uncertainty sections). Present issues directly; add the `## Review Mode: single-perspective` marker.

### Verdict criteria

- **PASS** — no blockers, no important improvements, only minor suggestions
- **CONDITIONAL** (only in alphabets containing it) — no blockers, but important improvements would significantly affect quality
- **WARN** (only in alphabets containing it) — blockers satisfied but secondary items (e.g., test-plan (d)/(e)) violated; pipeline continues
- **FAIL** — has blockers

## Step 5 — Post-review action

### Fix routing

Per `profile.source_routing`:

| Source | Action (default) |
|--------|------------------|
| **Plan Mode** | `EnterPlanMode` with issues list |
| **File** | Edit the file directly (add `## Issues to Resolve` or restructure inline) |
| **Conversation** | Present issues and work through inline with user |

Profiles may override or mark actions as `N/A` for sources they don't support.

### Receipt integration

If `profile.receipt` is present:
- Resolve `receipt.path_template` by substituting `<slug>`
- For each field in `receipt.fields_to_update`, write the corresponding value derived from the verdict (e.g., `review_verdict: WARN`, `review_warnings: [...]`, `review_blockers: [...]`)
- If profile path is `swarm-report/...` — create if missing (respecting generate-test-plan's receipt contract)

If `profile.receipt` is absent — skip receipt writing.

### Verdict handling

- **PASS** — confirm artifact is ready; done.
- **CONDITIONAL** — present improvements; ask user; fix per `source_routing` if confirmed.
- **WARN** — pipeline continues; engine records warnings in receipt; no revise-loop.
- **FAIL** — fix per `source_routing` without asking; auto re-run review on same agents + same profile; update state file with cycle N and new verdict. After cycle 3 still FAIL → escalate to user.

## Error semantics

All engine errors produce exactly this prefix on the first line of output:

```
[multiexpert-review ERROR] <CATEGORY>: <details>
```

Categories:

- `UNKNOWN_PROFILE_HINT` — caller hint not in inventory
- `FORBIDDEN_PROFILE_FIELD` — profile frontmatter contains forbidden field
- `NO_REVIEWERS_AVAILABLE` — no agents remain after discovery/filtering, or panel required but single
- `AMBIGUOUS_REVIEWER` — short-name resolves to multiple agent files after the family tie-break
- `PROFILE_INVENTORY_MISMATCH` — README list vs. `profiles/*.md` presence disagree
- `ROUTING_NOT_SUPPORTED` — engine reached Step 5 with a source the profile declared `N/A` in `source_routing`

Consumers (`feature-flow`, `write-spec`, etc.) detect this prefix to distinguish engine errors from ordinary review FAIL verdicts.

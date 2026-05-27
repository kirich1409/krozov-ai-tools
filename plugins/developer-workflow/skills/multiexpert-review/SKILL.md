---
name: multiexpert-review
description: >-
  Use when the user wants a plan, spec, or test-plan reviewed by a panel of independent
  expert agents (PoLL — Panel of LLM Evaluators — protocol) before committing.
  Triggers: "review the plan", "review the spec", "review the test-plan",
  "multi-expert review", "panel review", "validate the approach", "sanity check this",
  "what did I miss?", "review the spec", "review the test-plan",
  "evaluate the plan". Do NOT use for code review (use code-reviewer).
---

# Multi-Expert Review

Engine for multi-agent independent review of a documentation artifact (plan, spec, test-plan, etc.) followed by consensus synthesis. Artifact-specific semantics live in **profiles** at `profiles/<name>.md`. The engine here is artifact-agnostic — it discovers and routes, but never encodes one artifact type's rubric in its own body.

Protocol is PoLL (Panel of LLM Evaluators): independent parallel review per agent, structured severity/confidence output, confidence-weighted synthesis, disagreements surfaced as "requires decision" rather than silently resolved.

Each reviewing agent must check the artifact against the `## Non-negotiables` sections in applicable `CLAUDE.md` files (project root, global, plugin-specific) before forming their opinion. Any proposed approach that violates a non-negotiable is automatically a blocker — critical severity, confidence 100, not subject to the reporting filter or trade-off discussion.

## Engine invariants (not overridable by profiles)

Profiles MUST NOT declare these — they are engine constants:

- **Review output structure** — Summary / Domain Relevance / Issues with severity+confidence+issue+suggestion (fixed in Step 3 prompt)
- **Aggregation rules** — convergence → escalate, contradictions → surface, confidence-weighting (fixed in Step 4)
- **State machine transitions** — fixed in this file
- **Revise-loop cap** — max 3 cycles (engine constant)
- **Review prompt template skeleton** — profiles add via `## Prompt augmentation`, never replace

See `profiles/README.md` for the negative-list of forbidden frontmatter fields and the `FORBIDDEN_PROFILE_FIELD` error behavior.

## Workflow

Read artifact + detect profile → discover agents, pre-select per `profile.reviewer_roster` → spawn agents in parallel for independent review → collect reviews → synthesize verdict (engine aggregation + profile-supplied verdict alphabet) → present verdict + update receipt (if profile has one) → PASS done; CONDITIONAL / WARN per profile policy; FAIL → fix artifact at source → re-review (back to parallel review with same agents + locked profile).

**Forbidden:** skipping Read+Detect → Review, or re-running detection in cycle ≥2 (profile is locked at cycle 1).

**Cycle cap:** 3 total (initial + 2 re-reviews). Still FAIL after cycle 3 → escalate to user.

## Persistence (compaction resilience)

Save state to `./swarm-report/multiexpert-review-<slug>-state.md` (or `multiexpert-review-<YYYYMMDD-HHMM>-state.md` if no slug known). Follow the persistent-state template conventions from `~/.claude/CLAUDE.md` § Context compaction resilience.

**Slug source** (priority order): explicit caller args (`slug:`), artifact frontmatter `slug:`, artifact filename without extension, timestamp fallback.

**Legacy read:** if the slug-qualified file doesn't exist, try `./swarm-report/plan-review-state.md` (legacy from pre-rename era). If found, copy content into the new slug-qualified name and continue on it. Do not delete the legacy file — user decides. Always write to the new slug-qualified name.

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
- [x] {agent1} — {N critical, M major, K minor}
- [ ] {agent2} — pending

## Verdict History
### Cycle 1: {PASS | CONDITIONAL | FAIL | WARN}
- Blockers: {list}
- Improvements: {list}
```

Re-read the file before each action — skip completed steps.

## Step 1 — Read artifact and detect profile

Locate the artifact in this order: (1) active Plan Mode output in conversation, (2) file reference (user points to a `.md`), (3) inline description in conversation, (4) ask. Track the source — Step 5 needs it.

**Detect profile** — follow the precedence chain in `profiles/README.md` §Detection precedence (canonical source). Engine enforces error semantics from that section: `UNKNOWN_PROFILE_HINT` on unknown caller hint, never silent fallback to a default profile. Cycle-locking, profile validation (negative-list), and inventory-mismatch checks also live in `profiles/README.md` — applied on every invocation before Step 2.

## Step 2 — Discover and select agents

### Discovery

Find real agents via `Glob("**/agents/*.md")` + built-in subagents from system prompt. Read each agent's frontmatter to confirm. Never invent phantom agents.

**Short-name collision tie-break:** prefer first match in order: (1) same-plugin as caller, (2) sibling `developer-workflow-*` plugin, (3) any other source. Still ambiguous → fail loud with `[multiexpert-review ERROR] AMBIGUOUS_REVIEWER: short-name <name> resolves to <paths>`. Distinct from `NO_REVIEWERS_AVAILABLE`. The family guarantees unique short-names — this only triggers on non-family conflicts.

### Selection per profile

Use `profile.reviewer_roster`:

- **`primary`** — mandatory roster. Include if installed, skip if missing.
- **`optional_if`** — for each entry, include if `when` regex matches artifact content AND agent is installed.
- **Empty primary + no optional match** — fall back to tech-match selection (implementation-plan profile relies on this): scan artifact for technology keywords, score agents by technology match / problem-specific value / gap coverage, recommend 2–3.

### Single-reviewer guard

Exactly 1 agent selected:
- `profile.allow_single_reviewer: true` → proceed. Verdict carries `## Review Mode: single-perspective` marker (output text only; receipt schemas are profile-declared and do not include `review_mode`).
- `profile.allow_single_reviewer: false` → fail loud `[multiexpert-review ERROR] NO_REVIEWERS_AVAILABLE: profile <name> requires panel, only <agent> available`.

0 agents → same `NO_REVIEWERS_AVAILABLE` error regardless of flag.

### User confirmation

Use `AskUserQuestion` with `multiSelect: true`, recommended agents first with one-sentence reason. If the user's prompt named specific agents (e.g., "review with kotlin-engineer"), skip discovery confirmation and use those.

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

### Summary
2-3 sentence overall assessment from your perspective.

### Domain Relevance
One of: high | medium | low — how much this artifact touches your expertise.

### Issues
For each issue:

**Issue N: {short title}**
- **severity**: critical | major | minor
- **confidence**: high | medium | low
- **issue**: what the problem is (1-2 sentences)
- **suggestion**: what to do instead (1-2 sentences)

Severity: critical = blocks implementation; major = significantly affects quality/perf/maintainability; minor = nice-to-have.
Confidence: high = squarely in your domain; medium = relevant but could be wrong; low = outside core expertise.

Respond in the same language the artifact is written in.
```

`{PROFILE_PROMPT_AUGMENTATION}` is substituted from the profile's `## Prompt augmentation` section (empty when none defined).

### Invariant rules

- **Never share one agent's review with another** — independence is the whole point.
- **All agents get the same artifact text** — no summaries or interpretations.
- **Prompt skeleton is engine-fixed** — profiles only add via augmentation, never replace.

## Step 4 — Synthesize verdict

Read all reviews. Engine aggregation rules (non-overridable):

| Signal | Action |
|--------|--------|
| Critical severity, high confidence | Blocker |
| Same issue from 2+ agents independently | Escalate to critical regardless of individual severity |
| Major severity, high domain_relevance | Important improvement |
| Contradicting opinions between agents | Surface as "Uncertainty — requires decision"; never silently pick one |
| Minor severity OR low confidence (single agent) | Suggestion |
| Low domain_relevance flag | Note, weight lower |

Profile contributes `verdicts` (alphabet, e.g. `[PASS, CONDITIONAL, FAIL]` or `[PASS, WARN, FAIL]`) and `severity_mapping` (for checklist-based profiles like test-plan items a-e).

### Verdict format

```
## Multi-Expert Review Verdict: {PASS | CONDITIONAL | WARN | FAIL}

### Blockers (must fix)
- {issue} — raised by {agent(s)}, severity: critical / Suggestion: {what to do}

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

**Single-agent case:** skip cross-referencing sections. Present issues directly; add the `## Review Mode: single-perspective` marker.

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
| **Conversation** | Surface highest-severity item first, ONE question per round, work through item by item. Never dump the full list. |

Profiles may override or mark actions as `N/A` for sources they don't support.

### Receipt integration

If `profile.receipt` is present, resolve `receipt.path_template` by substituting `<slug>`, then write each `receipt.fields_to_update` field with the derived value (e.g., `review_verdict: WARN`, `review_warnings: [...]`, `review_blockers: [...]`). For `swarm-report/...` paths — create if missing (respects generate-test-plan's receipt contract). If `profile.receipt` is absent, skip receipt writing.

### Verdict handling

- **PASS** — confirm artifact is ready; done.
- **CONDITIONAL** — present improvements in chat as bullets (max 5; group by category if more). ONE question if a user decision is needed. Fix per `source_routing` once confirmed.
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

Consumers (e.g. `write-spec`) detect this prefix to distinguish engine errors from ordinary review FAIL verdicts.

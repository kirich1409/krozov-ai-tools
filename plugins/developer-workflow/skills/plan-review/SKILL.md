---
name: plan-review
description: >-
  Multi-agent review of an implementation plan using the PoLL (Panel of LLM Evaluators) consensus
  protocol. The plan can come from any source — Plan Mode output, a file, or conversation context.
  Use this skill when the user asks to "review the plan", "get feedback on the plan",
  "check the plan", "validate the approach", "review with different perspectives", "multi-agent
  review", "план ревью", "проверь план", "оцени план", or after exiting Plan Mode and wanting
  independent expert evaluation before implementation. Also invoke when the user says "is this
  plan good?", "what did I miss?", "sanity check this", "review this before I start", "check my
  approach", or wants multiple viewpoints on an implementation strategy — even if the plan is
  described inline in the message or referenced as a file. Do NOT invoke for code review (use
  code-reviewer agent instead) or PR review.
---

# Plan Review

Multi-agent independent review of an implementation plan, followed by consensus synthesis.

## Why This Exists

A single reviewer has blind spots. Different experts catch different problems — an architect
spots coupling issues, a security engineer finds auth gaps, a performance expert flags N+1 queries.
Independent parallel review prevents groupthink: each agent forms their own opinion before seeing
anyone else's, which surfaces more diverse issues than sequential discussion.

The core value is not that individual reviews are better — it's that **multiple independent
perspectives surface issues that any single reviewer would miss**, and the structured synthesis
makes disagreements and consensus explicit rather than hidden.

## Protocol: PoLL (Panel of LLM Evaluators)

The review follows the Panel of LLM Evaluators protocol, backed by research showing that
independent panels outperform iterative debates (debates cause conformity and suppress dissent):

1. **Independent parallel review** — each agent reviews the plan from their expertise, unaware of other reviewers
2. **Structured output** — every agent returns issues with severity and confidence scores
3. **Confidence-weighted synthesis** — the orchestrator aggregates results, weighting by domain relevance
4. **Explicit uncertainty** — disagreements between agents surface as "requires decision", not silently resolved

## Workflow

```
┌─ Read plan (track source: Plan Mode / file / conversation)
│       ↓
│  Discover available agents (only real, existing agents)
│       ↓
│  Pre-select relevant agents → present multi-select to user
│       ↓
│  Spawn selected agents in parallel (independent review)
│       ↓
│  Collect all reviews
│       ↓
│  Synthesize verdict (PoLL aggregation, or single-agent verdict)
│       ↓
│  Present verdict
│       ↓
│  ┌─ PASS → Done (proceed to implementation)
│  ├─ CONDITIONAL → Fix plan at source → Re-review ─┐
│  └─ FAIL → Fix plan at source → Re-review ────────┘
│                                        │
└────────────────────────────────────────┘
         (max 3 review cycles)
```

### Allowed Transitions

The review follows a strict state machine. Only these transitions are valid:

```
Read Plan    → Discover Agents
Discover     → Select Agents
Select       → Parallel Review
Review       → Synthesize
Synthesize   → Verdict
Verdict:PASS → Done
Verdict:COND → Fix Plan
Verdict:FAIL → Fix Plan
Fix Plan     → Re-review (back to Parallel Review with same agents)
Re-review    → Synthesize → Verdict (same cycle)
```

**Forbidden transitions:**
- Cannot skip from Read Plan directly to Review (must discover and select agents first)
- Cannot go from Verdict back to Discover (agents are locked after first selection)
- Cannot go from Fix Plan to Done (must re-review after fixing)

**Cycle limit:** maximum 3 full review cycles (initial + 2 re-reviews). If the plan still has
blockers after 3 cycles, stop and escalate to the user — the plan may need a fundamentally
different approach rather than incremental fixes.

## Persistence (compaction resilience)

For long reviews (multiple agents, re-review cycles), save state to a file so work survives
context compaction. Use `./swarm-report/plan-review-state.md` with this structure:

```markdown
# Plan Review State
Source: {plan_mode | file:<path> | conversation}
Cycle: {1 | 2 | 3} of 3
Status: {discovering | reviewing | synthesizing | fixing | done}

## Plan Summary
{goal, technologies, scope — extracted in Step 1}

## Selected Agents
- {agent1} (recommended)
- {agent2} (recommended)

## Reviews Completed
- [x] {agent1} — {severity counts: N critical, M major, K minor}
- [ ] {agent2} — pending

## Verdict History
### Cycle 1: {PASS | CONDITIONAL | FAIL}
- Blockers: {list}
- Improvements: {list}

### Cycle 2: ...
```

**Rules:**
- Create this file at the start of Step 2 (after plan is read and source is tracked)
- Update after each significant step (agent review completed, verdict synthesized, fix applied)
- Before each action — re-read the state file. Skip completed steps.
- On re-review cycles, append to Verdict History, don't overwrite

## Step 1 — Read the Plan

Locate the current plan. Check these sources in order:

1. **Active Plan Mode output** — if the user just exited Plan Mode, the plan is in conversation context
2. **File reference** — if the user points to a file (e.g., `plan.md`, `PLAN.md`, or any markdown file), read it
3. **Conversation context** — if the user described the plan in their message, extract it
4. **Ask** — if none of the above, ask the user: "Where is the plan? Is it in a file, or should I look at the Plan Mode output?"

**Track the plan source** — remember whether it came from Plan Mode, a file (save the path),
or conversation context. Step 5 needs this to know how to apply fixes.

Extract from the plan:
- **Goal** — what is being built or changed
- **Technologies** — languages, frameworks, libraries involved
- **Scope** — which modules, layers, or systems are affected
- **Key decisions** — architectural choices made in the plan

## Step 2 — Discover and Select Agents

### Discovery

Find all available agents by scanning for real agent definition files:

1. **Plugin agent directories** — `Glob("**/agents/*.md")` across plugin paths in the project
2. **Built-in subagent types** — only those listed in the system prompt under "Available agent types" (e.g., `general-purpose`, `manual-tester`, etc.)

**Critical rule: only include agents that actually exist.** Read each agent file's frontmatter
(`name`, `description`) to confirm it's real. Never invent, imagine, or assume agents that aren't
physically present as files or listed in the system prompt. If you're not sure an agent exists —
check before listing it. A phantom agent in the selection list erodes trust.

### Pre-selection

Score each discovered agent's relevance **to the specific content of this plan** based on:
- **Technology match** — the plan must specifically mention technologies, frameworks, or layers this agent specializes in. Generic "architecture" or "security" relevance is NOT enough — e.g., `security-expert` only when the plan touches auth, encryption, tokens, or user data; `architecture-expert` only when new modules, dependency direction changes, or public API modifications are involved.
- **Problem-specific value** — would this agent catch issues that others on the panel wouldn't? An agent that merely overlaps with another's coverage adds noise, not signal. Do not recommend an agent just because its domain is tangentially related.
- **Gap coverage** — does this agent cover a blind spot that the other recommended agents miss?

Mark the top-scoring agents as `recommended`. Prefer 2–3 agents, but quality over quantity — if only 1 agent is genuinely relevant, recommend just 1. Do not pad recommendations to reach a number. `general-purpose` is a fallback only when no specialist covers a genuine gap.

### Present Agent Selection

Use `AskUserQuestion` with `multiSelect: true` showing all discovered agents. Recommended agents are listed first with "(Recommended)" in the label and a one-sentence reason specific to this plan (not generic descriptions). Non-recommended agents are available below — the user knows their context best.

**Explicit agent specification:** if the user named specific agents (e.g., "review with kotlin-engineer and security-expert"), skip discovery entirely and use those agents directly. No confirmation needed — the user already chose.

## Step 3 — Parallel Independent Review

Spawn each selected agent as a subagent via the `Agent` tool. **All agents launch in a single
message** to maximize parallelism.

### Review Prompt Template

Each agent receives this prompt (adapted to their expertise). The structured format is important
because the synthesis step depends on parsing severity, confidence, and domain_relevance from
each review. Without consistent structure, aggregation becomes guesswork.

```
You are reviewing an implementation plan as a {agent_role} expert.

## The Plan
{full_plan_text}

## Your Task
Review this plan from the perspective of your expertise. Be specific and actionable.

## Required Output Format

You MUST structure your response exactly as follows:

### Summary
2-3 sentence overall assessment from your perspective.

### Domain Relevance
State one of: high | medium | low — how much does this plan touch your area of expertise.

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

Be honest about confidence — a low-confidence flag from outside your domain is still valuable,
but it should be weighted accordingly in synthesis.

Respond in the same language the plan is written in.
```

### Important Rules

- **Never share one agent's review with another** — independence is the whole point
- **All agents get the same plan text** — no summaries or interpretations
- **Don't filter or edit agent prompts based on other agents** — each is independent

## Step 4 — Synthesize Verdict

After all agents complete, the orchestrator (main session) reads all reviews and synthesizes.
This is the step where multi-agent review delivers its core value — cross-referencing independent
opinions to find signal that no single reviewer could produce alone.

**Single-agent case:** if only one agent reviewed the plan (either by user's choice or because
only one was relevant), skip cross-referencing. Present that agent's issues directly using the
same verdict format, but note that the review represents a single perspective. Convergence
signals and uncertainties sections are not applicable — omit them.

### Aggregation Rules

| Signal | Action |
|--------|--------|
| **Critical severity** from any agent with high confidence | → Blocker. Must be addressed. |
| **Same issue** raised by 2+ agents independently | → Escalate to critical regardless of individual severity. Multiple experts seeing the same problem = real problem. |
| **Major severity** from agent with high domain_relevance | → Important improvement. Include in verdict. |
| **Contradicting opinions** between agents | → Surface as "Uncertainty — requires decision". Present both sides with context. Do NOT silently pick one. |
| **Minor severity** or **low confidence** from single agent | → Include as suggestion, not requirement. |
| **Low domain_relevance** agent flagging an issue | → Note it but weight lower. They may be right, but it's outside their core expertise. |

Pay special attention to **convergence signals** — when agents with different expertise
independently flag the same concern, that's the strongest signal the review can produce.
Call these out explicitly in the verdict.

### Verdict Format

Present the synthesized result:

```
## Plan Review Verdict: {PASS | CONDITIONAL | FAIL}

### Blockers (must fix before implementing)
- {issue} — raised by {agent(s)}, severity: critical
  Suggestion: {what to do}

### Important Improvements (strongly recommended)
- {issue} — raised by {agent(s)}, confidence: {level}
  Suggestion: {what to do}

### Suggestions (nice to have)
- {issue}
  Suggestion: {what to do}

### Uncertainties (requires your decision)
- {topic} — {Agent A} says X, {Agent B} says Y
  Context: {why they disagree}

### Consensus
{What all agents agreed on — the strengths of the plan}
```

**Verdict criteria:**
- **PASS** — no blockers, no important improvements, or only minor suggestions
- **CONDITIONAL** — no blockers, but has important improvements that would significantly affect quality
- **FAIL** — has blockers that must be resolved before implementation makes sense

## Step 5 — Post-Review Action

This step is not optional — always execute it based on the verdict.

The action depends on **where the plan came from** (tracked in Step 1):

| Source | How to fix |
|--------|-----------|
| **Plan Mode** | Call `EnterPlanMode` with the list of issues to address |
| **File** (e.g., `plan.md`) | Edit the file directly with the improvements |
| **Conversation context** | Present the issues and work with the user to revise the plan inline |

### PASS
Confirm the plan is ready. Say so explicitly and proceed to implementation.

### CONDITIONAL
1. Present the improvements clearly
2. Ask the user: "These improvements would significantly strengthen the plan. Want to address them now?"
3. If the user agrees, fix the plan using the appropriate method for its source:
   - **Plan Mode source** → call `EnterPlanMode` with the improvement list
   - **File source** → edit the file, incorporating the improvements into the existing plan
   - **Conversation source** → work with the user to revise inline
4. Include the specific list of improvements (copy from the verdict, not a reference to it)

### FAIL
1. Present blockers clearly
2. Do not ask — directly proceed to fix the plan:
   - **Plan Mode source** → "The plan has {N} blockers. Entering Plan Mode to address them." Call `EnterPlanMode` with the blockers list and suggestions.
   - **File source** → "The plan has {N} blockers. Updating the plan file." Edit the file, adding a "## Issues to Resolve" section with the blockers, or restructure the plan to address them directly.
   - **Conversation source** → present the blockers and start working through them with the user one by one.
3. Always include the full blocker text with suggestions — don't make the user re-read the verdict.
4. After the plan is updated, automatically re-run the review (back to Step 3 with the same
   agents) to verify the issues are resolved. This is the re-review cycle from the state machine.
5. Update the state file with the new cycle number and verdict.
6. If still FAIL after 3 cycles — stop and tell the user: "The plan has failed review {N} times.
   The remaining issues may require a fundamentally different approach. Let's discuss before
   another iteration."

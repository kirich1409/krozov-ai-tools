---
name: write-spec
description: "Specification-Driven Development — transforms a feature idea into an exhaustive spec that enables autonomous implementation without user interruptions downstream. Researches codebase, interviews user with pre-filled suggestions, produces structured spec with acceptance criteria, affected modules, constraints, and decisions. Spec is auto-reviewed (self-review + plan-review), discussed with user, saved as permanent document. Use when: \"write a spec\", \"spec this out\", \"design doc\", \"spec-driven\", \"let's spec it before building\", \"write a specification for\", \"design the architecture for\", \"let's plan it properly\", \"I don't want to wing it\". Invoke proactively when a feature is complex enough that jumping straight to implementation would be risky. Do NOT use for: bug fixes (use debug + implement), research-only questions (use research skill), single-file changes, decomposition without design (use decompose-feature). Saved spec feeds into decompose-feature and implement."
---

# Write Spec

Transform a feature idea into an exhaustive specification that serves as a contract for
autonomous implementation. Once the spec is approved and saved, the implementing agent can
execute it end-to-end — asking the user only at critical blockers where human judgment
is genuinely required.

**Role:** this skill acts as BA + Tech Lead. It takes a stakeholder's request — which may
be vague, incomplete, or phrased as a specific solution — and translates it into a proper
technical specification. Like a business analyst, it probes the real need behind the
request. Like a tech lead, it evaluates approaches and recommends the best one for the
context.

**Core principles:**

1. **The user's request is input, not a mandate.** If the user proposes a specific solution
   ("add retry with backoff"), treat it as one candidate option — possibly the best one, but
   not necessarily. Research the problem independently and recommend the optimal approach.
   The user's idea may be exactly right, partially right, or there may be a clearly better
   alternative. Always say which and why.

2. **Surface requests hide deep complexity.** "I want a withdrawal button" is not a UI task
   — it implies payment infrastructure, compliance, bank integrations, fraud checks, and more.
   Before writing a spec, understand the full scope of what the request actually entails.
   Show the user what they're really asking for. Help them make an informed decision about
   what to build now vs later.

3. **User attention is precious.** Everything that can be figured out without asking — codebase
   patterns, architectural fit, best practices, dependency chains — is researched first.
   The user is asked only what cannot be determined otherwise, and every question comes with
   a recommended answer to accept or override.

---

## Phase 0: Parse Input

### 0.1 Separate the need from the proposed solution

Extract two distinct things from the user's request:

- **Business need** — the underlying problem or goal the user is trying to solve. What
  outcome do they want? Why does this matter? This is often implicit in what they said.
- **Proposed solution** — the specific approach or feature the user mentioned. This is
  what they said, not necessarily what's best.

These can be identical ("I want offline support" → the need IS offline support) or very
different ("I want a withdrawal button" → need: users can cash out earnings; proposed
solution: a UI button, which is only the tip of the iceberg).

When they differ, acknowledge both explicitly. The spec will address the business need
using the best available solution — not necessarily the one literally proposed.

Also extract:
- **Known constraints** — platform, libraries, "no new deps", deadline, etc.
- **Assumed context** — what the user seems to know vs what they may not have considered

Generate a short kebab-case slug: `offline-mode`, `data-export`, `push-notifications`.

Artifacts:
- Spec: `docs/specs/YYYY-MM-DD-<slug>.md` (version-controlled, permanent)
- State: `./swarm-report/spec-<slug>-state.md` (operational, deleted after)

### 0.2 Hidden complexity check

Before launching research, assess: does this request potentially hide more complexity than
it appears? Signs that it does:

- The request names a UI element ("button", "screen", "modal") but the real work is backend
- The request implies integrating with external services, money, legal, or compliance
- The request modifies a flow that other features depend on
- The request uses domain jargon that could mean different levels of scope

If yes: note this in the state file and make sure the research tracks it. The user may
not realize the full scope — surfacing it early is one of the most valuable things this
skill does.

If the feature is clearly enormous (months of work, multiple teams), say so upfront
and ask one scoping question before proceeding.

### Scope depth clarification

Before launching any research, assess whether the request is ambiguous in **depth** — the
same phrase can mean very different scopes of work. If so, ask ONE question that lays out
the options from minimal to full:

```
"Push notifications" can mean different things — which scope do you have in mind?

A) **Local only** — OS-level desktop/in-app alerts, no server involved
B) **Full integration** — server sends pushes to devices via FCM/APNs; requires
   service accounts, console setup, device token management, etc.
C) **Something in between** — describe: ___

Recommended: A — based on the current project context [explain why].
```

Trigger this when the feature touches: external services, multi-system integration,
OS-level capabilities, or when "add X" could mean anything from "show a notification"
to "build a notification platform". If scope is clearly understood — skip and proceed.

### Research track selection

Before launching any agents, decide which sources of information are actually needed.
Don't run everything by default — assess what will give useful signal for this feature.

| Signal in the request | Research tracks to activate |
|-----------------------|-----------------------------|
| Touches existing product functionality | Codebase (always) + Business Analyst |
| New module, cross-layer, or architectural change | Codebase + Architecture Expert |
| External API, protocol, algorithm, or unfamiliar domain | Web Research |
| Vague idea with unclear scope or user-facing impact | Business Analyst |
| Library choice, versioning, or dependency concern | Web Research (+ maven-mcp if JVM project) |
| Straightforward change within one module | Codebase only |
| Existing PRD, spec, or business doc referenced | Read that document first before launching any agent |

**Rule:** if the project has existing business or requirements documents (`docs/`, `*.md` specs,
linked issues), read them before launching research agents — they may answer questions
before the research even starts.

**Default when uncertain:** Codebase + Business Analyst. Add others as findings reveal gaps.

---

## Phase 1: Research

### 1.1 Launch research consortium

Launch relevant expert agents **in a single message** (parallel). Each works independently.
Select tracks based on what the feature actually needs — not all every time.

#### Codebase Expert (Explore subagent) — always include

```
Investigate the codebase for everything related to: {feature goal}

Find and report:
1. Existing code that relates to this feature — classes, interfaces, modules, files
2. Current patterns used for similar concerns in this project
3. Dependencies already in the project that are relevant
4. Module boundaries and architectural layers that would be affected
5. Integration points — where would new code connect to existing code?
6. Any TODO/FIXME comments related to this feature area
7. Test infrastructure available for the affected areas

Use ast-index for all symbol searches. Use Grep only for string literals and comments.
Check build files, configuration, and test code too.

Report: overview paragraph, then findings grouped by category with file paths and
class/function names.
```

#### Architecture Expert (architecture-expert agent)

Include when: feature adds a new module, changes dependency direction, introduces new
abstractions, or crosses more than one architectural layer.

```
Evaluate the architectural implications of: {feature goal}

Analyze:
1. Which modules and layers would be affected?
2. Does this align with the current architecture? What structural changes are needed?
3. Dependency direction — any problematic new dependencies introduced?
4. API boundaries — what contracts need to change or be created?
5. Where should new code live (which module, which layer)?
6. What existing architectural patterns should this follow?
7. Are there alternative approaches worth comparing?

Read the relevant module structure and build files before making judgments.
```

#### Web Research (general-purpose subagent)

Include when: feature involves external protocols, non-trivial algorithms, third-party
integration, or unfamiliar domain.

```
Research best practices and implementation approaches for: {feature goal}

If Perplexity MCP is available, use it for deep research (perplexity_research or
perplexity_ask). Otherwise use built-in web search tools.

Investigate:
1. Common implementation approaches with trade-offs
2. Known pitfalls and mistakes to avoid
3. Relevant libraries or standards
4. Real-world examples from open-source projects
5. Platform-specific considerations (Android/iOS/KMP if relevant)

Note if web search was unavailable. Include source URLs for key claims.
```

#### Business Analyst (business-analyst agent)

Include when: feature has user-facing impact, unclear scope, or comes from a vague idea.

```
Analyze the scope and requirements of: {feature goal}

Assess:
1. Is the scope well-defined? What's ambiguous?
2. What is the MVP — smallest version that delivers real value?
3. What requirements are implicit but not stated?
4. Edge cases and error scenarios not yet covered?
5. Where could this feature grow beyond its original intent?
6. Dependencies on external systems, APIs, or other teams?

Be concrete — list specific scenarios, not abstract concerns.
```

#### Critical Evaluation (general-purpose subagent)

Include when: the user proposed a specific technical approach, OR the codebase has
established patterns in this area that may be outdated or problematic.

```
Critically evaluate the approach for: {feature goal}
User's proposed approach (if any): {what the user suggested}

Investigate:
1. Existing patterns in the codebase for this concern — are they good practice or
   legacy/problematic? If problematic, explain why and what would be better.
2. Is the user's proposed approach optimal? What are its trade-offs?
3. What would a modern/industry-recommended approach look like?
4. Prepare 3 concrete approach options for the user to choose from:
   - **Radical**: most complete, modern, future-proof — higher upfront cost
   - **Classic**: follows existing project patterns — familiar but may carry baggage
   - **Conservative**: minimal change, quickest to ship — simplest but most limited
5. For each option: trade-offs, estimated complexity, recommended when.

Do NOT recommend blindly following project patterns if they are outdated or problematic.
Flag bad patterns explicitly — the user should know before committing to them.
```

#### Dependency Chain (general-purpose subagent)

Include when: feature integrates with external services, requires OS-level capabilities,
touches infrastructure, or the user's request implies a setup phase.

```
Map the full dependency chain for: {feature goal}

Identify everything that must exist or be configured BEFORE the feature can work:

1. Infrastructure / services — third-party APIs, cloud services, databases, queues
2. Platform requirements — OS permissions, capability declarations, entitlements
3. Console / dashboard setup — developer consoles, API keys, service accounts
4. Configuration — environment variables, config files, secrets
5. Code prerequisites — base classes, interfaces, or modules that must exist first
6. Test prerequisites — what test infrastructure or fixtures are needed

For each dependency: is it already in place, or does it need to be created/configured?
Flag any dependency that requires manual steps outside of code (e.g., "create FCM project
in Firebase console") — these become explicit prerequisite steps in the spec.
```

### 1.2 State file

Create `./swarm-report/spec-<slug>-state.md` before launching agents:

```markdown
# Spec State: {feature name}

Slug: {slug}
Status: researching
Started: {date}

## Input
- Goal: {goal}
- Motivation: {why now}
- Known constraints: {list or "none stated"}

## Research Tracks
- [ ] Codebase — launched
- [ ] Architecture — {launched | skipped: reason}
- [ ] Web — {launched | skipped: reason}
- [ ] Business Analyst — {launched | skipped: reason}

## Findings
(populated as agents complete)

## Interview Log
(populated during Phase 2)
```

Update as each agent completes.

---

## Phase 2: Interview

### 2.1 Synthesize and run feature checklist

After research completes, before formulating questions, run through this checklist.
Any item that applies and is unanswered becomes a question or a spec entry.

**Feature Checklist:**
- [ ] **OS permissions** — does this feature need to request permissions (notifications,
      camera, location, contacts, storage)? What happens if denied?
- [ ] **Platform-specific behavior** — does this work differently on different OS/devices?
- [ ] **Prerequisites** — are there external setup steps (console config, service accounts,
      API keys, entitlements) that can't be automated in code?
- [ ] **Error states** — what can fail? What does the user see when it fails?
- [ ] **Security** — does this expose sensitive data, require auth, or touch user credentials?
- [ ] **Performance** — any risk of blocking the main thread, excessive memory, or battery drain?
- [ ] **Backward compatibility** — does this change existing behavior anyone depends on?
- [ ] **Pattern quality** — did Critical Evaluation flag any existing pattern as problematic?

### 2.2 Present approach options

If Critical Evaluation ran, present the 3 approach options **before** asking other questions.
This is the most important decision — it shapes everything else.

```
Based on research, here are the implementation approaches:

**Option A — Radical:** {name}
{2-3 sentences describing the approach}
Trade-offs: {pros} / {cons}
Best when: {context where this wins}

**Option B — Classic:** {name}
{2-3 sentences describing the approach}
Trade-offs: {pros} / {cons}
Best when: {context where this wins}

**Option C — Conservative:** {name}
{2-3 sentences describing the approach}
Trade-offs: {pros} / {cons}
Best when: {context where this wins}

Recommended: Option {X} — {one sentence rationale}
Or describe a custom approach: ___
```

Wait for the user to choose before proceeding. The chosen approach becomes the baseline
for all subsequent questions.

### 2.3 Synthesize gaps

After the approach is chosen, synthesize remaining findings into three categories:
- **Already known** — research gave a clear answer, no need to ask
- **Proposed defaults** — research suggests a direction, propose it for confirmation
- **Genuine gaps** — requires user input to resolve

Only ask about genuine gaps. Present proposed defaults as recommendations the user
confirms or overrides.

### 2.4 Question format

Each question in a round:

```
**Q: {question}**
→ Recommended: {answer} — {brief rationale}
→ Alternative: {different option}
→ Alternative: {another option, if relevant}
→ Or describe your preference: ___
```

Skip questions where the recommendation is overwhelmingly obvious and the answer
doesn't meaningfully change the architecture. Save those decisions for the "Decisions
Made" section in the spec.

### 2.5 Round structure

Each round:
1. Present what's already understood (brief — gives user context)
2. Ask all current open questions with recommended answers
3. Wait for responses
4. Record answers in state file
5. Check if any new gaps opened from the answers
6. If gaps remain → another round. If complete → proceed to drafting.

**Cap: maximum 100 interview rounds.** If the 100th round completes and gaps remain,
record them as open questions in the spec (non-blocking where possible) and proceed
to drafting. Surface any remaining blockers to the user in the review phase.

### 2.6 Large feature handling

If the feature spans multiple independent development phases, offer phased approach:

```
This feature is substantial. Suggested phases:

**Phase 1 — {name}:** {what it delivers and why first}
**Phase 2 — {name}:** {what it adds, depends on Phase 1}
**Phase 3 — {name}:** {what it adds}

Recommendation: spec and fully implement Phase 1 before speccing Phase 2.
Real feedback from Phase 1 will inform Phase 2 design.

Proceed phased, or spec the full feature at once?
```

If phased: spec covers Phase 1 only. Include a "Future Phases" section for what's
planned but not yet specced.

---

## Phase 3: Write Spec Draft

Write the spec as if the reader is an implementing agent with zero additional context.
Nothing can be left to inference. Every requirement is verifiable. Every decision is
explicit with its rationale.

```markdown
---
type: spec
slug: {slug}
date: {YYYY-MM-DD}
status: draft
# Optional fields — leave blank when not applicable. Consumed by `acceptance`
# (choreography) and by `generate-test-plan` (platform-aware coverage).
platform: []                     # e.g. [android], [ios], [web], [backend-jvm], [cli], [library], [desktop]. May be multi-value for cross-platform features.
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
stable `AC-N` id that MUST appear in the frontmatter `acceptance_criteria_ids` list; this is
what `acceptance` uses to drive AC-coverage checks via `business-analyst`.

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

---

## Phase 4: Review Loop

### 4.1 Present draft to user

Share the draft spec with the user. Invite them to review it — read through it,
check if anything is missing, wrong, or needs adjustment.

### 4.2 Self-review while user reads

While the user reviews, run a self-check:
- Every acceptance criterion is objectively verifiable (not "should feel fast")
- Every affected module listed with change type
- No decision left to the implementing agent's judgment
- Out of scope is explicit — nothing accidentally implied
- No blocking open questions remain unresolved

Fix any self-identified gaps.

### 4.3 Run plan-review

Run the `plan-review` skill on the spec. Provide:
- The full spec content
- The original feature goal

The plan-review checks completeness, internal consistency, implementation-readiness,
and scope alignment. Address findings:

| Severity | Action |
|----------|--------|
| No issues | Proceed |
| Minor gaps | Fix inline, note changes |
| Major gaps | Surface to user, discuss, resolve |
| Contradictions | Surface to user, resolve |

### 4.4 Discussion round after review

After self-review and plan-review complete, if either surfaced issues or open questions:
present them to the user for a final discussion round. This may loop back into Phase 2
style Q&A to close remaining gaps.

Once the user is satisfied and no issues remain, update spec status from `draft` to
`approved` and proceed to save.

---

## Phase 5: Save

### 5.1 Create docs/specs/ if needed

Check if `docs/specs/` exists in the project root. Create it if not.

### 5.2 Save

Save spec to `docs/specs/YYYY-MM-DD-<slug>.md`.

Update state file status to `done`.

### 5.3 Confirm

```
Spec saved: docs/specs/{filename}

This document is self-sufficient for implementation. When you're ready,
decompose-feature will break it into tasks for autonomous execution.
```

Do not auto-invoke decompose-feature or any other skill. The spec is the deliverable.
The user decides when and how to proceed.

---

## Red Flags / STOP Conditions

- **Fundamental contradiction** — acceptance criteria are mutually exclusive, or a constraint
  makes the feature impossible. Surface the conflict, don't invent a workaround.
- **Missing critical access** — feature requires systems, APIs, or credentials not available.
  List what's needed and stop.
- **Scope genuinely unbounded** — after one scoping attempt, still too large to spec.
  Propose phased approach and wait for user alignment.
- **Decision requires product authority** — choice has business, legal, or brand implications
  the team cannot make unilaterally. Flag as blocking open question.

---

## Output Artifacts

| Artifact | Path | Lifetime |
|----------|------|----------|
| Spec | `docs/specs/YYYY-MM-DD-<slug>.md` | Permanent — version controlled |
| State file | `./swarm-report/spec-<slug>-state.md` | Temporary — delete after save |

The spec is the sole deliverable. It is designed to be handed to `decompose-feature` +
`implement` at any future point, producing a complete autonomous implementation with
user involvement only at genuine critical blockers.

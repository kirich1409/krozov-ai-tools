---
name: write-spec
description: "Specification-Driven Development — transforms a feature idea into an exhaustive spec that enables autonomous implementation without user interruptions downstream. Researches codebase, interviews user with pre-filled suggestions, produces structured spec with acceptance criteria, affected modules, constraints, and decisions. Spec is auto-reviewed (self-review + multiexpert-review), discussed with user, saved as permanent document. Use when: \"write a spec\", \"spec this out\", \"design doc\", \"spec-driven\", \"let's spec it before building\", \"write a specification for\", \"design the architecture for\", \"let's plan it properly\", \"I don't want to wing it\". Invoke proactively when a feature is complex enough that jumping straight to implementation would be risky. Do NOT use for: bug fixes (use debug + implement), research-only questions (use research skill), single-file changes, decomposition without design (use decompose-feature). Saved spec feeds into decompose-feature and implement."
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

Tracks and their inclusion rules:

- **Codebase Expert (Explore subagent)** — always include. Surveys existing code, patterns, deps, module boundaries, integration points, TODOs, test infra.
- **Architecture Expert (architecture-expert agent)** — include when the feature adds a new module, changes dependency direction, introduces new abstractions, or crosses more than one architectural layer.
- **Web Research (general-purpose subagent)** — include when the feature involves external protocols, non-trivial algorithms, third-party integration, or unfamiliar domain.
- **Business Analyst (business-analyst agent)** — include when the feature has user-facing impact, unclear scope, or comes from a vague idea.
- **Critical Evaluation (general-purpose subagent)** — include when the user proposed a specific technical approach, OR the codebase has established patterns in this area that may be outdated or problematic. Produces 3 approach options (Radical / Classic / Conservative).
- **Dependency Chain (general-purpose subagent)** — include when the feature integrates with external services, requires OS-level capabilities, touches infrastructure, or the user's request implies a setup phase.

Use these research-agent prompt templates verbatim when launching each expert. See `references/research-prompts.md` for the full per-agent prompt text.

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

Follow the canonical Markdown spec template — YAML frontmatter with `type`/`slug`/`date`/`status` plus optional `platform`/`surfaces`/`risk_areas`/`non_functional`/`acceptance_criteria_ids`/`design` fields that drive downstream `acceptance` and `generate-test-plan`, followed by body sections: Context and Motivation, Acceptance Criteria (stable `AC-N` ids), Prerequisites, Affected Modules and Files, Technical Approach, Technical Constraints, Decisions Made, Out of Scope, Open Questions, and Future Phases.

See `references/spec-template.md` for the full template (frontmatter fields, section headers, table shapes, and inline instructions) — copy it verbatim into the draft and fill in each placeholder.

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

### 4.3 Run multiexpert-review (spec profile)

Run the `multiexpert-review` skill on the draft spec with an **explicit `spec` profile hint**.
Prepend this prefix to the args (engine parses the first two lines as hint):

```
profile: spec
---
<rest of args: full spec content + original feature goal>
```

The hint is defense-in-depth: inline-arg callsites lack the frontmatter the detector would classify on, and the one-line prefix short-circuits detection deterministically and independently of detector internals. See `references/profile-hint-rationale.md` for the full rationale.

**Artifact source:** in-memory draft, so engine classifies source as `conversation` and
uses the spec profile's `source_routing.conversation: inline-revise` action for FAIL fixes
(not `file: edit-in-place` — the draft isn't saved to `docs/specs/` yet). Revise-loop
iterations happen inline in the write-spec flow.

The spec profile (panel: business-analyst + architecture-expert) checks falsifiability of
Acceptance Criteria, prerequisite realism, explicit Out of Scope, decisions with rationale,
affected modules completeness, open questions tagged blocking vs non-blocking, and
technical approach detail. Address findings per the verdict:

| Severity | Action |
|----------|--------|
| No issues (PASS) | Proceed |
| Minor gaps | Fix inline, note changes |
| Major gaps (CONDITIONAL) | Surface to user, discuss, resolve |
| Contradictions | Surface to user, resolve |
| Critical (FAIL) | Engine drives revise-loop on the draft; Phase 4.3 iterates until PASS/CONDITIONAL or user escalation |

### 4.4 Discussion round after review

After self-review and multiexpert-review complete, if either surfaced issues or open questions:
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

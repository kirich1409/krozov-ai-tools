---
name: reverse-spec
description: "Reverse-engineers an existing feature into a tech-agnostic specification — reads the code, maps behavior, interviews the user for missing intent, and produces a PM/BA-grade spec that a developer on any stack could use to reimplement the feature identically. Use when: \"reverse spec\", \"extract spec from code\", \"document this feature from code\", \"reverse engineer this screen\", \"turn this code into a spec\", \"build a spec for existing feature\", \"what does this feature actually do\", \"write docs for this module\", \"recreate this feature on <other stack>\", \"migrate this feature — first document it\". Input can be a file/class/directory path or a prose description of the feature. Output: single versioned markdown in docs/spec/. Do NOT use for: new features (use write-spec), high-level architecture overview of a whole project (too broad), library API docs (use the library's own docs), bug investigation (use plan mode)."
---

# Reverse Spec

Take an existing feature that already lives in code and produce a specification that is
good enough to rebuild the feature from scratch — on a different stack, with a different
implementation, but with the same observable behavior, the same UX, and the same
integrations.

**Role:** this skill acts as a senior engineer translating implementation back into a
PM/BA-grade document. Like a tech lead handing a feature brief to a new team, it extracts
*what the feature does and why it matters*, not *how the current code happens to be
organized*. The output is what you would give a stranger on another platform so they can
ship the same feature.

**Core principles:**

1. **Zero code identifiers in the body.** Sections 1–8 and 10–11 must not contain any
   name that only exists in the current codebase (classes, methods, types, fields,
   sealed-class cases, enum values, package or file paths, framework idioms).
   Implementation names live in Section 13 (Code map) as location pointers, not as
   the subject of description.

   Sanity check: *"If I renamed every class in the codebase, would this sentence still
   describe the same feature?"* If it breaks, rewrite. See
   [`references/behavior-translation.md`](references/behavior-translation.md) for the
   full rule, recipes, and before/after examples.

2. **Tech stays in only when load-bearing.** "Uses Jetpack Compose" is noise (any UI
   toolkit could render this). "Uses Google ML Kit face detection" matters (swapping
   changes capability, accuracy, latency, licensing). Tech belongs in §12 only when
   removing it would change the feature's behavior, constraints, or cost — phrased as
   a capability with acceptable substitutes, not a direct SDK reference. See
   [`references/tech-abstraction.md`](references/tech-abstraction.md).

3. **Inferred intent is flagged, not guessed.** When the code shows *what* but not
   *why* (retry=3, debounce=250 ms, specific error copy), write it as observed fact
   and raise a clarification question. Do not invent rationale.

4. **Project conventions fill cross-cutting gaps.** Accessibility, error-copy style,
   analytics naming, localization, logging are usually project-wide. Check the project
   before asking the user: reference an existing convention, or explicitly mark its
   absence. See [`references/analysis-checklist.md`](references/analysis-checklist.md).

5. **One question per round.** Each answer reshapes which question matters next.
   Batching locks in assumptions prematurely. The user may override ("ask me everything
   at once") — respect that, but default is one-by-one. Offer a final freeform round
   when the curated queue is empty.

---

## Phase 0: Parse Input

### 0.1 Identify the target

The user may specify the feature in several ways:

- **Explicit path** — `app/src/main/.../PaymentScreen.kt`, a directory, or a set of files.
- **Class / symbol name** — `PaymentCheckoutViewModel`.
- **Prose description** — "the onboarding welcome screen", "the search bar with
  autocomplete".

For path/symbol inputs, verify the target exists and resolve it to a concrete location.
Use ast-index where available to expand a class name into all related files.
Grep / Glob are fallbacks only.

For prose inputs, run a short discovery pass:

1. Extract likely keywords from the description (screen names, UI strings, domain nouns).
2. Search the codebase for candidates via ast-index / grep for user-visible strings, route
   names, feature folders.
3. Present 1-3 candidates to the user and confirm before proceeding. If ambiguous, ask
   one question: *"Which of these matches what you mean? [A] X, [B] Y, [C] none — let me
   search with different terms."*

### 0.2 Scout before scope lock

Do not lock the boundary yet — the scope of a feature is rarely visible from the target
alone. Run a *scout pass*:

1. Open the confirmed target (file / class / directory).
2. Trace one hop outward — every type the target directly depends on, every symbol
   that calls into it, every resource it reads (strings, layouts, navigation graph
   entries).
3. Note modules / directories that appear in the scout set.

Then **propose** a boundary to the user in one line:

- **In scope** — the files and symbols that clearly implement the feature itself.
- **Direct dependencies** — modules the feature calls into (repositories, shared UI
  kit, auth, analytics) that will be referenced, not redescribed. Every module on
  this list is later detailed in §10.7 Collaborators and consumers as a capability
  contract. Keep the list here high-level; contract detail belongs to §10.7.
- **Out of scope** — unrelated modules surfaced by the scout but not part of this
  feature.

Ask the user for confirmation with a single question: *"Here is what I'm including in
the feature: [in scope]. Dependencies: [deps]. Out of scope: [out]. Do these boundaries
look right?"*. Adjust based on the answer before proceeding. A wrong boundary at this
step cascades: too narrow misses behaviors, too wide drowns the spec in unrelated detail.

**Scope sanity check** (soft gate). After the boundary is confirmed, flag aggregates:
multiple user-facing flows (sign-in + sign-up + password reset), multiple top-level
feature directories, or multiple screens with distinct purposes. If tripped, recommend
splitting into per-flow specs — aggregates produce unusable §10.1 tables and state files.

Generate a kebab-case slug from the feature name: `payment-checkout`, `search-bar`,
`onboarding-welcome`.

### 0.3 Create or resume state file

State lives in `./swarm-report/reverse-spec-<slug>-state.md` and holds: target
location(s), confirmed boundary, spec language, open-questions queue, per-phase
checklist, draft fragments.

**If the file already exists**, summarize in one line (*"Found unfinished state — Phase
N, K open questions. Continue or restart?"*) and default to **continue** — restart
wipes prior answers. Re-read at the start of each phase for compaction resilience.

### 0.4 Determine spec language

Check the project for signals of working language:

- existing `docs/`, `docs/spec/`, `docs/specs/` contents — what language do they use?
- README, commit history, code comments — dominant language?
- CLAUDE.md — any language directive?

Pick the dominant project language as the default. Announce it to the user in one line
and offer to override: *"Defaulting to <language> for the spec (matching the rest of the
project docs). Different language?"* A single yes/no check is enough; do not escalate if
the user says nothing.

### 0.5 Output path

Default: `docs/spec/<slug>.md`.

If the project already uses a different convention (`docs/specs/`, `specs/`, `doc/spec/`,
etc.), match it — consistency with the repo beats the skill's default. Announce the
chosen path before writing.

### 0.6 Project-overview check

Check for a project-overview document at `docs/project-overview.md` (alternates:
`docs/PROJECT.md`, `docs/overview.md`, `PROJECT.md`). If found, read it and reference
it from the feature spec instead of duplicating project-wide context. If not found,
offer to draft one and wait for user review before proceeding (or proceed without it
if the user declines, noting the gap as `[OQ-N]`).

Full protocol — when to check, what the overview contains, how the feature spec
short-circuits when an overview exists, update discipline — in
`references/project-overview-protocol.md`.

Override: *"skip project-overview"* (or any equivalent phrasing) skips this phase entirely.

---

## Phase 1: Static Analysis

No interview yet. Walk through
[`references/analysis-checklist.md`](references/analysis-checklist.md) section by
section, capture findings into the state file. The checklist covers entry points,
user-visible states, data in/out, external dependencies, side effects, code-enforced
constraints, platform capabilities, navigation, localization, and accessibility.

For each finding: *what happens*, *under which condition*, *with which concrete parameters*. Capture concrete numbers and strings verbatim (retry=3, debounce=250 ms, "Something went wrong") — the spec carries these exact values so a reimplementation matches. Defer feature-specific vs project-wide judgments to Phase 2.

---

## Phase 2: Convention Mapping

For every cross-cutting concern not owned by the feature (error handling, a11y, analytics naming, localization, logging, pagination, caching), check the rest of the project. Four outcomes:

- **Follows project convention** — reference it; do not redescribe.
- **Deviates** — call out explicitly; rationale → Open Questions if unknown.
- **No project convention, feature absent too** — mark absent honestly. Most commonly forgotten case.
- **No project convention, feature present** — describe; flag the missing shared pattern.

Judgments live in the state file and become cross-references in the spec.

---

## Phase 3: Clarification Loop

Close gaps the code cannot answer.

**Default pacing: one question per round.** Each question is informed by the previous
answer — batching locks in assumptions prematurely. Before the first question, announce
queue size: *"Found ~N gaps. One question per round; say 'batch' to switch."* Prevents
the failure mode where the user patiently answers 10 questions then says "could've been
one message".

Per question:

1. Re-read state file.
2. Pick the single highest-uncertainty item — one that unblocks the most downstream sections, or whose wrong answer is most expensive.
3. Ask with a **pre-filled default** derived from code or project convention. Example: *"Retry count is 3 in code. Intentional product requirement or implementation default? (default: intentional)"*. Accept / override / "don't know" (→ Open Questions) all valid.
4. Update state file. Repeat.

Switch to batch mode if queue > 8 and the user explicitly asks. Respect overrides.

Common question categories: intent behind observed behavior, out-of-scope confirmation, missing business context, design source (Figma/PRD/analytics), deviation rationale.

### 3.1 Freeform round

When the curated queue is empty, ask: *"Any additional context I haven't asked about? (design links, analytics plan, PRD, constraints, history…)"*. Common authoritative inputs: Figma/design links, screenshots, API contracts (OpenAPI/Protobuf), analytics taxonomy, localization glossary, PRD, historical context (owner, partner, incidents). User-supplied inputs override inferred-from-code data and are referenced in the spec.

---

## Phase 4: Draft Spec

### Phase 4.0: Translate findings to behavior (mandatory)

Before writing a single sentence into the spec, translate every Phase 1 finding into
behavior. This is the step where code identifiers die.

The state file holds findings in the code's own vocabulary — class names, sealed-class
cases, exception types, reactive primitives, method signatures. Leaving any of that in
the spec produces a document that describes the current implementation, not the feature.
The whole point of the skill is the opposite.

Open `references/behavior-translation.md` and apply the 13 translation recipes to the
findings. The recipes cover sealed-class cases, method signatures, exception
hierarchies, reactive / async primitives, DTO shapes, DI plumbing, UI-toolkit
components, defect observations, navigation graphs, and more.

Rewrite each finding into a sentence that would remain correct if every class in the
codebase were renamed tomorrow. If the sentence breaks under that test, it is code, not
behavior — rewrite again.

Preserve literally, from the state file into the spec:

- user-visible copy (quoted verbatim)
- exact numeric values (retries, timeouts, lengths, thresholds)
- external-contract names (URLs, endpoints, event names, provider field names,
  protocol/RFC references)

### Phase 4.1: Write the spec

Produce the draft at `docs/spec/<slug>.md` following
[`references/spec-template.md`](references/spec-template.md). Template structure
(product first, tech last):

- **Part A (§§1-7) Product behavior** — Overview, User-facing behavior, UI, States, Navigation, L10n & a11y, Analytics.
- **Part B (§§8-9) Decisions & risks** — Open Questions (body uses `[OQ-N]` cross-refs), Known Defects (identifiers allowed as evidence).
- **Part C (§§10-12.5) Technical integration** — Data & integrations (network ops / persistence / platform events / flags / services / contracts / collaborators / domain model), Platform capabilities, Tech-specific constraints, External references.
- **Part D (§13) Appendix** — Code map (the only place code identifiers are allowed).

Writing rules (enforced by Phase 5 verification):

- Zero code identifiers in §§1–8 and 10–11 (Principle 1).
- Tech only when load-bearing, in §12, phrased as capability (Principle 2).
- Concrete observable facts: exact copy, numbers, states.
- Cross-reference project conventions instead of inlining.
- Every claim verifiable against code, user answer, convention, or `[OQ-N]`. Speculation goes to Open Questions, not body.
- Inapplicable sections are written `N/A — reason`, not omitted.

---

## Phase 5: Coverage Verification

Run five passes plus a typo sweep against the **proof standard**: every factual claim
in the body traces to code location, recorded user answer, project convention, or an
explicit Open Questions entry. Speculation is not a proof — remove or escalate.

Passes (detailed procedure in
[`references/coverage-verification.md`](references/coverage-verification.md)):

1. **Code → spec** (coverage) — every significant code branch maps to a spec section or is explicitly omitted in §13.
2. **Spec → code** (grounding) — every claim traces to one of the four proof sources. §9 Known Defects requires code pointer + defect class + consequence.
3. **Identifier-leak scan** (vocabulary) — §§1-8 and 10-11, zero tolerance for codebase-only tokens. §9, §12, §13 excluded.
4. **Reference integrity** — every body `[OQ-N]` has a §8 entry, every body-impacting §8 entry has ≥1 `[OQ-N]`. Grep-scriptable.
5. **Code-map validity** — every `path:line` in §13 points to an existing file with the line within bounds. `test -f` + `wc -l` scriptable.

Plus a **typo / formatting sweep**: orphan spaces, doubled words, mixed Latin/Cyrillic, inconsistent punctuation around quotes. Light but mandatory — typos erode reader trust.

Verification output (passed items, gaps fixed, leaks cleaned, ref-integrity resolutions, code-map count, typo result, unresolved gaps) goes into the state file and is summarized in one line at draft presentation.

### Definition of Done

The five passes plus the typo sweep are mechanical. The spec is hand-off-ready only
when all **eleven Definition-of-Done gates** pass — section presence, the six checks
above, Open Questions and Known Defects completeness, Code map coverage, header fill,
user review. See
[`references/definition-of-done.md`](references/definition-of-done.md). Half-satisfied
is a progress report, not a ready spec.

---

## Phase 6: User Review & Iteration

Present the draft path plus a one-paragraph summary. Ask:

- anything missing or wrong?
- additional inputs to incorporate (Figma, screenshots, etc.)?

Iterate based on feedback. Each iteration re-runs the relevant phase (typically Phase 3
with specific new questions, then Phase 4 partial regeneration, then Phase 5).

When the user approves, the spec is final.

---

## Phase 7: Save & Handoff

The spec already lives at `docs/spec/<slug>.md`. Final steps:

- Confirm the file exists and is readable.
- Delete the state file (`./swarm-report/reverse-spec-<slug>-state.md`) — operational,
  no longer needed.
- Offer to commit: *"Spec saved to `docs/spec/<slug>.md`. Want me to commit it?"*. Do not
  commit without explicit confirmation.
- **Hygiene artefact (optional).** If the analysis surfaced implementation-level
  concerns that did not qualify for §9 Known Defects (hardcoded strings, weak PRNG
  for security values, plaintext token storage, log leakage, code-style issues),
  save them to `docs/spec/<slug>-hygiene.md` per `references/analysis-checklist.md`
  §14. Mention the artefact in the handoff: *"Also saved implementation-hygiene
  findings to `docs/spec/<slug>-hygiene.md` (N items) — backlog for the team,
  unrelated to feature behavior."* If no hygiene findings exist, mention briefly
  (*"Hygiene artefact: not needed."*) and do not create the file.
- **Project overview update flag.** If Phase 0.6 surfaced discrepancies between the
  observed code and the existing project-overview document, mention them once:
  *"In `docs/project-overview.md`, field <X> may be stale — observed <Y>.
  Did not update — out of scope for the current feature."*. The skill never silently edits
  the project overview.
- If the user intends to use this spec for reimplementation on another stack, mention
  that `write-spec` can take this spec as input for the new implementation.

---

## Anti-patterns

Common failure modes and their fixes are catalogued in `references/anti-patterns.md`.
Run through that list as a pre-publish checklist before declaring a draft ready — most
anti-patterns are invisible from inside the skill itself.

Recurring themes:
- Code identifiers leaking into body (use `behavior-translation.md` recipes).
- Copying code structure (ViewModel/UseCase/Repository naming) into the spec.
- Inventing rationale that was never confirmed.
- Skipping Phase 4.0 translate-step or Phase 5 verification.
- Hiding absent conventions (silent omission of things like missing a11y).
- Treating defect findings as spec content (defects go in §9, not body).

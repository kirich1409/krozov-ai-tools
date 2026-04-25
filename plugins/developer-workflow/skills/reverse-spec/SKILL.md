---
name: reverse-spec
description: "Reverse-engineers an existing feature into a tech-agnostic specification — reads the code, maps behavior, interviews the user for missing intent, and produces a PM/BA-grade spec that a developer on any stack could use to reimplement the feature identically. Use when: \"reverse spec\", \"extract spec from code\", \"document this feature from code\", \"reverse engineer this screen\", \"turn this code into a spec\", \"build a spec for existing feature\", \"what does this feature actually do\", \"write docs for this module\", \"recreate this feature on <other stack>\", \"migrate this feature — first document it\". Input can be a file/class/directory path or a prose description of the feature. Output: single versioned markdown in docs/spec/. Do NOT use for: new features (use write-spec), high-level architecture overview of a whole project (too broad), library API docs (use the library's own docs), bug investigation (use debug)."
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

1. **Zero code identifiers in the body.** The body of the spec (Sections 1–8 and
   10–11) must not contain any name that only exists in the current codebase. That
   includes class names, method names, type names, field names, sealed-class cases,
   enum values, package paths, file paths, and framework idioms. The spec describes
   *what the feature does*, in language a PM/BA can read. Implementation names live
   in Section 13 (Code map) — as location pointers, not as the subject of
   description. See `references/behavior-translation.md` for the full rule and
   before/after examples.

   Sanity check a sentence by asking: *"If I renamed every class in the codebase, would
   this sentence still describe the same feature?"* If the sentence breaks, it is
   talking about code, not behavior — rewrite it.

   Quick examples of what this forbids in the body:
   - ❌ "`OAuthClient.authorize()` returns an `OAuthResult.Success(tokens)` or
     `OAuthResult.Error(exception)`"
     ✅ "Authorization returns either a valid token set or a structured failure."
   - ❌ "An observable `StateFlow<AuthState>` with cases `Unauthenticated`,
     `Authenticating`, `Authenticated(tokens)`, `Error(exception)` drives the UI."
     ✅ "The UI reflects the current authentication state: not authenticated, authorizing,
     authenticated, or failed."
   - ❌ "`TokenStorage.save(tokens)` persists the `OAuthTokens` to KV storage."
     ✅ "The token set is persisted in platform key-value storage after a successful
     exchange."

2. **Tech stays in only when it is load-bearing.** Keeping "Uses Jetpack Compose" in the
   spec is noise — any UI toolkit can render the same result. Keeping "Uses Google ML
   Kit face detection" matters — swapping changes capability, accuracy, latency, or
   licensing. Rule of thumb: a technology stays in the spec only if removing it would
   change the feature's behavior, constraints, or cost. Even when kept, it belongs in
   Section 12 (Tech-specific constraints), phrased as a *capability* with acceptable
   substitutes — not as a direct SDK reference. See `references/tech-abstraction.md`.

3. **Inferred intent is flagged, not guessed silently.** When the code reveals *what*
   happens but not *why* (a retry count of 3, a 250 ms debounce, a specific error copy),
   write it into the spec as an observed fact and raise a clarification question. Do not
   invent rationale.

4. **Project conventions fill the gaps the feature does not own.** Things like
   accessibility, error copy style, analytics naming, localization coverage, logging
   levels are usually project-wide rather than feature-specific. Before asking the user,
   check the project: if a convention exists, reference it ("error states follow project
   convention X, see `<path>`"); if not, explicitly mark the absence ("no accessibility
   handling — consistent with project-wide absence"). See
   `references/analysis-checklist.md` for the full list of cross-cutting concerns.

5. **One question per round.** After each interview question, new answers change which
   question is most valuable next. Batching locks in assumptions prematurely. The user
   can always override ("just ask me everything at once") — respect that, but the default
   is one-by-one. After the main interview is complete, offer the user a freeform round
   to add anything that was not covered.

---

## Phase 0: Parse Input

### 0.1 Identify the target

The user may specify the feature in several ways:

- **Explicit path** — `app/src/main/.../PaymentScreen.kt`, a directory, or a set of files.
- **Class / symbol name** — `PaymentCheckoutViewModel`.
- **Prose description** — "the onboarding welcome screen", "the search bar with
  autocomplete".

For path/symbol inputs, verify the target exists and resolve it to a concrete location.
Use ast-index where available (see global code-search rules) to expand a class name into
all related files. Grep / Glob are fallbacks only.

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

Ask the user for confirmation with a single question: *"Вот что я отношу к фиче: [in
scope]. Зависимости: [deps]. Вне скоупа: [out]. Подтверждаешь границы?"*. Adjust based
on the answer before proceeding. A wrong boundary at this step cascades: too narrow
misses behaviors, too wide drowns the spec in unrelated detail.

**Scope sanity check** (soft gate). After the boundary is confirmed, evaluate against
these heuristics:

- Scope covers **more than one user-facing flow** (e.g., both sign-in AND sign-up AND
  password reset) — probably an aggregate, not a feature.
- Scope spans **more than one top-level feature directory** in the project's module
  tree — probably more than one feature.
- Scope includes **more than one screen** with distinct purposes (onboarding carousel
  across 4 screens is one flow; sign-in + profile-edit + settings is three).

If any of these trip, surface to the user: *"Scope на [N flows / N features / N
screens] — это, скорее, набор фич, чем одна. Хочешь одну большую спеку или
per-flow спеки? Рекомендация — разбить: каждая отдельная спека полезнее
реимплементатору, чем аггрегат."*. A large aggregate spec produces a Phase 1 state
file and §10.1 Network operations table that are unusable in practice. Split first,
then spec each piece.

Generate a kebab-case slug from the feature name: `payment-checkout`, `search-bar`,
`onboarding-welcome`.

### 0.3 Create or resume state file

State lives in `./swarm-report/reverse-spec-<slug>-state.md`. It persists across
context compaction and holds:

- target location(s) and confirmed boundary
- spec language (see 0.4)
- open questions queue
- per-phase checklist (pending / in progress / done)
- draft fragments as they accumulate

**If the state file already exists** when the skill starts — that means this feature
has been started before. Read the file and present a one-line summary to the user:
*"Нашёл незавершённый state на фичу `<slug>` (Phase N, queue: K open questions).
Продолжить с того же места или начать заново?"*. Default is **continue**; restart wipes
answers already given and is rarely what the user wants.

If the user confirms restart, delete the old state file and start fresh. Otherwise
resume from the first unchecked phase.

Re-read this file at the start of each phase so that work survives compaction.

### 0.4 Determine spec language

Check the project for signals of working language:

- existing `docs/`, `docs/spec/`, `docs/specs/` contents — what language do they use?
- README, commit history, code comments — dominant language?
- CLAUDE.md — any language directive?

Pick the dominant project language as the default. Announce it to the user in one line
and offer to override: *"По умолчанию пишу спеку на русском (как остальные доки проекта).
Другой язык?"* A single yes/no check is enough; do not escalate if the user says nothing.

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

Override: *"пропусти project-overview"* skips this phase entirely.

---

## Phase 1: Static Analysis

No interview yet. Extract everything the code itself answers.

Go through `references/analysis-checklist.md` section by section and capture findings
into the state file. The checklist covers:

- entry points and triggers (how the user reaches this feature)
- user-visible states (happy path, loading, empty, error, offline, permission-denied,
  degraded)
- data in / data out (API calls, persistence, events emitted)
- external dependencies (SDKs, native APIs, third-party services)
- side effects (analytics, logging, notifications, inter-feature messages)
- constraints enforced by the code (rate limits, retries, timeouts, debounces, maxima)
- platform capabilities used (camera, location, biometrics, file system, background
  work)
- navigation in and out
- localization and accessibility treatment

For each item, note: *what happens*, *under which condition*, *with which concrete
parameters*. Do not yet decide what is feature-specific vs project-wide — that happens in
Phase 2.

When the code shows a concrete number or string (retry = 3, debounce = 250 ms, error
copy = "Something went wrong"), write it down verbatim. The spec will carry these exact
values so a reimplementation matches.

---

## Phase 2: Convention Mapping

For every cross-cutting concern not owned by the feature (error handling, a11y,
analytics naming, localization, logging, pagination, caching), check how the rest of the
project handles it.

Decision table:

- **Feature follows project convention** — reference the convention in the spec
  ("Error states follow the project's standard ErrorBanner pattern; see
  `docs/<path>`"). Do not redescribe the convention itself.
- **Feature deviates** — call it out explicitly ("This screen overrides the project
  error banner with an inline snackbar; rationale unknown — see Open Questions").
- **Project has no convention and feature does not address it either** — mark absent
  ("No accessibility labels; consistent with project-wide absence."). This is the most
  commonly forgotten case; mark it honestly rather than inventing requirements.
- **Project has no convention but feature does something** — describe the feature
  behavior; flag that the project lacks a shared pattern.

These judgments live in the state file. They become cross-references in the spec.

---

## Phase 3: Clarification Loop

Now the user gets involved. Goal: close gaps the code cannot answer on its own.

**Default pacing: one question per round.** Each question is chosen based on the highest
remaining uncertainty after the previous answer. This is deliberately slower than batch
interviews — it produces better questions because each follow-up is informed by the
previous answer.

**Before the first question, set expectation.** Announce the queue size in one line so
the user can make an informed choice about pacing: *"Нашёл ~N пробелов после анализа.
Пойду по одному вопросу за раунд (так лучше формируются следующие вопросы). Скажи
«батчем» если хочешь получить всё сразу."*. This prevents the common failure mode where
the user patiently answers 10 questions in a row, then at the end says "could have done
that in one message".

For each open question in the state queue:

1. Re-read the state file.
2. Pick the single most valuable open question — typically one that unblocks the most
   downstream spec sections or one whose assumed answer would be most expensive to get
   wrong.
3. Ask it, with a **pre-filled default** derived from the code or from project
   convention. Example: *"Retry count is 3 in code. Is that an intentional product
   requirement, or an implementation default? (default: intentional — keep in spec as
   requirement)"*. The user accepts, overrides, or says "не знаю" (which itself is a
   valid answer and goes into Open Questions).
4. Update the state file with the answer.
5. Repeat until the queue is empty.

If the queue is large (>8 questions) and the user signals impatience or explicitly asks
to batch ("задавай всё сразу"), switch to batched mode for the remainder. Always respect
an explicit override.

Question categories that typically need user input:

- **Intent behind observed behavior** — is that 3-second timeout a product decision or
  copy-paste default?
- **Out of scope confirmation** — "these related screens are not in scope; confirm?"
- **Missing business context** — success metric, target user segment, historical
  context ("this was built for X partner integration").
- **Design source** — is there a Figma / design doc? Analytics plan? PRD?
- **Deviation rationale** — why does this feature bypass the project's standard error
  handler?

### 3.1 Freeform round

When the curated queue is empty, ask one final open question: *"Any additional context
that I have not asked about? (design links, analytics plan, PRD, constraints,
history…)"*.

Offer a menu of common inputs the user can supply:

- Figma or design links
- Screenshots / screen recordings
- API contract documents (OpenAPI, Protobuf, sample payloads)
- Analytics event taxonomy
- Localization glossary
- Product requirements document (PRD) or brief
- Historical context (who owns it, which partner requested it, prior incidents)

Anything the user supplies is treated as authoritative over inferred-from-code
information and is referenced in the spec.

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

Produce a draft at `docs/spec/<slug>.md` following `references/spec-template.md`.

Writing rules:

- **Zero code identifiers in the body** (see Principle 1 and
  `references/behavior-translation.md`). Sections 1–8 and 10–11 must read as if no
  particular codebase exists. Code identifiers belong only in §13 (Code map) as
  location pointers; §9 (Known defects) allows identifiers as evidence.
- **Tech only when load-bearing.** Technology names appear only in §12, and only when
  they pass the four-question test in `references/tech-abstraction.md`. Even then,
  phrase as a capability with acceptable substitutes, not as a direct SDK reference.
- **Concrete observable facts.** "On tap, the list refreshes" beats "the refresh flow
  is invoked". Include exact copy, exact numbers, exact states.
- **Cross-references instead of duplication.** When a section relies on a project
  convention, link to the existing doc or code rather than inlining.
- **Every claim is verifiable.** A reviewer with access to the code should be able to
  confirm or refute each bullet. Speculation goes under Open Questions, not in the
  body.
- **Appendix: code map.** At the end of the spec, include a table mapping each spec
  section to the file(s) that implement it. This is the only place where code paths
  appear. It enables round-trip verification and future maintenance.

Template structure — product first, tech at the end, defined in full at
`references/spec-template.md`:

- **Part A (§§1-7) Product behavior** — Overview, User-facing behavior, UI, States,
  Navigation, L10n & a11y, Analytics.
- **Part B (§§8-9) Product decisions & risks** — Open Questions (body uses `[OQ-N]`
  cross-refs), Known Defects.
- **Part C (§§10-12.5) Technical integration** — Data & integrations (8
  subsections: network ops / persistence / platform events at capability level /
  flags / services / contracts / collaborators at business level / domain model),
  Platform capabilities, Tech-specific constraints, External references (links to
  provider docs / RFCs).
- **Part D (§13) Appendix** — Code map (the only place code identifiers are
  allowed).

Sections that are genuinely not applicable are written as "N/A — reason", not
omitted. Missing sections look like oversight; explicit N/A shows intent.

---

## Phase 5: Coverage Verification

Before presenting the draft to the user, run a five-pass self-review plus a typo
sweep. The governing rule is the **proof standard** (full definition in
`references/coverage-verification.md`): every factual claim in the spec body traces
to one of four sources — code location, recorded user answer, project convention, or
an explicit Open Questions entry. Speculation — "it probably does X because that
would make sense" — is not a proof and must be removed or escalated.

Procedure (detailed steps in `references/coverage-verification.md`):

1. **Pass 1 — code → spec** (coverage). Every significant code branch maps to a spec
   section, or is explicitly recorded in §13 as intentionally omitted. Fix gaps.
2. **Pass 2 — spec → code** (grounding). Every spec claim traces to code, a user
   answer, a project convention, or §8 Open Questions. Remove or escalate
   untraceable claims. §9 Known Defects entries have an extra bar: code pointer +
   defect class + consequence all required.
3. **Pass 3 — identifier-leak scan** (vocabulary). Scan §§1-8 and 10-11 for tokens
   that exist only because this codebase exists. **Zero tolerance** — every hit is
   translated, moved to §13, or kept only if it is an external contract. §9, §12,
   §13 are excluded — they exist specifically for implementation detail.
4. **Pass 4 — reference integrity.** Every `[OQ-N]` marker in the body has a
   matching §8 entry; every §8 entry with body impact has at least one `[OQ-N]`
   in the body. Scriptable via grep.
5. **Pass 5 — code-map validity.** Every `path:line` in §13 points to an existing
   file, and the line (or end-of-range) is within the file's total lines. Scriptable
   via `test -f` + `wc -l`. Does not verify content match — that is covered
   indirectly by Pass 1 + Pass 2.

Plus a **typo / formatting sweep** at the end: orphan spaces inside words,
doubled-word typos, mixed Latin/Cyrillic characters, inconsistent punctuation around
quotes. Light but mandatory — a spec with typos erodes reader trust in substantive
claims.

The verification output — passed items, gaps fixed, identifier leaks cleaned,
reference-integrity resolutions, code-map validity count, typo sweep result,
unresolved gaps — goes into the state file and is summarized in one line when the
draft is presented.

### Definition of Done

The three passes above are mechanical checks. The spec is only ready to hand off when
the full **Definition of Done** checklist passes — eleven binary gates covering section
presence, the three Pass results, Open Questions and Known Defects completeness, Code
map coverage, header fill, and user review. See `references/definition-of-done.md`
for the detailed gates, rationale, and the handoff-format rules.

A half-satisfied checklist is not a ready spec — it is a progress report. Never
declare the draft ready unless all eleven gates pass.

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
- Offer to commit: *"Спека сохранена в `docs/spec/<slug>.md`. Закоммитить?"*. Do not
  commit without explicit confirmation.
- **Hygiene artefact (optional).** If the analysis surfaced implementation-level
  concerns that did not qualify for §9 Known Defects (hardcoded strings, weak PRNG
  for security values, plaintext token storage, log leakage, code-style issues),
  save them to `docs/spec/<slug>-hygiene.md` per `references/analysis-checklist.md`
  §14. Mention the artefact in the handoff: *"Также сохранил implementation-hygiene
  findings в `docs/spec/<slug>-hygiene.md` (N items) — это backlog для команды,
  поведения фичи не касается."* If no hygiene findings exist, mention briefly
  (*"Hygiene artefact: не понадобился."*) and do not create the file.
- **Project overview update flag.** If Phase 0.6 surfaced discrepancies between the
  observed code and the existing project-overview document, mention them once:
  *"В `docs/project-overview.md` поле <X> может быть устаревшим — наблюдаемое <Y>.
  Обновлять не стал — вне scope текущей фичи."*. The skill never silently edits
  the project overview.
- If the user intends to use this spec for reimplementation on another stack, mention
  that `write-spec` and `decompose-feature` can take this spec as input for the new
  implementation.

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

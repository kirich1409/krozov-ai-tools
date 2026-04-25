# Anti-patterns

Ways reverse-spec runs go wrong. Each entry describes the pattern, what makes it
tempting, and what to do instead. These are not rare — they are the most common
failure modes observed in practice, and most of them are invisible from inside the
skill itself (they feel right while being wrong).

Treat this list as a pre-publish review checklist: run through it before declaring
a draft ready.

## Leaking code identifiers into the body

Writing "`OAuthClient.authorize()` returns `OAuthResult.Success(tokens)` or
`OAuthResult.Error(exception)`" describes the current Kotlin API, not the feature. A
reimplementer on SwiftUI / Flutter / web gets nothing transferable from this.

The spec should say "authorization returns either a valid token set or a structured
failure" and let §13 (Code map) point at the file where that contract currently
lives. See `behavior-translation.md` for the full translation recipes.

## Copying code structure into the spec

"The feature has a ViewModel, a UseCase, and a Repository" describes the current
implementation, not the feature. A reimplementer on a different architecture gets
nothing from this — their architecture may have no equivalent concept. Describe
behavior; §13 records the current code layout.

## Inventing rationale

If the code has `retryCount = 3` and the user does not know why, the spec says
"retries 3 times" and adds "rationale unknown" to §8 Open Questions. Do NOT write
"retries 3 times to balance reliability and user wait time" unless the user confirmed
that. Invented rationale looks authoritative, but it corrupts decision-making
downstream when someone treats it as truth.

## Batching questions on the first pass

The user's preference by default is one question per round, because later questions
depend on earlier answers. Batch only when the user explicitly asks ("задавай всё
сразу"). Batching feels efficient but commonly produces shallower clarifications and
a queue of questions that needed the previous answers to formulate.

## Hiding absent conventions

If the feature has no accessibility support and the project has none either, the
spec must say so explicitly. Silent omission reads as "handled elsewhere" — the gap
is reintroduced during reimplementation because the new team assumes the spec
simply forgot to mention it. Explicit N/A with reason is the correct form.

## Over-specifying trivia

Exact font sizes, hex colors, and pixel margins are not spec-level unless they carry
product meaning (brand red, accessibility-critical contrast). Refer to the design
source (Figma, screenshots) for pixel-perfect values. Pinning trivia in the spec
creates spurious breaking-change reports every time a designer tweaks visuals.

## Declaring done without round-trip verification

A spec that misses a code branch will produce a reimplementation that misses a
behavior. Phase 5 is not optional — all five passes plus the typo sweep must run
before the draft is presented. Skipping to user review because the draft "looks
complete" is the most common way shipping specs acquire silent holes.

## Treating defect findings as spec content

When reverse-engineering surfaces a bug (crash path, dead link, security weakness),
the temptation is to describe the feature *as the code behaves*. That bakes the bug
into the spec and any reimplementation copies it. The feature's intent and the
current code's actual behavior are two different things. Defects belong in §9 with
four fields (what / class / evidence / consequence), marked "do not reproduce" —
never in the body.

## Skipping Phase 4.0 translate-step

The single biggest driver of identifier leakage is drafting directly from the state
file without the translate-step. Phase 4.0 is mandatory. A shortcut here shows up
several passes later as dozens of Pass 3 failures, and the translate work then has
to be done anyway — but now mid-document, which is harder.

## Confusing Phase 3 questions with §8 Open Questions

Phase 3 is the live interview with the user — questions get answers and close
immediately. §8 Open Questions is the section for questions that could *not* be
resolved in interview (user said "не знаю", no authoritative source available). Do
not dump every Phase 3 question into §8 — only the ones that remain open after the
interview.

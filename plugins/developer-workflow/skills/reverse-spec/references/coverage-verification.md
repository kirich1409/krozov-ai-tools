# Coverage Verification

Round-trip self-review run in Phase 5, before the draft is shown to the user. Purpose:
make sure the spec covers the code, and that everything in the spec is grounded in code
or user input.

A spec that looks thorough but misses a branch produces a reimplementation that misses
a behavior. A spec with claims that do not trace back to evidence is fiction. Both are
caught here.

---

## Proof standard (the rule that drives both passes)

Every factual claim in the spec body must trace to exactly one of these:

- **Code location** — `path/to/File.kt:42` or `path/to/File.kt:42-58`. Direct
  observation with a pointer a reviewer can open and verify.
- **User answer** — a Phase 3 clarification response recorded in the state file (quote
  the answer, not a paraphrase).
- **Project convention** — a cross-reference to an existing doc, shared component, or a
  code location that establishes the pattern project-wide. Recorded in Phase 2 findings.
- **Open Question** — the claim is marked as assumed in Section 8 of the spec and the
  consequence of being wrong is spelled out.

**No speculation.** If a claim cannot attach to one of the four sources, it does not
belong in the spec body — either find the evidence, escalate to Open Questions, or
delete the claim. "It probably does X because it would make sense" is not a proof; it
is speculation with nice phrasing.

This rule is what separates a reverse-engineered spec from an imagined one. A
reimplementer trusts the spec only if every statement can be traced back. The two passes
below operationalise the rule in both directions.

---

## Five passes, all required

Each pass catches a different class of failure and cannot substitute for the others:

- **Pass 1 — coverage:** *what code did the spec miss?*
- **Pass 2 — grounding:** *what spec claims have no evidence?*
- **Pass 3 — vocabulary:** *what implementation details leaked into the body?*
- **Pass 4 — reference integrity:** *do the spec's internal cross-references resolve?*
- **Pass 5 — code-map validity:** *do the Code Map pointers point at real code?*

Plus a final typo / formatting sweep before the draft leaves the skill. The five
passes are fast when run in order; skipping one breaks a specific guarantee the spec
claims to make.

---

## Pass 1 & 2: coverage and grounding

### Pass 1: code → spec (no code branch left behind)

Enumerate every significant branch, conditional, and public entry point in the feature's
files. For each one, locate the spec section that describes its **observable effect**.

**Branches that count as significant:**

- every `if / when / switch` that produces a different user-visible outcome
- every early return that changes what the user sees
- every `try / catch` branch that results in a distinct error state
- every `launch / runBlocking / Task { … }` that triggers side effects
- every navigation call
- every external call (API, DB, event emission, analytics, logging of product events)
- every string shown to the user (localized or hard-coded)
- every feature-flag / remote-config read that alters behavior

**Branches that do not count:**

- pure utility functions with no user-visible effect
- routine logging at debug / trace level
- architectural plumbing (DI wiring, coroutine scope management) without behavior
  change

Record findings in a simple table:

| Code location | What it does | Spec section | Status |
| --- | --- | --- | --- |
| `FooVM.kt:42` if branch | empty-state when list.isEmpty() | §4 States / empty | covered |
| `FooVM.kt:58` catch branch | offline error copy | — | **gap — add** |
| `FooUseCase.kt:77` retry loop | retry up to 3× | §2.2 / §7 | covered |

Every "gap" must be resolved before presenting the draft:

- **Add to spec** — the behavior is spec-worthy; extend the relevant section.
- **Justify omission** — the branch has no observable effect (e.g., a fallback logger);
  note in the code map that it is intentionally not in the spec.
- **Escalate** — the branch is ambiguous; put the question into Phase 6's open-questions
  queue instead of inventing coverage.

### Pass 2: spec → code (every claim is grounded)

Walk through the draft spec top to bottom. For each concrete claim — a number, an exact
copy string, a state description, an event name — answer: *what is the evidence?*

Valid evidence sources:

- **Code location** — direct observation, recorded in the code map.
- **User input** — a clarification answer from Phase 3, recorded in the state file.
- **Project convention** — a cross-reference to a documented or widely-used pattern in
  the project, recorded in Phase 2 findings.
- **Explicit Open Question** — the claim is marked "assumed" in section 8 of the spec.

**Extra bar for §9 Known defects entries.** A claim that the current code has a bug is
stronger than a regular spec claim and requires more than "I saw this in the code" as
evidence. Every §9 entry must have:

- A concrete code pointer showing the defective behavior (path:line with a short quote
  or condition).
- A stated defect class (crash, unreachable code, security weakness, dead link,
  localization gap, data loss, race condition, other).
- A stated consequence (what user sees, what risk is created).

If any of those three are missing, the entry is not a confirmed defect — downgrade it
to §8 Open Questions and let a later clarification round (or user review) decide.
Speculation disguised as a defect report is worse than a plain open question, because
it signals false confidence.

If a claim has no evidence, it is speculation and must be removed or rewritten:

- if the user can answer it → move it to Phase 6 questions
- if the user also does not know → leave the observed fact in the spec body, add an
  Open Questions entry for the missing rationale
- if it was filler ("this feature is important for customer retention") with no grounding
  → delete

---

### Pass 3: identifier-leak scan (the zero-tolerance pass)

The biggest failure mode of a reverse-engineered spec is describing the current code
instead of the feature. The first two passes catch coverage and grounding. Pass 3
catches vocabulary.

**Scan every sentence in the body (Sections 1–9 and 11)** for any token that exists
only because this codebase exists. The pattern list:

- `CamelCase` or `PascalCase` words that are class / interface / type names
- `lowerCamelCase` identifiers that are method or property names
- `snake_case_package` paths, `com.example.x.y.z` dotted paths
- file paths (`AuthScreen.kt`, `path/to/File.swift`)
- sealed-class case names (`OAuthResult.Success`, `AuthState.Error`)
- reactive-primitive names (`StateFlow`, `Observable`, `Publisher`, `BehaviorSubject`)
- async-primitive names (`suspend`, `Task`, `Future`, `Deferred`, `Promise`, `async`)
- language keywords that leak idioms (`expect`, `actual`, `sealed`, `data class`)
- framework-specific terms (`@Composable`, `@State`, React hook names)

For every hit, decide:

- **Translate** — rephrase using `references/behavior-translation.md`. Rewrite the
  sentence; re-run Pass 1 and Pass 2 on the rewritten claim to confirm coverage and
  grounding are preserved.
- **Move to §13** — if the identifier was a location pointer dressed as prose (`see
  AuthViewModel`), move it into the Code Map table and delete the mention from the
  body.
- **Keep** — only when the identifier is an *external contract* (e.g., `Bearer` token
  type from RFC 6749, `application/x-www-form-urlencoded` content type,
  `payment_confirmed` analytics event). The test: *does this name exist in an
  external specification or wire protocol, independent of this codebase?* If yes,
  keep literal. Otherwise, translate or move.

**Zero tolerance.** A single leaked identifier in the body means the spec describes the
implementation, not the feature. If the pass finds any, the draft is not ready — fix
and re-scan before presenting.

The scan output goes into the state file as a short report:

> *"Pass 3 scan: 14 identifier hits initially — 9 translated (see change log below), 4
> moved to Code Map, 1 kept as external contract (`Bearer` per RFC 6749). Final scan:
> 0 leaks."*

If the grep / search tool is available, this pass can be partially automated:
`rg -n "\b[A-Z][a-zA-Z]+(Client|Service|Repository|ViewModel|Component|Use[Cc]ase|State|Storage|Config|Result|Exception)\b"` through sections 1–9 and 11 flags the majority of candidate leaks. Human judgment still required on each hit.

---

### Pass 4: reference integrity

A spec with broken internal cross-references tells the reader to go somewhere that
isn't there. The most common break: body mentions `[OQ-3]` but §8 has no entry 3.

Run two scans:

**Body → §8** — grep the body (§§1-8 excluding §8 itself, §§10-11) for markers
matching `\[OQ-\d+\]`. For each hit:

- Does §8 contain an entry with exactly that marker? If not → fail.

**§8 → body** — list every entry in §8. For each entry:

- Does its `Why it matters` or `Current assumption` imply body impact (i.e., the
  claim is something the body relies on)? If yes, is there at least one matching
  `[OQ-N]` in the body? If no match → fail.
- Entries that are purely follow-ups without body dependency (e.g., "should we add
  analytics later?") are exempt from the reverse scan.

**Implementation note.** This pass can be automated with a small script: extract all
`[OQ-N]` from body text and all entry numbers from §8, then diff. Run it manually
during Phase 5 or bake into a pre-commit hook.

Any failure blocks the DoD gate for §8 — the spec is not ready until both directions
resolve.

### Pass 5: code-map validity

Every entry in §13 Code map is a promise: "open this file at this line and you'll
see the referenced behavior". When the file is renamed, deleted, or the lines shift,
the promise breaks silently. Pass 5 tests the promise mechanically.

For each row of the §13 table:

1. **Parse the pointer.** Format is `path/to/File.ext:N` or `path/to/File.ext:N-M`.
   Paths are relative to the repository root. Multiple pointers in one cell are
   comma-separated.
2. **File existence.** `test -f <path>` — file must exist. If not → fail with "file
   missing".
3. **Line range validity.** `wc -l <path>` — line number N (or end-of-range M) must
   be ≤ total lines in the file. If not → fail with "line out of range".
4. **Range sanity.** For ranges `N-M`, require `N ≤ M`. Reversed ranges → fail.

Pass 5 does not verify *content match* (whether the linked lines actually show the
described behavior) — that would require semantic analysis. It verifies only that
the pointer resolves. Content match is covered indirectly by Pass 1 (each body
section mapped to a location) + Pass 2 (each claim grounded in code).

A short shell snippet does all three checks:

```sh
while read path line_spec; do
  [ -f "$path" ] || { echo "FAIL: $path missing"; continue; }
  total=$(wc -l < "$path")
  end=${line_spec##*-}
  [ "$end" -le "$total" ] || echo "FAIL: $path:$line_spec exceeds $total lines"
done < code-map-pointers.txt
```

Any failure blocks the DoD gate for §13.

### Final sweep: typos and formatting

A trailing pass, light but mandatory. Run through the body and catch:

- stray orphan spaces inside words (`«не заверш ается»`)
- common misspellings in the document's working language
- inconsistent punctuation around code spans / quotes
- accidentally doubled words ("the the", "для для")
- mixed Latin / Cyrillic characters that look identical (e.g., Latin `a` inside a
  Cyrillic word)

This is not a rigorous spell-check pass — it is the equivalent of a quick proofread.
A spec with typos in the body reads as sloppy and erodes reader trust in the more
substantive claims nearby. The pass takes a minute; skipping it costs more.

---

## Summarizing the result

Before presenting the draft, write a one-line summary of the verification into the state
file and include it in the hand-off message:

> *"Coverage: 42/42 branches mapped, 3 intentionally omitted (see Code Map). All spec
> claims traced to code or answers. Identifier scan: 0 leaks in body. Reference
> integrity: 14 OQ-markers ↔ 14 entries, all resolve. Code-map validity: 18/18
> pointers valid. Typo sweep: clean. 2 entries in Open Questions remain unresolved."*

This summary is the signal to the user that the draft was checked, not just written.

---

## When gaps cannot be closed

Sometimes analysis reveals a branch whose behavior depends on context only the user can
supply (e.g., a server-driven config value that changes copy). In that case:

1. Capture the observed code behavior in the spec body ("renders copy from remote
   config key `payment.tooltip.copy`").
2. Add to Open Questions: *"What are the valid values for `payment.tooltip.copy`? The
   spec currently lists the fallback string only."*.
3. Do not fabricate values to close the gap.

The spec remains honest about what is known and what is outstanding. A reimplementer can
act on both — on the known behavior immediately, on the open questions once the user
answers.

---

## Interaction with Phase 6

The coverage report drives Phase 6's question batch. When the draft is presented:

- *"2 branches had ambiguous intent — do you want me to ask about them?"* is a natural
  opener if the user has capacity.
- If the user approves the draft as-is, the Open Questions entries stay and travel with
  the spec. That is the correct outcome: a spec that surfaces unknowns beats a spec that
  hides them.

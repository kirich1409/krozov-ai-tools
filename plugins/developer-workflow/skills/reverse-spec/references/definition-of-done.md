# Definition of Done

The five coverage-verification passes plus the typo sweep (Pass 1 / Pass 2 / Pass 3 /
Pass 4 / Pass 5 / typo) are mechanical checks. They catch specific failure modes —
missing coverage, ungrounded claims, leaked code identifiers, broken cross-refs,
dangling code-map pointers, sloppy text. But they do not by themselves answer the
question *"is this spec ready to hand off?"*.

This file is that answer: a binary gate of eleven items. The spec is ready only when
every item is checked. A half-satisfied checklist is not a ready spec — it is a
progress report. Always report the checklist in the Phase 6 handoff alongside the
Phase 5 verification summary.

Treat the gate as sequential only when convenient; most items can be checked in any
order, but all must be checked before the skill declares the draft ready.

## The eleven gates

### 1. All 13 sections present

Every section from `spec-template.md` appears in the draft, either with content or
with an explicit `N/A — <one-line reason>` stub. Never silently skip a section —
missing sections read as oversight; explicit N/A reads as considered absence.

### 2. Pass 1 (coverage) clean

Every significant code branch in the scoped files maps to a spec section, or is
explicitly recorded in §13 Code map as intentionally omitted (architectural plumbing,
routine logging, DI wiring). No unmapped branch is acceptable.

### 3. Pass 2 (grounding) clean

Every factual claim in the body traces to exactly one of: code location, recorded
user answer, project convention cross-reference, or an explicit Open Question entry.
Zero speculation. If a sentence cannot be traced, it is removed or demoted to an
Open Question.

### 4. Pass 3 (identifier leak) clean

Zero code identifiers in §§1-8 and 10-11. Allowed in body: external contract names — URL
patterns, RFC field names, analytics event names, wire-protocol terms. Forbidden in
body: codebase-specific class names, method names, sealed-class cases, reactive /
async primitive names, framework idioms, file paths.

### 5. §8 Open Questions populated or explicitly empty

Either ≥1 entry with assumption + consequence of being wrong, or the literal line
`No open questions — all clarifications resolved.` in the section body. An empty
section reads as oversight; either form of content reads as considered.

### 6. §9 Known defects complete

Every defect entry has all four required fields: **what**, **class**, **evidence**
(path:line pointer + quote/scenario), **consequence**. If the feature has no
confirmed defects, the section contains `N/A — no confirmed defects identified.`
Partial entries (missing one of the four fields) are not acceptable — demote to §8
Open Questions instead.

### 7. §13 Code map covers body

Every body section that has content (§§2-7 Product, §§10-11 Technical, as applicable;
sections marked N/A are exempt) has at least one location pointer in the Code map
table. A body section without any Code map entry means the claim cannot be verified
by a reader.

### 8. Header fully filled

The spec's header block contains, at minimum:

- **Status** — `Draft` or `Approved`
- **Source** — commit SHA or calendar date when the code was analysed
- **Language** — the working language of the document
- **Owner** — team / person, if known; `unknown` if not

Missing fields = spec not ready. The header is how a future reader knows which
version of the code this spec describes.

### 9. Pass 4 (reference integrity) clean

Every `[OQ-N]` marker in the body has a matching entry in §8, and every §8 entry
with body impact has at least one `[OQ-N]` in the body. Unidirectional references
in either direction fail this gate.

### 10. Pass 5 (code-map validity) clean

Every `path:line` pointer in §13 points to a file that exists and a line (or range)
that falls within the file's total lines. No missing files, no out-of-range pointers,
no reversed ranges.

### 11. Typo sweep and user review

Two items bundled as the final gate:

- **Typo sweep completed.** Body read through for orphan spaces inside words,
  doubled words, mixed Latin/Cyrillic characters, inconsistent punctuation. No
  typos remain.
- **User reviewed in Phase 6.** The user has seen the draft and either approved it
  or requested changes. The skill does not self-approve. This is the gate that
  distinguishes *"the machinery said yes"* from *"a human stakeholder confirmed
  this matches intent"*.

## Handoff format

When all eleven items are checked, the skill produces a one-line ready signal in the
Phase 6 / Phase 7 handoff:

> *"Spec ready — all DoD gates passed. Saved at `docs/spec/<slug>.md`."*

When any item is unchecked, the skill produces a progress report instead, listing:

- Which items are checked (say "N/11 passed" with the list)
- Which items remain open and what would need to happen to close each one
- Estimated next action (another review round? user clarification? coverage gap fix?)

Never hide an unchecked gate by treating it as optional. The DoD is the skill's
contract with the user — if gates are optional, the contract is empty.

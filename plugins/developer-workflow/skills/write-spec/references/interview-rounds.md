Referenced from: `plugins/developer-workflow/skills/write-spec/SKILL.md` (§Phase 2 Interview).

# Interview Rounds — Question Bank, Round Structure, and Per-Round Prompts

Full Phase 2 playbook. SKILL.md holds only the round-loop contract and exit
criteria. Everything a round actually *says* to the user lives here.

---

## Feature Checklist (run before formulating questions)

After research completes, sweep the checklist. Any item that applies and is
unanswered becomes a question or a spec entry.

- [ ] **OS permissions** — does this feature need to request permissions
      (notifications, camera, location, contacts, storage)? What happens if denied?
- [ ] **Platform-specific behavior** — does this work differently on different OS/devices?
- [ ] **Prerequisites** — are there external setup steps (console config, service
      accounts, API keys, entitlements) that can't be automated in code?
- [ ] **Error states** — what can fail? What does the user see when it fails?
- [ ] **Security** — does this expose sensitive data, require auth, or touch user
      credentials?
- [ ] **Performance** — any risk of blocking the main thread, excessive memory, or
      battery drain?
- [ ] **Backward compatibility** — does this change existing behavior anyone depends on?
- [ ] **Pattern quality** — did Critical Evaluation flag any existing pattern as
      problematic?

---

## Round 1: Present Approach Options (when Critical Evaluation ran)

If Critical Evaluation produced 3 approach options, present them **before** asking
other questions. This is the most important decision — it shapes everything else.

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

Wait for the user to choose before proceeding. The chosen approach becomes the
baseline for all subsequent questions.

---

## Synthesize Gaps

After the approach is chosen, sort remaining findings into three buckets:

- **Already known** — research gave a clear answer, no need to ask.
- **Proposed defaults** — research suggests a direction; propose it for confirmation.
- **Genuine gaps** — requires user input to resolve.

Only ask about genuine gaps. Present proposed defaults as recommendations the
user confirms or overrides.

---

## Question Format

Each question in a round:

```
**Q: {question}**
→ Recommended: {answer} — {brief rationale}
→ Alternative: {different option}
→ Alternative: {another option, if relevant}
→ Or describe your preference: ___
```

Skip questions where the recommendation is overwhelmingly obvious and the answer
doesn't meaningfully change the architecture. Save those decisions for the
"Decisions Made" section in the spec.

---

## Round Structure

Each round:

1. Present what's already understood (brief — gives user context).
2. Ask all current open questions with recommended answers.
3. Wait for responses.
4. Record answers in the state file.
5. Check whether any new gaps opened from the answers.
6. If gaps remain → another round. If complete → proceed to drafting.

**Cap: maximum 100 interview rounds.** If the 100th round completes and gaps
remain, record them as open questions in the spec (non-blocking where possible)
and proceed to drafting. Surface any remaining blockers to the user in the
review phase.

---

## Large-Feature Phasing

If the feature spans multiple independent development phases, offer a phased
approach:

```
This feature is substantial. Suggested phases:

**Phase 1 — {name}:** {what it delivers and why first}
**Phase 2 — {name}:** {what it adds, depends on Phase 1}
**Phase 3 — {name}:** {what it adds}

Recommendation: spec and fully implement Phase 1 before speccing Phase 2.
Real feedback from Phase 1 will inform Phase 2 design.

Proceed phased, or spec the full feature at once?
```

If phased: spec covers Phase 1 only. Include a "Future Phases" section for
what's planned but not yet specced.

---

## Post-Review Discussion Round

After self-review and `multiexpert-review` complete (Phase 4), if either
surfaced issues or open questions, open one more user-facing round using the
same question format above. This may loop back into the normal round loop to
close remaining gaps.

Once the user is satisfied and no issues remain, update spec status from
`draft` to `approved` and proceed to save.

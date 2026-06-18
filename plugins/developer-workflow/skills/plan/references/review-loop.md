# Review loop: writer vs. skeptic

The single most important property of this skill is that **the agent that writes the plan is not the
agent that approves it.** A planner has a built-in incentive to produce something that *passes the
gate quickly* — to declare the plan "good enough" and move on. Left unchecked, that incentive yields
plans full of hand-waving ("handle errors appropriately", "wire it up", "update the relevant
files") that look complete and fall apart in implementation.

The defence is a **separate, adversarial critic** whose only job is to find what is wrong. Two
mechanisms provide it, and they compose:

1. **multiexpert-review (`implementation-plan` profile)** — the panel critique (Phase 3). The
   profile's prompt augmentation puts each reviewer in a strict-but-fair red-team stance with an
   explicit anti-gaming rubric. This is the primary critic and is mandatory.
2. **Adversarial red-team pass** (Phase 3.5) — one skeptic agent that does not *review* the plan but
   tries to *use* it and break it, surfacing the holes an implementer would hit. Mirrors
   `write-spec` Phase 4.5.

"Strict but fair" cuts both ways: the critic must not wave through real weaknesses, and must not
invent blockers to look thorough. A finding has to name the weakness, where it is, and why it
matters.

---

## Phase 3 — multiexpert-review (the panel critic)

Invoke `multiexpert-review` **inline** (the skill calls it directly, as `write-spec` Phase 4.3 calls
it — skills do not chain through each other except these established in-skill invocations: the Phase 3
`multiexpert-review` call and the Phase 3.5 red-team Agent call are both part of the review gate, not
forbidden downstream chaining). Prepend the profile
hint so detection is deterministic for an inline file path:

```
profile: implementation-plan
---
docs/plans/<slug>/plan.md
```

Why the hint: inline-arg callsites lack the frontmatter the detector classifies on; the prefix
short-circuits detection. The plan is already on disk, so the engine classifies the source as
`file` and edits the plan in place on FAIL/CONDITIONAL, and writes the verdict back into the plan's
frontmatter via the profile's `receipt`.

The profile selects 2–3 reviewers by tech-match from the plan content (do not pad the panel; do not
drop a genuinely-triggered reviewer). `--quick` permits a single reviewer.

**Loop** — 3 review cycles total: 1 initial review + up to 2 re-reviews (same cap as `finalize`):

| Verdict | Action |
|---|---|
| PASS | `review_verdict: pass` → Phase 4. |
| CONDITIONAL | Engine edits the plan to address majors; re-review. Residual majors after the cap (cycle 3) → record in `## Open Questions` (non-blocking), proceed. |
| FAIL | Engine edits to fix blockers; re-review. On cycle 3 returning FAIL → go directly to escalate, no further re-review. |

After the 3rd cycle with blockers remaining → `review_verdict: escalate`, write blockers into
`## Open Questions` (tagged blocking), retire (delete) the state file
`./swarm-report/plan-<slug>-state.md`, and surface. This is the only autonomous stop, and only for
genuine blockers.

---

## Phase 3.5 — Adversarial red-team pass (the skeptic)

Run **one** Agent (general-purpose, sonnet) as a hostile implementer. It does not grade the plan
against a rubric — it tries to build from it and reports every place it would have to guess:

> You are the engineer ordered to implement `docs/plans/<slug>/plan.md` exactly as written, with no
> further questions allowed. Do not praise or summarize it. Pick the riskiest task in `tasks.md` and
> mentally implement it end-to-end: inputs → state changes → outputs → error paths → cleanup. Every
> time the plan forces you to GUESS a detail, invent a contract, or fill a gap, record it as:
> "I'd have to guess X because the plan doesn't specify Y (file/section)". Also flag any acceptance
> that is not actually checkable, any "handle/wire/update appropriately" hand-waving, any missing
> failure mode, and any task that secretly hides two days of work. Be strict but fair: only real
> gaps, no invented blockers. Cap 15 items, ordered by how badly each would derail implementation.

For each item:

- **Trivially fillable** (one-line clarification) → edit the plan inline, move on.
- **Real design gap** → fix the plan; if it needs a user decision, surface it subject to the
  **Headless mode** contract in `SKILL.md` (`AskUserQuestion` only when interactive / a user is
  present; otherwise record as a `[blocking]` Open Question, set `review_verdict: escalate`, stop).
- **Already specified, agent missed it** → no action.

Skip only with `--quick` on a small, well-bounded change with no risky tasks.

---

## Anti-gaming rubric (shared by both critics)

The critic rejects, as blockers or majors, plans that try to pass without substance:

- **Hand-waving verbs** — "handle errors appropriately", "wire it up", "update the relevant files",
  "as needed" with no concrete target. Demand the actual file, contract, or behaviour.
- **Unfalsifiable acceptance** — any task `check` that a human has to judge ("looks right", "works
  well"). Demand a test name, grep, or build target.
- **Missing failure modes** — happy path only. Demand the error/edge/empty/concurrent cases the
  change can hit.
- **Invisible scope** — a one-line task that hides a subsystem. Demand it be split or sized
  honestly.
- **Untraced requirements** — a spec `AC-N` with no task that satisfies it, or a task that satisfies
  nothing. Demand the mapping be complete.

This rubric is what converts "a plan that passes" into "a plan that is right". It lives in the
profile's prompt augmentation so the panel applies it automatically.

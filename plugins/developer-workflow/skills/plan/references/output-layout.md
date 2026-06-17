# Output layout & hand-off

## Paths

| File | Lifetime | Committed? |
|---|---|---|
| `docs/plans/<slug>/plan.md` | Permanent | Yes — reviewed in the PR |
| `docs/plans/<slug>/tasks.md` | Permanent | Yes |
| `docs/plans/<slug>/progress.md` | Permanent (volatile content) | Yes — the execution ledger / audit trail |
| `./swarm-report/plan-<slug>-state.md` | Operational | No (gitignored) — delete after |

`docs/plans/` is intentionally a sibling of `docs/specs/`: spec = *what* (requirements + AC), plan =
*how* (design + tasks). Both live in git because their value is being reviewable in the PR and
resumable later — the exact property built-in plan mode lacks.

Slug rules match the rest of the toolbox: kebab-case, derived from the feature/task or branch name
with common prefixes (`feature/`, `fix/`, …) stripped.

## Status lifecycle

`plan.md` frontmatter `status`: `draft` → `approved` (Phase 4 on PASS/CONDITIONAL). On
`review_verdict: escalate`, leave `status: draft` and stop with the blocking open questions
surfaced.

`review_verdict`: `pending` → `pass` | `conditional` | `escalate`, written by the Phase 3 loop (and
by the profile receipt).

## Confirmation message (default, autonomous)

One sentence, e.g.:

> Plan saved to `docs/plans/offline-mode/plan.md` (review: PASS, 7 tasks). Starting with T-1 —
> add the offline cache layer.

No approval prompt. With `--interactive`, present the compact summary and ask one go/adjust question
before flipping to `approved`.

## Hand-off rules

- Do **not** auto-invoke downstream skills. Suggest the next step (implement the tasks; then
  `/write-tests`, `/check`, `/finalize`, `/acceptance`) and let the user/agent drive — toolbox
  model.
- `progress.md` is the live ledger: as each `T-N` lands, check its box and append a one-line
  learning. The implementer commits plan + code together so the PR shows the plan that produced the
  change.
- `create-pr` discovers `docs/plans/<slug>/plan.md` and references it in the PR body; `finalize`
  anchors its `code-reviewer` pass on the same plan. No extra wiring needed beyond writing the file.

# Per-Check Artifact Schema

Every sub-check writes `swarm-report/<slug>-acceptance-<check>.md` with the frontmatter
below. File naming is **one file per `check` value** — when a single agent invocation
covers multiple concerns (e.g. `ux-expert` with mode `both`), it writes separate files per
concern to keep the one-file-per-check invariant intact.

## Frontmatter

```yaml
---
type: acceptance-check
check: manual | code | build | ac-coverage | design | a11y | security | performance | architecture | build-config | devops
agent: <agent-name or "bash">
verdict: PASS | WARN | FAIL | SKIPPED
severity: critical | major | minor | null
confidence: high | medium | low | null
domain_relevance: high | medium | low | null
diff_hash: <sha256 of `git diff <base>...HEAD` at the moment the check ran; null for checks that do not depend on the diff>
blocked_on: <optional — what the user must resolve; also used when a planned per-check artifact is missing>
---
```

`severity`, `confidence`, `domain_relevance` are required when `verdict` is `WARN` or
`FAIL`; null for `PASS` / `SKIPPED`. These drive the PoLL aggregation in Step 4.

## `diff_hash` semantics

Computed once per acceptance run from `git diff <base>...HEAD | sha256sum`; every check
written during that run records the same value. The Re-verification Loop uses it to decide
which checks to re-run (see `references/re-verification-loop.md`). Bash-only checks (build
smoke) record the same hash because their input is the same diff. Checks whose verdict does
not depend on the diff at all (e.g. a spec-only sanity check with no code to review) may
write `diff_hash: null` — the Re-verification Loop never skips such a check purely on hash
match.

## Check identifiers vs file naming

- `check: build` — non-UI build smoke run as a Bash command (Step 3.3).
- `check: build-config` — expert review of build config changes performed by
  `build-engineer` (Step 3.9). Distinct from `build` so aggregation can treat the two axes
  independently (a project can have a clean smoke and a broken config, or vice versa).
- `check: design` and `check: a11y` — produced by `ux-expert` in `design-review`, `a11y`,
  or `both` mode. In `both` mode the agent writes **two** artifacts.

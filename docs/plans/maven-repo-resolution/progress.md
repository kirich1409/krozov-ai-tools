# Progress: maven-mcp repository resolution layer (#310 + #311; core of #299)

> Plan: ./plan.md · Tasks: ./tasks.md · Branch fix/maven-repo-resolution (merged as #321)

## Status
- [x] T-1 — brace-depth block scanner
- [x] T-2 — Gradle/Maven repository parsers
- [x] T-3 — scoped discovery orchestrator
- [x] T-4 — ResolutionContext + project-first `_repos_for` + fallback
- [x] T-5 — merge metadata, keep raise-contract (#311)
- [x] T-6 — thread ctx through all resolvers + tool schemas
- [x] T-7 — docs + coverage-map + L5 smoke
- [x] T-8 — open PR (#321 merged 2026-06-29)

## #299 completion (Wave 4 verification, 2026-07-09)

All #299 acceptance criteria are now met on `main` via the follow-up sequence:

| AC | Delivered by |
|----|--------------|
| Project-declared repos primary; publics demoted to fallback | #321 (`_repos_for` + `MAVEN_MCP_PUBLIC_FALLBACK`) |
| Plugin vs dependency scope routing | #321 |
| Shorthands → URLs when declared | #321 |
| Results expose which repo answered + `viaPublicFallback` | #317 (#335) |
| `repositoriesMode` (PREFER_PROJECT / FAIL_ON_PROJECT_REPOS) | #318 |
| Maven parent-POM / active-profile inheritance | #319 (#337) |
| Content / group filtering | #320 (#339) |

No further product code required for #299. Residual gaps remain documented in `plugins/maven-mcp/AGENTS.md` (settings.xml profiles, exclusiveContent shorthand filters, root-only discovery) and are tracked separately — they do not block closing #299.

Verification (this branch): `python3 -m unittest discover -s plugins/maven-mcp/tests` → 599 OK (1 skipped); `bash scripts/validate.sh` → green.

## Learnings
- Cycle-1 review (build-engineer/architecture/pr-test-analyzer) → FAIL, ~25 findings. Revised: descoped #299 to core (deferred #317–#320), added hand-written brace scanner (regex can't balance), thread ctx through ALL resolvers (not just handlers), keep fetch_metadata raise-contract, Google-group heuristic in fallback, naive-union merge w/ stability-aware selection (dropped false "matches resolveAll"), buildscript→plugin scope, mavenLocal-only→fallback, per-invocation memoization, baseline 211.
- #299 stayed OPEN after #321 because the plan intentionally did not auto-close it; #317–#320 closed the deferred ACs but never linked `Fixes #299`. Wave 4 closes that bookkeeping gap.

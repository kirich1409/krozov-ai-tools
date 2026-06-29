# Progress: maven-mcp repository resolution layer (#310 + #311; core of #299)

> Plan: ./plan.md · Tasks: ./tasks.md · Branch fix/maven-repo-resolution

## Status
- [ ] T-1 — brace-depth block scanner
- [ ] T-2 — Gradle/Maven repository parsers
- [ ] T-3 — scoped discovery orchestrator
- [ ] T-4 — ResolutionContext + project-first `_repos_for` + fallback
- [ ] T-5 — merge metadata, keep raise-contract (#311)
- [ ] T-6 — thread ctx through all resolvers + tool schemas
- [ ] T-7 — docs + coverage-map + L5 smoke
- [ ] T-8 — open PR

## Learnings
<!-- one line per completed task -->
- Cycle-1 review (build-engineer/architecture/pr-test-analyzer) → FAIL, ~25 findings. Revised: descoped #299 to core (deferred #317–#320), added hand-written brace scanner (regex can't balance), thread ctx through ALL resolvers (not just handlers), keep fetch_metadata raise-contract, Google-group heuristic in fallback, naive-union merge w/ stability-aware selection (dropped false "matches resolveAll"), buildscript→plugin scope, mavenLocal-only→fallback, per-invocation memoization, baseline 211.

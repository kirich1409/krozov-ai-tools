# Progress: maven-mcp — Python as the single source of truth

> Plan: ./plan.md · Tasks: ./tasks.md

## Status
### PR A — chore/maven-python-tests (rebased on current main: #303/#304/#305)
- [ ] T-1 — Test harness scaffold
- [ ] T-2 — version domain tests
- [ ] T-3 — parser & scan tests
- [ ] T-4 — github + changelog tests
- [ ] T-5 — maven/search/OSV network tests
- [ ] T-6 — tool handler integration tests (+ #263 regression)
- [ ] T-7 — http_get / http_post_json tests
- [ ] T-8 — coverage-map deliverable + trace
- [ ] T-9 — CI: add python-tests job (mirror build gating)
- [ ] T-10 — file 4 divergence follow-up issues
- [ ] T-11 — open PR A

### PR B — chore/maven-remove-ts (after PR A merged)
- [ ] T-12 — remove TS reference
- [ ] T-13 — CI/release/codeql: remove node, python becomes gate
- [ ] T-14 — docs: Python-first
- [ ] T-15 — server.py docstring 3.6+ → 3.9+
- [ ] T-16 — branch ruleset required-check transition (2 steps)
- [ ] T-17 — L5 runtime smoke + open PR B

## Learnings
<!-- Append one line per completed task: surprises, gotchas, decisions taken during implementation. -->
- Cycle-1 review (architecture/devops/pr-test-analyzer) → FAIL. Revised: added release.yml + codeql.yml to PR B (both would break), split ruleset transition (T-16 a/b) to avoid BLOCKED-while-mergeable, python-tests job must mirror build's always-run+step-gate, removed invalid T-4 (agp/androidx/html absent in server.py), named big parsers (plugins-block 22 cases), added coverage-map deliverable, pinned #263 observable, 4 divergences (retry/cache/agp-androidx-html/http-sse). Version-sync already correct on main (#305).

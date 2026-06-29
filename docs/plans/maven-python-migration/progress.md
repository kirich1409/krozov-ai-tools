# Progress: maven-mcp — Python as the single source of truth

> Plan: ./plan.md · Tasks: ./tasks.md

## Status
### PR A — chore/maven-python-tests (rebased on current main: #303/#304/#305)
- [x] T-1 — Test harness scaffold (_helpers.py: __file__ shim, mock_urlopen, http_error, temp_project)
- [x] T-2 — version domain tests (30)
- [x] T-3 — parser & scan tests (81)
- [x] T-4 — github + changelog tests (27)
- [x] T-5 — maven/search/OSV network tests (33, incl. #6 first-hit)
- [x] T-6 — tool handler tests + #263 regression (24, incl. health P3 helpers)
- [x] T-7 — http tests (11) — 209 total, all green
- [x] T-8 — coverage-map.md (47: 30 ported/3 partial/12 diverged/2 N/A) + harness ResourceWarning fixed
- [x] T-9 — CI python-tests job (3.9/3.13, always-run + step-gate, actionlint clean)
- [x] T-10 — follow-up issues filed: #306 retry, #307 cache, #308 agp/androidx/html, #309 http-sse, #310 custom-repo (bug,→#293), #311 first-hit (bug,→#293), #312 version-selection (bug), #313 parser-gaps+utcnow
- [ ] T-11 — open PR A (in progress)

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

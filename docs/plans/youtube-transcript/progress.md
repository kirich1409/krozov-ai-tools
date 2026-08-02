# Progress: youtube-transcript MCP plugin (v1, stdio-only)

> Plan: ./plan.md · Tasks: ./tasks.md

## Status
- [x] T-1 — Package skeleton, pyproject.toml, test harness shim
- [ ] T-2 — `domain/` complete
- [ ] T-3 — Contracts freeze: session-scoped provider port, `net`/`formats` constants, AST import-boundary test
- [ ] T-4 — `providers/video_ref.py`
- [ ] T-5 — `formats/{text,srt,vtt}.py`
- [ ] T-6a — `net/client.py` policy: scheme/host allowlist, TLS, redirect handling
- [ ] T-6b — `net/client.py` resource controls: caps, deadline, retry, XML guard
- [ ] T-7 — `protocol/envelope.py` + `schemas.py`
- [ ] T-8 — `tools/cursor.py`
- [ ] T-9 — `tools/resolution.py`
- [ ] T-13a — `protocol/registry.py` + `dispatch.py`
- [ ] T-10 — `providers/innertube.py`
- [ ] T-11 — `tools/list_transcript_tracks.py`
- [ ] T-12 — `tools/get_transcript.py`
- [ ] T-13b — `composition.py` + `server.py`
- [ ] T-14 — Cross-cutting AC tests
- [ ] T-15 — Live canary
- [ ] T-16 — Plugin docs + final `validate.sh`/coverage pass
- [ ] T-P1 — Versioning and repo-doc generalization
- [ ] T-P2 — CI workflows
- [ ] T-P3 — Network spike: allowlist confirmation, canary videos, size/latency/RSS measurement
- [ ] T-P4 — Spec addendum: sync remaining plan/spec divergences

## Blocking / Human-owned items (not a task, tracked here so they aren't missed at merge time)
- [ ] Register the four new `youtube-transcript` CI jobs as required branch-protection status checks — repo-settings action, Human-owned, cannot be verified from the working tree by any agent. Blocks release (spec Prerequisites, plan.md Risks).

## Learnings
<!-- Дописывать по строке на завершённую задачу: неожиданности, подводные камни, решения,
     принятые по ходу реализации. Это память, переживающая сброс контекста. -->
- T-1: package skeleton + pyproject.toml mirrored from maven-mcp; `[[tool.mypy.overrides]]`/`[tool.ruff.lint.per-file-ignores]` blocks intentionally omitted (empty placeholders would mirror maven-mcp findings that don't exist here) — add only when a real finding needs one.

Referenced from: `plugins/developer-workflow/skills/write-spec/SKILL.md` (§Phase 4.3 Run multiexpert-review).

# Multiexpert-Review `spec` Profile Hint — Rationale

Why the hint (defense-in-depth, not a single-cause fix): the `spec` profile's detector
declares `frontmatter_type: [spec]` and `path_globs: ["docs/specs/**"]`. Either path would
normally classify a draft that carries `type: spec` frontmatter and lives under `docs/specs/`.
The explicit hint exists because:

1. **Invocation-path robustness** — in some callsites the draft is passed as inline args
   without the frontmatter block; the engine sees only body prose and can't rely on
   frontmatter detection.
2. **Cheapest deterministic route** — Step 1 hint-match short-circuits detection before
   any YAML parse or path-glob evaluation; cost is a single-line prefix.
3. **Detector-independence** — removes the orchestrator's dependency on detector internals.
   Future detector refactors (reordering, different fallback) cannot silently re-open the
   historical spec → implementation-plan misclassification drift that this profile exists
   to close.

# create-pr — Body Section Bank

Referenced from: `plugins/developer-workflow/skills/create-pr/SKILL.md` (§7.1).

Available sections (include only those that apply):

```markdown
## What changed
<!-- Technical description from commit log + diff -->

## Why / motivation
<!-- From task description or plan artifact; link ticket if URL in commits -->

## Artifacts
<!-- Bullet list of swarm-report/ paths that exist -->
- Plan: swarm-report/<slug>-plan.md
- Test plan: swarm-report/<slug>-test-plan.md
- ...

## How to test
<!-- From test-plan.md or plan.md acceptance criteria; checkbox list -->
- [ ] Scenario 1
- [ ] Scenario 2

## Release Notes
<!--
  Emitted when the change is user-visible (see SKILL.md §7.2.1).
  Format follows the project's existing changelog convention. PR body is text only —
  do NOT modify CHANGELOG.md, .changeset/, RELEASE_NOTES.md, or docs/CHANGELOG.md.
  Choose ONE form for the PR body:

  Keep-a-Changelog (CHANGELOG.md / RELEASE_NOTES.md / docs/CHANGELOG.md):
  ### Added
  - Short user-facing description (#NNN)

  Changesets (.changeset/) — PR-body shorthand only, NOT the actual changeset format:
  type: minor
  Short user-facing description.

  (The real .changeset/*.md file uses --- frontmatter mapping packages to bump levels;
  this PR-body snippet is just for review-time visibility.)

  No project changelog yet — plain bullet:
  - **<Area>:** short user-facing description.

  Breaking change marker (any format):
  **Breaking:** describe what users must do to migrate.

  When the section is intentionally skipped:
  > Release notes: skipped (<reason>)
-->

## Status
<!-- Table: Implement / Finalize / Acceptance stages, pass/fail/pending from artifacts -->
| Stage | Result | Notes |
|---|---|---|
| Implement | ✅ PASS | all gates green |
| Finalize  | ⏳ in progress | round 2/3 |
| Acceptance | ⏸ pending | waits for finalize |

## Screenshots / demo
<!-- For visual changes; prompt user -->

## Checklist
- [ ] Tests added or updated
- [ ] No breaking changes (or documented)
- [ ] Relevant docs updated

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

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

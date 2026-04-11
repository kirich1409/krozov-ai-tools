# Remove prepare-for-pr skill

## Task
Remove `prepare-for-pr` skill from developer-workflow plugin, merging useful parts into orchestration rules.

## What was done

### Orchestration rules (`~/.claude/rules/dev-workflow-orchestration.md`)
- Added trigger preamble to Quality Loop section
- Added "Build system detection" subsection with priority table (7 build systems)
- Added "Scope decision" subsection with in-scope/out-of-scope/minor/non-minor definitions
- Updated Skill and Agent Selection table: `prepare-for-pr` skill → Quality Loop gates

### implement-task (`plugins/developer-workflow/skills/implement-task/SKILL.md`)
- Phase 2 now references `simplify` skill + Quality Loop gates instead of `prepare-for-pr`

### create-pr (`plugins/developer-workflow/skills/create-pr/SKILL.md`)
- Draft decision table: `prepare-for-pr` → "quality checks"
- Output section: `prepare-for-pr` → "quality loop"

### README (`plugins/developer-workflow/README.md`)
- Removed `prepare-for-pr` section entirely
- Updated implement-task description: `prepare-for-pr` → "simplify + quality gates"

### Deleted
- `plugins/developer-workflow/skills/prepare-for-pr/SKILL.md` (via `git rm`)

### Skipped
- `pr-drive-to-merge` — already removed in commit c86b0ea

## Validation
- `grep -r "prepare-for-pr" plugins/developer-workflow/` — 0 results
- `grep "prepare-for-pr" ~/.claude/rules/dev-workflow-orchestration.md` — 0 results

## Status: Done

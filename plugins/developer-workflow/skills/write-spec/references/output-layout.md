Referenced from: `plugins/developer-workflow/skills/write-spec/SKILL.md` (§Phase 5 Save).

# Output Location and Artifact Layout

Where the spec and the operational state file live, how they are named, and
when they are retired.

---

## Target Layout

| Artifact | Path | Lifetime |
|----------|------|----------|
| Spec | `docs/specs/YYYY-MM-DD-<slug>.md` | Permanent — version controlled |
| State file | `./swarm-report/spec-<slug>-state.md` | Temporary — delete after save |

---

## Path Conventions

- **Spec filename**: `YYYY-MM-DD-<slug>.md` at the project root under
  `docs/specs/`. The date prefix is the day the spec was created (not merged,
  not approved). The `<slug>` is the same kebab-case slug generated in Phase 0.
- **State filename**: `spec-<slug>-state.md` under `./swarm-report/`. The
  state file is operational — it tracks round numbers, research progress, and
  open gaps. It is not committed; `swarm-report/` must be in the project's
  `.gitignore`.

Example: feature goal *"push notifications"* on 2026-04-20 →
- `docs/specs/2026-04-20-push-notifications.md`
- `./swarm-report/spec-push-notifications-state.md`

---

## Save Procedure

### 1. Ensure `docs/specs/` exists

Check if `docs/specs/` exists at the project root. Create it if not.

### 2. Save the spec

Write the approved draft to `docs/specs/YYYY-MM-DD-<slug>.md`. Update its
frontmatter `status:` from `draft` to `approved` before writing.

### 3. Retire the state file

Update state file status to `done`. The file may be deleted at the discretion
of the caller — it is no longer needed once the spec is saved.

### 4. Confirm to the user

```
Spec saved: docs/specs/{filename}

This document is self-sufficient for implementation. When you're ready,
decompose-feature will break it into tasks for autonomous execution.
```

Do not auto-invoke `decompose-feature` or any other skill. The spec is the
deliverable. The user decides when and how to proceed.

---

## Hand-off

The saved spec is the sole deliverable of `write-spec`. It is designed to be
handed to `decompose-feature` and then `implement` at any future point,
producing a complete autonomous implementation with user involvement only at
genuine critical blockers.

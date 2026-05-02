# Verify — Detailed Reference

Used by `code-migration` at the Acceptance phase and by the orchestrator to diagnose failures.
Does NOT contain snapshot procedures — see `developer-workflow-kotlin:snapshot`.

## Regression Diagnosis

**If tests fail after migration (regression):**

1. Do NOT proceed to other verify steps or Cleanup
2. Identify which test failed and why — this is a regression, not a pre-existing issue
3. Diagnose systematically:
   - Read the failing test — what behavior does it assert?
   - Read the new code that replaced the old — what changed that affects this behavior?
   - Compare old vs new: did the semantics change (nullability, exception handling, edge cases, ordering)?
   - If not obvious: temporarily revert the single file and re-run to confirm the test was green before — then narrow down which change broke it
4. Fix the regression in the migrated code (never by weakening or deleting the test)
5. Re-run until all pass before continuing

## UI Visual Diff

- Take new screenshots of all affected screens (same tool used in Snapshot: mobile MCP or manual)
- **Present before/after diff to user — wait for approval**
- User confirms: "expected change" (proceed) or "regression" (fix and re-verify)
- If user cannot respond: re-prompt once; if still no response, park migration as incomplete

## Behavior Spec Review

Walk through `behavior-spec.md` line by line against the new implementation:

- Every row in **Public Interface**: does the new code have the same signature or a documented intentional change?
- Every item in **Normal Behaviors** and **Edge Cases**: is it covered by a passing test, or manually verified?
- Every item in **Quirks**: is it preserved — or, if the user marked it for removal, confirm it's gone?
- Every item in **Out of Scope**: confirm the change is present and correct
- **Present the completed review to the user** — they confirm: "all behaviors accounted for" or point to gaps

## API Compilation Check

- Per public surface: run the appropriate compile task for the module type — must compile
- Per known caller: confirm it compiles; run any relevant tests

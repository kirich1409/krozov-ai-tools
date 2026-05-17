# Anti-orchestrator — five criteria

This skill must not become an orchestrator. The deleted `code-migration` skill (v0.14.0) was an orchestrator and was removed because forced pipelines are a worse user experience than plan mode + on-demand tools.

If any of the criteria below is violated in an iteration of this skill, the skill is reverting to the deleted v0.14.0 design. Treat each one as a hard constraint, not a guideline.

## Criterion 1: Each invocation is narrow

This is one skill for one migration at a time. Not a meta-skill that schedules multiple migrations. Not a wrapper that delegates to a sub-skill per migration type.

The deleted v0.14.0 tried to describe "the phenomenon of migration in general" with a state machine that branched on feature-flow vs bugfix-flow. This skill instead describes one phase structure that the user walks through for one migration; the user picks the approach inside Phase 4.

**Test.** If the SKILL.md grows a `feature-flow` / `bugfix-flow` / `<other>-flow` selector at the top, the skill is over-reaching.

## Criterion 2: Phases are checklists, not state transitions

The eight phases are headings in SKILL.md, not nodes in a graph. There is no explicit `state machine`, no enumerated transitions, no `Discovery → Plan → Implement → Acceptance` enforcement.

The single exception is Phase 4 (Strategy + User Gate). It is the only place where the skill explicitly waits for user confirmation before proceeding. Everything else flows naturally — the user can skip a phase, return to a previous one, or run phases out of order if it makes sense.

**Test.** If the SKILL.md text uses words like `cycle`, `cap`, `escalation point`, `state transition`, `PARTIAL`, `FULL`, or describes phase-to-phase routing rules, the skill is becoming a state machine.

## Criterion 3: Any phase except Phase 4 is optional

Tech-Study, Discover, Behavior-Fix, Implement, Device Verify, Cleanup, Final Audit — each can be skipped by the user. The skill describes what each phase produces and why it is useful; the user decides which ones apply.

Phase 4 is the only mandatory gate because the user explicitly asked for it during the design of this skill — they want to confirm the strategy before implementation starts.

**Test.** If the SKILL.md says "this phase is mandatory" or "this phase blocks the next" for any phase other than Phase 4, the skill is wrong.

## Criterion 4: This skill does not invoke other skills

It does not call `/check`, `/finalize`, `/create-pr`, `/drive-to-merge`, `/acceptance`, `/multiexpert-review`, `/write-spec`, or any other slash command from its phases.

The skill delegates to **agents** (kotlin-engineer, compose-developer, code-reviewer, architecture-expert, manual-tester) for implementation work — that is normal subagent delegation. But it does not chain skills.

Reasoning: the user is in control. Plan mode is the orchestrator. After Phase 7 (Cleanup), the user runs `/check` and `/finalize` because they want to, not because this skill schedules them.

**Test.** If `Phase N` in SKILL.md says "run `/check` now" or "invoke `/finalize` at the end", the skill is orchestrating other skills.

## Criterion 5: Artifacts inform; they do not gate

Files in `./swarm-report/` are documents for the user — `<slug>-tech-snapshot.md`, `<slug>-discover.md`, `<slug>-test-cases.md`, etc. They are not lock files. There is no `if file does not exist, refuse to proceed` logic.

The single exception is `<slug>-strategy.md` — Phase 4 produces it and the user confirms it before implementation. Implementation should not start without user confirmation, and the strategy document is the record of what was confirmed.

**Test.** If the SKILL.md text says "do not proceed without `<slug>-X.md`" for any X except `strategy.md`, the skill is using artifacts as gates.

---

## Dependency-direction enforcement (architectural, not skill-level)

A related risk: code-level loops between FROM and TO (new depends on old; old depends on new). These are not orchestrator issues but they are migration killers — they make cleanup impossible.

The skill does not enforce these — they belong in the project's architecture rules. But the skill should *recommend* them in Phase 4:

### Konsist rule example

```kotlin
@Test
fun `no new code depends on legacy databinding`() {
    Konsist.scopeFromProject()
        .files()
        .filterNot { it.packageDeclaration?.fullyQualifiedName?.contains(".legacy.") == true }
        .assertFalse { it.text.contains("import android.databinding") }
}
```

### Lint baseline as gate

`lint-baseline.xml` records current Databinding usages. New usages do not appear in the baseline and fail the lint check. Apply on the migration branch from day 1 so growth is blocked while migration progresses.

### Gradle dependency constraints

For module-level boundaries: actively fail the build if a module outside `:legacy:*` depends on the FROM library. A plain Gradle version constraint does not block a dependency — it only narrows version resolution; conflict resolution can still pick whatever the consumer requested. Use one of the mechanisms that actually fails the build instead:

```kotlin
// build.gradle.kts of a feature module — resolution strategy that hard-fails on the legacy artifact.
configurations.all {
    resolutionStrategy.eachDependency {
        if (requested.group == "com.google.dagger") {
            throw GradleException(
                "Module ${project.path} must not depend on Dagger directly. " +
                "Migrating to Metro — see migration plan in swarm-report/."
            )
        }
    }
}
```

Or, for repository-wide policy that does not need to live in every module, a Konsist or `ArchUnit` test (running in `:test` of a dedicated `:rules` module) is more discoverable and runs in CI.

These are recommendations to the user, not skill-enforced rules. The skill points at them; the user adopts them.

---

## How to spot drift

If a future iteration of this skill starts to look like an orchestrator, expect these symptoms:

- The SKILL.md grows beyond 500 lines.
- A new phase appears that "orchestrates" or "schedules" earlier phases.
- The skill starts emitting commands to run other skills.
- Artifacts get prefixed with `state-` (signal of state-machine thinking).
- A glossary of statuses appears (PARTIAL, FULL, ESCALATE, BLOCKED).
- The user reports "this feels like a forced pipeline".

The fix in all cases is to strip the orchestration and return to: one skill, eight phases as headings, one gate at Phase 4, everything else informational.

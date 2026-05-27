---
name: evaluate-dependency
description: "Evaluate whether a new library/dependency is worth adopting BEFORE adding it to a build file. Gathers objective signals (latest version, stability, known CVEs, GitHub activity, issue dynamics, license, owner) — via a Maven dependency-intelligence tool when available — plus web reputation/sentiment and adoption, then delegates to the dependency-evaluator agent for a verdict (ADOPT / ADOPT WITH CAUTION / AVOID) and asks how to proceed. Optimised for JVM/Maven; degrades to web-only for other ecosystems. Use when: about to add a new dependency, \"should we use X\", \"is this library worth adding\", \"vet/evaluate this library\", \"is X still maintained\". Do NOT use for: bumping an already-used dependency's version (use a version/changelog lookup tool), resolving version conflicts or BOM alignment (build-engineer), or deep code security audits (security-expert)."
---

# Evaluate Dependency

Vet a candidate library before it enters the build. The skill collects objective signals,
hands them to the `dependency-evaluator` agent for a verdict, and brings the
adopt/avoid decision back to you in chat — so a dependency is a deliberate choice, not a
side effect of writing code.

**When this fires.** Trigger it the moment a *new* dependency is about to be introduced —
whether the user asks "should we use X?" or you are about to edit `build.gradle[.kts]`,
`gradle/libs.versions.toml`, or `pom.xml` to add a coordinate that is not already present.
Upgrading an already-used dependency is out of scope (that is a version/changelog lookup).

**Graceful degradation — non-negotiable.** This skill must run without any MCP server. When a
Maven dependency-intelligence capability is available, use it for the deep objective metrics;
when it is not, fall back to web evidence and say so. Describe the data you need (latest
version, stability, CVEs, maintenance/activity/license signals) — do not depend on a specific
tool name.

---

## Phase 1: Identify the candidate(s)

Pin down what is being evaluated:
- **Coordinate / package** — `groupId:artifactId` for JVM/Maven, or the package name otherwise.
- **Version** — the one under consideration, or "latest" if unspecified.
- **Purpose** — what the user wants it for (feeds the "fit" judgement and alternative search).

If several libraries are proposed at once, evaluate them as a batch. If the coordinate is
ambiguous (e.g. only a feature is named), ask via `AskUserQuestion` or state the assumed
candidate before proceeding.

If the dependency is **already declared** in the project, stop — this skill is for *new*
adoptions. Redirect to a version/changelog lookup instead.

## Phase 2: Gather objective signals

Collect what is knowable without judgement:

- **JVM/Maven (preferred path):** if a Maven dependency-intelligence capability is available,
  request latest version + stability, known CVEs for the candidate version, and the library's
  health signals — maintenance (last commit/release, archived), activity (release cadence,
  open/closed issue counts, close ratio, time-to-close), license, owner type, publisher scale
  (public-repo count, account age), repository.
- **No such capability / other ecosystems:** gather the equivalents from the web — the project's
  repository, release history, issue tracker, and registry page.

Record signals as facts; do not interpret them yet. Mark anything unavailable as unknown rather
than guessing.

## Phase 3: Judge

Launch the `dependency-evaluator` agent via the Task tool, passing the candidate, its purpose,
and every signal gathered in Phase 2. Let the agent add web reputation/sentiment and adoption
checks and return the verdict — **ADOPT / ADOPT WITH CAUTION / AVOID** — with a signal table,
risks (with severity), and any alternatives.

Do not second-guess the agent's verdict; if it is missing a signal you can cheaply provide,
fetch it and re-run rather than overriding.

## Phase 4: Decide (dialogue)

Present a compact summary in chat — verdict, the 2–4 signals that drove it, and the top risk —
then use `AskUserQuestion` to let the user choose how to proceed. Offer options aligned to the
verdict, e.g.:
- **Adopt** — proceed to add the dependency.
- **Adopt with caution** — proceed, noting the mitigation(s).
- **Evaluate an alternative** — re-run this skill on the suggested alternative.
- **Don't adopt** — abandon this dependency.

The decision lives in chat, never parked in a file. Only after the user chooses "adopt" do you
edit the build file.

## Phase 5: Optional artifact

For a non-trivial evaluation worth keeping (e.g. a decision the team will revisit), save the
verdict and signal table to `./swarm-report/evaluate-dependency-<slug>.md`. Skip this for a
quick yes/no check — the chat summary is enough.

---

## Red Flags / STOP Conditions

- **Coordinate cannot be resolved anywhere** (not in Maven, not on the web) — report it; a
  package that cannot be found is itself a strong AVOID signal.
- **Active CVE with no fixed version** — surface as a critical risk before anything else.
- **Closed source / no public repository** — not an automatic AVOID, but call it out explicitly
  so the user weighs the reduced auditability.
- **User is mid-implementation and adding the dep is blocking them** — keep the evaluation tight;
  lead with the verdict so they can move.

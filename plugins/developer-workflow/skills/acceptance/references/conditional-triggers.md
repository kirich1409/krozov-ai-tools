# Step 3 — Conditional Triggers and Diff Heuristics

Acceptance's fan-out is built from a **base plan** (keyed off `has_ui_surface`) plus
**conditional triggers**. Each trigger maps to a specialist agent with a narrow prompt.
When no trigger fires for an agent, the agent is not spawned. Triggers read either from
spec frontmatter or directly from the diff.

The base check plan (keyed off `has_ui_surface`) lives in `SKILL.md` §Step 3. The
conditional triggers below are added on top of it when they fire.

## Conditional triggers table

| Trigger | Agent | Role |
|---|---|---|
| spec `acceptance_criteria_ids` non-empty | `business-analyst` | AC coverage — every `AC-N` has evidence in the diff, TC list, or manual-tester report |
| spec `design.figma` set, `has_ui_surface == true` | `ux-expert` design-review | Verify UI matches the referenced mockup + project design system |
| spec `non_functional.a11y` set, `has_ui_surface == true` | `ux-expert` a11y focus | Accessibility audit against the declared WCAG level |
| spec `risk_areas` includes any of `auth`, `payment`, `pii`, `data-migration` | `security-expert` | Security review against diff and any persisted state changes |
| spec `non_functional.sla` set, **or** `risk_areas` includes `perf-critical` | `performance-expert` | Bench/regress check against the declared SLA |
| diff touches a public API symbol, **or** changes span ≥ 3 top-level modules | `architecture-expert` | Module boundaries, dependency direction, public API contract |
| diff touches any build file (`build.gradle*`, `settings.gradle*`, `pom.xml`, `package.json`, `Cargo.toml`, `go.mod`, `pyproject.toml`, `Makefile`) | `build-engineer` | Build config sanity — plugin versions, task wiring, dependency additions |
| diff touches CI / release config (`.github/workflows/*`, `.gitlab-ci.yml`, `Dockerfile`, `docker-compose*`, `.circleci/config.yml`, `release.yml`) | `devops-expert` | Pipeline/release health, secret handling, rollout gates |

When both design-review and a11y triggers fire, combine into one `ux-expert` invocation
with mode `both`. When no trigger fires, acceptance runs the base plan only — preserving
backward compatibility with specs written before iteration 2.

**Future iterations** will add `visual-check` as a separate sibling skill (not a fan-out
member) for pixel-level regression.

## Diff-based trigger detection — two cached passes

1. **Path pass** — run `git diff --name-only <base>...HEAD` once and cache the path set.
   Use the cached set for all path-only rules (build files, CI/release config, cross-module
   span).
2. **Content pass (on demand)** — when the `architecture-expert` rule needs to decide
   "diff touches a public API symbol", read the diff body once via
   `git diff --unified=0 <base>...HEAD -- <cached-paths>` and cache it for the whole run.
   Evaluate public-API heuristics against those patch hunks.

Both caches live for the duration of the acceptance run — do not re-probe per agent.

## Public API detection heuristic (`architecture-expert`)

- **Kotlin/Java**: changes under `src/main/` that add/remove/rename a `public` / `open`
  symbol, or touch module-level files (`settings.gradle*`, `Module.kt`, `Dependencies.kt`).
- **TypeScript/JavaScript**: changes to `export` / re-export lines, `index.ts` public
  entrypoints, or `package.json` `"exports"` field.
- **Swift**: changes to `public` / `open` declarations or `Package.swift`
  `products` / `targets`.
- **HTTP/RPC surface**: changes to files matching `**/routes/**`, `**/controllers/**`,
  `**/handlers/**`, `**/api/**`, `*.proto`, `*.graphql`, `openapi.yaml`.
- **Cross-module threshold**: `git diff --name-only` spans ≥ 3 top-level module directories
  discovered from `settings.gradle*` / `package.json` workspaces / `Cargo.toml`
  `[workspace]` members.

If the heuristic is ambiguous, default to **not** spawning `architecture-expert` — a false
negative is safer than a false positive (the skill exists to catch high-risk changes, not
every diff).

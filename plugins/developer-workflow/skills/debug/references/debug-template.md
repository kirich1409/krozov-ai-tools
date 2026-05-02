# Debug Artifact Template

Canonical structure for `swarm-report/<slug>-debug.md`. Every section is required —
write `N/A: <reason>` when a section does not apply (e.g. Not Reproducible has no
RCA), do not delete the heading.

```markdown
# Debug: <slug>

Started: <ISO-8601 timestamp>
Severity: P0 | P1 | P2 | P3
Status: Reproduced | Not Reproducible | Diagnosed | Escalated

## 1. Reproduce

- Steps to reproduce (numbered list, copy-paste-runnable)
- Environment: device / OS / build / data state
- Expected behaviour vs observed behaviour
- Frequency: always | intermittent (rate) | once

## 2. Severity classification

- Impact: users / revenue / data integrity / security / dev velocity
- Urgency: immediate (hotfix) | this-sprint | next-release
- Workaround: yes/no, one-line description
- → Severity: P0 | P1 | P2 | P3 + one-line justification

## 3. Root-cause analysis

5-whys (truncate when the chain bottoms out earlier):

- Why 1: <symptom> happens because <observation>
- Why 2: <observation> happens because <next-level cause>
- Why 3: ...
- Why 4: ...
- Why 5: ...
- **Root cause:** one precise sentence — the actual fault

Localisation: `path/to/file.ext:LINE`, additional file:line entries when the cause
spans more than one site.

## 4. Blast-radius

Where else in the codebase the same defect-pattern is reachable.

- Search query used: `ast-index <query>` or `grep -nrE '<pattern>'` (record the
  exact command so the search can be reproduced)
- Matches found: `path/to/file:LINE` list
- Decision:
  - **Fix all** — covered by this fix; itemise sites being touched
  - **Fix this site only** — explicit reason (different lifecycle, owner, scope)
  - **Open follow-ups** — link new issues for the remaining sites

## Fix direction

Simple | Complex | Not Reproducible | Escalated.
One paragraph: what needs to change and where, NOT how. The implementation belongs
to the `implement` stage.

## Next step

Implement | Plan | Report | Escalate. Filled in by the orchestrator when it consumes
this artifact.
```

## Section rules

- **Frontmatter triplet (`Started` / `Severity` / `Status`) is mandatory.** Downstream
  stages key on `Severity` for routing decisions and on `Status` for the receipt-based
  gate.
- **`Severity` is a judgement, not an automation.** The Severity classification section
  must justify the chosen tier in one line.
- **`Status: Not Reproducible`** → sections 3 (RCA) and 4 (Blast-radius) are written as
  `N/A: not reproducible — see Reproduce section`. Do not invent a root cause from
  guesswork.
- **`Status: Escalated`** → fill what was learned up to the escalation point; mark
  remaining sections `N/A: escalated, awaiting <decision>`.
- **Blast-radius is mandatory even when only one site is affected.** Record the search
  query and "Matches found: only the original site" — this proves the search was
  performed, not skipped.
- **Localisation lines must be `file:line` (or `file:start-end`) — agent-readable.**
  Free-form descriptions ("around the auth handler") are not enough for downstream
  stages to act on.

## Severity rubric (concise)

| Tier | Trigger |
|------|---------|
| P0 | Production outage, data loss, security breach, blocked release |
| P1 | Major feature broken for many users, no workaround, regression on a core flow |
| P2 | Feature broken for some users, workaround exists, or non-core flow regression |
| P3 | Cosmetic / typo / minor degradation, no functional impact |

The rubric is a quick reference; the Severity classification section in the artifact
is still the source of truth.

## Worked examples

### Example A — P1 reproducible regression with broad blast-radius

```markdown
# Debug: token-refresh-loop

Started: 2026-04-30T14:22:00Z
Severity: P1
Status: Diagnosed

## 1. Reproduce

1. Sign in with an account whose refresh token expires within 60 seconds
2. Wait 65 seconds with the app foregrounded
3. Trigger any authenticated request

- Environment: pixel-7 / Android 14 / build 0.9.0 / staging
- Expected: silent re-authentication, request succeeds
- Observed: infinite loop of 401 → refresh → 401, app freezes
- Frequency: always

## 2. Severity classification

- Impact: every user with a near-expiry token; affects core flow (any authed request)
- Urgency: this-sprint — release branch cuts on Thursday
- Workaround: kill and relaunch the app
- → Severity: P1 — core flow broken, workaround is intrusive but not destructive

## 3. Root-cause analysis

- Why 1: 401 responses keep firing because the retry interceptor re-issues the same expired token
- Why 2: The interceptor uses the cached token because the refresh path never persists the new token
- Why 3: `TokenStore.update()` is called inside a coroutine that is cancelled when the parent scope dies
- Why 4: The parent scope is `viewModelScope`, which dies on configuration change during the refresh
- **Root cause:** token persistence runs in `viewModelScope`, so the new token is dropped if the user rotates the device mid-refresh.

Localisation: `auth/TokenRefreshInterceptor.kt:118`, `auth/TokenStore.kt:42`

## 4. Blast-radius

- Search query: `ast-index callers TokenStore.update`
- Matches found:
  - `auth/TokenRefreshInterceptor.kt:118` — original site
  - `auth/Logout.kt:54` — same `viewModelScope` pattern
  - `auth/SilentSignIn.kt:31` — uses `applicationScope`, not affected
- Decision: fix all — itemised in the fix direction below

## Fix direction

Persist token writes on `applicationScope` (or another long-lived dispatcher) so they
survive UI lifecycle transitions. Audit `TokenStore.update` callers identified above.

## Next step

Plan — touches three call sites, needs an architectural choice on which scope is the
right long-lived owner.
```

### Example B — Not Reproducible

```markdown
# Debug: intermittent-crash-on-launch

Started: 2026-04-29T09:10:00Z
Severity: P2
Status: Not Reproducible

## 1. Reproduce

- Steps from the report: cold start of the app (no specific data state)
- Environment: 1 user report, Samsung S22 / Android 13 / build 0.8.4
- Expected: app launches
- Observed: SIGSEGV before the splash screen
- Frequency: once, not reproduced on local Pixel 7 across 30 cold starts

## 2. Severity classification

- Impact: 1 known user, possibly OEM-specific
- Urgency: next-release; collect more crash reports first
- Workaround: relaunch
- → Severity: P2 — single-report crash, no clear pattern yet

## 3. Root-cause analysis

N/A: not reproducible — see Reproduce section.

## 4. Blast-radius

N/A: not reproducible.

## Fix direction

Not Reproducible. Add structured logging at startup boundaries
(`Application.onCreate`, `MainActivity.onCreate`) and ship a debug build to the
reporting user before resuming RCA.

## Next step

Report — return to user with instrumentation request.
```

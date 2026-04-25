# Static Analysis Checklist

What to extract from code before talking to the user. Work through this list in order;
each section maps to a spec section. Capture findings verbatim in the state file — exact
numbers, exact strings, exact conditions.

For every item, answer two questions:
1. **What** — the observable fact or value in code.
2. **Under what condition** — the trigger or branch that makes it apply.

When in doubt, record the raw observation and move on. Classification (intended
behavior / unknown intent / behavior defect / hygiene finding, and feature-specific
vs project-wide) happens in Phase 2 (Convention Mapping) and Phase 4.0 (Translate),
not here. Capture literally first.

**Code identifiers in the state file: allowed and encouraged.** The state file names
classes, methods, types, file paths, line numbers — that is what makes it a useful
operational artifact. It is the bridge between the code and the spec.

**Code identifiers in the spec body: forbidden.** The translation from code-vocabulary
to behavior-vocabulary happens in Phase 4.0 (see SKILL.md), using the recipes in
`behavior-translation.md`. Do not pre-translate in this phase — capture literally,
translate later. Pre-translation loses precision; post-translation is where judgment
applies.

---

## 1. Boundary & entry points

- Every route, deep link, intent, URL, navigation action, notification tap, widget tap,
  or programmatic call that can land the user on this feature.
- Dependencies the feature calls into — note them as cross-references, not as part of
  the feature.
- What calls the feature from outside (if any) — other features, background jobs,
  schedulers.

Record entry points as a list; each entry contains the trigger and any required
arguments (deep-link path params, navigation args, etc.).

### 1.1 Cross-feature surface (collaborators and consumers)

While enumerating entry points, also map the feature's broader integration surface
with the rest of the app. For every symbol the feature imports from outside its own
module, decide:

- Is it a **platform / third-party library** (stdlib, Kotlin stdlib, OS SDK)? — not a
  collaborator in the spec sense; skip.
- Is it a **value provided by the host app** (config, flags, keys, endpoints)? →
  collaborator (configuration type).
- Is it an **in-app service** (shared networking client, deep-link processor,
  navigation stack, analytics dispatcher, theme)? → collaborator (service type).
- Is it an **observable stream / store maintained elsewhere** that the feature
  subscribes to? → collaborator (shared state source).

In the other direction — who reads or subscribes to what this feature exposes? Grep
for imports of the feature's public symbols:
- **Downstream screens** that receive navigation arguments on completion → consumer.
- **Other modules** that subscribe to streams the feature emits → consumer.
- **Shared storage slots** the feature writes that others read (tokens, cache keys) →
  consumer (via shared state).

Also capture:
- **Preconditions** observable in code: assertions, early returns, required flags.
- **Postconditions** the feature commits to before it hands off: persistent writes,
  navigation-stack manipulations, stream values it must emit.

These findings feed §10.7 Collaborators and consumers, and the boundary they describe
is as important to preserve in a reimplementation as the feature's internal flow.

## 2. User-visible states

For each state variable or branch in the UI layer, identify the resulting state:

- **happy path** — primary success rendering
- **loading** — is there a spinner, skeleton, placeholder? where?
- **empty** — when does the feature render "no data"? what copy?
- **error** — every error path; group by error class if the code groups them
- **offline / no-network** — explicit handling or inherited from a shared error path?
- **permission-denied** — every platform permission requested; what if the user refuses?
- **degraded** — feature flag off, remote config disabled, third-party down, account in
  a special state (unverified, restricted, etc.)

For each, capture: trigger condition, visible copy (verbatim), available actions.

**State-diagram heuristic:** if the feature has 5+ distinct user-visible states or a
non-trivial state machine (loading → success → partial → retry → offline-cached), a
one-page state diagram is worth the effort. Sketch it in the state file — nodes for
states, edges labeled with the trigger that moves between them. Include it in the spec
as a fenced mermaid block in Section 4. For simpler features (≤4 states with linear
transitions), prose is enough.

## 3. Network operations (every endpoint the feature talks to)

If the feature makes any network call, capture **every single one** as a row for the
§10.1 Network operations table. Split by *trigger context*, not by transport: the same
URL called for "initial auth" vs "refresh" is two operations because the trigger and
the request shape differ.

For each call, record:

- **Operation name** in business terms ("authorize via browser", "exchange code for
  tokens", "fetch current user").
- **Method** (GET / POST / PATCH / WS / SSE / GQL query-name).
- **Endpoint** — URL pattern with path params in `{braces}`, hostname abstracted via
  §10.5 placeholder if applicable.
- **Auth** — none / Bearer / Basic / custom header.
- **Triggered when** — the user action, state transition, or lifecycle event that
  fires the call. Include conditions ("only when access token within 60 s of expiry").
- **Request fields actually sent** — wire names only.
- **Response fields actually read** — wire names only. Ignore fields the code doesn't
  consume.
- **Retry / timeout / idempotency** behavior if the code sets any.
- **Source** — `file:line` of the call site (for the §13 Code map).

Do not collapse similar calls into "uses REST endpoints"; a reimplementer needs the
full list.

## 4. Local persistence, platform events, and side effects

What the feature reads / writes locally, and what platform-level side effects it
triggers.

- **Local storage reads:** key / database table / file path, trigger (startup,
  on-demand, lifecycle event), what the data represents.
- **Local storage writes:** key, trigger, contents, invalidation rule (on logout, on
  expiry, on user action).
- **Platform events consumed:** deep-link intents, app lifecycle callbacks, OS push
  payloads — topic / URL pattern / event name as delivered by the platform.
- **Platform-level side effects:** system toasts, haptics, audio, clipboard writes,
  notifications, vibration — user-visible ones.
- **Feature-to-feature events:** in-app bus / signals — name, payload role, meaning.
  (Analytics events go in Section 7, not here.)
- **Flags / remote config:** name verbatim, default, consequence per legal value,
  source of truth.
- **Platform data requests:** location, contacts, calendar, clipboard, camera
  capture, file picker — trigger and what is requested.

Record each with `file:line` so the §13 Code map writes itself.

## 5. External dependencies

SDKs and services this feature pulls in. For each, note:

- purpose (why the SDK is used)
- scope (feature-only or project-wide)
- behavior contract exposed to the feature

Flag any that are load-bearing for the spec's Tech-specific constraints section
(ML/AI libraries, payment SDKs, biometrics, DRM, maps, AR, realtime, etc.).

## 6. Constraints & magic numbers

Any concrete value the code enforces that would affect behavior if changed:

- timeouts (network, UI, animation)
- retry counts and backoff schedules
- debounce / throttle intervals
- rate limits
- pagination page sizes
- maximum input lengths, file sizes, character counts
- minimum interaction intervals
- cache TTLs
- validation rules (regex, whitelists, blacklists)

Each value goes into the spec with its literal number. If the code allows overriding via
remote config, note the default AND the override mechanism.

### 6.1 Async / concurrency / timing behavior

Static analysis has a blind spot for *when things happen relative to each other*. If the
feature has any of the following, record the concrete behavior AND raise a question for
Phase 3 — these are areas where code alone often does not tell the full story:

- async callbacks that can fire after the screen is dismissed (what wins: the callback
  or the dismiss?)
- background work that continues after the user leaves (is it cancelled? does it write
  state the user will see next time?)
- concurrent updates to shared state from multiple coroutines / tasks / subscribers
- rapid repeated user actions (double-tap, fast scroll) that could race a debounce
- ordering guarantees between events (does event A always arrive before event B?)

Capture the observed code path. Phase 3 should ask the user whether the observed
behavior is intentional ("this is the contract") or incidental ("it just happened to
work this way"). The answer decides whether the spec pins the behavior or leaves it
flexible.

## 7. Platform capabilities & permissions

- runtime permissions requested, and the flow when they are denied or revoked
- hardware capabilities used (camera, microphone, location, biometrics, NFC, Bluetooth,
  sensors)
- background behavior (wake locks, background fetch, push wake-up, long-running tasks)
- minimum OS version requirements (API-level gates, version checks in code)
- platform-specific behavior branching (`if (Build.VERSION.SDK_INT >= …)` etc.)

## 8. Navigation (in and out)

- every way to arrive (from section 1, restated from the navigation-graph perspective)
- every way to leave: primary success exit, cancel exit, back behavior, deep-link exits
- what state is preserved on back navigation or process death
- modality (modal vs pushed vs replaced) — relevant if it affects interaction semantics
  (e.g. swipe-to-dismiss, gesture handling)

## 9. Analytics & logging

- every call to an analytics SDK or tracking utility — event name, properties
- every log statement that describes a user-visible event or a business-state transition
- any feature-flag evaluation logged (these are often product-relevant)

Distinguish product-meaningful events (user performed X) from engineering telemetry
(method entered, latency = Y ms). The former is spec-level; the latter is not.

## 10. Localization & accessibility

- strings sourced from resource files vs hard-coded
- pluralization, formatting (dates, numbers, currency)
- RTL handling (explicit code, layout mirroring)
- content descriptions / accessibility labels on interactive elements
- dynamic type / font-scaling support
- color/contrast considerations in code (high-contrast theme, reduced-motion handling)
- screen-reader announcements (live regions, focus management)

Absence is a finding, not a non-finding. "No accessibility labels in this feature" goes
into the state file.

## 11. Feature flags / remote config gates

Any runtime switch that changes the feature's behavior:

- flag name (verbatim)
- default value
- consequence when off / on / variant-A / variant-B
- source (Firebase Remote Config, launchdarkly, internal config service, etc.)

These affect the spec directly: a feature behind a flag has a "degraded (flag off)"
state, and the spec should describe both sides.

## 12. Tests as source of truth

Existing tests often encode invariants the code does not make obvious. Skim the test
files for:

- assertions about exact values (copy, counts, thresholds)
- behavior-describing test names ("shows error when network fails" → spec bullet)
- edge cases the developer bothered to test (they had a reason)

Tests are secondary to code, but they help confirm which behaviors are intentional.

## 13. Comments and TODOs

Read code comments and TODOs for intent the code alone does not express:

- "retry 3 times because payment API is flaky" — rationale to record
- "TODO: localize this when we ship in EU" — known gap, goes to Open Questions
- "HACK — remove when BE fixes X" — unstable area worth flagging

Do not treat comments as authoritative product statements, but do capture them as
evidence for Phase 3 questions.

## 14. Defect classification

During analysis you will find observations that look wrong. Classify each one into
exactly one of three buckets before Phase 4.0. Mixing them produces a spec that either
hides bugs or turns every rough edge into a defect report.

**Intended behavior** (→ spec body in §§2-7, 10-11)
The code does something that makes sense given the product intent, even if it is
unusual. The observation describes feature behavior. Record literally; translate in
Phase 4.0.

Examples:
- Retry count is 3 and rationale is plausible (product wants eventual consistency).
- The screen shows a different empty-state for new users vs returning users.
- A specific error type gets a specific copy.

**Unknown intent / ambiguous** (→ §8 Open Questions)
The code does something that could be intentional or accidental. You cannot tell from
the code alone. Every such finding goes to §8 with a stated assumption and the
consequence of being wrong. A later clarification round (or user review) resolves it.

Examples:
- Retry count is 3 but the surrounding code suggests copy-paste from another feature.
- A 250 ms debounce — product decision, UX safeguard, or left-over default?
- An error case is routed to a generic "Unknown error" screen — is that intentional
  grouping, or incomplete error handling?

**Behavior defect** (→ §9 Known defects in current implementation)
The code makes the **feature do something wrong as a feature** — the user observes
incorrect behavior, the feature crashes, a control silently does nothing it should
do, the wrong data is shown, an unreachable state is hit. A rebuild must not
reproduce it. Each entry requires three pieces of evidence:
1. Code pointer showing the defective state (path:line).
2. Defect class (`crash`, `unreachable state`, `dead UI control`, `wrong-data shown`,
   `silent failure`, `lost user action`, `incorrect state transition`, `other`).
3. **Observable user consequence** — what the user sees or what intended outcome
   is missed.

Examples:
- A use-case is wired into a dependency graph module that is never loaded → login
  tap throws at runtime → **crash**, user cannot sign in.
- A link points to a URL with no registered handler → tap silently no-ops →
  **dead UI control**, user has no way to start sign-up from the app.
- All non-network OAuth errors collapse into one "Unknown error" copy, including
  the case where the provider explicitly returned `error=access_denied` → user who
  *chose* to deny consent sees an error implying brokenness → **wrong-data shown**.

**Implementation hygiene finding** (→ separate `<slug>-hygiene.md` artefact, NOT
in §9)
The code does something concerning at the *implementation* level, but the feature
itself behaves as intended (or its behavior is unaffected). These are valuable
findings for the engineering team, but they are not what §9 is for. They go into
a separate hygiene artefact alongside the spec.

Examples:
- A single label is hard-coded where the rest of the screen uses localized
  resources. Feature still behaves correctly today; problem manifests only when
  the project ships another locale. → **hygiene** (localization-readiness).
- Tokens are stored in plaintext key-value storage. Feature works; the risk is
  about device-compromise threat models, not about feature behavior. →
  **hygiene** (security posture).
- Non-cryptographic `Random` for security-sensitive values like CSRF state or PKCE
  verifier. Feature flow completes successfully; the problem is the strength of
  the secret, not the feature behavior. → **hygiene** (security posture).
- Logging of full redirect URL containing the OAuth `code`. Feature works; risk is
  log exposure of a transient secret. → **hygiene** (security posture).
- Mixed code conventions, dead code, copy-pasted blocks. → **hygiene**
  (maintainability).

**Hard line for §9 vs hygiene:** if removing the finding does not change *what the
user observes when they use the feature*, it is hygiene, not §9. §9 is about
behavior; hygiene is about how the code is written.

**Hard line for §9 vs §8:** if you cannot produce all three pieces of evidence
(code pointer, defect class, observable user consequence), the finding is not a
behavior defect — demote to §8 Open Questions or to hygiene. "Looks wrong" is not
a defect report.

The distinction matters because each artefact has a different audience and
different action: §9 binds the reimplementer to *not reproduce* a behavior; hygiene
informs the original team's backlog without affecting the spec; §8 surfaces
unknowns for clarification.

## Hygiene artefact format

When hygiene findings exist, save them to `<slug>-hygiene.md` next to the spec
(`docs/spec/<slug>.md` → `docs/spec/<slug>-hygiene.md`). Format:

```markdown
# Implementation hygiene findings — <feature name>

> Related spec: `<slug>.md`
> Source: extracted during reverse-engineering at <commit-sha>

These findings are about **how the current code is written**, not about what the
feature does. The feature spec describes intent; this document tracks
implementation-level concerns the engineering team may want to act on as a
backlog.

## Findings

| What | Class | Evidence | Why it matters |
| --- | --- | --- | --- |
| Hardcoded "Cancel" label | localization-readiness | `AuthScreen.kt:171` — literal string instead of resource lookup | When the project adds a non-English locale, this single label will remain English |
| Non-cryptographic `Random` for OAuth `state` and PKCE `code_verifier` | security posture | `OAuthClient.kt:180-185`, `PKCEGenerator.kt:14-19` | Predictable secrets reduce CSRF protection strength and weaken PKCE benefit |
```

If no hygiene findings exist, do not create the file. Mention in handoff:
*"Hygiene artefact: not produced — no implementation-level concerns identified."*

---

## Recording findings

Capture everything into the state file in a consistent shape. A simple list works —
each finding carries a `file:line` or `file:start-end` pointer so the code map in the
final spec writes itself.

```
## Phase 1 findings

### Entry points
- deep link `app://payment/confirm?orderId=…` → opens PaymentConfirmScreen
- notification tap on type=`payment.required` → same screen with orderId param
- navigation from CartScreen "Checkout" button → same screen

### States
- loading: spinner centered, no copy; triggered while order fetch is in flight
- error (network): ErrorBanner with "Не удалось загрузить заказ. Проверьте интернет.";
  retry action present
- error (order not found): full-screen empty state with "Заказ не найден" and "Назад"
…
```

Tight, literal, with source references (files/lines captured in a separate column or as
trailing annotations) — interpretation waits for Phase 2 and the interview.

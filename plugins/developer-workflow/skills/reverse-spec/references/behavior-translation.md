# Behavior Translation

The single hardest thing about reverse-spec is resisting the pull of the codebase's own
vocabulary. Phase 1 captures findings in the code's native words — class names,
sealed-class cases, method signatures, reactive primitives — because that is what the
state file is *for*. The state file is an operational artifact. The spec is not.

In Phase 4, before a single sentence is written into the spec, every finding must be
translated into behavior. This file is the translation table.

---

## The rule

**The body of the spec (Sections 1–9 and 11) must not contain any name that only exists
in the current codebase.** That includes:

- Class, interface, struct, object, record, module names
- Method / function / property names
- Type parameters, generics
- Sealed-class cases, enum values
- Field / column / DTO names
- Package paths, file paths
- DI graph module names
- Reactive-primitive names (`StateFlow`, `Observable`, `Publisher`, `BehaviorSubject`, …)
- Async-primitive names (`suspend`, `async`, `Task`, `Future`, `Deferred`, `Promise`, …)
- Language keywords that leak idioms (`expect`/`actual`, `sealed`, `data class`, …)
- Framework-specific idioms (Compose `remember`, React hooks, SwiftUI `@State`, …)

The only place these names may appear is **Section 13 (Code map)** — and there they
appear as location pointers (`path/to/File.kt:42-58`), not as the subject of the
description.

**Sanity check a sentence by asking:** *if I renamed every symbol in the codebase
tomorrow, would this sentence still describe the same feature?* If the sentence would
break, it is talking about code, not behavior — rewrite it before it enters the spec.

---

## Translation recipes

### 1. Sealed-class / enum cases → business states

The code says:

> `AuthState` is a sealed class with cases `Unauthenticated`, `Authenticating`,
> `Authenticated(tokens)`, `Error(exception)`.

The spec says:

> The feature has four observable states: **not authenticated** (user has not signed in
> yet or has signed out), **authorizing** (sign-in in progress), **authenticated**
> (valid tokens are held), and **failed** (the last sign-in attempt ended with an
> error). Transitions are described in §4.

The case names are an implementation artifact. The *business states* they represent are
what the reimplementer needs.

### 2. Method signatures → user-observable operations

Code:

> `OAuthClient.authorize(): OAuthResult<OAuthTokens>` and
> `OAuthClient.refresh(): OAuthResult<OAuthTokens>` are the public API of the module.

Spec:

> The feature exposes two operations to its host: **sign in** (interactive; opens a
> browser, exchanges the resulting code for tokens, stores them) and **refresh tokens**
> (non-interactive; uses the stored refresh token to obtain a new access token). Both
> return either a valid token set or a structured failure.

Describe *what the operation accomplishes*, not the function signature.

### 3. Exception hierarchies → failure classes

Code:

> `OAuthException` is sealed into `NetworkError`, `AuthorizationError`, `TokenError`,
> `StorageError`, `InvalidConfiguration`, `RefreshTokenExpired`.

Spec:

> Authorization can fail in six distinguishable ways:
> 1. **No network** — request to the identity provider could not be made.
> 2. **Provider refused authorization** — the provider returned an error during the
>    browser redirect (e.g., user denied, invalid scope).
> 3. **Token exchange failed** — the provider accepted the code but returned an error
>    when the app requested tokens.
> 4. **Storage failed** — tokens could not be persisted locally.
> 5. **Misconfiguration** — the app was launched with an invalid OAuth configuration
>    and cannot start a sign-in.
> 6. **Refresh token expired** — a background refresh failed because the provider
>    revoked or expired the refresh token; the user must sign in again.

The reimplementer needs the *failure taxonomy and user consequences*, not the Kotlin
exception tree.

### 4. Reactive primitives → "subscribes to / reflects"

Code:

> `DefaultAuthComponent.authState: StateFlow<AuthState>` is collected by
> `AuthScreen` via `collectAsState()`.

Spec:

> The sign-in screen reflects the current authentication state: whenever the state
> changes, the UI re-renders to match.

The reactive plumbing is implementation detail. The behavior is: "UI is always in sync
with state".

### 5. Async primitives → "when ready / concurrently"

Code:

> `AuthUseCase.login()` is a `suspend fun` that awaits `oauthClient.authorize()` and
> then `frameClient.currentUser()` via `async`/`await`.

Spec:

> Sign-in completes in two steps: first the OAuth flow obtains tokens, then the app's
> user profile is fetched. The second step starts only after the first succeeds.

The suspension model is incidental. What matters is the ordering and dependency.

### 6. Internal DTO shapes → external contract

Code:

> `OAuthTokens(accessToken: String, refreshToken: String?, tokenType: String = "Bearer",
> expiresIn: Long, scope: String?, issuedAt: Long)`

Spec, Section 10.6 Data contracts:

> The token response from the identity provider includes, at minimum: an access token
> (string, required), a refresh token (string, optional — may be absent), a token type
> (string, currently always `"Bearer"`), an expiry in seconds (number, required), and
> an optional scope list (space-separated string).
>
> The app records the issuance timestamp (milliseconds since epoch) at receipt time so
> that expiry can be computed locally.
>
> The full OAuth 2.0 contract is defined by RFC 6749; this spec covers only the subset
> the feature relies on.

The Kotlin `data class` is not the contract. The *wire shape* is, and it is specified
by an RFC plus the fields the app actually reads.

### 7. DI / factory plumbing → "is configured with"

Code:

> `authFeatureKoinModule { factory { AuthUseCase(get(), get()) } }` — `AuthUseCase`
> depends on `OAuthClient` and `FrameClient`.

Spec:

> The authorization flow is configured with two collaborators: an OAuth client and the
> application's Frame API client. Both are expected to be provided by the host
> application.

DI is how *this* implementation wires the feature. The spec documents that the feature
has two required collaborators with stated responsibilities.

### 8. Platform `expect`/`actual` → "per platform"

Code:

> `expect class PKCEGenerator` with `actual` implementations in `androidMain`,
> `iosMain`, `desktopMain`.

Spec:

> PKCE code verifier and challenge are generated per platform, using each platform's
> native secure randomness source. Output shape and semantics are identical across
> platforms.

`expect`/`actual` is KMP-specific. The behavior — per-platform implementation of a
common contract — can be stated in plain language.

### 9. Coroutine / scope plumbing → "runs until / is cancelled when"

Code:

> `componentContext.coroutineScope` is used; on decompose destroy, all inflight jobs are
> cancelled.

Spec:

> When the sign-in screen is dismissed, any in-flight authorization is cancelled and
> does not complete in the background.

Component lifecycles are implementation. The behavior is: "closing the screen cancels
the work".

### 10. UI toolkit components → component role

Code:

> `AuthScreen` uses a `Box` with `Scaffold` containing a `Column` of `Text`, `Button`,
> and a `CircularProgressIndicator` shown on `AuthState.Authenticating`.

Spec:

> The screen is a single full-height surface with, top to bottom: the app identity, a
> short product pitch, a primary "Sign in" action, and a secondary link for sign-up.
> While authorization is in progress, a spinner replaces the primary action.

Describe the *roles* of the components, not their Compose names.

### 11. Storage library → "persists / retrieves"

Code:

> `SettingsTokenStorage` wraps a `Settings` instance and serialises `OAuthTokens` via
> `Json.encodeToString`.

Spec:

> Tokens are persisted in platform key-value storage as a JSON payload. On app start,
> the stored payload is read and used to restore the authenticated state.

Library name drops. What stays: storage medium (key-value, here non-encrypted — flagged
in §12), serialisation format, startup behavior.

### 12. Defect observation → §9 Known defects (behavior bug) OR hygiene artefact

This recipe has two forks because Phase 4.0 must distinguish **behavior defects**
(go to §9) from **implementation hygiene findings** (go to a separate
`<slug>-hygiene.md` file). The classification rule lives in
`analysis-checklist.md` §14; the hard line is: *if removing the finding does not
change what the user observes when they use the feature, it is hygiene, not §9*.

#### Fork A — Behavior defect (§9)

Code:

> `authFeatureKoinModule()` is defined in `AuthKoin.kt:12-18` but grep across
> `InitKoin.*.kt`, `AppModule.kt`, and every `platformKoinModule.*.kt` returns no
> callers — the module is never loaded. `AuthUseCase` therefore cannot resolve its
> dependencies at runtime.

State file entry:

> Phase 1 finding: DI module `authFeatureKoinModule` defined but never loaded.
> Classification (Phase 4.0): behavior defect — sign-in tap crashes (observable
> user consequence).

§9 entry in the spec:

> | Sign-in tap crashes on first use | crash | `AuthKoin.kt:12-18` defines the DI
> module for the authorization use case but no call site loads it (verified by
> grepping `InitKoin`, `AppModule`, and all platform DI modules) | Tapping the
> primary action on the sign-in screen throws a dependency-resolution error and
> the app crashes |

The translation shifts framing from **code structure** ("`authFeatureKoinModule()`
is not loaded") to **observable user consequence** ("sign-in tap crashes"). The
code pointer stays as evidence; it does not become the subject of the sentence. A
reimplementer on SwiftUI or web reads the entry and knows "make sure the
authorization use case is wired into whatever dependency system we end up using" —
not "match Koin's module-loading contract", which is meaningless on another stack.

#### Fork B — Implementation hygiene (separate artefact, NOT §9)

Code:

> `AuthScreen.kt:171` — `Text(text = "Cancel")`, a literal string instead of a
> resource lookup. All other strings on the screen go through the resource
> mechanism with keys in `strings.xml`.

State file entry:

> Phase 1 finding: "Cancel" hardcoded; rest of screen uses resources.
> Classification (Phase 4.0): hygiene — feature behaves correctly today; the
> problem only manifests when the project adds a non-English locale.

`<slug>-hygiene.md` entry:

> | Hardcoded "Cancel" label | localization-readiness | `AuthScreen.kt:171` —
> literal string, not a resource lookup; rest of screen uses resources |
> When the project ships a non-English locale, this single label will remain
> English |

The same code-finding could *not* go into §9 because the feature presently
behaves correctly — the user sees "Cancel" in English alongside other English
strings. Removing the finding (replacing the literal with a resource lookup)
does not change what the user sees today. It is hygiene.

Same fork applies to: weak PRNG for security values (feature flow completes;
risk is secret strength), plaintext token storage (feature works; risk is
device-compromise threat model), log leakage of sensitive data (feature works;
risk is log exposure). All hygiene, not §9.

### 13. Internal navigation graph → named transitions

Code:

> `DefaultRootComponent` uses `StackNavigation<RootConfig>`; on successful sign-in,
> `navigation.replaceAll(InitialUserSetup(userId))` is called.

Spec:

> On successful sign-in, the app replaces the sign-in screen with the initial user
> setup screen, passing the authenticated user's ID. The sign-in screen is not retained
> in the navigation back-stack.

Navigation library is implementation. What matters: destination, argument, back-stack
effect.

---

## What to preserve literally

The translation rule drops *code identifiers*. It does not drop:

- **Exact user-visible copy** — quote verbatim: `"Cancel"`, `"Не удалось загрузить заказ"`.
- **Exact numbers** — retry count 3, timeout 5 minutes, buffer 60 seconds.
- **Exact external contracts** — URL patterns, query parameter names (they are the
  *contract* with an external system, not internal code).
- **Exact event names and property keys** — these are the analytics contract;
  `"payment_confirmed"` with `order_id` stays as `"payment_confirmed"` with `order_id`.
- **Standard specification references** — "OAuth 2.0 Authorization Code + PKCE per
  RFC 7636" is a *protocol*, not a codebase name.

The test: *if the codebase burned down tonight and was rewritten on a different stack
by a different team, would this string/number/URL still appear identically?* If yes,
keep it literal.

---

## Where code identifiers are OK

**Section 13 (Code map) only.** That section is explicitly about the current
implementation — it points at files and line ranges so future readers (including a
re-run of this skill) can verify the spec still matches the code. The format is
`spec section → path:start-end`, not "`AuthViewModel` does X".

**State file (`./swarm-report/...`), not the spec.** Phase 1 findings are recorded with
code identifiers for operational reasons — the state file is how Phase 4 knows what to
translate. It is deleted in Phase 7 and never ships.

---

## Drafting discipline

Before writing each paragraph of the spec, scan the related Phase 1 findings in the
state file and ask two questions for every proper-noun-looking token:

1. *Is this name something that exists only in this repo?* If yes, translate.
2. *Is this name an external contract (URL, event, field in a provider response,
   protocol)?* If yes, keep literal.

The habit is uncomfortable at first — reverse-engineering rewards pattern-matching to
code, and dropping the code's vocabulary feels like losing information. But a spec that
leaks identifiers produces a reimplementation that copies structure instead of
behavior. The whole point of the skill is the opposite: extract behavior that survives
reimplementation on any stack.

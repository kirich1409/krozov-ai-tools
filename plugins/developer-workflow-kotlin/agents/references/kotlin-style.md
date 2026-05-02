# Kotlin Rules

Project-specific Kotlin conventions that go beyond what a modern model writes by default. Generic style — idiomatic Kotlin, null safety, naming, code organization — is **not** documented here; trust the model and the [official Kotlin Coding Conventions](https://kotlinlang.org/docs/coding-conventions.html).

This file lists only:
- Strong opinions where the model's default differs
- KMP / `commonMain` constraints
- Architectural conventions (Clean Architecture + MVI)

For coroutines, Flow, dispatchers, cancellation, and coroutine testing, see `coroutines.md`.

---

## Visibility

- **`internal` by default** for everything that is not a public module API. Kotlin's language default is `public`; do not rely on it.
- `private` for implementation details inside a class.
- `public` is explicit and intentional — every public declaration is a contract. Use for domain models and interfaces in shared modules consumed by other modules.
- If the project has a clearly different convention, follow the project.

## Value Class Validation

Wrapping a primitive in `@JvmInline value class` is the obvious part. The non-obvious part: **add `init { require(...) }` when the wrapper enforces a constraint** — non-blank, valid format, range. The model often skips this without a reminder.

```kotlin
@JvmInline
value class Email(val value: String) {
    init { require("@" in value) { "Invalid email: $value" } }
}

@JvmInline
value class FavoriteId(val value: String) {
    init { require(value.isNotBlank()) { "FavoriteId must not be blank" } }
}
```

If the wrapped value has no real constraint (e.g. opaque server-generated ID) — skip the `init` block. Validate where validation is meaningful, not as ceremony.

## Parameter Nullability and Overloads

A nullable parameter on an extension or top-level function is a **design smell**. It usually means the responsibility for handling the absent case belongs one level up, at the call site.

- Extension and top-level functions take non-nullable receivers and parameters whenever possible — `fun String.parse()` not `fun String?.parse()`
- If a caller may have a nullable value, provide an overload or let the caller use `?.` at the call site
- Prefer overloads over a single function with nullable/default parameters when the two variants have meaningfully different behaviour — Kotlin overloads are idiomatic and cheap

## KMP / commonMain

- No imports from `android.*`, `java.*`, `javax.*`, `dalvik.*` in `commonMain`
- Only Kotlin stdlib and KMP-compatible libraries in `commonMain`
- `expect/actual` only for platform-specific implementation details — business logic belongs in `commonMain`
- Prefer `kotlinx.*` equivalents over JVM-only alternatives (e.g., `kotlinx.datetime` over `java.time`, `kotlinx.serialization` over Gson/Moshi)

## Architecture (Clean Architecture + MVI)

- UseCases are single-responsibility: one public `operator fun invoke()` (or project's chosen convention)
- Repository **interfaces** live in the domain layer; **implementations** live in the data layer
- Domain models / entities have **no framework dependencies** (exception: `kotlinx.coroutines`, `kotlinx.datetime`, `kotlinx.serialization` annotations)
- Mappers are explicit functions or classes — never put mapping logic inside data classes
- Never expose data-layer types (DTOs, Entities) through repository interfaces — always map to domain models at the layer boundary
- `viewModelScope` / `lifecycleScope` belong in the Android presentation layer only — not in UseCases or Repositories

# Kotlin Rules

Rules for writing Kotlin code across all projects (Android, KMP, backend).

## Idiomatic Kotlin

Write code as the Kotlin team intended — use language features where they make the code cleaner and more expressive:
- Prefer language constructs over manual workarounds: `when`, `let`, `run`, `apply`, `also`, `takeIf`, `fold`, destructuring, etc.
- Before implementing something manually, ask: "does Kotlin stdlib or the language already have this?"
- Follow the official [Kotlin Coding Conventions](https://kotlinlang.org/docs/coding-conventions.html) for naming, formatting, and structure
- The goal is code that a Kotlin developer recognises as natural — not Java-in-Kotlin, not over-engineered DSL, just clear idiomatic Kotlin

## Modern Language Features

- Prefer `sealed interface` over `sealed class` when subclasses share no common state
- Use `value class` (inline class) to wrap primitives with domain meaning: `value class UserId(val value: String)`
- Use `enum class` with properties/methods instead of `when` over raw strings or magic constants
- Use `data class` only when `copy()` and structural equality are genuinely needed; prefer plain `class` otherwise
- Use `object` for singletons and stateless implementations; never instantiate a class just to call one method

## Null Safety

- Never use `!!` — always use `?: error("reason")`, `requireNotNull(x) { "reason" }`, or safe handling
- Prefer `?.let`, `?.also`, `?: return` over null checks with `if`

## Functions vs Extension Functions

- `fun` inside a class — only when logic needs access to private members or represents the object's core behaviour
- `extension fun` — for utility/transformation operations that don't need private access; preferred for domain-type conversions (e.g., `fun UserId.toDto()`)
- Do not add extension functions to types you don't own just to avoid writing a utility object; use a top-level function or object instead

## Parameter Nullability and Overloads

- Extension and top-level functions must take non-nullable receivers and parameters whenever possible — `fun String.parse()` not `fun String?.parse()`
- If a caller may have a nullable value, provide an overload or let the caller use `?.` at the call site rather than pushing `?` into the function signature
- Prefer overloads over a single function with nullable/default parameters when the two variants have meaningfully different behaviour: Kotlin overloads are idiomatic and cheap
- A nullable parameter is a design smell in an extension or top-level function — it usually means the responsibility for handling the absent case belongs one level up, at the call site

## Code Organisation

- One public class/interface per file; private helpers and extension functions may live in the same file
- Order of class members: `companion object` → properties → `init` → public functions → private functions
- Break a function when it has more than one level of abstraction or when sub-operations have distinct names worth expressing
- Prefer expression bodies (`= ...`) for single-expression functions that fit on one line

## Named Parameters

- Use named parameters when arguments are of primitive/simple types (`String`, `Int`, `Boolean`, etc.) and their meaning isn't obvious from context
- Always use named parameters when a call has two or more arguments of the same type to prevent argument order mistakes
- Apply judgement — well-named single-argument functions don't require it, but when in doubt, name it

## if Expressions

- Write `if` expressions on a single line when the entire expression (condition + both branches) fits comfortably on one line: `val x = if (flag) a else b`
- Use block form as soon as either branch needs multiple statements or the line becomes too long to read at a glance

## Visibility

- `internal` by default for everything that is not a public module API
- `private` for implementation details inside a class
- `public` is explicit and intentional — every public declaration is a contract
- Never leave a class/function `public` just because it's the default

## KMP / commonMain

- No imports from `android.*`, `java.*`, `javax.*`, `dalvik.*` in `commonMain`
- Only Kotlin stdlib and KMP-compatible libraries in `commonMain`
- Use `expect/actual` only for platform-specific implementation details; business logic belongs in `commonMain`
- Prefer `kotlinx.*` equivalents over JVM-only alternatives (e.g., `kotlinx.datetime` over `java.time`)

## Coroutines and Flow

- Never use `GlobalScope`
- `viewModelScope` / `lifecycleScope` belong in the Android layer only — not in UseCases or Repositories
- Prefer `Flow` over `suspend fun` when the operation emits multiple values over time
- Use `StateFlow` for UI state, `SharedFlow` for one-shot events
- Always specify a meaningful `CoroutineDispatcher`; default to `Dispatchers.Default` for CPU work, `Dispatchers.IO` for I/O

## Architecture (MVI + Clean Architecture)

- UseCases are single-responsibility: one public `operator fun invoke()` or `fun execute()`
- Repository interfaces live in the domain layer; implementations in the data layer
- Entities / domain models have no framework dependencies
- Mappers are explicit functions or classes — never put mapping logic inside data classes

# Escalation Patterns

When `binding-features-matrix.md` classifies a property-map row as `escalate`, its recipe lives
here. Each recipe names the triggering condition, the DataBinding semantic that blocks mechanical
conversion, and the options the user must choose between. The skill does not emit code for an
`escalate` row until a recipe is selected and confirmed.

---

## Adapter cleanup

**Condition.** A `@BindingAdapter`-annotated function must be retained or replaced after its
layout is migrated. Five disposal options are defined in `gradle-and-lint-gate.md §Five disposal
options`; this recipe maps origin to the recommended option.

| Origin | Recommended option |
|---|---|
| `project-local`, sole user is this module | `convert-to-extension` |
| `project-local`, used by multiple modules | `static-call` + move to shared module (see `gradle-and-lint-gate.md §Placement options`) |
| `monorepo`, 1–2 using modules | `duplicate-from-sources` — user approval + licence required |
| `monorepo`, many using modules | `keep-as-regular-dep` — call the function directly |
| `binary` library | `keep-as-regular-dep`; `duplicate-from-sources` only if explicitly dropping the dep |

Fall back to `escalate` when the adapter body references DataBinding internals
(`BR.*`, `Observable*`, runtime-generated binding classes).

For `convert-to-extension` and `duplicate-from-sources`, the placement destination is always
presented to the user explicitly via the prompt template in
`gradle-and-lint-gate.md "Placement options"` — it is never inferred silently.

---

## Two-way

**Condition.** A `@={…}` attribute on a standard widget (`EditText`, `Switch`,
`CompoundButton`, `RadioGroup`, `SeekBar`).

**Underlying semantic.** DataBinding generates a listener (widget→variable) and an observer
(variable→widget) with loop suppression. ViewBinding has neither.

**Option A — manual listener + coroutine collect (recommended).**

```kotlin
var suppressUpdate = false
binding.emailInput.addTextChangedListener { editable ->
    if (!suppressUpdate) viewModel.email.value = editable?.toString() ?: ""
}
viewLifecycleOwner.lifecycleScope.launch {
    repeatOnLifecycle(Lifecycle.State.STARTED) {
        viewModel.email.collect { value ->
            if (binding.emailInput.text?.toString() != value) {
                suppressUpdate = true; binding.emailInput.setText(value); suppressUpdate = false
            }
        }
    }
}
```

Same shape for `Switch` / `CompoundButton` (`setOnCheckedChangeListener`) and `SeekBar`
(`setOnSeekBarChangeListener`).

If this pattern repeats in ≥ 2 host classes in scope OR if its inline form runs longer than about 6 lines, the skill aggregates or flags it into the reuse-extraction step and prompts for placement per `gradle-and-lint-gate.md "Placement options"`.

**Option B — Compose state holder.** Only when the screen is also migrating to Compose.

**Option C — Drop to one-way.** Only when the variable is set once at setup and never
re-emitted programmatically. Remove `@=`, treat as `@{…}`.

---

## Two-way inverse

**Condition.** A `@={…}` on a custom widget with a project-local `@InverseBindingAdapter`.

**Underlying semantic.** DataBinding wires the `@BindingAdapter` (setter) +
`@InverseBindingAdapter` (getter/event) pair automatically; the loop cannot be reconstructed
from annotations alone.

Decision: call the `@BindingAdapter` directly for the write direction, wire the
`@InverseBindingAdapter`'s event source manually to push to the ViewModel, add the same
re-entry guard as Option A in §Two-way. Remove the `@InverseBindingAdapter` annotation after.

---

## LiveData wiring

**Condition.** A `LiveData<T>` / `StateFlow<T>` / `Flow<T>` variable whose lifecycle wiring
was implicit in `binding.lifecycleOwner = viewLifecycleOwner`. This row is `partial`; it appears
here because call-site placement requires a judgment call.

Wire each variable explicitly using the project's existing convention:

```kotlin
// StateFlow:
viewLifecycleOwner.lifecycleScope.launch {
    repeatOnLifecycle(Lifecycle.State.STARTED) {
        viewModel.userState.collect { binding.name.text = it.name }
    }
}
// LiveData:
viewModel.userLiveData.observe(viewLifecycleOwner) { binding.name.text = it.name }
```

For screens with many reactive bindings, group multiple `collect` calls in one
`repeatOnLifecycle` block.

If this pattern repeats in ≥ 2 host classes in scope OR if its inline form runs longer than about 6 lines, the skill aggregates or flags it into the reuse-extraction step and prompts for placement per `gradle-and-lint-gate.md "Placement options"`.

**Kotlin/Java generics interop — extension functions on Java-defined generic types.**
`LiveData<T>` is defined in Java and carries no nullability annotation on its type parameter.
As a result, an extension declared as `fun <T> LiveData<T>.x(...)` matches both `LiveData<UserUi>`
and `LiveData<UserUi?>` at the call site — the Kotlin type checker treats both as
bridge-compatible with the unannotated Java form. The same applies to other Java-defined generic
types that appear in DataBinding migrations: `MutableLiveData<T>`, `Observer<T>`, RxJava
`Observable<T>` / `Single<T>` / `Flowable<T>`, Guava `ListenableFuture<T>`, AndroidX `Callback<T>`.
Kotlin-defined containers (`StateFlow<T>`, `Flow<T>`, `Channel<T>`) do not carry this property —
an extension on `StateFlow<T>` will not match `StateFlow<T?>`. Practical implication: when writing
a LiveData extension helper, declare it on `LiveData<T>` (not `LiveData<T?>`) and it will apply
to both nullable and non-nullable type-argument use-sites, keeping the signature simpler.

---

## Observable decommission

**Condition.** A `<variable>` with `declared_type` `ObservableField<T>`, `ObservableBoolean`,
`ObservableInt`, `ObservableArrayList<T>`, or any `BaseObservable` subclass.

**Underlying semantic.** DataBinding observes these types via `PropertyChangeRegistry`.
ViewBinding has no equivalent; the type itself must change in the ViewModel / state holder.

Options (project convention drives the pick):
- **`StateFlow<T>`** — preferred for Coroutines-based projects.
- **`LiveData<T>`** — preferred when the rest of the codebase uses LiveData.
- **Plain `T`** — only when the value is set once and never re-emitted.

After the type is replaced, re-classify affected rows to `partial` (§LiveData wiring) or
`mechanical` (static value).

---

## ViewStub

**Condition.** The layout contains a `<ViewStub>` element with DataBinding's auto-binding
`OnInflateListener`.

**Underlying semantic.** `ViewStubProxy` inflates the stub and creates a typed binding
automatically. ViewBinding has no equivalent; the listener must be wired manually.

```kotlin
binding.stubContainer.setOnInflateListener { _, inflated ->
    val stubBinding = ItemStubContentBinding.bind(inflated)  // .bind(), not .inflate()
    stubBinding.title.text = viewModel.stubTitle
}
binding.stubContainer.inflate()
```

Use `.bind(inflated)` — `ViewStub.inflate()` returns the already-attached view, not an inflater context.

---

## Merge

**Condition.** The layout root is `<merge>`.

**Underlying semantic.** DataBinding handles `<merge>` parent-attachment internally; ViewBinding
requires the explicit two-arg form with `attachToParent = true`.

```kotlin
// DataBinding:   MergeItemBinding.inflate(inflater)
// ViewBinding:   MergeItemBinding.inflate(inflater, parent, true)
```

Locate every inflate call site for the layout (typically one per custom View or
`onCreateView`) and apply the two-arg form.

---

## BR references

**Condition.** The host class calls `binding.setVariable(BR.x, value)` or references `BR.*`.

**Underlying semantic.** `BR` is DataBinding's generated integer-constant class; ViewBinding
resolves all variables by name at compile time — `BR` has no equivalent.

Replacement driven by `replacement_strategy` in `<slug>-variables-map.md`:

- `field` / `constructor_param` / `direct_property_access` — replace each
  `setVariable(BR.x, value)` call with the materialised strategy (`mechanical-transforms.md
  §Variable wiring`); row becomes mechanical once strategy is confirmed.
- `escalate` — the variable's type or lifecycle requires §Observable decommission, §LiveData
  wiring, or §Two-way. Resolve those first; the `BR` call disappears as a side effect.

Delete `import …BR` after all call sites are replaced.

---

## Ambiguous overload

**Condition.** Adapter resolution found multiple `@BindingAdapter` overloads for the same
attribute bridgeable by `@BindingConversion`, with no specificity winner (per
`adapter-resolution.md §Overload selection`).

Decision: inspect the candidates listed in the property-map `notes` column, select the overload
matching the intended runtime behaviour, and record the choice in `notes`. The skill then
proceeds as if that overload were the unique match.

---

## Unresolved adapter or expression

**Condition.** Adapter resolution exhausted all source tiers (per `adapter-resolution.md §Output`),
or expression resolution failed to resolve an identifier (per
`expression-resolution.md §Escalation rules`).

Decision: manual investigation. Once the source is identified — typically a build-time-generated
class, conditional import, or macro — re-classify the row to `mechanical` or `partial` and
continue.

---

## Multi-method listener

**Condition.** A listener attribute maps to an interface with multiple abstract methods, or
DataBinding's SAM selection routed the expression to one method non-obviously.

**Underlying semantic.** DataBinding generates the full interface impl and picks the matching
method by signature. ViewBinding offers no generation; the host must implement the listener.

```kotlin
// Single-method shorthand:
binding.searchInput.addTextChangedListener { viewModel.onSearch(it?.toString() ?: "") }

// Multi-method — implement the full interface:
binding.searchInput.addTextChangedListener(object : TextWatcher {
    override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
    override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
        viewModel.onSearch(s?.toString() ?: "")
    }
    override fun afterTextChanged(s: Editable?) {}
})
```

The skill presents both forms and asks the user to confirm which methods carry logic.

---

## Cross-references

`binding-features-matrix.md` · `adapter-resolution.md` · `expression-resolution.md` ·
`gradle-and-lint-gate.md` · `mechanical-transforms.md`

# Mechanical Transforms

Mechanical transforms are the deterministic, no-judgment subset of the DataBinding-to-ViewBinding
conversion. Every property-map row with `bucket = mechanical` (per `binding-features-matrix.md`)
executes a transform from this reference; `developer-workflow-kotlin:kotlin-engineer` applies the
diff and `/check` (build + lint) is the acceptance gate.

---

## XML layout transforms

Apply to every layout file in scope — in this order, one pass.

**Remove the `<layout>` wrapper.** The direct child of `<layout>` becomes the new root. Preserve
all attributes of that child exactly; do not add or remove any. If the child had no
`xmlns:android` declaration (it was on `<layout>`), move the namespace declarations down to it.

**Delete the `<data>` block.** The `<variable>` and `<import>` declarations are transcribed into
`<slug>-variables-map.md` during Discovery; nothing about them remains in XML.

**Replace one-way `@{…}` attribute values.** For each attribute carrying a one-way expression:
- If the attribute has a natural static default (`android:text` → `""`; `android:contentDescription`
  → `""`; `android:enabled` → `"true"`): substitute the default and add a `tools:` namespace hint
  preserving the expression for documentation purposes, e.g.
  `tools:text="@{vm.name}"` alongside `android:text=""`.
- If the attribute is purely binding-driven (e.g. `app:imageUrl`, `android:visibility` driven
  entirely by a live value): **remove the attribute**. The host-Kotlin replacement supplies it
  at runtime.

**`@={…}` attribute values.** Not mechanical. Flag at Discovery time; route to `escalation-patterns.md §two-way`.

**Namespace cleanup.**
- Replace every `bind:` namespace prefix with `app:`. When a `bind:` and `app:` copy of the
  same attribute coexist, keep `app:` and delete `bind:`.
- Remove `xmlns:bind="http://schemas.android.com/apk/res-auto"` from the root element.

---

## Include transforms {#include}

`<include>` elements with no `bind:` variables: keep the element as-is; remove any `bind:`
attributes that are present (they will be gone after the `<data>` block is deleted). ViewBinding
generates a typed nested-binding field on the parent named after the `android:id` of the
`<include>`. Access the included layout's views via `binding.includedLayoutId.someChildViewId`.

`<include>` with `bind:variable="@{vm}"`: the variable is no longer passed via XML. The host
class must supply it explicitly — this is a `partial` row. The recipe lives alongside this
section but the wiring is a host-Kotlin change, not a pure XML one.

---

## Host-class inflate transforms

Three canonical shapes. Match the one the host class currently uses.

**Activity.**

```kotlin
// DataBinding:
binding = DataBindingUtil.setContentView(this, R.layout.activity_main)

// ViewBinding:
binding = ActivityMainBinding.inflate(layoutInflater)
setContentView(binding.root)
```

If the project already uses a helper (e.g. `by viewBinding(...)`) match that pattern instead of
the two-liner above.

**Fragment.**

```kotlin
// DataBinding (in onCreateView):
_binding = FragmentProfileBinding.inflate(inflater, container, false)
return binding.root

// ViewBinding — identical inflate call; no change needed here.
// The lifecycle cleanup (§_binding null) is still required.
```

**RecyclerView ViewHolder.**

```kotlin
// DataBinding:
class FooViewHolder(private val binding: ItemFooBinding) :
    RecyclerView.ViewHolder(binding.root) {
    fun bind(item: Foo) { binding.title.text = item.title }
}

// ViewBinding: identical structure. If the ViewHolder previously used
// binding.setItem(item) or binding.setVariable(BR.item, item), replace
// with direct field access inside bind().
```

---

## `_binding = null` rule

Every Fragment that holds a `binding` reference must null it in `onDestroyView`. Standard idiom:

```kotlin
private var _binding: FragmentProfileBinding? = null
private val binding get() = _binding!!

override fun onCreateView(...): View {
    _binding = FragmentProfileBinding.inflate(inflater, container, false)
    return binding.root
}

override fun onDestroyView() {
    super.onDestroyView()
    _binding = null
}
```

Apply this pattern to every Fragment that uses ViewBinding. Activities and ViewHolders do not
need the null pattern (their lifecycle matches the view's lifetime).

---

## DataBinding-only call removal

Three calls are removed with no replacement:

- **`executePendingBindings()`** — ViewBinding has no pending-binding queue. Delete the call
  site.
- **`binding.lifecycleOwner = …`** — ViewBinding has no observer integration. Delete the line.
  Lifecycle wiring for `LiveData` / `StateFlow` variables is a `partial` row handled separately.
- **`binding.setVariable(BR.x, value)`** — Replace per the `replacement_strategy` column in
  `<slug>-variables-map.md`. If the row's strategy is `escalate`, skip — it is not mechanical.

---

## Per-binding replacement assembly

For each property-map row with `bucket = mechanical`, `developer-workflow-kotlin:kotlin-engineer`:

1. Locates the host-class line that previously was `binding.setX(…)` or an implicit XML
   binding expression.
2. Inserts the row's `replacement_fragment` snippet (per `adapter-resolution.md`
   replacement-template builder).

By `adapter_origin`:

- **`implicit-setter`** — direct property assignment on the view:
  `binding.title.text = viewModel.user.name`.
- **`binary:<coords>`** — FQN import plus static call:
  `BindingAdapters.setImageUrl(binding.avatar, url)`.
- **`project-local`** — direct call to the same function (module visibility permitting).
- **`monorepo:<path>`** — if the module is already on the host's compile classpath, a direct
  call. If not, the row should have been classified `partial` during Discovery; re-check the
  property map.

---

## Per-overload templates

When generating an extension on a Java-defined generic type (LiveData, Observer, RxJava `Observable`/`Single`, etc.), see `escalation-patterns.md §LiveData wiring` — final note for the Kotlin/Java generics interop rule on nullable type arguments.

Common patterns from `adapter-resolution.md` overload selection:

```kotlin
// android:text="@{vm.title}" — implicit setter, CharSequence
binding.title.text = vm.title

// android:text="@{@string/label}" — setText(@StringRes Int)
binding.title.setText(R.string.label)

// app:imageUrl="@{vm.avatarUrl}" — binary adapter (databinding-adapters)
// Ensure explicit dep on the adapter library (gradle-and-lint-gate.md §keep-as-regular-dep).
ImageBindingAdapters.setImageUrl(binding.avatar, vm.avatarUrl)

// android:visibility="@{vm.isLoading ? View.VISIBLE : View.GONE}"
// Use isVisible (maps to VISIBLE/GONE). Use isInvisible for VISIBLE/INVISIBLE.
// Note: View.INVISIBLE and View.GONE behave differently — preserve the original semantics.
binding.spinner.isVisible = vm.isLoading

// android:onClick="@{vm::onSave}"
binding.saveButton.setOnClickListener { vm.onSave(it) }

// android:onClick="@{() -> vm.onSave()}"
binding.saveButton.setOnClickListener { vm.onSave() }
```

---

## Variable wiring (`<slug>-variables-map.md`)

For each variables-map row, apply the replacement strategy:

- **`field`** — declare a Kotlin property in the host class, assign it before any view
  references that depend on it execute.
  ```kotlin
  var user: User? = null
  // then: binding.name.text = user?.name ?: ""
  ```
- **`constructor_param`** — thread the value through the host's constructor or factory
  method (common in ViewHolder / custom View).
- **`direct_property_access`** — replace `binding.setX(value)` calls with direct property
  assignment on the value's owner object.
- **`escalate`** — not handled here; see `escalation-patterns.md`.

---

## Definition of done for a mechanical row

Three checks — all must pass before a row is marked complete:

1. The corresponding XML attribute or `<layout>` wrapper is absent from the layout file.
2. Host code compiles clean (`/check` build phase — zero new errors or warnings).
3. The lint baseline is not bumped by this row's changes (`/check` lint phase).

The skill does not run `/check` itself. The user runs it per screen after the engineer agent
applies the batch for that screen.

---

## Cross-references

`property-map-spec.md` · `adapter-resolution.md` · `expression-resolution.md` ·
`escalation-patterns.md`

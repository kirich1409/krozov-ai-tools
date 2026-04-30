# SwiftUI Design System — Non-Obvious Rules

This file lists only the design-system rules a modern Claude model omits or gets wrong without a reminder. Generic guidance — "consistency over cleverness", "Apple HIG is baseline", "tokens for spacing/radius/typography", "every interactive element has accessibilityLabel", "previews exist", basic theming syntax — is **not** documented here; trust the model and Apple's HIG.

For project-rollout playbooks (waves, ownership labels, migration strategy) see your project's design-system README, not this file.

---

## Don't Tokenize These

Three categories the model often tokenizes redundantly:

- **Shadow** — on macOS use `Material`; on iOS keep 2-3 elevations max, do not invent a shadow scale
- **Opacity** — use `.foregroundStyle(.secondary)` / `.tertiary` / `.quaternary` instead of an `opacity` token
- **Font weights as separate tokens** — apply `.fontWeight(.semibold)` on text styles directly

## Hard Bans (Beyond Generic "No Hardcoded Values")

The non-obvious ones the model still emits from older training data:

| Banned | Use instead |
|---|---|
| `.foregroundColor(_:)` | `.foregroundStyle(_:)` |
| `.accentColor(_:)` modifier | `.tint(_:)` + `AccentColor` asset |
| `RoundedRectangle(cornerRadius: 8)` | `.clipShape(.rect(cornerRadius: ..., style: .continuous))` for continuous corners |

Generic bans (no raw `.padding(16)`, no `Color.black`, no `Font.system(size: 14)` outside icons/canvas) are model-default knowledge — match project tokens when they exist.

## Accessibility Beyond `accessibilityLabel`

The model writes `accessibilityLabel` by default. Often missed:

- **Keyboard shortcuts on primary sheet/form actions** — `⌘Return` for confirm, `⌘.` for cancel
- **Color-alone signals fail.** Pair color with an SF Symbol (`exclamationmark.triangle.fill` for errors, `checkmark.circle.fill` for success). React to `@Environment(\.accessibilityDifferentiateWithoutColor)`.
- **Animations gated by `accessibilityReduceMotion`**: `withAnimation(reduceMotion ? nil : .spring) { ... }`
- **Custom backgrounds gated by `accessibilityReduceTransparency`** — system materials handle this automatically; custom backgrounds must match.

## Multi-Window: Environment Doesn't Cross Scenes

`@Environment` values do **not** propagate across `Scene` boundaries automatically. Every `WindowGroup`, `Window`, `Settings`, `MenuBarExtra` must inject the theme/dependency at its own scene root.

```swift
@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup    { RootView().environment(\.theme, store.theme) }
        Settings       { SettingsView().environment(\.theme, store.theme) }
        MenuBarExtra("App", systemImage: "x") {
            MenuContent().environment(\.theme, store.theme)
        }
    }
}
```

The model often injects only at the main `WindowGroup` and the second window crashes or shows defaults.

## Theming — Hybrid Decision Rule

- **Static enum** for primitives that do not change at runtime — spacing, radius, motion, typography
- **Semantic NSColor / system color wrappers** for adaptive colors (auto-handles light/dark/HCR)
- **Environment-injected struct** only when the user picks between palettes at runtime (terminal themes, accent palettes)

The model often jumps to environment injection for everything; static enums are simpler and don't need scene-by-scene re-injection.

## Component Styling — `*Style` Static Extensions

Expose reusable `ButtonStyle` / `LabelStyle` / `ToggleStyle` etc. via static extensions on the protocol — the call site reads naturally:

```swift
extension ButtonStyle where Self == BrandPrimaryButtonStyle {
    static var brandPrimary: Self { .init() }
}
// Usage: Button("Save") { ... }.buttonStyle(.brandPrimary)
```

`PrimitiveButtonStyle` only when the default tap gesture is insufficient.

## Previews — Coverage Matrix for Reusable Components

Reusable design-system components need preview coverage across:

- Light + Dark
- Increase Contrast (and Dark HCR)
- Reduce Transparency
- Dynamic Type at `.xSmall` and `.accessibility2`
- Disabled state (where applicable)

A dedicated catalog scheme (`DesignSystemCatalog` or similar) listing every component is the discovery surface — without it, developers duplicate.

## macOS 26+ / Liquid Glass

- Rebuilding with Xcode 26 auto-applies Liquid Glass to toolbar, sheet, popover, `NavigationSplitView` sidebar, `Settings` scene. No opt-in needed.
- **Never on monospaced canvases** (terminal, code editor) — text degrades under refraction. Use `.containerBackground(.thinMaterial, for: .window)` for window background material instead.
- `.glassEffect(_:in:isEnabled:)` / `GlassEffectContainer` / `.glassEffectID(_:in:)` — for floating UI only (command palette, floating buttons).
- `Reduce Transparency` / `Increase Contrast` / `Reduce Motion` — system handles fallbacks; custom code must follow.

## Dynamic Type on macOS

macOS largely ignores Dynamic Type — `@ScaledMetric` and `.dynamicTypeSize` are weakly applied or not applied at all. Write the Dynamic-Type-ready form (`.font(.body)`) anyway, but don't rely on it for user-facing scaling on macOS canvases.

For content canvases where scaling matters (terminal, editor): implement a per-app font scale preference (`⌘+` / `⌘−`) and pass the coefficient explicitly.

## i18n Baseline

Even for English-only apps, set up `Localizable.xcstrings` from day 1:

- All user-facing strings via `Text("key", bundle: .module)` (or `LocalizedStringResource`)
- Test layouts with long strings (German, Russian) — expect 30-40% wider text
- RTL — `.leading` / `.trailing` alignment, never `.left` / `.right`

Retrofitting i18n is ~10× more expensive than building it in.

## Sources

- Apple HIG, WWDC25 Sessions 323 (SwiftUI new design) and 310 (AppKit new design)
- NSColor UI element colors documentation

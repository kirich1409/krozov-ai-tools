# SwiftUI Design System Rules

Rules for building and maintaining a design system in any SwiftUI-based macOS/iOS/iPadOS project. Apply whenever writing or reviewing SwiftUI views, styles, or UI primitives.

## Core Principles

- **Consistency over cleverness**: one way to do each UI thing. If a token or component already exists, use it; don't reinvent.
- **Apple HIG is the baseline**: design decisions must align with the current Human Interface Guidelines for the target platform. When HIG and custom design conflict — HIG wins unless the project owner explicitly overrides.
- **Accessibility is not optional**: every interactive element must be keyboard-reachable and VoiceOver-labelled. Not a Wave 5 cleanup — a requirement from commit 1.
- **Semantic over literal**: prefer `Color.labelColor`, `Font.headline`, `Material.regular` over hex literals, fixed point sizes, opaque backgrounds.
- **Adaptive by default**: light/dark/high-contrast/transparency/motion — all supported without per-screen branching.

## Token Taxonomy

Every SwiftUI design system must provide these five token families. Names may differ by project, but the categories are required.

| Family | Examples | Type |
|---|---|---|
| **Spacing** | `xxs, xs, sm, md, lg, xl, xxl` (8pt grid: 4, 8, 12, 16, 24, 32, 48) | enum static |
| **Radius** | `xs, sm, md, lg, xl, pill` (corner radii) | enum static |
| **Motion** | `Duration.{instant, fast, standard, slow, deliberate}`, `Curve.{standard, emphasis, linear}` | enum static |
| **Text** | semantic wrappers over system text styles (`body`, `headline`, `title`, `caption`, `code`, `bodyMono`) | enum static factories |
| **Color** | semantic NSColor/UIColor wrappers + Asset Catalog brand palette with 4 appearances (Any / Dark / Any HCR / Dark HCR) | enum wrappers + Asset Catalog |

### What NOT to tokenize
- Shadow levels — on macOS rely on `Material`, on iOS keep 2-3 elevations max.
- Opacity — use `.foregroundStyle(.secondary)` / `.tertiary` / `.quaternary` instead of `.opacity(0.6)`.
- Font weights as separate tokens — apply `.fontWeight(.semibold)` on text styles.

## Hard Bans

Never use these in SwiftUI view code after a design system is in place:

| Banned | Use instead |
|---|---|
| `.padding(16)` (literal number) | `.padding(DS.Spacing.md)` |
| `.frame(width: 220, height: 48)` | `.frame(width: DS.Size.formField, height: DS.Size.controlLarge)` or named constants |
| `Color.black`, `Color(red:…)`, `Color(hex:…)` | `DS.Color.*` semantic wrappers or Asset Catalog |
| `Font.system(size: 14)` | `Font.system(.body)` / `.headline` / `DS.Text.body` (raw size OK for icons and terminal canvas only) |
| `.foregroundColor(_:)` | `.foregroundStyle(_:)` |
| `.accentColor(_:)` modifier | `.tint(_:)` + `AccentColor` asset |
| Hardcoded `RoundedRectangle(cornerRadius: 8)` | `.clipShape(.rect(cornerRadius: DS.Radius.md, style: .continuous))` |
| `.shadow(radius: 10)` without purpose | `Material`-based elevation, shadows only for popover/menu |
| Icon-only `Button` without `.accessibilityLabel` | **forbidden** — every icon button requires a label |

SwiftLint custom rules should enforce (1), (3), and (5) after Wave 1 of the design-system rollout — warning level initially, error after full migration.

## Accessibility Checklist — Every Interactive View

Before merging a PR that adds or modifies a view, verify all nine:

1. `.accessibilityLabel(_:)` — concise noun, no "button"/"tab" fillers.
2. `.accessibilityHint(_:)` — for non-trivial actions, describes what happens.
3. `.accessibilityValue(_:)` — for controls with state (Toggle, Slider, Picker).
4. `.keyboardShortcut(_:modifiers:)` — on every primary action in a sheet/form (⌘Return confirmation, ⌘. cancel).
5. `.focusable()` + `.contentShape(_:)` — for custom controls, so the focus ring follows the interactive area.
6. **Don't rely on colour alone**: pair colour with an SF Symbol (`exclamationmark.triangle.fill` for errors, `checkmark.circle.fill` for success). React to `@Environment(\.accessibilityDifferentiateWithoutColor)`.
7. **Animations guarded**: wrap `withAnimation` / `.animation(_:)` in `@Environment(\.accessibilityReduceMotion)` check. `accessibilityReduceMotion ? nil : .spring(...)`.
8. **Materials**: verify behaviour with `\.accessibilityReduceTransparency == true`. SwiftUI makes system materials opaque automatically; custom backgrounds must do the same explicitly.
9. **Icon-only buttons**: `.accessibilityLabel` is **mandatory**. VoiceOver must not announce "button" alone.

## Theming Approach — Recommended Pattern

Hybrid: static enums for primitives, semantic wrappers for color, environment-injected theme for runtime-switchable palettes.

```swift
// Primitives — static, don't change at runtime
enum DS {
    enum Spacing { static let xxs: CGFloat = 4, xs: CGFloat = 8, ... }
    enum Radius  { static let xs: CGFloat = 2, ... }
    enum Motion  { /* Duration + Curve */ }
    enum Text    { static let body = Font.system(.body), ... }
}

// Color — semantic wrappers (light/dark/HCR adaptation via NSColor/Asset Catalog)
extension DS {
    enum Color {
        static let textPrimary = SwiftUI.Color(nsColor: .labelColor)
        static let surface     = SwiftUI.Color(nsColor: .windowBackgroundColor)
        // Brand colors from Asset Catalog (4 appearances)
        static let brandPrimary = SwiftUI.Color("brand/primary", bundle: .module)
    }
}

// Runtime-switchable palettes (terminal colors, user-selected themes) — environment
private struct TerminalThemeKey: EnvironmentKey {
    static let defaultValue: TerminalTheme = .default
}
extension EnvironmentValues {
    var terminalTheme: TerminalTheme {
        get { self[TerminalThemeKey.self] }
        set { self[TerminalThemeKey.self] = newValue }
    }
}
```

**When to use `@Environment(\.theme)` vs. static tokens**:
- Static enum — values don't change at runtime (spacing, radius, motion).
- Semantic NSColor wrappers — adapt automatically to colorScheme and HCR.
- Environment-injected struct — only when the user actually picks between palettes at runtime.

## Multi-Window Injection Rule

Every `Scene` — `WindowGroup`, `Window`, `Settings`, `MenuBarExtra` — must receive the theme injection at its scene-root. Environment does not cross window boundaries automatically.

```swift
@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup {
            RootView().environment(\.terminalTheme, store.terminalTheme)
        }
        Settings {
            SettingsView().environment(\.terminalTheme, store.terminalTheme)
        }
        MenuBarExtra("App", systemImage: "terminal") {
            MenuContent().environment(\.terminalTheme, store.terminalTheme)
        }
    }
}
```

## Component Styling Patterns

- `ButtonStyle` for reusable button variants (primary, secondary, ghost, icon). Expose via static extensions: `extension ButtonStyle where Self == BrandPrimaryButtonStyle { static var brandPrimary: Self { .init() } }`.
- `LabelStyle`, `ToggleStyle`, `ProgressViewStyle`, `TextFieldStyle`, `MenuStyle` — same pattern.
- `ViewModifier` for composition patterns (`.dsCard()`, `.dsSection()`, `.dsEmptyState()`).
- Custom `PrimitiveButtonStyle` only when default gesture (tap) is insufficient.

## Previews as First-Class

Every reusable component in the design system must have `#Preview` coverage for:

- Light mode
- Dark mode
- High Contrast (Increase Contrast + Dark HCR variant)
- Reduce Transparency
- Dynamic Type at `.xSmall` and `.accessibility2`
- Disabled state (where applicable)

A dedicated "catalog app" scheme (`DesignSystemCatalog` or similar) listing every component is required before feature views start consuming the design system — it's the discovery surface. Without a catalog, developers duplicate.

## macOS 26+ / Liquid Glass Specifics

- Rebuilding with Xcode 26 automatically applies Liquid Glass to toolbar, sheet, popover, `NavigationSplitView` sidebar, `Settings` scene. No opt-in needed.
- `.glassEffect(_:in:isEnabled:)` / `GlassEffectContainer` / `.glassEffectID(_:in:)` — for floating UI only (command palette, floating buttons). **Never on text-heavy canvases** (terminal, code editor) — monospaced text degrades under refraction.
- `.windowStyle(.hiddenTitleBar)` + `.windowToolbarStyle(.unifiedCompact)` — for terminal-focused windows where chrome should recede.
- `.containerBackground(.thinMaterial, for: .window)` — correct way to set window background material.
- `Reduce Transparency` / `Increase Contrast` / `Reduce Motion` — system handles opacity/contrast/animation fallbacks automatically. Custom code must follow the same convention.

## Dynamic Type on macOS

On macOS Dynamic Type has limited effect (`@ScaledMetric`, `.dynamicTypeSize`, `dynamicTypeSize` environment — either not applied or applied weakly by the system). Always write code in the Dynamic-Type-ready form (`.font(.body)`, `Font.system(.title)`), but don't rely on it for user-facing scaling on macOS.

For content canvases where scaling matters (terminal, editor) — implement a per-app font-scale preference (⌘+ / ⌘−) and pass the coefficient explicitly.

## Ownership and Change Policy

- Every design system must have a designated **owner** (or owner team) listed in the package README.
- Changes to public API of the design system require PR approval from the owner. Label such PRs `ds-api` to surface them.
- New tokens (colors, spacing values, radii) must be justified: at least 2 consumer sites, or an HIG reference.
- Removing tokens is a breaking change — deprecate for one release before deletion.

## Migration Strategy for Legacy Projects

When introducing a design system to a codebase that currently lacks one:

1. **Foundation wave** — create the package, tokens, Asset Catalog. No view rewrites.
2. **Styles wave** — write all ButtonStyles, LabelStyles, ViewModifiers. No view rewrites.
3. **Critical screens wave** — migrate 2-3 highest-traffic screens, validating tokens against real use.
4. **Forms wave** — unify sheet/form structure, collapse duplicated components (badges, rows).
5. **Lists wave** — unify row and list-cell components.
6. **Accessibility wave** — pass through every interactive view, fill the 9-point checklist, run Accessibility Inspector audit.
7. **Specialized wave** — canvas/terminal/editor-specific theming, per-app font scale.

Migration waves can proceed in parallel with feature development after Wave 1 — waves 2-7 don't block new feature work, they just impose a "migrate when you touch" rule.

Enforce "no new hardcoded values" via SwiftLint custom rules at warning level from Wave 2, error level from Wave 5.

## Design Hand-off

If the project lacks Figma / design artifacts:
- Accept code as source of truth — the owner makes visual decisions based on HIG.
- Keep the catalog app as the canonical reference.
- When designers join later, export tokens to Figma (via `figma-generate-library` skill or manual mapping) rather than re-designing.

## Internationalization Baseline

Even for English-only apps — set up `Localizable.xcstrings` from day 1:
- All user-facing strings via `Text("key", bundle: .module)` not `Text("literal")`.
- Test layouts with long strings (German, Russian) — expect 30-40% wider text.
- RTL: use `.leading` / `.trailing` alignment, not `.left` / `.right`.

Retrofitting i18n after the fact is 10× more expensive than building it in.

## Sources

- Apple HIG: https://developer.apple.com/design/human-interface-guidelines
- WWDC25 Session 323 — Build a SwiftUI app with the new design
- WWDC25 Session 310 — Build an AppKit app with the new design
- NSColor UI element colors: https://developer.apple.com/documentation/appkit/nscolor/ui_element_colors
- Microsoft FluentUI Apple Design Tokens: https://github.com/microsoft/fluentui-apple/wiki/Design-Tokens
- Apple Accessibility Inspector: Xcode → Open Developer Tool → Accessibility Inspector

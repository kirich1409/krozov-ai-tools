# KMP Migration Steps — Detailed Reference

## Step 2 — Apply KMP Plugin

In `build.gradle.kts`, replace `id("com.android.library")` + `id("org.jetbrains.kotlin.android")` with the multiplatform plugin:

```kotlin
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlin.multiplatform)
    alias(libs.plugins.android.library)  // keep this for Android target
}

kotlin {
    androidTarget {
        compilerOptions {
            jvmTarget = JvmTarget.JVM_17
        }
    }
    // iOS targets — declare all three for device + both simulator architectures:
    iosX64()
    iosArm64()
    iosSimulatorArm64()
    // jvm()  // if also targeting JVM desktop/server
}

android {
    // android config stays here unchanged
}
```

### iOS Framework Configuration

If targeting iOS, configure the framework that Xcode will consume:

| Option | How | Best for |
|--------|-----|----------|
| **Direct XCFramework** | `./gradlew assembleXCFramework` → embed `.xcframework` in Xcode project | Most teams starting out |
| **CocoaPods** | Apply `kotlin("native.cocoapods")` plugin, add podspec config, run `pod install` | Teams already using CocoaPods |
| **Swift Package Manager** | Embed XCFramework as a binary target in `Package.swift` | Teams using SPM |

For **CocoaPods or SPM**, add inside `kotlin { }`:
```kotlin
listOf(iosX64(), iosArm64(), iosSimulatorArm64()).forEach { target ->
    target.binaries.framework {
        baseName = "ModuleName"   // the import name in Swift: import ModuleName
        isStatic = true           // static linking is simpler for most projects
    }
}
```

For **direct XCFramework**:
```kotlin
val xcf = XCFramework("ModuleName")
listOf(iosX64(), iosArm64(), iosSimulatorArm64()).forEach { target ->
    target.binaries.framework {
        baseName = "ModuleName"
        isStatic = true
        xcf.add(this)
    }
}
```
Then `./gradlew assembleXCFramework` — output in `build/XCFrameworks/`.

Run `./gradlew :module:assemble` — must stay green before touching source files.

## Step 3 — Source Directory Restructure

**Source set directories:**
```
src/
  commonMain/kotlin/   ← platform-agnostic code (pure Kotlin, no Android SDK)
  androidMain/kotlin/  ← Android-specific (anything using android.*, Context, Activity, etc.)
  iosMain/kotlin/      ← iOS-specific implementations (if targeting iOS)
  commonTest/kotlin/   ← shared tests
  androidUnitTest/kotlin/
```

**Migration sequence — the safest path:**

1. **Move everything to `androidMain` first** — rename `src/main/kotlin` → `src/androidMain/kotlin`. Build stays green.
2. **Split dependencies** (Step 4).
3. **Promote files to `commonMain` one by one** — for each file, move it, then fix compilation errors:
   - Android imports that fail → extract behind `expect`/`actual` or leave in `androidMain`
   - Files that can't be fully de-Androidified → keep in `androidMain`; expose interface from `commonMain`

**What belongs where:**

| `commonMain` | `androidMain` |
|---|---|
| Domain models, data classes | Anything importing `android.*` (Android SDK proper) |
| Business logic, use cases | `Context`, `Activity`, `Fragment` usage |
| Repository interfaces **and implementations** (if deps are KMP-compatible) | Room implementations at version < 2.7 |
| Pure utility classes | Hilt/Dagger modules (`@Module`, `@Provides`, `@InstallIn`) |
| Coroutines logic | Platform-specific engines (Ktor Android engine) |
| Serialization models | Android-specific networking configs |
| `androidx.*` libraries **that publish KMP artifacts** | `androidx.*` libraries without KMP metadata |

### `expect` / `actual` Pattern

For code that needs different implementations per platform:

```kotlin
// commonMain
expect fun currentTimeMillis(): Long

// androidMain
actual fun currentTimeMillis(): Long = System.currentTimeMillis()

// iosMain
import platform.Foundation.NSDate
actual fun currentTimeMillis(): Long = (NSDate().timeIntervalSince1970 * 1000.0).toLong()
```

**`actual typealias` shortcut** — when a platform already provides exactly the type you need:

```kotlin
// commonMain
expect class AtomicRef<T>(value: T) {
    fun get(): T
    fun set(value: T)
}

// androidMain
actual typealias AtomicRef<T> = java.util.concurrent.atomic.AtomicReference<T>

// iosMain
actual class AtomicRef<T>(value: T) { ... }
```

Use `expect`/`actual` sparingly — prefer interfaces and injection. In Kotlin 2.x, the compiler enforces stricter matching.

### Common Platform-Specific Concerns

| Concern | Don't do | Do instead |
|---------|----------|------------|
| Date/time formatting | `expect fun formatDate(...)` with Java/NSDate actuals | Add `kotlinx-datetime` — KMP-native |
| UUID generation | Platform-specific UUID calls | Use `com.benasher44:uuid` or `expect fun randomUUID()` |
| Logging | Direct `Log.d` / `NSLog` | Use `co.touchlab:kermit` or `expect fun log(...)` |
| JSON serialization | Platform-specific JSON parsers | Use `kotlinx-serialization-json` — fully KMP |
| HTTP networking | OkHttp / NSURLSession | Ktor with per-platform engines |

**Prefer KMP-native libraries over `expect`/`actual`** — they reduce boilerplate and are maintained by the community.

## Step 4 — Split Dependencies

Replace the flat `dependencies {}` block with source-set-scoped blocks:

```kotlin
kotlin {
    sourceSets {
        commonMain.dependencies {
            implementation(libs.kotlinx.coroutines.core)
            implementation(libs.kotlinx.serialization.json)
            implementation(libs.ktor.client.core)
            implementation(libs.koin.core)
        }
        androidMain.dependencies {
            implementation(libs.ktor.client.android)
            implementation(libs.androidx.core.ktx)
            implementation(libs.koin.android)
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
            implementation(libs.kotlinx.coroutines.test)
        }
    }
}
```

**Rules for placing a dependency:**
- Pure Kotlin with KMP metadata → `commonMain`
- Wraps Android SDK or uses platform-specific engine → `androidMain`
- Has core + engine artifacts (e.g. Ktor) → core in `commonMain`, engine in `androidMain`
- Not sure → run `./gradlew :module:compileCommonMainKotlinMetadata`; if it compiles, `commonMain`

## Step 5 — Compile Checks

```bash
./gradlew :module:compileCommonMainKotlinMetadata   # commonMain compiles alone
./gradlew :module:compileDebugKotlinAndroid          # full Android target
./gradlew :module:assemble                          # full module build
```

Run after plugin setup, after each source file promotion, and after dependency split.

## Phase 4: Verify + Cleanup

### Re-run Tests on All Targets

```bash
./gradlew :module:testDebugUnitTest          # Android unit tests
./gradlew :module:iosSimulatorArm64Test      # iOS tests (if targeting iOS)
./gradlew :module:jvmTest                    # JVM tests (if targeting JVM)
```

If tests fail: stop → diagnose → fix in migrated code, never by weakening/deleting tests.

### Behavior Spec Review

Walk through `behavior-spec.md` line by line:
- Every public interface entry: same signature or documented intentional change?
- Every normal behavior and edge case: covered by a passing test or manually verified?
- Every platform assumption: handled via `expect`/`actual` or confirmed platform-agnostic?
- **Present completed review to user — wait for confirmation**

### Cleanup

1. Find: old Android-only Gradle deps no longer needed after source set split
2. Find: any `dependencies {}` block not converted to `sourceSets { }` style
3. Find: dead code or adapter layers made obsolete
4. **Present full removal list to user — wait for acknowledgment**
5. Remove everything on the list
6. `./gradlew build` — must be green

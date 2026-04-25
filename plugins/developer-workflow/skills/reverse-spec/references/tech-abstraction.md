# Tech Abstraction Heuristic

When to strip a technology from the spec, when to keep it, and how to phrase it either
way.

The spec describes *what the feature does*, not *how this codebase happens to build it*.
A reimplementation on a different stack must remain faithful to the product — but not to
the current architecture. This file is the rulebook for deciding which technology
references survive that translation and which do not.

---

## The test

A technology reference stays in the spec only if **removing it would change the
feature's behavior, capability, cost, legal posture, or performance envelope**.

Work through these four questions for every technology mention:

1. **Does the feature's observable behavior depend on this specific technology?**
   Face detection via ML Kit produces different bounding boxes than OpenCV Haar
   cascades. The observable result differs. → keep.
   Render via Jetpack Compose vs UIKit. The observable result is identical text on a
   screen. → drop.

2. **Does a swap require reworking integrations or compliance?**
   Payment via Stripe SDK keeps card data out of the app — a PCI-compliance win.
   Swapping to a custom form changes the regulatory scope. → keep.
   Swap Kotlin coroutines for RxJava. Identical behavior. No compliance impact. → drop.

3. **Is there a capability unique to the technology that the feature relies on?**
   AR via ARKit uses LiDAR for precise depth on iPhone Pro models. The feature's
   accuracy depends on it. → keep.
   HTTP via Ktor vs OkHttp. Both send HTTP. → drop.

4. **Does cost or licensing materially change?**
   Maps via Google Maps — tile cost, quota, licensing. → keep.
   Logging via Timber vs SLF4J. → drop.

If the answer to **any** of the four is yes, keep the technology. Otherwise drop.

---

## Load-bearing categories (usually keep)

- **ML / computer vision / speech** — ML Kit, Core ML, ONNX, AR frameworks, TTS/STT
  engines. Model differences are user-visible.
- **Payments** — Stripe, Adyen, Braintree, Apple Pay, Google Pay. Compliance and UX
  rules are SDK-specific.
- **Biometrics** — Android BiometricPrompt, iOS LocalAuthentication. Platform capability.
- **Maps & location** — Google Maps, Apple Maps, Mapbox, HERE. Tile licensing and
  rendering differ.
- **Realtime communication** — WebRTC, Agora, Twilio. Protocol and provider differ.
- **DRM / media** — Widevine, FairPlay, ExoPlayer streaming protocols. Compatibility is
  content-dependent.
- **Push / messaging backbone** — Firebase Cloud Messaging, APNs, Amazon SNS. Delivery
  semantics differ.
- **Identity providers** — Firebase Auth, AWS Cognito, Auth0. Flow and token shape
  differ.
- **Large vendor SDKs with product impact** — Segment (analytics pipeline), Branch
  (deep-link attribution), AppsFlyer (attribution), Intercom (support chat UX).
- **Platform-specific APIs** — Android WorkManager, iOS BackgroundTasks,
  BluetoothGattCallback patterns. The reimplementation needs an equivalent.

When keeping, phrase the constraint, not the SDK call:

> *"Face detection requires an on-device CV model with accuracy comparable to Google ML
> Kit v1.x (currently in use). Cloud-based detection is not acceptable for latency and
> privacy reasons."*

Not:

> *"Use `FaceDetector.getClient(...).process(image)` from the ML Kit SDK."*

The first lets a reimplementer substitute any equivalent; the second pins them to ML
Kit.

---

## Not load-bearing (usually drop)

- **UI toolkits** — Jetpack Compose, SwiftUI, React, UIKit, AppKit, Qt, Flutter.
  Describe the UI as components and behaviors; let the reimplementer choose.
- **HTTP clients** — Ktor, OkHttp, URLSession, Alamofire, axios, fetch. HTTP is HTTP.
- **Serialization** — Moshi, kotlinx.serialization, Codable, JSON.NET, Jackson.
- **DI frameworks** — Hilt, Koin, Dagger, Swinject, InversifyJS.
- **Async primitives** — coroutines, RxJava, Combine, async/await, Promises.
- **Persistence** — Room, SQLDelight, Core Data, SQLite directly, Realm (borderline —
  Realm's sync is load-bearing if used; plain Realm storage is not).
- **Image loading** — Coil, Glide, Picasso, SDWebImage, Kingfisher.
- **Logging / crash** — Timber, SLF4J, CocoaLumberjack, Crashlytics (borderline if the
  project uses a proprietary crash taxonomy; usually not).
- **Testing frameworks** — irrelevant to spec; the spec is not a test plan.
- **Build tools** — Gradle, Bazel, CocoaPods, SPM, npm. Never in a spec.

When you find these in code during analysis, ignore them for the spec body. A one-line
mention may appear under Code Map if it helps future maintenance.

---

## Borderline cases

Some technologies are load-bearing only because of *how* the feature uses them:

- **Caching libraries** — mostly not load-bearing, but if the feature relies on a
  specific invalidation behavior (e.g., Realm's live-updating queries driving UI
  reactivity), call it out.
- **State management** — MVI, Redux, MVVM are not spec-level. But if the feature exposes
  an observable stream to other features (inter-feature contract), describe the contract
  tech-agnostically.
- **Analytics backends** — the event *names and properties* are spec-level; the
  *pipeline* (Segment vs Mixpanel direct) usually is not, unless the feature has
  backend-coupled event validation.
- **Localization libraries** — the *coverage* is spec-level; which library drives it is
  not.

When uncertain: apply the four-question test. If still unclear, describe the *capability
or contract* rather than the technology, and add a note to Open Questions so the user
can flag it for keep-or-drop.

---

## Phrasing pattern

When a technology must be mentioned, prefer this shape:

> *"[Capability / contract] — currently provided by [technology], any equivalent is
> acceptable that preserves [specific property]."*

Examples:

- *"Face detection on-device — currently ML Kit v1.x. Any equivalent is acceptable that
  provides landmark detection (left eye, right eye, nose base) at ≥15 FPS on
  mid-range hardware."*

- *"Card input form — currently Stripe PaymentSheet. Any equivalent is acceptable that
  keeps PAN data out of application memory and storage (PCI SAQ-A eligibility)."*

- *"Push delivery — currently FCM for Android, APNs for iOS. Equivalents are acceptable
  if they preserve at-least-once delivery and the existing `payment.required` topic."*

This pattern transfers the *requirement* without pinning the *implementation*.

---

## Review step

Before declaring the spec draft complete, search it for technology names. For each hit:

1. Does it pass the four-question test?
2. If yes, is it phrased as a capability-with-acceptable-substitute rather than a
   direct-SDK-reference?
3. If no, delete the reference and describe the behavior instead.

Technology mentions in the Code Map appendix are fine — that section is explicitly about
the current implementation. The restriction applies to the spec body.

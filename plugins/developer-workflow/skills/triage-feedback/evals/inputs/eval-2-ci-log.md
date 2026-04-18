# CI log — build failure

User pastes this raw output from a failed GitHub Actions run. No PR context
is available to the skill beyond what's in this text.

```
> Task :app:compileDebugKotlin FAILED
e: /runner/work/app/src/main/kotlin/feature/Cart.kt:45:27 Unresolved reference: cartRepo
e: /runner/work/app/src/main/kotlin/feature/Cart.kt:78:14 Type mismatch: inferred type is String? but String was expected

> Task :app:lintDebug
Lint found 1 error:
ExifInterface /runner/work/app/src/main/kotlin/feature/ImageUpload.kt:22
    Using deprecated android.media.ExifInterface — use androidx.exifinterface.media.ExifInterface instead.

> Task :app:testDebugUnitTest
com.example.CartTest > addItem_emptyCart_addsItem FAILED
    java.lang.AssertionError: expected:<1> but was:<0>
        at com.example.CartTest.addItem_emptyCart_addsItem(CartTest.kt:24)

com.example.CartTest > addItem_existingItem_incrementsQuantity FAILED
    java.lang.AssertionError: expected:<2> but was:<0>
        at com.example.CartTest.addItem_existingItem_incrementsQuantity(CartTest.kt:38)

> Task :app:testDebugUnitTest FAILED

BUILD FAILED in 2m 14s
```

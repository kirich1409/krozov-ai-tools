# Mock PR — Mixed review comments

Represents the output of `gh pr view` + `gh api pulls/N/comments` for a hypothetical
PR. Use this as the `triage-feedback` source instead of a live API call.

## PR metadata

- **Title:** Add password reset flow
- **Number:** 142
- **Base:** main
- **Head:** feature/password-reset
- **Body:**
  > Implements password reset via email link. Fixes #89.
- **Labels:** feature, auth
- **Linked issue #89:**
  > As a user, I want to reset my password if I forget it. Acceptance: user receives
  > email with time-limited link; link opens a form to set a new password; token is
  > invalidated after use.

## Diff (relevant excerpt)

```diff
--- a/src/main/kotlin/auth/PasswordResetService.kt
+++ b/src/main/kotlin/auth/PasswordResetService.kt
@@ -10,6 +10,15 @@
 class PasswordResetService(
     private val db: Database,
     private val mailer: Mailer,
 ) {
+    fun requestReset(email: String) {
+        val user = db.query("SELECT * FROM users WHERE email = '$email'").firstOrNull()
+        val token = generateToken()
+        db.insert("password_reset_tokens", mapOf("user_id" to user.id, "token" to token))
+        mailer.send(email, "Reset your password: /reset?token=$token")
+    }
+
+    fun completeReset(token: String, newPassword: String) {
+        val record = db.query("SELECT * FROM password_reset_tokens WHERE token = '$token'").first()
+        db.update("users", mapOf("password_hash" to hash(newPassword)), "id = ${record.userId}")
+    }
 }
--- a/src/main/kotlin/auth/TokenGenerator.kt
+++ b/src/main/kotlin/auth/TokenGenerator.kt
@@ -1,3 +1,6 @@
 package auth
+
+fun generateToken(): String = java.util.UUID.randomUUID().toString()
+
```

## Review comments

### Comment #501 (inline, PasswordResetService.kt:13) — @alice

> SQL injection: you're concatenating `email` directly into the query. Use a
> parameterized query. Same problem on line 19 with `token`.

### Comment #502 (inline, PasswordResetService.kt:14) — @bob

> `user.id` — `user` here can be null (firstOrNull returns nullable). This will
> crash if the email isn't in the DB.

### Comment #503 (inline, PasswordResetService.kt:19) — @alice

> Token is never invalidated after use. The spec says "token is invalidated after
> use" — this is a compliance gap.

### Comment #504 (inline, PasswordResetService.kt:16) — @bob

> You could extract the email body building into a `PasswordResetEmailTemplate`
> class so we can localise it later. Not blocking.

### Comment #505 (inline, TokenGenerator.kt:3) — @alice

> trailing newline here

### Comment #506 (review summary) — @carol

> Why use UUID for the token? Any reason not to use a cryptographically secure
> random string of 32 bytes, base64-encoded?

### Comment #507 (review summary) — @dave

> Looks good overall, nice work on structuring the service.

### Comment #508 (inline, PasswordResetService.kt:12) — @carol

> We should also migrate the existing password change flow to use this same token
> mechanism — currently it uses the legacy hash-based approach.

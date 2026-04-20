Referenced from: `plugins/developer-workflow/skills/acceptance/SKILL.md` (§Re-verification Loop).

# Acceptance — Re-verification Loop

On fix-loop re-entry (after `FAILED` → `implement` fix → re-run acceptance):

1. Re-probe Step 0 and Step 1 (project type rarely changes; inputs may).
2. Compute `diff_hash_new` = `sha256(git diff <base>...HEAD)`.
3. Decide per-check action using the previous per-check artifact and `diff_hash`:

   | Previous verdict | Previous `diff_hash` vs `diff_hash_new` | Action |
   |---|---|---|
   | `PASS` or `SKIPPED` | match | **Skip** — reuse the existing artifact as-is. Record `re-used previous verdict` in the aggregated receipt. |
   | `PASS` or `SKIPPED` | mismatch | Re-run. |
   | `WARN` | match | Skip. Re-used verdict keeps the WARN; user had the option to ship with it. |
   | `WARN` | mismatch | Re-run. |
   | `FAIL` | any | **Always re-run.** A FAIL is the point of the loop; hash match means the fix didn't land in the diff yet — still must re-run to confirm. |
   | any prior verdict with previous `diff_hash` = `null`, absent, or unreadable | any | Re-run — cannot prove idempotency without a usable hash. |

   An explicit `diff_hash: null` and a missing `diff_hash` field are treated the same way:
   both mean the prior artifact does not carry enough information to prove idempotency, so
   the check must be re-run.

4. For checks that are re-run:
   - Overwrite the per-check artifact with fresh content and a new `diff_hash`.
   - `manual-tester` specifically re-runs previously-failed TCs plus a Smoke tier by default;
     the full plan is re-run only on explicit request or when the spec changed.
5. Aggregate into a fresh `swarm-report/<slug>-acceptance.md`, overwriting the previous one.
6. Repeat until VERIFIED or the user decides to ship as-is.

**Spec/test-plan change override.** If the spec file or test-plan file changed between runs
(detected by comparing their `sha256` to values recorded in the previous aggregated receipt
under `spec_hash` / `test_plan_hash`), `business-analyst` and `manual-tester` are always
re-run regardless of `diff_hash` — their input is the spec/TC list, not just the code diff.
Other checks remain subject to the `diff_hash` policy.

**Back-compat rule.** If the previous aggregated receipt does not contain `spec_hash`
and/or `test_plan_hash` (e.g. a pre-iteration-3 receipt) — or either prior value is unknown
or unreadable — treat that input as **changed** and re-run the affected checks to be safe:
missing/unknown `spec_hash` forces `business-analyst`; missing/unknown `test_plan_hash`
forces `manual-tester`. If both are missing/unknown, re-run both. Other checks remain
subject to the `diff_hash` policy.

This is the full idempotency pass that iteration 2 parked. Cost saving: on a single-file fix
after a 5-agent FAIL, typically 2–3 passed checks are re-used instead of re-run.

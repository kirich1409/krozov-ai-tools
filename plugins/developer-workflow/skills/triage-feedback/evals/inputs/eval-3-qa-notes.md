# QA notes — free-text feedback

User pastes a list from a QA session. No PR context, no diff. Pure
prioritization exercise.

Notes from testing the new order checkout on staging build 2026.04.18-rc1:

1. The order confirmation email arrives but uses the wrong currency symbol
   for users in the UK — shows $ instead of £. Probably breaks revenue
   reporting too. Happens 100% of the time.

2. Spinner on the "Place order" button is pixel-perfect now, matches Figma.
   Nice.

3. Checkout sometimes charges the wrong card. Testing with multiple saved
   cards, tapping the one I want, but the default one is used instead.
   Reproduced 3 out of 5 times. Money at risk.

4. The "apply promo code" field accepts uppercase only. Lowercase codes
   fail silently. Minor, but confusing for users who type casually.

5. Could we also redesign the address picker while we're in this area?
   The current three-dropdown approach (country/city/street) is clunky.

6. Padding on the totals row is 12px; design says 16px. Not blocking.

7. Why did we go with a separate review screen before checkout instead of
   an inline summary? Just curious — the old flow was inline.

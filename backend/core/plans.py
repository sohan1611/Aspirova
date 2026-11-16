"""Plan availability for public pricing and checkout, not subscriber access."""

# Plans deliberately withdrawn from sale (founder decision 2026-07-22).
# pro_lite_annual: under the cancel-then-resubscribe policy, a mistaken Pro
# Lite Annual purchase would lock the customer into the bottom tier for a FULL
# YEAR with no way up. The plans row and the Razorpay plan object remain
# (Razorpay plans cannot be deleted; the row is historical data): GET /plans
# hides it and checkout refuses it. Verified in prod before retiring: nobody
# was ever subscribed to it.
RETIRED_PLAN_KEYS = frozenset({"pro_lite_annual"})

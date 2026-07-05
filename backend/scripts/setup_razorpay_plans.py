"""One-time setup: creates the 4 paid Razorpay-side Plan objects (Razorpay
has its own "Plan" concept - a recurring billing template - distinct from,
but linked to, our own `plans` table) and records each one's Razorpay plan
ID back onto the matching local row.

BLOCKED ON CREDENTIALS: requires a real Razorpay account with test-mode
API keys (RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET in .env) - a manual
prerequisite (Doc handoffs/PHASE-2-HANDOFF.md sec 10), not something this
script can create for you. Run scripts/seed_plans.py FIRST (this script
looks up existing local plan rows by key and only fills in the missing
razorpay_plan_id).

Idempotent - skips any plan that already has a razorpay_plan_id. Usage:
uv run python -m scripts.setup_razorpay_plans
"""

import razorpay
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import make_engine
from core.models import Plan

# key -> Razorpay plan "item" description/amount (paise, INR) - must match
# scripts/seed_plans.py's PLANS exactly; kept separate rather than derived,
# since Razorpay's Plan.create() needs its own period/interval fields that
# our local schema doesn't otherwise track.
_RAZORPAY_PLAN_SPECS = {
    "pro_lite_monthly": {
        "period": "monthly",
        "interval": 1,
        "amount": 3900,
        "name": "Pro Lite (Monthly)",
    },
    "pro_lite_annual": {
        "period": "yearly",
        "interval": 1,
        "amount": 39900,
        "name": "Pro Lite (Annual)",
    },
    "pro_monthly": {"period": "monthly", "interval": 1, "amount": 4900, "name": "Pro (Monthly)"},
    "pro_annual": {"period": "yearly", "interval": 1, "amount": 49900, "name": "Pro (Annual)"},
}


def setup() -> None:
    settings = get_settings()
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        raise SystemExit(
            "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET are not set - create a Razorpay account, "
            "grab test-mode API keys from the dashboard, and set them in backend/.env first."
        )

    client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    engine = make_engine()

    with Session(engine) as session:
        created = 0
        for key, spec in _RAZORPAY_PLAN_SPECS.items():
            plan = session.scalar(select(Plan).where(Plan.key == key))
            if plan is None:
                print(f"skipped {key}: no local plan row - run scripts/seed_plans.py first")
                continue
            if plan.razorpay_plan_id:
                print(f"skipped {key}: already has razorpay_plan_id={plan.razorpay_plan_id}")
                continue

            razorpay_plan = client.plan.create(
                {
                    "period": spec["period"],
                    "interval": spec["interval"],
                    "item": {
                        "name": spec["name"],
                        "amount": spec["amount"],
                        "currency": "INR",
                    },
                }
            )
            plan.razorpay_plan_id = razorpay_plan["id"]
            created += 1
            print(f"created Razorpay plan for {key}: {razorpay_plan['id']}")

        session.commit()
        print(f"done: {created} Razorpay plans created")


if __name__ == "__main__":
    setup()

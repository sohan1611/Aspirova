"""Seed the 5 canonical plan rows (Doc 03 sec 4.1, Doc 06 sec 1 - binding
prices; Doc handoffs/PHASE-2-HANDOFF.md sec 6 - binding features shape).
Prices are in paise. Idempotent - safe to re-run.

The Phase-3 AI feature flags (copilot/resume_match/prediction) are present
but false/absent on every plan except pro, where they're already true -
the gate is built once now; the features behind them are NOT built until
Phase 3 (Doc handoffs/PHASE-2-HANDOFF.md sec 1: "OUT of scope").

Usage: uv run python -m scripts.seed_plans
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Plan

FREE_FEATURES = {
    "dream_companies_limit": 1,
    "instant_alerts": False,
    "weekly_report": False,
    "hidden_opps": "limited",
    "unlimited_bookmarks": False,
    "daily_digest": True,
    "copilot": False,
    "resume_match": False,
    "prediction": False,
}

PRO_LITE_FEATURES = {
    "dream_companies_limit": 5,
    "instant_alerts": True,
    "weekly_report": True,
    "hidden_opps": True,
    "unlimited_bookmarks": True,
    "daily_digest": True,
    "copilot": False,
    "resume_match": False,
    "prediction": False,
}

PRO_FEATURES = {
    "dream_companies_limit": None,  # unlimited
    "instant_alerts": True,
    "weekly_report": True,
    "hidden_opps": True,
    "unlimited_bookmarks": True,
    "daily_digest": True,
    "copilot": True,
    "resume_match": True,
    "prediction": True,
}

# (key, price_paise, billing, features) - exact canonical seed (Doc 06 sec 1)
PLANS = [
    ("free", 0, None, FREE_FEATURES),
    ("pro_lite_monthly", 3900, "monthly", PRO_LITE_FEATURES),
    ("pro_lite_annual", 39900, "annual", PRO_LITE_FEATURES),
    ("pro_monthly", 4900, "monthly", PRO_FEATURES),
    ("pro_annual", 49900, "annual", PRO_FEATURES),
]


def seed() -> None:
    engine = make_engine()
    with Session(engine) as session:
        created, updated = 0, 0
        for key, price_paise, billing, features in PLANS:
            plan = session.scalar(select(Plan).where(Plan.key == key))
            if plan is None:
                session.add(
                    Plan(key=key, price_paise=price_paise, billing=billing, features=features)
                )
                created += 1
            else:
                plan.price_paise = price_paise
                plan.billing = billing
                plan.features = features
                updated += 1

        session.commit()
        print(f"plans: {created} created, {updated} updated")


if __name__ == "__main__":
    seed()

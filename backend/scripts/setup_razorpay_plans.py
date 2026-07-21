"""Create the 4 paid Razorpay-side Plan objects and record their IDs locally.

Razorpay has its own recurring-billing ``Plan`` concept, distinct from but
linked to our ``plans`` table. Run ``scripts/seed_plans.py`` first so this
script can find each local plan row by key.

Razorpay TEST and LIVE keys use separate object spaces: a plan ID created
with test keys does not exist when live keys are used. The default invocation
is idempotent and skips a row that already has a ``razorpay_plan_id``. After
switching to live keys, use ``--relink`` to create matching LIVE plans and
replace those stored IDs. Use ``--dry-run`` first to preview the changes.

BLOCKED ON CREDENTIALS: requires a real Razorpay account and API keys
(``RAZORPAY_KEY_ID``/``RAZORPAY_KEY_SECRET`` in ``.env``) - a manual
prerequisite (Doc handoffs/PHASE-2-HANDOFF.md sec 10), not something this
script can create for you.

Usage:
uv run python -m scripts.setup_razorpay_plans
uv run python -m scripts.setup_razorpay_plans --dry-run --relink
"""

import argparse

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


def _plan_action(existing_plan_id: str | None, relink: bool) -> str:
    """Return the requested action for a locally stored Razorpay plan ID."""
    if not existing_plan_id:
        return "create"
    if relink:
        return "relink"
    return "skip"


def _razorpay_key_mode(key_id: str | None) -> str:
    """Classify a Razorpay key ID without exposing the key itself."""
    if key_id and key_id.startswith("rzp_live_"):
        return "live"
    if key_id and key_id.startswith("rzp_test_"):
        return "test"
    return "unknown"


def _print_razorpay_mode(mode: str) -> None:
    if mode == "live":
        print("MODE: LIVE (rzp_live_...)")
    elif mode == "test":
        print("MODE: TEST (rzp_test_...)")
    else:
        print("MODE: UNKNOWN (unrecognised key prefix)")


def setup(relink: bool = False, dry_run: bool = False) -> None:
    settings = get_settings()
    mode = _razorpay_key_mode(settings.razorpay_key_id)
    _print_razorpay_mode(mode)

    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        raise SystemExit(
            "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET are not set - create a Razorpay account, "
            "grab test-mode API keys from the dashboard, and set them in backend/.env first."
        )

    if dry_run:
        print("DRY RUN: Razorpay will not be called and local plan IDs will not be changed.")
        client = None
    else:
        client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    engine = make_engine()

    with Session(engine) as session:
        plans_by_key = None
        if mode == "live" and relink:
            plans_by_key = {
                key: session.scalar(select(Plan).where(Plan.key == key))
                for key in _RAZORPAY_PLAN_SPECS
            }
            warning = "WARNING: LIVE MODE --relink will overwrite existing Razorpay plan IDs."
            if dry_run:
                warning = "WARNING: LIVE MODE --relink would overwrite existing Razorpay plan IDs."
            print(warning)
            for key, plan in plans_by_key.items():
                if plan is not None and plan.razorpay_plan_id:
                    print(f"{key}: {plan.razorpay_plan_id} -> (new)")

        created = 0
        for key, spec in _RAZORPAY_PLAN_SPECS.items():
            if plans_by_key is None:
                plan = session.scalar(select(Plan).where(Plan.key == key))
            else:
                plan = plans_by_key[key]
            if plan is None:
                print(f"skipped {key}: no local plan row - run scripts/seed_plans.py first")
                continue
            existing_plan_id = plan.razorpay_plan_id
            action = _plan_action(existing_plan_id, relink)
            if action == "skip":
                print(f"skipped {key}: already has razorpay_plan_id={existing_plan_id}")
                continue

            if dry_run:
                if action == "relink":
                    print(f"would relink Razorpay plan for {key}: {existing_plan_id} -> (new)")
                else:
                    print(f"would create Razorpay plan for {key}")
                created += 1
                continue

            assert client is not None
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
            if action == "relink":
                print(
                    f"relinked Razorpay plan for {key}: "
                    f"{existing_plan_id} -> {razorpay_plan['id']}"
                )
            else:
                print(f"created Razorpay plan for {key}: {razorpay_plan['id']}")

        if dry_run:
            print(f"dry run: {created} Razorpay plans would be created")
        else:
            session.commit()
            print(f"done: {created} Razorpay plans created")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--relink",
        action="store_true",
        help="create replacement Razorpay plans and overwrite stored plan IDs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview actions without calling Razorpay or committing local changes",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    setup(relink=args.relink, dry_run=args.dry_run)

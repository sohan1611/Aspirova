"""Retry paid subscription upgrades whose Razorpay plan edit previously failed.

The payment and local entitlement are deliberately retained when the initial
Razorpay subscription edit fails: a customer who paid must keep access. This
script repairs the remaining Razorpay schedule change so its next renewal uses
the upgraded plan. Use ``--dry-run`` first when operating against live billing.

Usage:
uv run python -m scripts.reconcile_upgrades
uv run python -m scripts.reconcile_upgrades --dry-run
"""

import argparse

import razorpay
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.config import get_settings
from core.db import make_engine
from scripts.setup_razorpay_plans import _print_razorpay_mode, _razorpay_key_mode


def reconcile_upgrades(
    session: Session,
    client: razorpay.Client | None,
    *,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Retry every failed Razorpay plan edit and return found, fixed, failing counts."""

    rows = session.execute(
        select(models.SubscriptionUpgrade, models.Subscription, models.Plan)
        .join(
            models.Subscription,
            models.Subscription.id == models.SubscriptionUpgrade.subscription_id,
        )
        .join(models.Plan, models.Plan.id == models.SubscriptionUpgrade.to_plan_id)
        .where(models.SubscriptionUpgrade.status == "applied_with_error")
        .order_by(models.SubscriptionUpgrade.id)
    ).all()
    found = len(rows)

    if dry_run:
        for upgrade, subscription, target_plan in rows:
            print(
                f"would retry upgrade {upgrade.id}: subscription {subscription.razorpay_sub_id} "
                f"to target plan {target_plan.key}"
            )
        print(f"summary: {found} found, 0 fixed, {found} still failing")
        return found, 0, found

    if client is None:
        raise ValueError("A Razorpay client is required unless --dry-run is used")

    fixed = 0
    still_failing = 0
    for upgrade, subscription, target_plan in rows:
        try:
            client.subscription.edit(
                subscription.razorpay_sub_id,
                {
                    "plan_id": target_plan.razorpay_plan_id,
                    "schedule_change_at": "cycle_end",
                },
            )
        except Exception as exc:
            still_failing += 1
            print(
                f"upgrade {upgrade.id}: applied_with_error -> applied_with_error "
                f"(Razorpay retry failed: {exc})"
            )
            continue

        upgrade.status = "applied"
        session.commit()
        fixed += 1
        print(f"upgrade {upgrade.id}: applied_with_error -> applied")

    print(f"summary: {found} found, {fixed} fixed, {still_failing} still failing")
    return found, fixed, still_failing


def reconcile(dry_run: bool = False) -> None:
    """Open the configured database and reconcile its failed upgrades."""

    settings = get_settings()
    _print_razorpay_mode(_razorpay_key_mode(settings.razorpay_key_id))

    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        raise SystemExit(
            "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET are not set - create a Razorpay account, "
            "grab test-mode API keys from the dashboard, and set them in backend/.env first."
        )

    if dry_run:
        print("DRY RUN: Razorpay will not be called and upgrade statuses will not be changed.")
        client = None
    else:
        client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))

    engine = make_engine()
    with Session(engine) as session:
        reconcile_upgrades(session, client, dry_run=dry_run)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview reconciliation without calling Razorpay or changing local statuses",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    reconcile(dry_run=args.dry_run)

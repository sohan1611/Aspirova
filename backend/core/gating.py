"""The single gating seam (Doc 08 sec 1: "MUST drive plan gating from
plans.features via a single can(user, feature) helper. MUST NOT scatter
if plan == 'pro' checks."). Every feature gate in the codebase goes
through can() - never a scattered plan-string comparison.

Reads the user's most recent subscription with status IN ('active',
'trialing') whose period has not ended beyond the configured grace window.
'past_due'/'canceled' subscriptions do NOT grant paid features, and neither
does an ended period. The short grace window avoids locking out a paying user
while a delayed Razorpay renewal webhook arrives. An unauthenticated user or
one with no such subscription resolves to the 'free' plan's features - there
is always a fallback, never a KeyError.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core import models
from core.config import get_settings

FREE_PLAN_KEY = "free"


def active_subscription_filters() -> list[Any]:
    """Criteria for subscriptions that currently retain paid access."""
    grace_interval = timedelta(days=get_settings().subscription_grace_days)
    return [
        models.Subscription.status.in_(("active", "trialing")),
        or_(
            models.Subscription.current_period_end.is_(None),
            models.Subscription.current_period_end > func.now() - grace_interval,
        ),
    ]


def _free_features(db: Session) -> dict:
    features = db.scalar(select(models.Plan.features).where(models.Plan.key == FREE_PLAN_KEY))
    if features is None:
        raise RuntimeError(
            "the 'free' plan row is missing - run scripts/seed_plans.py before serving traffic"
        )
    return features


def get_features(db: Session, user: "models.User | None") -> dict:
    """The full features dict for a user's active plan - free tier if
    unauthenticated or with no active/trialing subscription."""
    if user is None:
        return _free_features(db)

    features = db.scalar(
        select(models.Plan.features)
        .join(models.Subscription, models.Subscription.plan_id == models.Plan.id)
        .where(
            models.Subscription.user_id == user.id,
            *active_subscription_filters(),
        )
        .order_by(models.Subscription.created_at.desc())
        .limit(1)
    )
    return features if features is not None else _free_features(db)


def can(db: Session, user: "models.User | None", feature: str) -> Any:
    """Returns the feature's value from the user's plan: bool for
    toggles (instant_alerts, copilot, ...), int/None for limits
    (dream_companies_limit - None means unlimited, matching Doc 03 sec
    4.1's example). Missing keys resolve to False, not a KeyError - a
    feature absent from a plan's jsonb is a feature that plan doesn't
    have, not a bug."""
    return get_features(db, user).get(feature, False)

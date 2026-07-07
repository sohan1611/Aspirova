"""Referral invite-code service and complimentary reward grant."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import choice
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core import models

INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INVITE_CODE_LENGTH = 8
MAX_INVITE_CODE_ATTEMPTS = 10
DEFAULT_REWARD_PLAN_KEY = "pro_lite_monthly"
DEFAULT_REWARD_DAYS = 30

ReferralReason = Literal["ok", "already_referred", "self_referral", "unknown_code"]


@dataclass(frozen=True)
class ReferralResult:
    referred: bool
    reason: ReferralReason


def _generate_invite_code() -> str:
    return "".join(choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def get_or_create_invite_code(db: Session, user: models.User) -> str:
    """Return the user's stable invite code, creating one lazily if needed."""
    if user.invite_code:
        return user.invite_code

    for _attempt in range(MAX_INVITE_CODE_ATTEMPTS):
        code = _generate_invite_code()
        if resolve_code(db, code) is not None:
            continue

        user.invite_code = code
        try:
            db.add(user)
            db.commit()
        except IntegrityError:
            db.rollback()
            db.refresh(user)
            if user.invite_code:
                return user.invite_code
            continue

        return code

    raise RuntimeError("could not allocate a unique invite code")


def resolve_code(db: Session, code: str) -> models.User | None:
    """Resolve an invite code case-insensitively."""
    normalized = code.strip().lower()
    if not normalized:
        return None

    return db.scalar(select(models.User).where(func.lower(models.User.invite_code) == normalized))


def grant_comp_pro(
    db: Session,
    referrer: models.User,
    *,
    days: int = DEFAULT_REWARD_DAYS,
    plan_key: str = DEFAULT_REWARD_PLAN_KEY,
) -> models.Subscription:
    """Add a bounded complimentary Pro Lite subscription; caller commits."""
    plan = db.scalar(select(models.Plan).where(models.Plan.key == plan_key))
    if plan is None:
        raise RuntimeError(
            f"the '{plan_key}' plan row is missing - run scripts/seed_plans.py "
            "before referral rewards"
        )

    subscription = models.Subscription(
        user_id=referrer.id,
        plan_id=plan.id,
        status="active",
        razorpay_sub_id=None,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.add(subscription)
    return subscription


def record_referral(db: Session, new_user: models.User, code: str) -> ReferralResult:
    """Set a user's referrer once and grant the referrer in the same commit."""
    referrer = resolve_code(db, code)
    if referrer is None:
        return ReferralResult(referred=False, reason="unknown_code")
    if referrer.id == new_user.id:
        return ReferralResult(referred=False, reason="self_referral")

    locked_user = db.scalar(
        select(models.User).where(models.User.id == new_user.id).with_for_update()
    )
    if locked_user is None:
        locked_user = new_user
    if locked_user.referred_by is not None:
        return ReferralResult(referred=False, reason="already_referred")

    locked_user.referred_by = referrer.id
    grant_comp_pro(db, referrer)
    db.commit()
    return ReferralResult(referred=True, reason="ok")

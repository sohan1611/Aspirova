"""Authenticated account profile, plan state, and subscription management."""

from datetime import datetime

import razorpay
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.payments import _razorpay_client
from api.schemas import AccountMe, AccountUpdate, PlanState
from core import models
from core.gating import get_features

router = APIRouter()


def _active_subscription_query(user: models.User):
    return (
        select(models.Subscription, models.Plan)
        .join(models.Plan, models.Plan.id == models.Subscription.plan_id)
        .where(
            models.Subscription.user_id == user.id,
            models.Subscription.status.in_(("active", "trialing")),
            or_(
                models.Subscription.razorpay_sub_id.isnot(None),
                models.Subscription.current_period_end.is_(None),
                models.Subscription.current_period_end > func.now(),
            ),
        )
        .order_by(models.Subscription.created_at.desc())
        .limit(1)
    )


def _build_account_me(db: Session, user: models.User) -> AccountMe:
    features = get_features(db, user)
    active = db.execute(_active_subscription_query(user)).first()

    if active is None:
        plan = db.scalar(select(models.Plan).where(models.Plan.key == "free"))
        if plan is None:
            raise RuntimeError(
                "the 'free' plan row is missing - run scripts/seed_plans.py before serving traffic"
            )
        status = "free"
        current_period_end = None
        cancel_at_period_end = False
    else:
        subscription, plan = active
        status = subscription.status
        current_period_end = subscription.current_period_end
        cancel_at_period_end = subscription.cancel_at_period_end

    return AccountMe(
        email=user.email,
        display_name=user.display_name,
        college=user.college,
        graduation_year=user.graduation_year,
        created_at=user.created_at,
        invite_code=user.invite_code,
        notification_prefs=user.notification_prefs or {},
        plan=PlanState(
            key=plan.key,
            price_paise=plan.price_paise,
            billing=plan.billing,
            features=features,
            status=status,
            current_period_end=current_period_end,
            cancel_at_period_end=cancel_at_period_end,
        ),
    )


@router.get("/account/me", response_model=AccountMe)
def get_account_me(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> AccountMe:
    return _build_account_me(db, user)


@router.patch("/account/me", response_model=AccountMe)
def update_account_me(
    request: AccountUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> AccountMe:
    for field in ("display_name", "college", "graduation_year"):
        if field in request.model_fields_set:
            setattr(user, field, getattr(request, field))

    if "notification_prefs" in request.model_fields_set and request.notification_prefs is not None:
        user.notification_prefs = {
            **(user.notification_prefs or {}),
            **request.notification_prefs,
        }

    db.commit()
    return _build_account_me(db, user)


@router.post("/subscription/cancel")
def cancel_subscription(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, str | datetime | None]:
    subscription = db.scalar(
        select(models.Subscription)
        .where(
            models.Subscription.user_id == user.id,
            models.Subscription.status.in_(("active", "trialing")),
            models.Subscription.razorpay_sub_id.isnot(None),
        )
        .order_by(models.Subscription.created_at.desc())
        .limit(1)
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="No active subscription")

    if subscription.cancel_at_period_end:
        return {
            "status": "cancel_scheduled",
            "current_period_end": subscription.current_period_end,
        }

    client = _razorpay_client()
    try:
        client.subscription.cancel(
            subscription.razorpay_sub_id,
            {"cancel_at_cycle_end": 1},
        )
    except razorpay.errors.BadRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (razorpay.errors.GatewayError, razorpay.errors.ServerError) as exc:
        raise HTTPException(status_code=502, detail="Payment provider error") from exc

    subscription.cancel_at_period_end = True
    db.commit()

    return {
        "status": "cancel_scheduled",
        "current_period_end": subscription.current_period_end,
    }

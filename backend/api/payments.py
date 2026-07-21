"""Razorpay checkout + webhook (Doc 02 sec 3.9, Doc handoffs/
PHASE-2-HANDOFF.md sec 2/6). Test-mode keys first - "never auto-charge or
auto-create live billing" (Doc handoffs/PHASE-2-HANDOFF.md sec 2); going
live is the user's own action in the Razorpay dashboard, not something
this code decides.

Subscription state is driven entirely by Razorpay's webhook events, never
guessed client-side or optimistically set on checkout - the webhook is the
single source of truth for `subscriptions.status`, matching how Razorpay
itself models the lifecycle (checkout success is not the same event as a
subscription actually being confirmed active).

total_count (Razorpay's "number of billing cycles before the subscription
naturally ends") is set high enough to behave as "recurring until
cancelled" in practice, since Razorpay Subscriptions have no literal
"forever" option: 120 for monthly (10 years), 10 for annual (10 years).
This is a judgment call flagged for architect review, not a documented
canon value.
"""

import logging
from datetime import datetime, timezone
from html import escape

import razorpay
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from core import models
from core.config import get_settings
from core.email_client import send_email
from core.email_templates import email_layout, text_footer
from core.gating import active_subscription_filters

router = APIRouter()

logger = logging.getLogger(__name__)

_TOTAL_COUNT_BY_BILLING = {"monthly": 120, "annual": 10}

# Razorpay subscription-lifecycle events this handler acts on -> our
# subscriptions.status. Events not listed here (e.g. subscription.
# authenticated, .paused, .resumed) currently have no product behavior
# tied to them and are acknowledged but ignored, not silently 500'd.
_STATUS_BY_EVENT = {
    "subscription.activated": "active",
    "subscription.charged": "active",
    "subscription.completed": "canceled",
    "subscription.cancelled": "canceled",
    "subscription.halted": "past_due",
}
_TERMINAL_STATUSES = frozenset({"canceled"})


def _send_subscription_status_email(
    db: Session, subscription: models.Subscription, new_status: str
) -> None:
    """Best-effort customer email plus delivery record after a status transition."""

    try:
        user = db.scalar(select(models.User).where(models.User.id == subscription.user_id))
        if user is None or not user.email:
            return

        plan = db.scalar(select(models.Plan).where(models.Plan.id == subscription.plan_id))
        if plan is None:
            return

        plan_name = escape(plan.key.replace("_", " ").title(), quote=True)
        site_url = get_settings().site_url.rstrip("/")

        if new_status == "active":
            subject = "Your Aspirova Pro is active"
            html = email_layout(
                title="Your Aspirova Pro is active",
                intro_html=(
                    '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:15px;'
                    'line-height:22px;margin:0 0 20px">'
                    f"Your {plan_name} plan is now active."
                    "</p>"
                ),
                body_html=(
                    '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:15px;'
                    'line-height:22px;margin:0 0 20px">'
                    "Your Pro features are ready whenever you are."
                    "</p>"
                ),
                cta_label="Open Aspirova",
                cta_url=site_url,
            )
            text = (
                f"Your {plan_name} plan is now active.\n\n"
                "Your Pro features are ready whenever you are.\n"
                f"Open Aspirova: {site_url}\n\n"
                f"{text_footer()}"
            )
            notification_type = "subscription_activated"
        else:
            subject = "We couldn't process your payment"
            html = email_layout(
                title="We couldn't process your payment",
                intro_html=(
                    '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:15px;'
                    'line-height:22px;margin:0 0 20px">'
                    f"We couldn't process the payment for your {plan_name} plan."
                    "</p>"
                ),
                body_html=(
                    '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:15px;'
                    'line-height:22px;margin:0 0 20px">'
                    "Please update your payment method. Pro features are paused until your payment "
                    "succeeds."
                    "</p>"
                ),
                cta_label="View your subscription",
                cta_url=f"{site_url}/account?section=subscription",
            )
            text = (
                f"We couldn't process the payment for your {plan_name} plan.\n\n"
                "Please update your payment method. Pro features are paused until your payment "
                "succeeds.\n"
                f"View your subscription: {site_url}/account?section=subscription\n\n"
                f"{text_footer()}"
            )
            notification_type = "subscription_payment_failed"

        try:
            sent = send_email(user.email, subject, html, text)
        except Exception:
            logger.exception("subscription email send failed for subscription %s", subscription.id)
            sent = False

        now = datetime.now(timezone.utc)
        db.add(
            models.Notification(
                user_id=user.id,
                type=notification_type,
                status="sent" if sent else "failed",
                sent_at=now if sent else None,
                meta={
                    "subscription_id": subscription.id,
                    "razorpay_sub_id": subscription.razorpay_sub_id,
                },
            )
        )
        db.commit()
    except Exception:
        # The subscription state was committed before this helper is called.
        db.rollback()
        logger.exception(
            "subscription email notification failed for subscription %s", subscription.id
        )


def _razorpay_client() -> razorpay.Client:
    settings = get_settings()
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        raise HTTPException(status_code=503, detail="Payments are not configured yet")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


class UpgradeVerificationRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


def _prorated_top_up_paise(
    current_price_paise: int,
    new_price_paise: int,
    billing: str,
    current_period_end: datetime,
    now: datetime,
) -> int:
    """Return the remaining-period price difference in paise.

    Billing periods deliberately use nominal 365-day annual and 30-day monthly
    lengths. This is an approximation (rather than adding dateutil); at these
    plan-price differences its error is sub-rupee.
    """

    nominal_days = 365 if billing == "annual" else 30
    remaining_days = (current_period_end - now).total_seconds() / 86_400
    fraction = max(0.0, min(1.0, remaining_days / nominal_days))
    top_up = round((new_price_paise - current_price_paise) * fraction)
    return max(0, int(top_up))


def _active_subscription_with_plan(db: Session, user: models.User):
    return db.execute(
        select(models.Subscription, models.Plan)
        .join(models.Plan, models.Plan.id == models.Subscription.plan_id)
        .where(
            models.Subscription.user_id == user.id,
            *active_subscription_filters(),
        )
        .order_by(models.Subscription.created_at.desc())
        .limit(1)
        .with_for_update(of=models.Subscription)
    ).first()


def _apply_subscription_upgrade(
    db: Session,
    client: razorpay.Client,
    subscription: models.Subscription,
    target_plan: models.Plan,
    upgrade: models.SubscriptionUpgrade,
) -> None:
    # The local entitlement and the Razorpay schedule are independent money/state
    # operations with no shared transaction. Commit local access first: the worst
    # case is a customer has what they paid for and Razorpay needs reconciliation,
    # never a customer who paid and got nothing.
    subscription.plan_id = target_plan.id
    db.commit()

    try:
        client.subscription.edit(
            subscription.razorpay_sub_id,
            {
                "plan_id": target_plan.razorpay_plan_id,
                "schedule_change_at": "cycle_end",
            },
        )
    except Exception:
        logger.exception(
            "Razorpay subscription plan change failed after local upgrade "
            "for subscription %s / upgrade %s",
            subscription.id,
            upgrade.id,
        )
        upgrade.status = "applied_with_error"
        db.commit()
        return

    upgrade.status = "applied"
    db.commit()


@router.post("/payments/upgrade/verify")
def verify_upgrade_payment(
    request: UpgradeVerificationRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict:
    upgrade = db.scalar(
        select(models.SubscriptionUpgrade).where(
            models.SubscriptionUpgrade.razorpay_order_id == request.razorpay_order_id
        )
    )
    if upgrade is None:
        raise HTTPException(status_code=404, detail="Upgrade payment not found")
    if upgrade.user_id != user.id:
        raise HTTPException(status_code=403, detail="This upgrade payment does not belong to you")

    # Use the same lock as order creation/replacement so a payment from an
    # already-open checkout cannot race a newly computed upgrade amount.
    subscription = db.scalar(
        select(models.Subscription)
        .where(models.Subscription.id == upgrade.subscription_id)
        .with_for_update()
    )
    if subscription is None:
        raise RuntimeError(f"subscription upgrade {upgrade.id} has missing referenced records")
    db.refresh(upgrade)

    if upgrade.status in {"applied", "applied_with_error"}:
        return {"status": "upgraded", "amount_paise": upgrade.amount_paise}
    if upgrade.status == "failed":
        raise HTTPException(status_code=409, detail="This upgrade payment is no longer valid")

    client = _razorpay_client()
    try:
        client.utility.verify_payment_signature(
            {
                "razorpay_order_id": request.razorpay_order_id,
                "razorpay_payment_id": request.razorpay_payment_id,
                "razorpay_signature": request.razorpay_signature,
            }
        )
    except razorpay.errors.SignatureVerificationError as exc:
        upgrade.status = "failed"
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid payment signature") from exc

    target_plan = db.get(models.Plan, upgrade.to_plan_id)
    if target_plan is None:
        raise RuntimeError(f"subscription upgrade {upgrade.id} has missing referenced records")

    upgrade.razorpay_payment_id = request.razorpay_payment_id
    upgrade.status = "paid"
    db.commit()
    _apply_subscription_upgrade(db, client, subscription, target_plan, upgrade)

    return {"status": "upgraded", "amount_paise": upgrade.amount_paise}


@router.post("/payments/upgrade/{plan_key}")
def create_subscription_upgrade(
    plan_key: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict:
    plan = db.scalar(select(models.Plan).where(models.Plan.key == plan_key))
    if plan is None:
        raise HTTPException(status_code=404, detail="Unknown plan")
    if plan.key == "free":
        raise HTTPException(status_code=400, detail="The free plan has no checkout")
    if plan.razorpay_plan_id is None:
        raise HTTPException(
            status_code=503,
            detail=f"Plan '{plan_key}' has not been provisioned on Razorpay yet",
        )

    active = _active_subscription_with_plan(db, user)
    if active is None:
        raise HTTPException(status_code=409, detail="You do not have an active plan to upgrade.")

    subscription, current_plan = active
    if subscription.cancel_at_period_end:
        raise HTTPException(
            status_code=409,
            detail="Your current plan is already scheduled to end and cannot be upgraded.",
        )
    if plan.billing != current_plan.billing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Only same-period upgrades are supported; "
                f"{current_plan.billing} to {plan.billing} is not available."
            ),
        )
    if plan.price_paise <= current_plan.price_paise:
        raise HTTPException(
            status_code=409,
            detail="You can only upgrade to a higher-priced plan.",
        )
    if subscription.current_period_end is None:
        raise HTTPException(
            status_code=409,
            detail="Cannot prorate an upgrade without a current period end.",
        )

    top_up = _prorated_top_up_paise(
        current_plan.price_paise,
        plan.price_paise,
        current_plan.billing or "monthly",
        subscription.current_period_end,
        datetime.now(timezone.utc),
    )

    # Locking the active subscription above serializes concurrent requests for
    # this upgrade. Normalize any legacy duplicate pending rows as well, so
    # this subscription/target pair has at most one payable order.
    pending_upgrades = list(
        db.scalars(
            select(models.SubscriptionUpgrade)
            .where(
                models.SubscriptionUpgrade.subscription_id == subscription.id,
                models.SubscriptionUpgrade.to_plan_id == plan.id,
                models.SubscriptionUpgrade.status == "pending",
            )
            .order_by(
                models.SubscriptionUpgrade.created_at.desc(),
                models.SubscriptionUpgrade.id.desc(),
            )
        )
    )
    reusable_upgrade = next(
        (
            upgrade
            for upgrade in pending_upgrades
            if upgrade.amount_paise == top_up and upgrade.razorpay_order_id is not None
        ),
        None,
    )

    if reusable_upgrade is not None:
        razorpay_order_id = reusable_upgrade.razorpay_order_id
        amount_paise = reusable_upgrade.amount_paise
        stale_pending_upgrades = [
            upgrade for upgrade in pending_upgrades if upgrade is not reusable_upgrade
        ]
        for stale_upgrade in stale_pending_upgrades:
            stale_upgrade.status = "failed"
        if stale_pending_upgrades:
            db.commit()
        return {
            "status": "payment_required",
            "amount_paise": amount_paise,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_key_id": get_settings().razorpay_key_id,
        }

    for stale_upgrade in pending_upgrades:
        stale_upgrade.status = "failed"

    client = _razorpay_client()

    if top_up < 100:
        upgrade = models.SubscriptionUpgrade(
            user_id=user.id,
            subscription_id=subscription.id,
            from_plan_id=current_plan.id,
            to_plan_id=plan.id,
            amount_paise=0,
            status="pending",
        )
        db.add(upgrade)
        _apply_subscription_upgrade(db, client, subscription, plan, upgrade)
        return {"status": "upgraded", "amount_paise": 0, "waived": True}

    razorpay_order = client.order.create(
        {
            "amount": top_up,
            "currency": "INR",
            "notes": {
                "user_id": str(user.id),
                "from_plan": current_plan.key,
                "to_plan": plan.key,
                "subscription_id": str(subscription.id),
            },
        }
    )
    upgrade = models.SubscriptionUpgrade(
        user_id=user.id,
        subscription_id=subscription.id,
        from_plan_id=current_plan.id,
        to_plan_id=plan.id,
        amount_paise=top_up,
        razorpay_order_id=razorpay_order["id"],
        status="pending",
    )
    db.add(upgrade)
    db.commit()

    return {
        "status": "payment_required",
        "amount_paise": top_up,
        "razorpay_order_id": razorpay_order["id"],
        "razorpay_key_id": get_settings().razorpay_key_id,
    }


@router.post("/payments/checkout/{plan_key}")
def create_checkout(
    plan_key: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict:
    plan = db.scalar(select(models.Plan).where(models.Plan.key == plan_key))
    if plan is None:
        raise HTTPException(status_code=404, detail="Unknown plan")
    if plan.key == "free":
        raise HTTPException(status_code=400, detail="The free plan has no checkout")
    if plan.razorpay_plan_id is None:
        raise HTTPException(
            status_code=503,
            detail=f"Plan '{plan_key}' has not been provisioned on Razorpay yet",
        )

    active_subscription = db.scalar(
        select(models.Subscription)
        .where(
            models.Subscription.user_id == user.id,
            *active_subscription_filters(),
        )
        .order_by(models.Subscription.created_at.desc())
        .limit(1)
    )
    if active_subscription is not None:
        if (
            active_subscription.cancel_at_period_end
            and active_subscription.current_period_end is not None
        ):
            period_end = active_subscription.current_period_end.date().isoformat()
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Your current plan is already ending on {period_end}. "
                    "You can subscribe again after that date."
                ),
            )
        raise HTTPException(
            status_code=409,
            detail="Please cancel your current plan before switching plans.",
        )

    client = _razorpay_client()
    total_count = _TOTAL_COUNT_BY_BILLING.get(plan.billing, 12)
    razorpay_sub = client.subscription.create(
        {
            "plan_id": plan.razorpay_plan_id,
            "total_count": total_count,
            "customer_notify": 1,
            "notes": {"user_id": str(user.id), "plan_key": plan.key},
        }
    )

    db.add(
        models.Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status="created",
            razorpay_sub_id=razorpay_sub["id"],
        )
    )
    db.commit()

    return {
        "razorpay_subscription_id": razorpay_sub["id"],
        "razorpay_key_id": get_settings().razorpay_key_id,
    }


@router.post("/payments/webhook", status_code=200)
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(None),
) -> dict:
    settings = get_settings()
    if not settings.razorpay_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")
    if not x_razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    raw_body = await request.body()
    client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    try:
        client.utility.verify_webhook_signature(
            raw_body.decode("utf-8"), x_razorpay_signature, settings.razorpay_webhook_secret
        )
    except razorpay.errors.SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail="Invalid signature") from exc

    payload = await request.json()
    event = payload.get("event", "")
    new_status = _STATUS_BY_EVENT.get(event)
    if new_status is None:
        return {"status": "ignored", "event": event}

    event_payload = payload.get("payload")
    subscription_payload = (
        event_payload.get("subscription") if isinstance(event_payload, dict) else None
    )
    subscription_entity = (
        subscription_payload.get("entity") if isinstance(subscription_payload, dict) else None
    )
    if not isinstance(subscription_entity, dict):
        return {"status": "malformed_payload", "event": event}

    razorpay_sub_id = subscription_entity.get("id")
    if not isinstance(razorpay_sub_id, str):
        return {"status": "malformed_payload", "event": event}

    subscription = db.scalar(
        select(models.Subscription).where(models.Subscription.razorpay_sub_id == razorpay_sub_id)
    )
    if subscription is None:
        # Not one we created a local row for (e.g. a webhook retried after
        # a DB issue, or a subscription created outside this app) -
        # acknowledge so Razorpay doesn't keep retrying, but there is
        # nothing local to update.
        return {"status": "no_matching_subscription", "razorpay_sub_id": razorpay_sub_id}

    # Razorpay can redeliver and reorder webhooks; do not resurrect a
    # terminal subscription or rewind the local billing period.
    if subscription.status in _TERMINAL_STATUSES:
        return {"status": "ignored_terminal", "event": event}

    previous_status = subscription.status
    subscription.status = new_status
    current_end = subscription_entity.get("current_end")
    if current_end:
        incoming_period_end = datetime.fromtimestamp(current_end, tz=timezone.utc)
        if (
            subscription.current_period_end is None
            or incoming_period_end > subscription.current_period_end
        ):
            subscription.current_period_end = incoming_period_end

    db.commit()

    if previous_status != new_status and new_status in {"active", "past_due"}:
        _send_subscription_status_email(db, subscription, new_status)

    return {"status": "ok", "event": event}

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
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from core import models
from core.config import get_settings
from core.email_client import send_email
from core.email_templates import email_layout, text_footer

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

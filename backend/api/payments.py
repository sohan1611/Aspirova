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

from datetime import datetime, timezone

import razorpay
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from core import models
from core.config import get_settings

router = APIRouter()

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

    subscription_entity = payload["payload"]["subscription"]["entity"]
    razorpay_sub_id = subscription_entity["id"]

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
    return {"status": "ok", "event": event}
